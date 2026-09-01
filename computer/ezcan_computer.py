from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import sqlite3
import sys
import threading
import uuid
import base64
import tkinter as tk
from tkinter import messagebox, ttk
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterator

import qrcode
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


ARCHIVE_LETTERS = "ABCDEFGHJKLMNPQRTUVWXY"
ARCHIVE_DIGITS = "2346789"
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_VIDEO_BYTES = 300 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def computer_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def safe_file_name(value: str) -> str:
    candidate = Path(value or "upload.bin").name
    cleaned = "".join(character for character in candidate if character.isalnum() or character in ".-_ ")
    cleaned = cleaned.strip().replace(" ", "_")
    return cleaned[:120] or "upload.bin"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_archive_code(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 4
        and value[0].isupper()
        and value[0].isascii()
        and value[0].isalpha()
        and value[1].isascii()
        and value[1].isdigit()
        and value[2].isupper()
        and value[2].isascii()
        and value[2].isalpha()
        and value[3].isascii()
        and value[3].isdigit()
    )


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.incoming = root / "Incoming"
        self.cards = root / "Cards"
        self.backups = root / "Backups"
        self.logs = root / "Logs"
        self.database_path = root / "ezcan.sqlite3"
        for folder in (self.incoming, self.cards, self.backups, self.logs):
            folder.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS intakes (
                    intake_id TEXT PRIMARY KEY,
                    temporary_path TEXT NOT NULL,
                    note TEXT,
                    status TEXT NOT NULL,
                    archive_code TEXT UNIQUE,
                    internal_id TEXT,
                    created_at TEXT NOT NULL,
                    finalized_at TEXT
                );
                CREATE TABLE IF NOT EXISTS media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intake_id TEXT NOT NULL REFERENCES intakes(intake_id),
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(intake_id, file_name)
                );
                CREATE TABLE IF NOT EXISTS cards (
                    internal_id TEXT PRIMARY KEY,
                    archive_code TEXT NOT NULL UNIQUE,
                    folder_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    card_name TEXT,
                    set_name TEXT,
                    card_number TEXT,
                    language TEXT,
                    edition TEXT,
                    printing TEXT,
                    finish TEXT,
                    condition TEXT,
                    authenticity_status TEXT,
                    notes TEXT
                );
                """
            )

    def create_intake(self, note: str | None) -> tuple[str, Path]:
        intake_id = str(uuid.uuid4())
        temporary_path = self.incoming / f"uploading-{intake_id}"
        (temporary_path / "original").mkdir(parents=True)
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO intakes VALUES (?, ?, ?, ?, NULL, NULL, ?, NULL)",
                (intake_id, str(temporary_path), note, "uploading", utc_now()),
            )
        return intake_id, temporary_path

    def intake(self, intake_id: str) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute("SELECT * FROM intakes WHERE intake_id = ?", (intake_id,)).fetchone()

    def media(self, intake_id: str) -> list[sqlite3.Row]:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM media WHERE intake_id = ? ORDER BY id", (intake_id,)
            ).fetchall()

    def add_media(
        self,
        intake_id: str,
        file_name: str,
        file_path: Path,
        media_type: str,
        file_hash: str,
        file_size: int,
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO media (intake_id, file_name, file_path, media_type, file_hash, file_size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (intake_id, file_name, str(file_path), media_type, file_hash, file_size, utc_now()),
            )

    def finalize(self, intake_id: str, requested_archive_code: str | None = None) -> str:
        intake = self.intake(intake_id)
        if intake is None:
            raise HTTPException(status_code=404, detail="Intake not found")
        if intake["archive_code"]:
            return str(intake["archive_code"])
        media = self.media(intake_id)
        if not media:
            raise HTTPException(status_code=400, detail="At least one media file is required")

        archive_code = self.new_archive_code() if requested_archive_code is None else requested_archive_code
        if requested_archive_code is not None and (not isinstance(archive_code, str) or not valid_archive_code(archive_code)):
            raise HTTPException(
                status_code=422,
                detail="Archive code must match uppercase letter-digit-letter-digit format",
            )
        with self.connection() as connection:
            if connection.execute(
                "SELECT 1 FROM cards WHERE archive_code = ? OR archive_code IN (SELECT archive_code FROM intakes WHERE archive_code = ?)",
                (archive_code, archive_code),
            ).fetchone():
                raise HTTPException(status_code=409, detail="Archive code is already in use")
        internal_id = str(uuid.uuid4())
        temporary_path = Path(intake["temporary_path"])
        final_path = self.cards / archive_code
        if final_path.exists():
            raise HTTPException(status_code=409, detail="Archive folder already exists")
        (temporary_path / "generated").mkdir(exist_ok=True)
        (temporary_path / "screenshots").mkdir(exist_ok=True)
        temporary_path.rename(final_path)

        manifest_media = []
        with self.connection() as connection:
            for item in media:
                new_path = final_path / "original" / item["file_name"]
                connection.execute(
                    "UPDATE media SET file_path = ? WHERE id = ?",
                    (str(new_path), item["id"]),
                )
                manifest_media.append(
                    {
                        "fileName": item["file_name"],
                        "type": item["media_type"],
                        "sha256": item["file_hash"],
                        "size": item["file_size"],
                    }
                )
            now = utc_now()
            connection.execute(
                "UPDATE intakes SET status = 'finalized', archive_code = ?, internal_id = ?, finalized_at = ? WHERE intake_id = ?",
                (archive_code, internal_id, now, intake_id),
            )
            connection.execute(
                "INSERT INTO cards (internal_id, archive_code, folder_path, status, created_at, updated_at, notes) VALUES (?, ?, ?, 'received', ?, ?, ?)",
                (internal_id, archive_code, str(final_path), now, now, intake["note"]),
            )

        manifest = {
            "archiveCode": archive_code,
            "internalId": internal_id,
            "intakeId": intake_id,
            "status": "received",
            "createdAt": intake["created_at"],
            "media": manifest_media,
        }
        (final_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return archive_code

    def new_archive_code(self) -> str:
        with self.connection() as connection:
            for _ in range(100):
                code = "".join(
                    (
                        secrets.choice(ARCHIVE_LETTERS),
                        secrets.choice(ARCHIVE_DIGITS),
                        secrets.choice(ARCHIVE_LETTERS),
                        secrets.choice(ARCHIVE_DIGITS),
                    )
                )
                exists = connection.execute(
                    "SELECT 1 FROM cards WHERE archive_code = ? OR archive_code IN (SELECT archive_code FROM intakes WHERE archive_code = ?)",
                    (code, code),
                ).fetchone()
                if exists is None:
                    return code
        raise RuntimeError("Could not generate a unique archive code")

    def recent_cards(self) -> list[sqlite3.Row]:
        with self.connection() as connection:
            return connection.execute("SELECT * FROM cards ORDER BY created_at DESC LIMIT 25").fetchall()

    def dashboard_stats(self) -> tuple[int, int, int]:
        with self.connection() as connection:
            cards = connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            active_intakes = connection.execute(
                "SELECT COUNT(*) FROM intakes WHERE status = 'uploading'"
            ).fetchone()[0]
            media = connection.execute("SELECT COUNT(*) FROM media").fetchone()[0]
        return int(cards), int(active_intakes), int(media)


def program_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def default_data_root() -> Path:
    configured = os.environ.get("EZCAN_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return program_directory() / "Archive"


def create_app(data_root: Path | None = None) -> FastAPI:
    root = data_root or default_data_root()
    store = Store(root)
    token = secrets.token_urlsafe(24)
    app = FastAPI(title="Ezcan Computer", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.token = token
    app.state.port = int(os.environ.get("EZCAN_PORT", "8765"))

    def require_token(request: Request) -> None:
        authorization = request.headers.get("authorization", "")
        received = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(received, app.state.token):
            raise HTTPException(status_code=401, detail="Invalid pairing token")

    def pairing_payload(request: Request) -> dict[str, object]:
        host = computer_ip()
        port = app.state.port
        return {
            "protocol": "ezcan",
            "version": 1,
            "url": f"http://{host}:{port}",
            "token": app.state.token,
            "computerName": socket.gethostname(),
        }

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/pairing")
    async def pairing(request: Request) -> dict[str, object]:
        return pairing_payload(request)

    @app.get("/pairing/qr")
    async def pairing_qr(request: Request) -> StreamingResponse:
        payload = json.dumps(pairing_payload(request), separators=(",", ":"))
        image = qrcode.make(payload)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return StreamingResponse(buffer, media_type="image/png")

    @app.post("/api/pair")
    async def pair(request: Request) -> dict[str, object]:
        body = await request.json()
        if body.get("token") != app.state.token:
            raise HTTPException(status_code=401, detail="Invalid pairing token")
        return {"paired": True, "computerName": socket.gethostname()}

    @app.post("/api/intakes")
    async def create_intake(request: Request) -> JSONResponse:
        require_token(request)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        intake_id, _ = store.create_intake(body.get("note"))
        return JSONResponse({"intakeId": intake_id, "suggestedArchiveCode": store.new_archive_code()})

    @app.post("/api/intakes/{intake_id}/media")
    async def upload_media(intake_id: str, request: Request) -> JSONResponse:
        require_token(request)
        intake = store.intake(intake_id)
        if intake is None:
            raise HTTPException(status_code=404, detail="Intake not found")
        if intake["status"] == "finalized":
            raise HTTPException(status_code=409, detail="Intake is already finalized")
        media_type = request.headers.get("x-ezcan-media-type", "image")
        if media_type not in {"image", "video"}:
            raise HTTPException(status_code=400, detail="Media type must be image or video")
        maximum = MAX_VIDEO_BYTES if media_type == "video" else MAX_IMAGE_BYTES
        file_name = safe_file_name(request.headers.get("x-ezcan-file-name", "upload.bin"))
        expected_hash = request.headers.get("x-ezcan-sha256", "").lower()
        temporary_path = Path(intake["temporary_path"]) / "original"
        destination = temporary_path / file_name
        if destination.exists():
            existing_hash = file_sha256(destination)
            if expected_hash and hmac.compare_digest(existing_hash, expected_hash):
                return JSONResponse({"uploaded": True, "duplicate": True, "fileName": file_name})
            raise HTTPException(status_code=409, detail="A different file already uses this name")

        total = 0
        digest = hashlib.sha256()
        try:
            with destination.open("wb") as output:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > maximum:
                        raise HTTPException(status_code=413, detail="Media file is too large")
                    digest.update(chunk)
                    output.write(chunk)
        except HTTPException:
            destination.unlink(missing_ok=True)
            raise
        actual_hash = digest.hexdigest()
        if expected_hash and not hmac.compare_digest(actual_hash, expected_hash):
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="SHA-256 hash does not match")
        try:
            store.add_media(intake_id, file_name, destination, media_type, actual_hash, total)
        except sqlite3.IntegrityError:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail="Media file was already uploaded")
        return JSONResponse({"uploaded": True, "fileName": file_name, "size": total, "sha256": actual_hash})

    @app.get("/api/intakes/{intake_id}/status")
    async def intake_status(intake_id: str, request: Request) -> dict[str, object]:
        require_token(request)
        intake = store.intake(intake_id)
        if intake is None:
            raise HTTPException(status_code=404, detail="Intake not found")
        return {
            "intakeId": intake_id,
            "status": intake["status"],
            "archiveCode": intake["archive_code"],
            "mediaCount": len(store.media(intake_id)),
        }

    @app.post("/api/intakes/{intake_id}/complete")
    async def complete_intake(intake_id: str, request: Request) -> dict[str, str]:
        require_token(request)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        return {"archiveCode": store.finalize(intake_id, body.get("archiveCode"))}

    return app


class DesktopWindow:
    background = "#0b1020"
    panel = "#121a2b"
    panel_alt = "#18233a"
    border = "#263653"
    text = "#f4f7fb"
    muted = "#91a0b9"
    blue = "#4f8cff"
    green = "#43d39e"

    def __init__(self, application: FastAPI, server: uvicorn.Server):
        self.application = application
        self.server = server
        self.store: Store = application.state.store
        self.root = tk.Tk()
        self.root.title("Ezcan Computer")
        self.root.geometry("1180x780")
        self.root.minsize(940, 650)
        self.root.configure(bg=self.background)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.address = f"http://{computer_ip()}:{application.state.port}"
        self.address_var = tk.StringVar(value=self.address)
        self.connection_var = tk.StringVar(value="ONLINE  •  PRIVATE NETWORK")
        self.archive_var = tk.StringVar(value=str(self.store.root))
        self.cards_var = tk.StringVar(value="0")
        self.active_var = tk.StringVar(value="0")
        self.media_var = tk.StringVar(value="0")
        self.updated_var = tk.StringVar(value="Waiting for activity")
        self.qr_photo: tk.PhotoImage | None = None
        self.tree: ttk.Treeview
        self.build_styles()
        self.build_layout()
        self.refresh()

    def build_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Ezcan.Treeview",
            background=self.panel,
            fieldbackground=self.panel,
            foreground=self.text,
            borderwidth=0,
            rowheight=42,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Ezcan.Treeview.Heading",
            background=self.panel_alt,
            foreground=self.muted,
            borderwidth=0,
            font=("Segoe UI Semibold", 9),
        )
        style.map("Ezcan.Treeview", background=[("selected", "#25477d")], foreground=[("selected", self.text)])

    def build_layout(self) -> None:
        header = tk.Frame(self.root, bg=self.background)
        header.pack(fill="x", padx=34, pady=(28, 18))

        brand = tk.Frame(header, bg=self.background)
        brand.pack(side="left")
        tk.Label(
            brand,
            text="EZCAN",
            bg=self.background,
            fg=self.text,
            font=("Segoe UI Black", 27),
        ).pack(anchor="w")
        tk.Label(
            brand,
            text="CARD OPERATIONS CONSOLE",
            bg=self.background,
            fg=self.blue,
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w")

        status = tk.Label(
            header,
            textvariable=self.connection_var,
            bg="#12382f",
            fg=self.green,
            padx=14,
            pady=8,
            font=("Segoe UI Semibold", 9),
        )
        status.pack(side="right", anchor="n", pady=5)

        body = tk.Frame(self.root, bg=self.background)
        body.pack(fill="both", expand=True, padx=34, pady=(0, 24))
        body.grid_columnconfigure(0, weight=0, minsize=330)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.build_pairing_panel(body).grid(row=0, column=0, sticky="nsew", padx=(0, 22))
        right = tk.Frame(body, bg=self.background)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)
        self.build_stats(right).grid(row=0, column=0, sticky="ew")
        self.build_archive_bar(right).grid(row=1, column=0, sticky="ew", pady=(22, 14))
        self.build_cards_table(right).grid(row=2, column=0, sticky="nsew")

    def build_pairing_panel(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.panel, highlightthickness=1, highlightbackground=self.border)
        tk.Label(
            frame,
            text="PAIR DEVICE",
            bg=self.panel,
            fg=self.text,
            font=("Segoe UI Semibold", 13),
        ).pack(anchor="w", padx=24, pady=(24, 3))
        tk.Label(
            frame,
            text="Scan this code in the Ezcan iOS app",
            bg=self.panel,
            fg=self.muted,
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=24)

        qr_frame = tk.Frame(frame, bg="#ffffff", width=240, height=240)
        qr_frame.pack(padx=24, pady=22)
        qr_frame.pack_propagate(False)
        payload = json.dumps(
            {
                "protocol": "ezcan",
                "version": 1,
                "url": self.address,
                "token": self.application.state.token,
                "computerName": socket.gethostname(),
            },
            separators=(",", ":"),
        )
        image = qrcode.make(payload)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        self.qr_photo = tk.PhotoImage(data=base64.b64encode(buffer.getvalue()).decode("ascii"))
        tk.Label(qr_frame, image=self.qr_photo, bg="#ffffff").place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            frame,
            text="COMPUTER ADDRESS",
            bg=self.panel,
            fg=self.muted,
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", padx=24)
        address_label = tk.Label(
            frame,
            textvariable=self.address_var,
            bg=self.panel,
            fg=self.text,
            font=("Consolas", 10),
            cursor="hand2",
        )
        address_label.pack(anchor="w", padx=24, pady=(4, 12))
        address_label.bind("<Button-1>", lambda _event: self.copy_text(self.address))

        tk.Button(
            frame,
            text="Copy address",
            command=lambda: self.copy_text(self.address),
            bg=self.panel_alt,
            fg=self.text,
            activebackground=self.border,
            activeforeground=self.text,
            relief="flat",
            borderwidth=0,
            padx=14,
            pady=9,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        ).pack(anchor="w", padx=24, pady=(0, 24))
        return frame

    def build_stats(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.background)
        for column in range(3):
            frame.grid_columnconfigure(column, weight=1)
        self.stat_card(frame, "ARCHIVED CARDS", self.cards_var, self.blue, 0)
        self.stat_card(frame, "ACTIVE INTAKES", self.active_var, "#f2b84b", 1)
        self.stat_card(frame, "MEDIA RECEIVED", self.media_var, self.green, 2)
        return frame

    def stat_card(self, parent: tk.Misc, label: str, value: tk.StringVar, accent: str, column: int) -> None:
        card = tk.Frame(parent, bg=self.panel, highlightthickness=1, highlightbackground=self.border)
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 8 if column < 2 else 0))
        tk.Frame(card, bg=accent, height=3).pack(fill="x")
        tk.Label(card, text=label, bg=self.panel, fg=self.muted, font=("Segoe UI Semibold", 8)).pack(
            anchor="w", padx=16, pady=(15, 3)
        )
        tk.Label(card, textvariable=value, bg=self.panel, fg=self.text, font=("Segoe UI Black", 25)).pack(
            anchor="w", padx=16, pady=(0, 14)
        )

    def build_archive_bar(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.panel, highlightthickness=1, highlightbackground=self.border)
        left = tk.Frame(frame, bg=self.panel)
        left.pack(side="left", fill="x", expand=True, padx=18, pady=13)
        tk.Label(left, text="ARCHIVE LOCATION", bg=self.panel, fg=self.muted, font=("Segoe UI Semibold", 8)).pack(anchor="w")
        tk.Label(left, textvariable=self.archive_var, bg=self.panel, fg=self.text, font=("Consolas", 9)).pack(anchor="w", pady=(3, 0))
        tk.Button(
            frame,
            text="Open Archive",
            command=self.open_archive,
            bg=self.blue,
            fg="white",
            activebackground="#6ea3ff",
            activeforeground="white",
            relief="flat",
            borderwidth=0,
            padx=15,
            pady=9,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        ).pack(side="right", padx=14, pady=12)
        return frame

    def build_cards_table(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.panel, highlightthickness=1, highlightbackground=self.border)
        heading = tk.Frame(frame, bg=self.panel)
        heading.pack(fill="x", padx=20, pady=(18, 10))
        tk.Label(heading, text="RECENT ARCHIVE ACTIVITY", bg=self.panel, fg=self.text, font=("Segoe UI Semibold", 13)).pack(side="left")
        tk.Label(heading, textvariable=self.updated_var, bg=self.panel, fg=self.muted, font=("Segoe UI", 9)).pack(side="right")
        table_frame = tk.Frame(frame, bg=self.panel)
        table_frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.tree = ttk.Treeview(
            table_frame,
            columns=("code", "status", "folder", "created"),
            show="headings",
            style="Ezcan.Treeview",
        )
        headings = {"code": "ARCHIVE CODE", "status": "STATUS", "folder": "FOLDER", "created": "RECEIVED"}
        widths = {"code": 130, "status": 120, "folder": 300, "created": 150}
        for column, title in headings.items():
            self.tree.heading(column, text=title, anchor="w")
            self.tree.column(column, width=widths[column], anchor="w", stretch=column in {"folder", "created"})
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return frame

    def refresh(self) -> None:
        cards, active_intakes, media = self.store.dashboard_stats()
        self.cards_var.set(str(cards))
        self.active_var.set(str(active_intakes))
        self.media_var.set(str(media))
        for item in self.tree.get_children():
            self.tree.delete(item)
        for card in self.store.recent_cards():
            created = str(card["created_at"]).replace("T", " ")[:19]
            self.tree.insert(
                "",
                "end",
                values=(card["archive_code"], str(card["status"]).upper(), card["folder_path"], created),
            )
        self.updated_var.set(f"Updated {datetime.now().strftime('%H:%M:%S')}")
        self.root.after(1500, self.refresh)

    def copy_text(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.connection_var.set("ADDRESS COPIED  •  PRIVATE NETWORK")
        self.root.after(2200, lambda: self.connection_var.set("ONLINE  •  PRIVATE NETWORK"))

    def open_archive(self) -> None:
        try:
            if not hasattr(os, "startfile"):
                raise OSError("Opening the archive folder is supported on Windows only")
            os.startfile(str(self.store.root))
        except OSError as error:
            messagebox.showerror("Ezcan Archive", f"Could not open the archive folder.\n\n{error}")

    def close(self) -> None:
        self.server.should_exit = True
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def start() -> None:
    app = create_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=app.state.port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True, name="ezcan-api").start()
    DesktopWindow(app, server).run()

if __name__ == "__main__":
    start()
