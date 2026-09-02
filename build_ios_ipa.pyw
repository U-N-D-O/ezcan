import json
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk


ROOT = Path(__file__).resolve().parent
WORKFLOW = "build-ios.yml"
ARTIFACT_NAME = "ezcan-ios-ipa"
DEFAULT_TIMEOUT_MINUTES = 45


class PipelineError(RuntimeError):
    pass


class EzcanIPABuilder:
    def __init__(self, window):
        self.window = window
        self.events = queue.Queue()
        self.worker = None

        window.title("Ezcan IPA Builder")
        window.geometry("720x520")
        window.minsize(620, 440)
        window.configure(bg="#071323")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#071323")
        style.configure("TLabel", background="#071323", foreground="#edf7ff")
        style.configure("Muted.TLabel", background="#071323", foreground="#8ba6bc")
        style.configure("Title.TLabel", background="#071323", foreground="#39e5d4", font=("Segoe UI", 19, "bold"))
        style.configure("TButton", padding=(12, 8))
        style.configure("Accent.TButton", background="#20c7bb", foreground="#031417")
        style.map("Accent.TButton", background=[("active", "#55f0df")])
        style.configure("Horizontal.TProgressbar", troughcolor="#142b40", background="#39e5d4", lightcolor="#39e5d4", darkcolor="#39e5d4")

        outer = ttk.Frame(window, padding=22)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="EZCAN IPA BUILDER", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Double-click workflow runner for the unsigned iOS build", style="Muted.TLabel").pack(anchor="w", pady=(2, 18))

        options = ttk.Frame(outer)
        options.pack(fill="x", pady=(0, 14))
        ttk.Label(options, text="Commit message").grid(row=0, column=0, sticky="w")
        self.commit_message = ttk.Entry(options)
        self.commit_message.insert(0, "Build latest Ezcan IPA")
        self.commit_message.grid(row=1, column=0, sticky="ew", padx=(0, 14), pady=(5, 0))
        ttk.Label(options, text="Build timeout (minutes)").grid(row=0, column=1, sticky="w")
        self.timeout = ttk.Spinbox(options, from_=5, to=180, width=8)
        self.timeout.set(str(DEFAULT_TIMEOUT_MINUTES))
        self.timeout.grid(row=1, column=1, sticky="w", pady=(5, 0))
        options.columnconfigure(0, weight=1)

        self.status = ttk.Label(outer, text="Ready. Changes will be committed and pushed automatically.", style="Muted.TLabel")
        self.status.pack(anchor="w", pady=(0, 7))
        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100, style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0, 14))

        log_frame = ttk.Frame(outer)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_frame,
            height=14,
            state="disabled",
            wrap="word",
            bg="#0b1c2d",
            fg="#d7e8f3",
            insertbackground="#d7e8f3",
            relief="flat",
            padx=12,
            pady=10,
        )
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(16, 0))
        ttk.Label(bottom, text="IPA output: artifacts\\ios", style="Muted.TLabel").pack(side="left")
        self.start_button = ttk.Button(bottom, text="Build and download IPA", style="Accent.TButton", command=self.start)
        self.start_button.pack(side="right")

        self.window.after(100, self.process_events)

    def write_log(self, message):
        self.events.put(("log", message))

    def set_progress(self, percent, message):
        self.events.put(("progress", percent, message))

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        commit_message = self.commit_message.get().strip() or "Build latest Ezcan IPA"
        try:
            timeout = int(self.timeout.get())
        except ValueError:
            messagebox.showerror("Invalid timeout", "Build timeout must be a number of minutes.")
            return
        if timeout < 5 or timeout > 180:
            messagebox.showerror("Invalid timeout", "Build timeout must be between 5 and 180 minutes.")
            return

        self.start_button.configure(state="disabled")
        self.progress.configure(value=0)
        self.append_log("Starting Ezcan IPA build...")
        self.worker = threading.Thread(target=self.run_pipeline, args=(commit_message, timeout), daemon=True)
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
                    self.progress.configure(value=event[1])
                    self.status.configure(text=event[2])
                elif event[0] == "success":
                    self.start_button.configure(state="normal")
                    self.progress.configure(value=100)
                    messagebox.showinfo("Ezcan IPA build complete", event[1])
                elif event[0] == "failure":
                    self.start_button.configure(state="normal")
                    messagebox.showerror("Ezcan IPA build failed", event[1])
        except queue.Empty:
            pass
        self.window.after(100, self.process_events)

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
            staged_check = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(ROOT))
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
        self.events.put(("success", "The IPA was built and downloaded to:\n\n{}".format(ipa_path)))

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