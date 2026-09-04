from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import secrets
import socket
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


PROJECT_DIR = Path(__file__).resolve().parent
RECEIVED_DIR = Path(os.environ.get("PHONE_SHARE_DATA_DIR", PROJECT_DIR / "received"))
STATIC_DIR = PROJECT_DIR / "static"
MAX_FILE_SIZE = int(os.environ.get("PHONE_SHARE_MAX_FILE_SIZE", 2 * 1024 * 1024 * 1024))
ACCESS_TOKEN = os.environ.get("PHONE_SHARE_TOKEN") or secrets.token_urlsafe(18)
SERVER_PORT = 8765

app = FastAPI(title="Pocket Drop", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_local_ip() -> str:
    """Find the LAN address that other devices can use to reach this computer."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def check_token(
    query_token: str | None,
    authorization: str | None,
) -> None:
    supplied = query_token
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not secrets.compare_digest(supplied, ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="This share link is not valid.")


def safe_filename(filename: str | None) -> str:
    raw_name = (filename or "untitled").replace("\\", "/")
    cleaned = Path(raw_name).name.strip().replace("\x00", "")
    return cleaned or "untitled"


def available_path(filename: str) -> Path:
    candidate = RECEIVED_DIR / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for number in range(1, 10_000):
        candidate = RECEIVED_DIR / f"{stem} ({number}){suffix}"
        if not candidate.exists():
            return candidate
    raise HTTPException(status_code=507, detail="Too many files with this name.")


def file_details(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "contentType": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "receivedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/session")
def session(
    token: Annotated[str | None, Query()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    check_token(token, authorization)
    local_ip = get_local_ip()
    phone_url = f"http://{local_ip}:{SERVER_PORT}/?token={quote(ACCESS_TOKEN)}&mode=phone"
    return {"phoneUrl": phone_url, "receivedFolder": str(RECEIVED_DIR)}


@app.get("/api/files")
def files(
    token: Annotated[str | None, Query()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    check_token(token, authorization)
    entries = [path for path in RECEIVED_DIR.iterdir() if path.is_file() and not path.name.endswith(".part")]
    entries.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return {"files": [file_details(path) for path in entries]}


@app.post("/api/upload")
def upload(
    upload_file: Annotated[UploadFile, File(...)],
    token: Annotated[str | None, Query()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    check_token(token, authorization)
    RECEIVED_DIR.mkdir(parents=True, exist_ok=True)
    destination = available_path(safe_filename(upload_file.filename))
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(6)}.part")
    digest = hashlib.sha256()
    total_size = 0

    try:
        with temporary.open("wb") as output:
            while chunk := upload_file.file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail="This file is larger than the configured limit.")
                digest.update(chunk)
                output.write(chunk)
        temporary.replace(destination)
    except HTTPException:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Could not save the file: {error}") from error
    finally:
        upload_file.file.close()

    return {
        "file": file_details(destination),
        "sha256": digest.hexdigest(),
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def print_startup_info(port: int) -> None:
    local_ip = get_local_ip()
    desktop_url = f"http://127.0.0.1:{port}/?token={quote(ACCESS_TOKEN)}&mode=desktop"
    phone_url = f"http://{local_ip}:{port}/?token={quote(ACCESS_TOKEN)}&mode=phone"
    print("\nPocket Drop is ready")
    print(f"Computer: {desktop_url}")
    print(f"Phone:    {phone_url}")
    print(f"Saving to: {RECEIVED_DIR}")
    print("Keep this window running while sending files.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Receive files from a phone over local Wi-Fi.")
    parser.add_argument("--host", default="0.0.0.0", help="Network interface to listen on.")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on.")
    args = parser.parse_args()
    SERVER_PORT = args.port
    RECEIVED_DIR.mkdir(parents=True, exist_ok=True)
    print_startup_info(args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
