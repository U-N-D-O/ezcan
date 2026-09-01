from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import shutil
import socket
import sqlite3
import threading
import uuid
import webbrowser
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterator

import qrcode
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse


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

    def finalize(self, intake_id: str) -> str:
        intake = self.intake(intake_id)
        if intake is None:
            raise HTTPException(status_code=404, detail="Intake not found")
        if intake["archive_code"]:
            return str(intake["archive_code"])
        media = self.media(intake_id)
        if not media:
            raise HTTPException(status_code=400, detail="At least one media file is required")

        archive_code = self.new_archive_code()
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


def default_data_root() -> Path:
    configured = os.environ.get("EZCAN_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Ezcan"
    return Path.home() / "Ezcan"


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
        return JSONResponse({"intakeId": intake_id})

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
        return {"archiveCode": store.finalize(intake_id)}

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        cards = store.recent_cards()
        card_rows = "".join(
            f"<tr><td><strong>{html.escape(card['archive_code'])}</strong></td>"
            f"<td>{html.escape(card['status'])}</td><td>{html.escape(card['folder_path'])}</td></tr>"
            for card in cards
        )
        payload = html.escape(json.dumps(pairing_payload(Request(scope={"type": "http", "headers": []}))))
        return f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Ezcan Computer</title>
<style>body{{font-family:Segoe UI,system-ui,sans-serif;max-width:1000px;margin:0 auto;padding:32px;color:#202124;background:#f5f7f8}}main{{background:white;padding:28px;border-radius:12px;box-shadow:0 3px 14px #0001}}h1{{margin-top:0}}.grid{{display:grid;grid-template-columns:220px 1fr;gap:24px;align-items:center}}img{{width:200px;height:200px;border:1px solid #ddd}}code{{word-break:break-all}}table{{border-collapse:collapse;width:100%;margin-top:18px}}td,th{{border-bottom:1px solid #ddd;text-align:left;padding:10px 6px}}.muted{{color:#5f6368}}</style></head>
<body><main><h1>Ezcan Computer</h1><p class=\"muted\">Receive card media from the paired iPhone over your private Wi-Fi network.</p>
<div class=\"grid\"><img src=\"/pairing/qr\" alt=\"Pairing QR code\"><div><h2>Pair this computer</h2><p>Scan this code in the Ezcan iOS app.</p><p><strong>Address</strong><br><code id=\"address\"></code></p><p><strong>Pairing payload</strong><br><code>{payload}</code></p></div></div>
<h2>Archived cards</h2><table><thead><tr><th>Archive code</th><th>Status</th><th>Folder</th></tr></thead><tbody>{card_rows or '<tr><td colspan=\"3\" class=\"muted\">No cards received yet.</td></tr>'}</tbody></table>
<script>fetch('/api/pairing').then(r=>r.json()).then(p=>document.getElementById('address').textContent=p.url)</script></main></body></html>"""

    return app


def start() -> None:
    port = int(os.environ.get("EZCAN_PORT", "8765"))
    app = create_app()
    url = f"http://{computer_ip()}:{port}"
    print(f"Ezcan Computer is running at {url}")
    print(f"Data folder: {app.state.store.root}")
    if os.environ.get("EZCAN_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


app = create_app()

if __name__ == "__main__":
    start()
