import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox


ROOT = Path(__file__).resolve().parent
WORKFLOW = "build-ios.yml"
ARTIFACT_NAME = "ezcan-ios-ipa"
BUILD_TIMEOUT_MINUTES = 45
WHITE = "#f4f7f8"
INK = "#26363d"
MUTED = "#8b9aa1"
CYAN = "#14c9d6"
CYAN_PALE = "#d8f5f6"
GREEN = "#4bd18c"
GREEN_PALE = "#e3f9ed"
LINE = "#d9e2e5"


class PipelineError(RuntimeError):
    pass


def hidden_process_options():
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


class EzcanIPABuilder:
    def __init__(self, window):
        self.window = window
        self.events = queue.Queue()
        self.worker = None

        window.title("Ezcan IPA Builder")
        window.geometry("760x720")
        window.minsize(620, 620)
        window.resizable(True, True)
        window.configure(bg=WHITE)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.update_idletasks()
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        window.geometry("760x720+{}+{}".format(max(0, (screen_width - 760) // 2), max(0, (screen_height - 720) // 2)))

        outer = tk.Frame(window, bg=WHITE, padx=42, pady=30)
        outer.pack(fill="both", expand=True)

        self.top_fade = tk.Canvas(outer, height=86, bg=WHITE, highlightthickness=0)
        self.top_fade.pack(fill="x")
        self.top_fade.bind("<Configure>", self.paint_top_fade)

        dial_area = tk.Frame(outer, bg=WHITE)
        dial_area.pack(fill="both", expand=True, pady=(12, 0))
        self.dial = tk.Canvas(dial_area, width=330, height=330, bg=WHITE, highlightthickness=0)
        self.dial.pack(pady=(0, 0))
        self.dial.create_oval(32, 32, 298, 298, outline="#e4eaec", width=1)
        self.dial.create_arc(46, 46, 284, 284, start=90, extent=-360, outline=CYAN_PALE, width=8, style="arc")
        self.dial.create_oval(63, 63, 267, 267, outline=LINE, width=1)
        self.dial_arc = self.dial.create_arc(46, 46, 284, 284, start=90, extent=0, outline=CYAN, width=8, style="arc")
        self.dial_percent = self.dial.create_text(165, 143, text="0%", fill=INK, font=("Segoe UI", 30, "bold"))
        self.dial_state = self.dial.create_text(165, 184, text="READY", fill=CYAN, font=("Segoe UI", 10, "bold"))
        self.dial_detail = self.dial.create_text(165, 207, text="SYSTEM STANDBY", fill=MUTED, font=("Segoe UI", 8))

        self.status = tk.Label(outer, text="Ready to build the latest unsigned IPA", bg=WHITE, fg=INK, font=("Segoe UI", 12))
        self.status.pack(pady=(0, 8))
        self.progress = tk.Canvas(outer, height=5, bg=CYAN_PALE, highlightthickness=0)
        self.progress.pack(fill="x", pady=(0, 18))
        self.progress_fill = self.progress.create_rectangle(0, 0, 0, 5, fill=CYAN, outline="")

        activation_row = tk.Frame(outer, bg=WHITE)
        activation_row.pack(pady=(0, 20))
        self.activate_hover = False
        self.activate_pressed = False
        self.activate_active = False
        self.activate_button = tk.Canvas(activation_row, width=110, height=124, bg=WHITE, highlightthickness=0, cursor="hand2")
        self.activate_button.pack()
        self.paint_activate_button()
        self.activate_button.bind("<Enter>", self.activate_enter)
        self.activate_button.bind("<Leave>", self.activate_leave)
        self.activate_button.bind("<ButtonPress-1>", self.activate_press)
        self.activate_button.bind("<ButtonRelease-1>", self.activate_release)

        log_header = tk.Frame(outer, bg=WHITE)
        log_header.pack(fill="x")
        tk.Label(log_header, text="ACTIVITY", bg=WHITE, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
        tk.Label(log_header, text="OUTPUT  /  artifacts\\ios", bg=WHITE, fg=MUTED, font=("Segoe UI", 8), anchor="e").pack(side="right")
        log_frame = tk.Frame(outer, bg=WHITE, highlightbackground=LINE, highlightthickness=1)
        log_frame.pack(fill="both", expand=False, pady=(7, 0))
        self.log = tk.Text(
            log_frame,
            height=7,
            state="disabled",
            wrap="word",
            bg="#fbfcfc",
            fg="#60747c",
            insertbackground=INK,
            relief="flat",
            padx=14,
            pady=12,
            font=("Consolas", 9),
        )
        scrollbar = tk.Scrollbar(log_frame, orient="vertical", command=self.log.yview, bg=WHITE, troughcolor=WHITE, relief="flat", highlightthickness=0)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.window.after(100, self.process_events)

    def paint_top_fade(self, event=None):
        width = max(1, event.width if event else self.top_fade.winfo_width())
        height = max(1, self.top_fade.winfo_height())
        start = (216, 245, 246)
        end = (255, 255, 255)
        self.top_fade.delete("fade")
        bands = 24
        for index in range(bands):
            amount = index / max(1, bands - 1)
            color = "#{:02x}{:02x}{:02x}".format(
                int(start[0] + (end[0] - start[0]) * amount),
                int(start[1] + (end[1] - start[1]) * amount),
                int(start[2] + (end[2] - start[2]) * amount),
            )
            top = height * index / bands
            bottom = height * (index + 1) / bands + 1
            self.top_fade.create_rectangle(0, top, width, bottom, fill=color, outline="", tags="fade")

    def close(self):
        self.window.destroy()

    def paint_activate_button(self):
        self.activate_button.delete("all")
        center_x, center_y = 55, 43
        offset = 2 if self.activate_pressed else 0
        face = "#7e929d" if self.activate_active else ("#31dbe4" if self.activate_hover else CYAN)
        border = "#617681" if self.activate_active else "#0a9ba7"
        self.activate_button.create_oval(13, 2, 97, 86, fill=CYAN_PALE, outline="#b7dfe1", width=1)
        self.activate_button.create_oval(19, 10 + offset, 91, 82 + offset, fill="#6f818d", outline="")
        self.activate_button.create_oval(19, 6 + offset, 91, 78 + offset, fill=face, outline=border, width=1)
        self.activate_button.create_arc(23, 10 + offset, 87, 74 + offset, start=28, extent=124, style="arc", outline="#7ae7eb", width=4)
        self.activate_button.create_arc(23, 10 + offset, 87, 74 + offset, start=205, extent=112, style="arc", outline="#087d87", width=4)
        scale = 0.92 if self.activate_pressed else 1.0
        half_width = 12 * scale
        half_height = 15 * scale
        self.activate_icon = self.activate_button.create_polygon(
            center_x - half_width,
            center_y - half_height + offset,
            center_x - half_width,
            center_y + half_height + offset,
            center_x + half_width,
            center_y + offset,
            fill="#e9ffff" if not self.activate_active else "#d2dadd",
            outline="",
        )
        self.activate_label = self.activate_button.create_text(
            center_x,
            106,
            text="BUILD IPA",
            fill=MUTED if self.activate_active else CYAN,
            font=("Segoe UI", 8, "bold"),
        )

    def activate_enter(self, _event):
        self.activate_hover = True
        self.paint_activate_button()

    def activate_leave(self, _event):
        self.activate_hover = False
        self.activate_pressed = False
        self.paint_activate_button()

    def activate_press(self, _event):
        self.activate_pressed = True
        self.paint_activate_button()

    def activate_release(self, _event):
        was_pressed = self.activate_pressed
        self.activate_pressed = False
        self.paint_activate_button()
        if was_pressed:
            self.start()

    def update_dial(self, percent, state, detail):
        self.dial.itemconfigure(self.dial_arc, extent=-3.6 * percent)
        self.dial.itemconfigure(self.dial_percent, text="{}%".format(int(percent)))
        self.dial.itemconfigure(self.dial_state, text=state)
        self.dial.itemconfigure(self.dial_detail, text=detail)
        width = max(0, self.progress.winfo_width())
        self.progress.coords(self.progress_fill, 0, 0, width * percent / 100, 5)

    def set_activation_state(self, active):
        self.activate_active = active
        self.activate_button.configure(cursor="watch" if active else "hand2")
        self.paint_activate_button()

    def write_log(self, message):
        self.events.put(("log", message))

    def set_progress(self, percent, message):
        self.events.put(("progress", percent, message))

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.set_activation_state(True)
        self.update_dial(0, "ACTIVE", "CONNECTING")
        self.status.configure(text="Starting secure build sequence")
        self.append_log("Starting Ezcan IPA build...")
        self.worker = threading.Thread(target=self.run_pipeline, args=("Build latest Ezcan IPA", BUILD_TIMEOUT_MINUTES), daemon=True)
        self.worker.start()

    def append_log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def process_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "log":
                    self.append_log(event[1])
                elif event[0] == "progress":
                    percent = event[1]
                    message = event[2]
                    self.update_dial(percent, "ACTIVE", self.dial_detail_text(message))
                    self.status.configure(text=message)
                elif event[0] == "success":
                    self.set_activation_state(False)
                    self.update_dial(100, "COMPLETE", "IPA READY")
                    self.status.configure(text="IPA downloaded and ready for AltStore")
                    self.show_success_dialog(Path(event[1]))
                elif event[0] == "failure":
                    self.set_activation_state(False)
                    self.update_dial(0, "ERROR", "CHECK ACTIVITY")
                    self.status.configure(text="Build stopped. See activity for details.")
                    messagebox.showerror("Ezcan IPA build failed", event[1])
        except queue.Empty:
            pass
        self.window.after(100, self.process_events)

    def show_success_dialog(self, ipa_path):
        dialog = tk.Toplevel(self.window)
        dialog.title("Ezcan IPA build complete")
        dialog.configure(bg=WHITE)
        dialog.transient(self.window)
        dialog.resizable(False, False)

        content = tk.Frame(dialog, bg=WHITE, padx=28, pady=24)
        content.pack(fill="both", expand=True)
        tk.Label(
            content,
            text="EZCAN IPA BUILD COMPLETE",
            bg=WHITE,
            fg=GREEN,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        tk.Label(
            content,
            text="Your IPA is ready.",
            bg=WHITE,
            fg=INK,
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w", pady=(8, 4))
        tk.Label(
            content,
            text=str(ipa_path),
            bg=WHITE,
            fg=MUTED,
            justify="left",
            wraplength=470,
            font=("Consolas", 9),
        ).pack(anchor="w")

        buttons = tk.Frame(content, bg=WHITE)
        buttons.pack(anchor="e", pady=(22, 0))
        tk.Button(
            buttons,
            text="Open destination folder",
            command=lambda: self.open_destination_folder(ipa_path, dialog),
            bg=GREEN_PALE,
            fg=INK,
            activebackground="#c8f1d9",
            activeforeground=INK,
            relief="flat",
            bd=0,
            padx=14,
            pady=8,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            buttons,
            text="OK",
            command=dialog.destroy,
            bg=CYAN,
            fg=INK,
            activebackground="#75e1e5",
            activeforeground=INK,
            relief="flat",
            bd=0,
            padx=22,
            pady=8,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        ).pack(side="left")
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.bind("<Return>", lambda _event: dialog.destroy())
        dialog.grab_set()
        dialog.focus_force()

    @staticmethod
    def open_destination_folder(ipa_path, dialog):
        try:
            if not hasattr(os, "startfile"):
                raise OSError("Opening the destination folder is supported on Windows only")
            os.startfile(str(ipa_path.parent))
        except OSError as error:
            messagebox.showerror("Open destination folder", str(error), parent=dialog)

    @staticmethod
    def dial_detail_text(message):
        upper = message.upper()
        if "PUSH" in upper:
            return "PUSHING MAIN"
        if "TRACKING" in upper or "ACTIONS" in upper:
            return "ACTIONS RUNNING"
        if "DOWNLOAD" in upper:
            return "DOWNLOADING"
        if "WAITING" in upper:
            return "QUEUEING"
        if "CHECK" in upper:
            return "SYSTEM CHECK"
        return "BUILDING"

    def run_command(self, command, label, quiet=False):
        if not quiet:
            self.write_log("$ " + " ".join(command))
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_process_options(),
        )
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        if completed.returncode != 0:
            detail = output or "no output"
            raise PipelineError("{} failed (exit code {}).\n{}".format(label, completed.returncode, detail))
        if output and not quiet:
            self.write_log(output)
        return completed.stdout.strip()

    def git(self, args, label=None, quiet=False):
        return self.run_command(["git"] + args, label or "git", quiet=quiet)

    def gh(self, args, label=None, quiet=False):
        return self.run_command(["gh"] + args, label or "gh", quiet=quiet)

    def run_pipeline(self, commit_message, timeout_minutes):
        try:
            self.pipeline(commit_message, timeout_minutes)
        except Exception as error:
            message = str(error)
            self.write_log("ERROR: " + message)
            self.events.put(("failure", message))

    def pipeline(self, commit_message, timeout_minutes):
        self.set_progress(4, "Checking Git and GitHub CLI...")
        if shutil.which("git") is None:
            raise PipelineError("Git was not found on PATH.")
        if shutil.which("gh") is None:
            raise PipelineError("GitHub CLI (gh) was not found on PATH.")

        branch = self.git(["branch", "--show-current"], quiet=True).strip()
        if branch != "main":
            raise PipelineError("This builder only pushes main. Current branch is '{}'.".format(branch))
        self.gh(["auth", "status"], label="GitHub authentication check")
        self.assert_no_sensitive_paths()

        status = self.git(["status", "--porcelain"], quiet=True)
        changed = bool(status.strip())
        manual_run = False
        requested_at = datetime.now(timezone.utc)

        if changed:
            self.set_progress(10, "Staging repository changes...")
            self.git(["add", "--all"], label="Stage changes")
            staged_check = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=str(ROOT),
                **hidden_process_options(),
            )
            if staged_check.returncode == 0:
                raise PipelineError("The worktree had changes, but nothing was staged.")
            self.set_progress(18, "Creating commit...")
            self.git(["commit", "-m", commit_message], label="Create commit")
            sha = self.git(["rev-parse", "HEAD"], quiet=True).strip()
            self.set_progress(26, "Pushing {} to origin/main...".format(sha[:12]))
            self.git(["push", "origin", "main"], label="Push to origin/main")
        else:
            sha = self.git(["rev-parse", "HEAD"], quiet=True).strip()
            manual_run = True
            self.set_progress(26, "No changes found. Starting a build for current main...")
            requested_at = datetime.now(timezone.utc)
            self.gh(["workflow", "run", WORKFLOW, "--ref", "main"], label="Start GitHub Actions workflow")

        run = self.wait_for_run(sha, requested_at, manual_run)
        self.set_progress(38, "Tracking GitHub Actions run {}...".format(run["databaseId"]))
        completed = self.wait_for_completion(run, timeout_minutes)

        artifact_directory = ROOT / "artifacts" / "ios"
        if artifact_directory.exists():
            shutil.rmtree(str(artifact_directory))
        artifact_directory.mkdir(parents=True, exist_ok=True)
        self.set_progress(92, "Downloading the IPA artifact...")
        self.gh(
            ["run", "download", str(completed["databaseId"]), "--name", ARTIFACT_NAME, "--dir", str(artifact_directory)],
            label="Download IPA artifact",
        )
        ipa_files = sorted(artifact_directory.rglob("*.ipa"))
        if not ipa_files:
            raise PipelineError("The workflow succeeded, but no .ipa file was found in {}.".format(artifact_directory))

        ipa_path = ipa_files[0]
        self.write_log("IPA ready: {}".format(ipa_path))
        self.write_log("Actions run: {}".format(completed.get("url", "")))
        self.set_progress(100, "Complete. IPA downloaded.")
        self.events.put(("success", str(ipa_path)))

    def assert_no_sensitive_paths(self):
        status = self.git(["status", "--porcelain"], quiet=True)
        blocked = re.compile(r"(?i)(^|[\\/])([^\\/]*(password|secret|token|credential)[^\\/]*|[^\\/]+\.(p12|mobileprovision|pem|key|env))$")
        for line in status.splitlines():
            match = re.match(r"^..\s+(.+)$", line)
            if not match:
                continue
            changed_path = match.group(1).split(" -> ")[-1]
            if blocked.search(changed_path):
                raise PipelineError("Refusing to stage a possibly sensitive path: {}".format(changed_path))

    def workflow_runs(self, sha):
        raw = self.gh(
            [
                "run", "list", "--workflow", WORKFLOW, "--branch", "main", "--limit", "20",
                "--json", "databaseId,status,conclusion,headSha,event,createdAt,url",
            ],
            label="Find GitHub Actions run",
            quiet=True,
        )
        return [run for run in json.loads(raw or "[]") if run.get("headSha") == sha]

    @staticmethod
    def parse_time(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def wait_for_run(self, sha, requested_at, manual_run):
        deadline = time.time() + 180
        while time.time() < deadline:
            for run in self.workflow_runs(sha):
                if manual_run and run.get("event") != "workflow_dispatch":
                    continue
                if self.parse_time(run["createdAt"]) >= requested_at:
                    return run
            self.set_progress(32, "Waiting for GitHub Actions to create the build run...")
            time.sleep(5)
        raise PipelineError("GitHub Actions did not create a build run for commit {}.".format(sha))

    def wait_for_completion(self, run, timeout_minutes):
        deadline = time.time() + timeout_minutes * 60
        while time.time() < deadline:
            raw = self.gh(
                ["run", "view", str(run["databaseId"]), "--json", "databaseId,status,conclusion,url"],
                label="Check GitHub Actions status",
                quiet=True,
            )
            current = json.loads(raw)
            status = current.get("status", "unknown")
            if status == "completed":
                if current.get("conclusion") != "success":
                    raise PipelineError(
                        "GitHub Actions finished with '{}'.\nRun: {}".format(current.get("conclusion"), current.get("url", run.get("url", "")))
                    )
                return current
            elapsed = timeout_minutes * 60 - max(0, deadline - time.time())
            percent = min(88, int(38 + elapsed / (timeout_minutes * 60) * 48))
            self.set_progress(percent, "iOS build is {}...".format(status))
            time.sleep(10)
        raise PipelineError("The iOS build exceeded the {} minute timeout.\nRun: {}".format(timeout_minutes, run.get("url", "")))


def main():
    window = tk.Tk()
    EzcanIPABuilder(window)
    window.mainloop()


if __name__ == "__main__":
    main()