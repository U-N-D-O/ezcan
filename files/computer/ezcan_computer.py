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
import webbrowser
from tkinter import filedialog, messagebox, ttk
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterator

import qrcode
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ebay import open_picture_search
from image_processor import IMAGE_SUFFIXES, prepare_search_image
from listing_drafts import build_listing_draft
from pricing import PricingRecommendation, recommend_price


SEQUENTIAL_ARCHIVE_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SEQUENTIAL_ARCHIVE_DIGITS = "0123456789"
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_VIDEO_BYTES = 300 * 1024 * 1024
MAX_SHARED_FILE_BYTES = 1024 * 1024 * 1024
SUPPORTED_LANGUAGES = {"japanese", "english"}
SUPPORTED_CONDITIONS = {"near_mint", "excellent", "very_good", "good", "played", "poor", "graded"}
SUPPORTED_GRADING_COMPANIES = {"none", "psa", "bgs", "cgc", "other"}


def pairing_qr_image(payload: str, target_pixels: int):
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    total_modules = qr.modules_count + (qr.border * 2)
    qr.box_size = max(1, target_pixels // total_modules)
    return qr.make_image(fill_color="black", back_color="white")


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


def validate_card_details(details: dict[str, str]) -> dict[str, str]:
    language = details.get("language", "japanese")
    condition = details.get("condition", "near_mint")
    grade_company = details.get("gradeCompany", "none")
    grade = details.get("grade", "")
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Language must be Japanese or English")
    if condition not in SUPPORTED_CONDITIONS:
        raise HTTPException(status_code=422, detail="Unsupported card condition")
    if grade_company not in SUPPORTED_GRADING_COMPANIES:
        raise HTTPException(status_code=422, detail="Unsupported grading company")
    if grade_company == "none" and grade:
        raise HTTPException(status_code=422, detail="Ungraded cards cannot have a grade")
    if grade_company != "none" and not grade:
        raise HTTPException(status_code=422, detail="A grade is required for graded cards")
    return {
        "language": language,
        "condition": condition,
        "gradeCompany": grade_company,
        "grade": grade,
        "authenticityStatus": "authenticated",
    }


def increment_archive_code(value: str) -> str:
    if not valid_archive_code(value):
        raise ValueError("Archive code must match uppercase letter-digit-letter-digit format")
    characters = list(value)
    alphabets = (
        SEQUENTIAL_ARCHIVE_LETTERS,
        SEQUENTIAL_ARCHIVE_DIGITS,
        SEQUENTIAL_ARCHIVE_LETTERS,
        SEQUENTIAL_ARCHIVE_DIGITS,
    )
    for index in (3, 2, 1, 0):
        alphabet = alphabets[index]
        position = alphabet.index(characters[index])
        if position < len(alphabet) - 1:
            characters[index] = alphabet[position + 1]
            return "".join(characters)
        characters[index] = alphabet[0]
    raise ValueError("Archive code sequence is exhausted")


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.incoming = root / "Incoming"
        self.cards = root / "Cards"
        self.to_iphone = root / "To iPhone"
        self.backups = root / "Backups"
        self.logs = root / "Logs"
        self.database_path = root / "ezcan.sqlite3"
        for folder in (self.incoming, self.cards, self.to_iphone, self.backups, self.logs):
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
                    grade_company TEXT,
                    grade TEXT,
                    authenticity_status TEXT,
                    notes TEXT
                );
                CREATE TABLE IF NOT EXISTS archive_sequence (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    latest_code TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ebay_searches (
                    search_id TEXT PRIMARY KEY,
                    internal_id TEXT NOT NULL,
                    archive_code TEXT NOT NULL,
                    prepared_image_path TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS ebay_candidates (
                    candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    search_id TEXT NOT NULL,
                    internal_id TEXT NOT NULL,
                    archive_code TEXT NOT NULL,
                    market_status TEXT NOT NULL,
                    item_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    sale_or_listing_date TEXT,
                    price REAL NOT NULL,
                    shipping_price REAL NOT NULL,
                    total_buyer_cost REAL NOT NULL,
                    condition TEXT,
                    grade TEXT,
                    listing_format TEXT,
                    seller_notes TEXT,
                    screenshot_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS listings (
                    listing_id TEXT PRIMARY KEY,
                    internal_id TEXT NOT NULL,
                    archive_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    draft_path TEXT NOT NULL,
                    suggested_price_low REAL NOT NULL,
                    suggested_price_high REAL NOT NULL,
                    shipping_price REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(cards)")}
            if "grade_company" not in columns:
                connection.execute("ALTER TABLE cards ADD COLUMN grade_company TEXT")
            if "grade" not in columns:
                connection.execute("ALTER TABLE cards ADD COLUMN grade TEXT")

    def create_intake(self, note: str | None) -> tuple[str, Path, str]:
        intake_id = str(uuid.uuid4())
        temporary_path = self.incoming / f"uploading-{intake_id}"
        (temporary_path / "original").mkdir(parents=True)
        archive_code = self.new_archive_code()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO intakes VALUES (?, ?, ?, ?, ?, NULL, ?, NULL)",
                (intake_id, str(temporary_path), note, "uploading", archive_code, utc_now()),
            )
        return intake_id, temporary_path, archive_code

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

    def finalize(
        self,
        intake_id: str,
        requested_archive_code: str | None = None,
        details: dict[str, str] | None = None,
    ) -> str:
        intake = self.intake(intake_id)
        if intake is None:
            raise HTTPException(status_code=404, detail="Intake not found")
        if intake["status"] == "finalized":
            return str(intake["archive_code"])
        media = self.media(intake_id)
        if not media:
            raise HTTPException(status_code=400, detail="At least one media file is required")
        card_details = validate_card_details(details or {})

        if requested_archive_code:
            archive_code = requested_archive_code
        else:
            archive_code = intake["archive_code"] or self.new_archive_code()
        if requested_archive_code and (not isinstance(archive_code, str) or not valid_archive_code(archive_code)):
            raise HTTPException(
                status_code=422,
                detail="Archive code must match uppercase letter-digit-letter-digit format",
            )
        with self.connection() as connection:
            if connection.execute(
                "SELECT 1 FROM cards WHERE archive_code = ? UNION ALL SELECT 1 FROM intakes WHERE archive_code = ? AND intake_id != ?",
                (archive_code, archive_code, intake_id),
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
                "INSERT INTO archive_sequence (id, latest_code) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET latest_code = excluded.latest_code",
                (archive_code,),
            )
            connection.execute(
                "INSERT INTO cards (internal_id, archive_code, folder_path, status, created_at, updated_at, language, condition, grade_company, grade, authenticity_status, notes) VALUES (?, ?, ?, 'received', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    internal_id,
                    archive_code,
                    str(final_path),
                    now,
                    now,
                    card_details["language"],
                    card_details["condition"],
                    card_details["gradeCompany"],
                    card_details["grade"],
                    card_details["authenticityStatus"],
                    intake["note"],
                ),
            )

        manifest = {
            "archiveCode": archive_code,
            "internalId": internal_id,
            "intakeId": intake_id,
            "status": "received",
            "createdAt": intake["created_at"],
            "listingDetails": card_details,
            "media": manifest_media,
        }
        (final_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return archive_code

    def new_archive_code(self) -> str:
        with self.connection() as connection:
            row = connection.execute("SELECT latest_code FROM archive_sequence WHERE id = 1").fetchone()
        candidate = "A0A0" if row is None else increment_archive_code(str(row["latest_code"]))
        with self.connection() as connection:
            for _ in range(26 * 10 * 26 * 10):
                exists = connection.execute(
                    "SELECT 1 FROM cards WHERE archive_code = ? OR archive_code IN (SELECT archive_code FROM intakes WHERE archive_code = ?)",
                    (candidate, candidate),
                ).fetchone()
                if exists is None:
                    connection.execute(
                        "INSERT INTO archive_sequence (id, latest_code) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET latest_code = excluded.latest_code",
                        (candidate,),
                    )
                    return candidate
                candidate = increment_archive_code(candidate)
        raise RuntimeError("Could not generate a unique archive code")

    def recent_cards(self) -> list[sqlite3.Row]:
        with self.connection() as connection:
            return connection.execute("SELECT * FROM cards ORDER BY created_at DESC LIMIT 25").fetchall()

    def card_by_archive_code(self, archive_code: str) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM cards WHERE archive_code = ?", (archive_code,)
            ).fetchone()

    def start_ebay_search(self, card: sqlite3.Row, image_path: Path) -> str:
        search_id = str(uuid.uuid4())
        now = utc_now()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO ebay_searches (search_id, internal_id, archive_code, prepared_image_path, mode, status, started_at) VALUES (?, ?, ?, ?, 'browser_assisted', 'started', ?)",
                (search_id, card["internal_id"], card["archive_code"], str(image_path), now),
            )
            connection.execute(
                "UPDATE cards SET status = 'searching', updated_at = ? WHERE internal_id = ?",
                (now, card["internal_id"]),
            )
        return search_id

    def finish_ebay_search(self, search_id: str, status: str, error: str | None = None) -> None:
        if status not in {"awaiting_manual_upload", "failed"}:
            raise ValueError("Unsupported eBay search status")
        now = utc_now()
        with self.connection() as connection:
            connection.execute(
                "UPDATE ebay_searches SET status = ?, completed_at = ?, error = ? WHERE search_id = ?",
                (status, now, error, search_id),
            )

    def latest_ebay_search(self, archive_code: str) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM ebay_searches WHERE archive_code = ? ORDER BY started_at DESC LIMIT 1",
                (archive_code,),
            ).fetchone()

    def add_ebay_candidate(self, search_id: str, candidate: dict[str, object]) -> int:
        market_status = str(candidate.get("market_status", "")).strip().lower()
        if market_status not in {"sold", "active"}:
            raise ValueError("Market status must be sold or active")
        title = str(candidate.get("title", "")).strip()
        item_url = str(candidate.get("item_url", "")).strip()
        if not title:
            raise ValueError("A candidate title is required")
        if not item_url.startswith(("http://", "https://")):
            raise ValueError("A valid eBay listing URL is required")
        try:
            price = float(candidate.get("price", 0))
            shipping_price = float(candidate.get("shipping_price", 0))
        except (TypeError, ValueError) as error:
            raise ValueError("Item and shipping prices must be numbers") from error
        if price < 0 or shipping_price < 0:
            raise ValueError("Item and shipping prices cannot be negative")
        with self.connection() as connection:
            search = connection.execute(
                "SELECT internal_id, archive_code FROM ebay_searches WHERE search_id = ?",
                (search_id,),
            ).fetchone()
            if search is None:
                raise ValueError("eBay search session was not found")
            cursor = connection.execute(
                """INSERT INTO ebay_candidates (
                    search_id, internal_id, archive_code, market_status, item_url, title,
                    sale_or_listing_date, price, shipping_price, total_buyer_cost,
                    condition, grade, listing_format, seller_notes, screenshot_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    search_id,
                    search["internal_id"],
                    search["archive_code"],
                    market_status,
                    item_url,
                    title,
                    str(candidate.get("sale_or_listing_date", "")).strip() or None,
                    price,
                    shipping_price,
                    price + shipping_price,
                    str(candidate.get("condition", "")).strip() or None,
                    str(candidate.get("grade", "")).strip() or None,
                    str(candidate.get("listing_format", "")).strip() or None,
                    str(candidate.get("seller_notes", "")).strip() or None,
                    str(candidate.get("screenshot_path", "")).strip() or None,
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE ebay_searches SET status = 'candidate_recorded' WHERE search_id = ?",
                (search_id,),
            )
            return int(cursor.lastrowid)

    def ebay_candidates(self, archive_code: str) -> list[sqlite3.Row]:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM ebay_candidates WHERE archive_code = ? ORDER BY created_at DESC",
                (archive_code,),
            ).fetchall()

    def market_recommendation(self, archive_code: str) -> PricingRecommendation:
        card = self.card_by_archive_code(archive_code)
        if card is None:
            raise ValueError("Card was not found")
        if card["status"] != "identified":
            raise ValueError("Confirm the card identity before calculating pricing")
        return recommend_price(dict(candidate) for candidate in self.ebay_candidates(archive_code))

    def create_listing_draft(self, archive_code: str) -> Path:
        card = self.card_by_archive_code(archive_code)
        if card is None:
            raise ValueError("Card was not found")
        if card["status"] != "identified":
            raise ValueError("Confirm the card identity before creating a listing draft")
        recommendation = self.market_recommendation(archive_code)
        card_folder = Path(card["folder_path"])
        image_paths = [
            str(path)
            for path in sorted((card_folder / "original").iterdir())
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ]
        if not image_paths:
            raise ValueError("At least one archived card image is required")
        draft = build_listing_draft(dict(card), recommendation, image_paths)
        draft_path = card_folder / "generated" / "listing-draft.json"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
        listing_id = str(uuid.uuid4())
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO listings (
                    listing_id, internal_id, archive_code, status, draft_path,
                    suggested_price_low, suggested_price_high, shipping_price, created_at
                ) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?)""",
                (
                    listing_id,
                    card["internal_id"],
                    archive_code,
                    str(draft_path),
                    float(recommendation.suggested_item_low),
                    float(recommendation.suggested_item_high),
                    float(recommendation.owner_shipping_charge),
                    utc_now(),
                ),
            )
        return draft_path

    def latest_listing_draft(self, archive_code: str) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM listings WHERE archive_code = ? ORDER BY created_at DESC LIMIT 1",
                (archive_code,),
            ).fetchone()

    def confirm_card_identity(self, archive_code: str, identity: dict[str, object]) -> None:
        card_name = str(identity.get("card_name", "")).strip()
        set_name = str(identity.get("set_name", "")).strip()
        card_number = str(identity.get("card_number", "")).strip()
        if not card_name or not set_name or not card_number:
            raise ValueError("Card name, set, and card number are required")
        now = utc_now()
        with self.connection() as connection:
            card = connection.execute(
                "SELECT internal_id FROM cards WHERE archive_code = ?", (archive_code,)
            ).fetchone()
            search = connection.execute(
                "SELECT search_id FROM ebay_searches WHERE archive_code = ? ORDER BY started_at DESC LIMIT 1",
                (archive_code,),
            ).fetchone()
            if card is None or search is None:
                raise ValueError("An eBay search session is required before identity confirmation")
            if connection.execute(
                "SELECT 1 FROM ebay_candidates WHERE archive_code = ? LIMIT 1", (archive_code,)
            ).fetchone() is None:
                raise ValueError("Record at least one eBay match before confirming identity")
            connection.execute(
                """UPDATE cards SET card_name = ?, set_name = ?, card_number = ?, edition = ?,
                    printing = ?, finish = ?, status = 'identified', updated_at = ?
                    WHERE archive_code = ?""",
                (
                    card_name,
                    set_name,
                    card_number,
                    str(identity.get("edition", "")).strip() or None,
                    str(identity.get("printing", "")).strip() or None,
                    str(identity.get("finish", "")).strip() or None,
                    now,
                    archive_code,
                ),
            )
            connection.execute(
                "UPDATE ebay_searches SET status = 'identity_confirmed', completed_at = ? WHERE search_id = ?",
                (now, search["search_id"]),
            )

    def shared_files(self) -> list[dict[str, object]]:
        files = []
        for path in sorted(self.to_iphone.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            if path.is_file():
                stat = path.stat()
                files.append(
                    {
                        "fileName": path.name,
                        "size": stat.st_size,
                        "modifiedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    }
                )
        return files

    def shared_file(self, file_name: str) -> Path | None:
        if safe_file_name(file_name) != file_name:
            return None
        path = self.to_iphone / file_name
        return path if path.is_file() else None

    def add_shared_file(self, source: Path) -> Path:
        if not source.is_file():
            raise ValueError("The selected file no longer exists")
        if source.stat().st_size > MAX_SHARED_FILE_BYTES:
            raise ValueError("The selected file is larger than 1 GB")
        file_name = safe_file_name(source.name)
        destination = self.to_iphone / file_name
        counter = 2
        while destination.exists():
            destination = self.to_iphone / f"{source.stem}_{counter}{source.suffix}"
            counter += 1
        shutil.copy2(source, destination)
        return destination

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
        image = pairing_qr_image(payload, target_pixels=420)
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

    @app.get("/api/shared-files")
    async def shared_files(request: Request) -> dict[str, list[dict[str, object]]]:
        require_token(request)
        return {"files": store.shared_files()}

    @app.get("/api/shared-files/{file_name}")
    async def download_shared_file(file_name: str, request: Request) -> FileResponse:
        require_token(request)
        path = store.shared_file(file_name)
        if path is None:
            raise HTTPException(status_code=404, detail="Shared file not found")
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @app.post("/api/intakes")
    async def create_intake(request: Request) -> JSONResponse:
        require_token(request)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        intake_id, _, archive_code = store.create_intake(body.get("note"))
        return JSONResponse({"intakeId": intake_id, "suggestedArchiveCode": archive_code})

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
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="Completion payload must be an object")
        details = body.get("listingDetails", {})
        if not isinstance(details, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in details.items()):
            raise HTTPException(status_code=422, detail="Listing details must contain text values")
        return {"archiveCode": store.finalize(intake_id, body.get("archiveCode"), details)}

    return app


class DesktopWindow:
    background = "#eef2f6"
    panel = "#ffffff"
    panel_alt = "#f5fbfb"
    panel_deep = "#f8fbfb"
    border = "#d8e4e6"
    border_bright = "#12c7d1"
    text = "#102033"
    muted = "#6d7d8c"
    cyan = "#12c7d1"
    blue = "#006bb3"
    magenta = "#d94d78"
    green = "#32c77b"
    amber = "#eab849"

    def __init__(self, application: FastAPI, server: uvicorn.Server, server_thread: threading.Thread | None = None):
        self.application = application
        self.server = server
        self.server_thread = server_thread
        self.closing = False
        self.store: Store = application.state.store
        self.root = tk.Tk()
        self.root.title("Ezcan Card Workbench")
        self.root.geometry("1220x820")
        self.root.minsize(980, 680)
        self.root.configure(bg=self.background)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.address = f"http://{computer_ip()}:{application.state.port}"
        self.address_var = tk.StringVar(value=self.address)
        self.connection_var = tk.StringVar(value="ONLINE - PRIVATE NETWORK")
        self.archive_var = tk.StringVar(value=str(self.store.root))
        self.transfer_var = tk.StringVar(value="No files queued")
        self.cards_var = tk.StringVar(value="0")
        self.active_var = tk.StringVar(value="0")
        self.media_var = tk.StringVar(value="0")
        self.updated_var = tk.StringVar(value="Waiting for activity")
        self.research_var = tk.StringVar(value="Select an archived card to search")
        self.candidate_var = tk.StringVar(value="Record a selected eBay result")
        self.identity_var = tk.StringVar(value="Confirm the exact card identity")
        self.draft_var = tk.StringVar(value="Create a local draft after confirmation")
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
            background=self.panel_deep,
            fieldbackground=self.panel_deep,
            foreground=self.text,
            borderwidth=0,
            rowheight=38,
            font=("Consolas", 9),
        )
        style.configure(
            "Ezcan.Treeview.Heading",
            background=self.panel_alt,
            foreground=self.cyan,
            borderwidth=0,
            font=("Consolas", 8),
        )
        style.map("Ezcan.Treeview", background=[("selected", "#d8f5f6")], foreground=[("selected", self.text)])
        style.configure(
            "Ezcan.Vertical.TScrollbar",
            background="#a9dfe1",
            darkcolor="#d8e4e6",
            lightcolor="#a9dfe1",
            troughcolor="#edf4f5",
            bordercolor="#edf4f5",
            arrowcolor=self.cyan,
            relief="flat",
            borderwidth=0,
        )

    def build_background(self) -> None:
        self.background_canvas = tk.Canvas(
            self.root,
            bg=self.background,
            bd=0,
            highlightthickness=0,
        )
        self.background_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.background_canvas.bind("<Configure>", self.draw_background)

    def draw_background(self, event: tk.Event) -> None:
        canvas = event.widget
        canvas.delete("grid")
        width = max(1, event.width)
        height = max(1, event.height)
        for x in range(24, width, 42):
            canvas.create_line(x, 0, x, height, fill="#e3edef", tags="grid")
        for y in range(24, height, 42):
            canvas.create_line(0, y, width, y, fill="#e3edef", tags="grid")

        points = [
            (0.03, 0.16), (0.14, 0.08), (0.28, 0.14), (0.42, 0.06),
            (0.56, 0.16), (0.72, 0.07), (0.88, 0.17), (0.98, 0.09),
            (0.04, 0.78), (0.18, 0.9), (0.34, 0.82), (0.52, 0.94),
            (0.7, 0.84), (0.86, 0.93), (0.98, 0.76),
        ]
        coordinates = [(int(width * x), int(height * y)) for x, y in points]
        for first, second in zip(coordinates, coordinates[1:]):
            canvas.create_line(*first, *second, fill="#d4e5e7", width=1, tags="grid")
        for x, y in coordinates:
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#a9dfe1", outline=self.cyan, tags="grid")
        for x, y in coordinates[::2]:
            canvas.create_line(x, y, x + 26, y, fill="#c4dfe1", tags="grid")
            canvas.create_line(x + 26, y, x + 26, y + 18, fill="#c4dfe1", tags="grid")
        canvas.create_line(0, 1, width, 1, fill="#b5dadd", tags="grid")

    def panel_texture(self, parent: tk.Misc, accent: str) -> tk.Canvas:
        texture = tk.Canvas(parent, bg=self.panel, bd=0, highlightthickness=0)
        texture.place(relx=0, rely=0, relwidth=1, relheight=1)
        texture.create_line(12, 14, 84, 14, fill=accent, width=2)
        texture.create_line(12, 18, 54, 18, fill="#c6e0e2")
        texture.create_line(14, 18, 14, 66, fill="#dbeaec")
        texture.create_line(14, 66, 78, 66, fill="#dbeaec")
        texture.create_oval(10, 62, 18, 70, fill=accent, outline="")
        texture.create_line(0, 78, 62, 78, fill="#dbeaec")
        texture.create_line(62, 78, 82, 58, fill="#dbeaec")
        texture.create_line(62, 78, 62, 112, fill="#dbeaec")
        texture.create_oval(58, 108, 66, 116, fill="#a9dfe1", outline="")
        texture.tk.call("lower", texture._w)
        return texture

    def rounded_button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        width: int,
        color: str,
        foreground: str = "white",
    ) -> tk.Canvas:
        height = 52
        state = {"pressed": False}
        button = tk.Canvas(
            parent,
            width=width,
            height=height,
            bg=parent.cget("bg"),
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )

        def rounded_shape(left: float, top: float, right: float, bottom: float, fill: str, outline: str = "") -> None:
            radius = (bottom - top) / 2
            button.create_rectangle(left + radius, top, right - radius, bottom, fill=fill, outline=outline)
            button.create_rectangle(left, top + radius, right, bottom - radius, fill=fill, outline=outline)
            button.create_oval(left, top, left + radius * 2, bottom, fill=fill, outline=outline)
            button.create_oval(right - radius * 2, top, right, bottom, fill=fill, outline=outline)

        def paint() -> None:
            button.delete("all")
            offset = 3 if state["pressed"] else 0
            rounded_shape(2, 6 + offset, width - 2, height - 1 + offset, "#b8c4d0")
            rounded_shape(0, 2 + offset, width - 4, height - 5 + offset, "#654358", "#654358")
            rounded_shape(3, 5 + offset, width - 7, height - 8 + offset, "#170928")
            rounded_shape(5, 7 + offset, width - 9, height - 10 + offset, "#1d0d33")
            rounded_shape(5, 7 + offset, width - 9, height // 2 + offset, "#654358")
            rounded_shape(5, height // 2 - 1 + offset, width - 9, height - 10 + offset, "#170928")
            button.create_text(width // 2 - 7, height // 2 - 2 + offset, text=text, fill=foreground, font=("Segoe UI", 10, "bold"), tags="label")
            button.create_text(width - 22, height // 2 - 2 + offset, text="→", fill=foreground, font=("Segoe UI", 16, "bold"), tags="icon")

        def press(_event: tk.Event) -> None:
            state["pressed"] = True
            paint()

        def release(_event: tk.Event) -> None:
            state["pressed"] = False
            paint()
            command()

        paint()
        button.bind("<ButtonPress-1>", press)
        button.bind("<ButtonRelease-1>", release)
        return button

    def build_layout(self) -> None:
        shell = tk.Frame(self.root, bg=self.background)
        shell.pack(fill="both", expand=True, padx=42, pady=34)
        self.root.bind("<Escape>", lambda _event: self.close())

        workspace = tk.Frame(shell, bg=self.background)
        workspace.pack(fill="both", expand=True)
        workspace.grid_columnconfigure(0, weight=5)
        workspace.grid_columnconfigure(1, weight=3)
        workspace.grid_rowconfigure(0, weight=1)
        workspace.grid_rowconfigure(1, weight=0)

        self.build_connection_dock(workspace).grid(row=0, column=0, sticky="nsew", padx=(0, 42))
        self.build_archive_surface(workspace).grid(row=0, column=1, sticky="nsew")
        self.build_action_strip(workspace).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(30, 0))
        self.root.state("zoomed")

    def raised_surface(self, parent: tk.Misc, accent: str | None = None) -> tuple[tk.Frame, tk.Frame]:
        shadow = tk.Frame(parent, bg="#d6e1e4", padx=4, pady=4)
        inner = tk.Frame(shadow, bg=self.panel, highlightthickness=1, highlightbackground=accent or self.border)
        inner.pack(fill="both", expand=True)
        return shadow, inner

    def build_connection_dock(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.background)
        content = tk.Frame(frame, bg=self.background)
        content.pack(fill="both", expand=True)
        tk.Label(content, text="01", bg=self.background, fg=self.cyan, font=("Bahnschrift", 28, "bold")).pack(anchor="w")
        tk.Label(content, text="PAIR YOUR IPHONE", bg=self.background, fg=self.text, font=("Bahnschrift", 26, "bold")).pack(anchor="w", pady=(2, 5))
        tk.Label(content, text="Use the Ezcan camera to join this workbench.", bg=self.background, fg=self.muted, font=("Segoe UI", 10)).pack(anchor="w")
        rule = tk.Frame(content, bg=self.cyan, height=3)
        rule.pack(fill="x", pady=(22, 18))
        qr_shell = tk.Frame(content, bg=self.text, padx=10, pady=10)
        qr_shell.pack(anchor="w", pady=(0, 18))
        qr_frame = tk.Frame(qr_shell, bg="#ffffff", width=238, height=238)
        qr_frame.pack()
        qr_frame.pack_propagate(False)
        payload = json.dumps({"protocol": "ezcan", "version": 1, "url": self.address, "token": self.application.state.token, "computerName": socket.gethostname()}, separators=(",", ":"))
        image = pairing_qr_image(payload, target_pixels=198)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        self.qr_photo = tk.PhotoImage(data=base64.b64encode(buffer.getvalue()).decode("ascii"))
        tk.Label(qr_frame, image=self.qr_photo, bg="#ffffff").place(relx=0.5, rely=0.5, anchor="center")
        address_label = tk.Label(content, textvariable=self.address_var, bg=self.background, fg=self.text, font=("Consolas", 10), cursor="hand2")
        address_label.pack(anchor="w", pady=(0, 5))
        address_label.bind("<Button-1>", lambda _event: self.copy_text(self.address))
        tk.Label(content, text="Tap the address to copy it", bg=self.background, fg=self.muted, font=("Segoe UI", 8)).pack(anchor="w")
        self.rounded_button(content, "COPY ADDRESS", lambda: self.copy_text(self.address), 172, self.blue).pack(anchor="w", pady=(16, 0))
        return frame

    def build_action_strip(self, parent: tk.Misc) -> tk.Frame:
        strip = tk.Frame(parent, bg=self.background)
        strip.grid_columnconfigure(0, weight=1)
        strip.grid_columnconfigure(1, weight=1)
        strip.grid_columnconfigure(2, weight=1)
        strip.grid_columnconfigure(3, weight=1)
        strip.grid_columnconfigure(4, weight=1)
        strip.grid_columnconfigure(5, weight=1)
        self.action_line(strip, 0, "ARCHIVE", self.archive_var, "OPEN", self.open_archive, self.blue)
        self.action_line(strip, 1, "SEND TO IPHONE", self.transfer_var, "CHOOSE", self.choose_file_for_iphone, self.magenta)
        self.action_line(strip, 2, "EBAY PICTURE SEARCH", self.research_var, "SEARCH", self.search_selected_card, self.green)
        self.action_line(strip, 3, "EBAY MATCH", self.candidate_var, "ADD", self.record_selected_candidate, self.amber)
        self.action_line(strip, 4, "CARD IDENTITY", self.identity_var, "REVIEW", self.review_selected_matches, self.cyan)
        self.action_line(strip, 5, "LISTING DRAFT", self.draft_var, "MAKE", self.create_draft_for_selected_card, self.blue)
        return strip

    def action_line(self, parent: tk.Misc, column: int, title: str, value: tk.StringVar, button_text: str, command, accent: str) -> None:
        line = tk.Frame(parent, bg=self.background)
        line.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 22, 22 if column == 0 else 0))
        tk.Frame(line, bg=accent, width=4, height=46).pack(side="left", fill="y", padx=(0, 14))
        details = tk.Frame(line, bg=self.background)
        details.pack(side="left", fill="x", expand=True)
        tk.Label(details, text=title, bg=self.background, fg=accent, font=("Consolas", 8, "bold")).pack(anchor="w")
        tk.Label(details, textvariable=value, bg=self.background, fg=self.text, font=("Segoe UI", 9), anchor="w").pack(anchor="w", pady=(4, 0))
        self.rounded_button(line, button_text, command, 112, accent, foreground="#ffffff").pack(side="right", pady=1)

    def action_tile(self, parent: tk.Misc, column: int, title: str, value: tk.StringVar, button_text: str, command, accent: str, icon: str) -> None:
        frame, content = self.raised_surface(parent, accent)
        frame.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 9, 9 if column == 0 else 0))
        tk.Label(content, text=icon, bg=self.panel_alt, fg=accent, font=("Bahnschrift", 18, "bold"), width=3).pack(side="left", padx=(12, 4), pady=11)
        details = tk.Frame(content, bg=self.panel)
        details.pack(side="left", fill="x", expand=True, padx=8, pady=10)
        tk.Label(details, text=title, bg=self.panel, fg=accent, font=("Consolas", 7, "bold")).pack(anchor="w")
        tk.Label(details, textvariable=value, bg=self.panel, fg=self.text, font=("Segoe UI", 9), anchor="w").pack(anchor="w", pady=(3, 0))
        self.rounded_button(content, button_text, command, 126, accent, foreground=self.text).pack(side="right", padx=14, pady=10)

    def build_archive_surface(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.background)
        content = tk.Frame(frame, bg=self.background)
        content.pack(fill="both", expand=True)
        tk.Label(content, text="RECENT ACTIVITY", bg=self.background, fg=self.text, font=("Bahnschrift", 18, "bold")).pack(anchor="w")
        tk.Label(content, textvariable=self.updated_var, bg=self.background, fg=self.muted, font=("Consolas", 8)).pack(anchor="w", pady=(4, 16))
        table_frame = tk.Frame(content, bg=self.panel, highlightthickness=1, highlightbackground=self.border)
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table_frame, columns=("code", "status", "folder", "created"), show="headings", style="Ezcan.Treeview")
        headings = {"code": "ARCHIVE CODE", "status": "STATUS", "folder": "FOLDER", "created": "RECEIVED"}
        widths = {"code": 130, "status": 120, "folder": 300, "created": 150}
        for column, title in headings.items():
            self.tree.heading(column, text=title, anchor="w")
            self.tree.column(column, width=widths[column], anchor="w", stretch=column in {"folder", "created"})
        self.tree.tag_configure("stripe_even", background=self.panel_deep, foreground=self.text)
        self.tree.tag_configure("stripe_odd", background=self.panel_alt, foreground=self.text)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview, style="Ezcan.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _event: self.search_selected_card())
        return frame

    def build_pairing_panel(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.cyan, highlightthickness=1, highlightbackground=self.cyan)
        content = tk.Frame(frame, bg=self.panel)
        content.pack(fill="both", expand=True, padx=3, pady=3)
        self.panel_texture(content, self.cyan)
        tk.Label(
            content,
            text="PAIR DEVICE",
            bg=self.panel,
            fg=self.text,
            font=("Segoe UI Semibold", 13),
        ).pack(anchor="w", padx=24, pady=(24, 3))
        tk.Label(
            content,
            text="Scan this code in the Ezcan iOS app",
            bg=self.panel,
            fg=self.muted,
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=24)

        qr_shell = tk.Frame(content, bg=self.cyan, padx=5, pady=5)
        qr_shell.pack(padx=24, pady=22)
        qr_frame = tk.Frame(qr_shell, bg="#ffffff", width=250, height=250)
        qr_frame.pack()
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
        image = pairing_qr_image(payload, target_pixels=220)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        self.qr_photo = tk.PhotoImage(data=base64.b64encode(buffer.getvalue()).decode("ascii"))
        tk.Label(qr_frame, image=self.qr_photo, bg="#ffffff").place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            content,
            text="COMPUTER ADDRESS",
            bg=self.panel,
            fg=self.muted,
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", padx=24)
        address_label = tk.Label(
            content,
            textvariable=self.address_var,
            bg=self.panel,
            fg=self.text,
            font=("Consolas", 9),
            cursor="hand2",
        )
        address_label.pack(anchor="w", padx=24, pady=(4, 12))
        address_label.bind("<Button-1>", lambda _event: self.copy_text(self.address))

        self.rounded_button(
            content,
            "COPY ADDRESS",
            lambda: self.copy_text(self.address),
            142,
            self.cyan,
        ).pack(anchor="w", padx=24, pady=(0, 24))
        return frame

    def build_stats(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.background)
        for column in range(3):
            frame.grid_columnconfigure(column, weight=1)
        circuit = tk.Canvas(frame, height=28, bg=self.background, bd=0, highlightthickness=0)
        circuit.grid(row=0, column=0, columnspan=3, sticky="ew")
        circuit.bind("<Configure>", self.draw_circuit)
        self.stat_card(frame, "ARCHIVED CARDS", self.cards_var, self.blue, 0, "01")
        self.stat_card(frame, "ACTIVE INTAKES", self.active_var, self.amber, 1, "02")
        self.stat_card(frame, "MEDIA RECEIVED", self.media_var, self.green, 2, "03")
        return frame

    def draw_circuit(self, event: tk.Event) -> None:
        canvas = event.widget
        canvas.delete("all")
        width = event.width
        canvas.create_line(4, 14, max(4, width - 4), 14, fill="#c4dfe1", width=1)
        for position in (width // 6, width // 2, width * 5 // 6):
            canvas.create_line(position - 22, 14, position - 6, 14, fill=self.cyan, width=2)
            canvas.create_line(position + 6, 14, position + 22, 14, fill="#c4dfe1", width=1)
            canvas.create_oval(position - 5, 9, position + 5, 19, fill=self.panel, outline=self.cyan, width=1)
            canvas.create_oval(position - 2, 12, position + 2, 16, fill=self.cyan, outline="")

    def stat_card(
        self,
        parent: tk.Misc,
        label: str,
        value: tk.StringVar,
        accent: str,
        column: int,
        index: str,
    ) -> None:
        card = tk.Frame(parent, bg=self.panel, highlightthickness=1, highlightbackground=accent)
        card.grid(row=1, column=column, sticky="ew", padx=(0 if column == 0 else 8, 8 if column < 2 else 0))
        tk.Frame(card, bg=accent, height=4).pack(fill="x")
        meta = tk.Frame(card, bg=self.panel)
        meta.pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(meta, text=label, bg=self.panel, fg=self.muted, font=("Consolas", 8)).pack(side="left")
        tk.Label(meta, text=f"// {index}", bg=self.panel, fg=accent, font=("Consolas", 8)).pack(side="right")
        tk.Label(card, textvariable=value, bg=self.panel, fg=self.text, font=("Segoe UI Black", 27)).pack(
            anchor="w", padx=16, pady=(0, 13)
        )

    def build_archive_bar(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.border, highlightthickness=1, highlightbackground=self.border)
        inner = tk.Frame(frame, bg=self.panel)
        inner.pack(fill="both", expand=True, padx=4, pady=4)
        self.panel_texture(inner, self.cyan)
        left = tk.Frame(inner, bg=self.panel)
        left.pack(side="left", fill="x", expand=True, padx=18, pady=13)
        tk.Label(left, text="ARCHIVE LOCATION", bg=self.panel, fg=self.cyan, font=("Consolas", 8)).pack(anchor="w")
        tk.Label(left, textvariable=self.archive_var, bg=self.panel, fg=self.text, font=("Consolas", 9)).pack(anchor="w", pady=(3, 0))
        self.rounded_button(inner, "OPEN ARCHIVE", self.open_archive, 132, self.blue).pack(
            side="right", padx=14, pady=11
        )
        return frame

    def build_transfer_bar(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.border, highlightthickness=1, highlightbackground=self.border)
        inner = tk.Frame(frame, bg=self.panel)
        inner.pack(fill="both", expand=True, padx=4, pady=4)
        self.panel_texture(inner, self.magenta)
        left = tk.Frame(inner, bg=self.panel)
        left.pack(side="left", fill="x", expand=True, padx=18, pady=13)
        tk.Label(left, text="SEND TO IPHONE", bg=self.panel, fg=self.magenta, font=("Consolas", 8)).pack(anchor="w")
        tk.Label(left, textvariable=self.transfer_var, bg=self.panel, fg=self.text, font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
        self.rounded_button(inner, "CHOOSE FILE", self.choose_file_for_iphone, 126, self.magenta).pack(
            side="right", padx=14, pady=11
        )
        return frame

    def build_cards_table(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.panel, highlightthickness=1, highlightbackground=self.border)
        heading = tk.Frame(frame, bg=self.panel)
        heading.pack(fill="x", padx=20, pady=(18, 10))
        tk.Frame(heading, bg=self.cyan, width=3, height=18).pack(side="left", padx=(0, 9))
        tk.Label(heading, text="RECENT ARCHIVE ACTIVITY", bg=self.panel, fg=self.cyan, font=("Consolas", 11)).pack(side="left")
        tk.Label(heading, textvariable=self.updated_var, bg=self.panel, fg=self.muted, font=("Segoe UI", 9)).pack(side="right")
        table_frame = tk.Frame(frame, bg=self.panel_deep, highlightthickness=1, highlightbackground=self.border)
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
        self.tree.tag_configure("stripe_even", background=self.panel_deep, foreground=self.text)
        self.tree.tag_configure("stripe_odd", background=self.panel_alt, foreground=self.text)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview, style="Ezcan.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return frame

    def refresh(self) -> None:
        cards, active_intakes, media = self.store.dashboard_stats()
        self.cards_var.set(str(cards))
        self.active_var.set(str(active_intakes))
        self.media_var.set(str(media))
        shared = self.store.shared_files()
        self.transfer_var.set(f"{len(shared)} file{'s' if len(shared) != 1 else ''} ready in To iPhone")
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, card in enumerate(self.store.recent_cards()):
            created = str(card["created_at"]).replace("T", " ")[:19]
            self.tree.insert(
                "",
                "end",
                values=(card["archive_code"], str(card["status"]).upper(), card["folder_path"], created),
                tags=("stripe_even" if index % 2 == 0 else "stripe_odd",),
            )
        self.updated_var.set(f"Updated {datetime.now().strftime('%H:%M:%S')}")
        self.root.after(1500, self.refresh)

    def choose_file_for_iphone(self) -> None:
        source = filedialog.askopenfilename(
            title="Choose a file to send to iPhone",
            filetypes=[
                ("iPhone files", "*.ipa *.zip *.pdf *.jpg *.jpeg *.png *.mov"),
                ("All files", "*.*"),
            ],
        )
        if not source:
            return
        try:
            destination = self.store.add_shared_file(Path(source))
            self.transfer_var.set(f"Ready to download: {destination.name}")
        except (OSError, ValueError) as error:
            messagebox.showerror("Send to iPhone", f"Could not queue that file.\n\n{error}")

    def search_selected_card(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("eBay Picture Search", "Select an archived card first.")
            return
        values = self.tree.item(selected[0], "values")
        archive_code = str(values[0]) if values else ""
        card = self.store.card_by_archive_code(archive_code)
        if card is None:
            messagebox.showerror("eBay Picture Search", "That archived card is no longer available.")
            return
        search_id: str | None = None
        try:
            image_path = prepare_search_image(Path(card["folder_path"]))
            search_id = self.store.start_ebay_search(card, image_path)
            launch = open_picture_search(image_path, opener=webbrowser.open_new_tab)
            self.store.finish_ebay_search(search_id, "awaiting_manual_upload")
            self.root.clipboard_clear()
            self.root.clipboard_append(str(launch.image_path))
            self.research_var.set(f"{archive_code}: browser opened; image path copied")
            messagebox.showinfo(
                "eBay Picture Search",
                "eBay is open. Click the camera icon in the search field, choose browse to a file, and select:\n\n"
                f"{launch.image_path}\n\nThe image path is also copied to the clipboard.",
            )
        except (OSError, FileNotFoundError, ValueError) as error:
            if search_id is not None:
                self.store.finish_ebay_search(search_id, "failed", str(error))
            self.research_var.set(f"{archive_code}: search preparation failed")
            messagebox.showerror("eBay Picture Search", f"Could not prepare the search.\n\n{error}")

    def record_selected_candidate(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Record eBay Match", "Select an archived card first.")
            return
        values = self.tree.item(selected[0], "values")
        archive_code = str(values[0]) if values else ""
        card = self.store.card_by_archive_code(archive_code)
        search = self.store.latest_ebay_search(archive_code)
        if card is None or search is None:
            messagebox.showinfo("Record eBay Match", "Run an eBay picture search for this card first.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Record eBay Match - {archive_code}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        body = tk.Frame(dialog, bg=self.panel, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=f"RECORD COMPARABLE  //  {archive_code}", bg=self.panel, fg=self.cyan, font=("Consolas", 10, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))

        fields: dict[str, tk.StringVar] = {
            "market_status": tk.StringVar(value="sold"),
            "title": tk.StringVar(),
            "item_url": tk.StringVar(),
            "sale_or_listing_date": tk.StringVar(),
            "price": tk.StringVar(value="0"),
            "shipping_price": tk.StringVar(value="0"),
            "condition": tk.StringVar(value=str(card["condition"] or "")),
            "grade": tk.StringVar(value=str(card["grade"] or "")),
            "listing_format": tk.StringVar(value="fixed_price"),
            "screenshot_path": tk.StringVar(),
        }
        labels = (
            ("MARKET STATUS", "market_status"),
            ("TITLE", "title"),
            ("EBAY URL", "item_url"),
            ("SALE / LISTING DATE", "sale_or_listing_date"),
            ("ITEM PRICE", "price"),
            ("SHIPPING PRICE", "shipping_price"),
            ("CONDITION", "condition"),
            ("GRADE", "grade"),
            ("LISTING FORMAT", "listing_format"),
        )
        for row, (label, key) in enumerate(labels, start=1):
            tk.Label(body, text=label, bg=self.panel, fg=self.muted, font=("Consolas", 8, "bold")).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=5)
            if key == "market_status":
                widget = ttk.Combobox(body, textvariable=fields[key], values=("sold", "active"), state="readonly", width=34)
            elif key == "listing_format":
                widget = ttk.Combobox(body, textvariable=fields[key], values=("fixed_price", "auction"), state="readonly", width=34)
            else:
                widget = tk.Entry(body, textvariable=fields[key], width=38)
            widget.grid(row=row, column=1, sticky="ew", pady=5)

        tk.Label(body, text="SELLER NOTES", bg=self.panel, fg=self.muted, font=("Consolas", 8, "bold")).grid(row=10, column=0, sticky="nw", padx=(0, 16), pady=5)
        notes = tk.Text(body, width=36, height=4, wrap="word")
        notes.grid(row=10, column=1, sticky="ew", pady=5)
        tk.Label(body, text="SCREENSHOT", bg=self.panel, fg=self.muted, font=("Consolas", 8, "bold")).grid(row=11, column=0, sticky="w", padx=(0, 16), pady=5)
        screenshot_row = tk.Frame(body, bg=self.panel)
        screenshot_row.grid(row=11, column=1, sticky="ew", pady=5)
        tk.Entry(screenshot_row, textvariable=fields["screenshot_path"], width=27).pack(side="left")
        tk.Button(screenshot_row, text="BROWSE", command=lambda: fields["screenshot_path"].set(filedialog.askopenfilename(title="Choose eBay screenshot") or fields["screenshot_path"].get())).pack(side="left", padx=(6, 0))

        def save() -> None:
            try:
                candidate_id = self.store.add_ebay_candidate(
                    str(search["search_id"]),
                    {
                        **{key: value.get() for key, value in fields.items()},
                        "seller_notes": notes.get("1.0", "end").strip(),
                    },
                )
            except ValueError as error:
                messagebox.showerror("Record eBay Match", str(error), parent=dialog)
                return
            self.candidate_var.set(f"{archive_code}: candidate #{candidate_id} saved")
            dialog.destroy()

        buttons = tk.Frame(body, bg=self.panel)
        buttons.grid(row=12, column=0, columnspan=2, sticky="e", pady=(18, 0))
        tk.Button(buttons, text="CANCEL", command=dialog.destroy).pack(side="right", padx=(8, 0))
        tk.Button(buttons, text="SAVE MATCH", command=save).pack(side="right")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.bind("<Return>", lambda _event: save())
        dialog.focus_force()

    def review_selected_matches(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Confirm Card Identity", "Select an archived card first.")
            return
        values = self.tree.item(selected[0], "values")
        archive_code = str(values[0]) if values else ""
        card = self.store.card_by_archive_code(archive_code)
        candidates = self.store.ebay_candidates(archive_code)
        if card is None or not candidates:
            messagebox.showinfo("Confirm Card Identity", "Record at least one eBay match for this card first.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Confirm Card Identity - {archive_code}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("980x700")
        dialog.minsize(820, 600)
        body = tk.Frame(dialog, bg=self.panel, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=f"REVIEW MATCHES  //  {archive_code}", bg=self.panel, fg=self.cyan, font=("Consolas", 11, "bold")).pack(anchor="w")
        tk.Label(body, text="Compare the saved results, then enter the exact identity before continuing.", bg=self.panel, fg=self.muted, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 14))

        table_frame = tk.Frame(body, bg=self.panel_deep)
        table_frame.pack(fill="both", expand=True)
        candidate_tree = ttk.Treeview(table_frame, columns=("status", "title", "price", "shipping", "total", "url"), show="headings", height=8)
        headings = {"status": "STATUS", "title": "TITLE", "price": "ITEM", "shipping": "SHIPPING", "total": "TOTAL", "url": "URL"}
        widths = {"status": 80, "title": 260, "price": 75, "shipping": 85, "total": 75, "url": 260}
        for column, title in headings.items():
            candidate_tree.heading(column, text=title, anchor="w")
            candidate_tree.column(column, width=widths[column], anchor="w", stretch=column in {"title", "url"})
        for candidate in candidates:
            candidate_tree.insert("", "end", values=(candidate["market_status"], candidate["title"], f"${candidate['price']:.2f}", f"${candidate['shipping_price']:.2f}", f"${candidate['total_buyer_cost']:.2f}", candidate["item_url"]))
        candidate_tree.pack(side="left", fill="both", expand=True)
        candidate_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=candidate_tree.yview)
        candidate_scrollbar.pack(side="right", fill="y")
        candidate_tree.configure(yscrollcommand=candidate_scrollbar.set)

        identity = tk.Frame(body, bg=self.panel)
        identity.pack(fill="x", pady=(20, 0))
        fields = {
            "card_name": tk.StringVar(value=str(card["card_name"] or "")),
            "set_name": tk.StringVar(value=str(card["set_name"] or "")),
            "card_number": tk.StringVar(value=str(card["card_number"] or "")),
            "edition": tk.StringVar(value=str(card["edition"] or "")),
            "printing": tk.StringVar(value=str(card["printing"] or "")),
            "finish": tk.StringVar(value=str(card["finish"] or "")),
        }
        labels = (("CARD NAME", "card_name"), ("SET", "set_name"), ("CARD NUMBER", "card_number"), ("EDITION", "edition"), ("PRINTING", "printing"), ("FINISH", "finish"))
        for index, (label, key) in enumerate(labels):
            row, column = divmod(index, 2)
            cell = tk.Frame(identity, bg=self.panel)
            cell.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 16, 16 if column == 0 else 0), pady=4)
            tk.Label(cell, text=label, bg=self.panel, fg=self.muted, font=("Consolas", 8, "bold")).pack(anchor="w")
            tk.Entry(cell, textvariable=fields[key], width=38).pack(fill="x", pady=(3, 0))
        identity.grid_columnconfigure(0, weight=1)
        identity.grid_columnconfigure(1, weight=1)

        pricing_var = tk.StringVar(value="Pricing is available after identity confirmation and a sold comparable.")
        tk.Label(body, textvariable=pricing_var, bg=self.panel, fg=self.text, justify="left", anchor="w", wraplength=880, font=("Segoe UI", 9)).pack(fill="x", pady=(14, 0))

        def refresh_pricing() -> None:
            try:
                recommendation = self.store.market_recommendation(archive_code)
            except ValueError as error:
                pricing_var.set(f"Pricing unavailable: {error}")
                return
            pricing_var.set(
                f"SOLD {recommendation.sold_count}  |  MEDIAN BUYER TOTAL ${recommendation.median_sold_total:.2f}  |  "
                f"ACTIVE {recommendation.active_count}\n"
                f"Suggested card price ${recommendation.suggested_item_low:.2f}-${recommendation.suggested_item_high:.2f} "
                f"+ ${recommendation.owner_shipping_charge:.2f} first-item shipping "
                f"(${recommendation.suggested_total_low:.2f}-${recommendation.suggested_total_high:.2f} buyer total)\n"
                f"Estimated fees ${recommendation.estimated_fee_low:.2f}-${recommendation.estimated_fee_high:.2f}; "
                "profit shown before card cost and postage"
            )
        refresh_pricing()

        def confirm() -> None:
            try:
                self.store.confirm_card_identity(
                    archive_code,
                    {key: value.get() for key, value in fields.items()},
                )
            except ValueError as error:
                messagebox.showerror("Confirm Card Identity", str(error), parent=dialog)
                return
            self.identity_var.set(f"{archive_code}: identity confirmed")
            dialog.destroy()

        buttons = tk.Frame(body, bg=self.panel)
        buttons.pack(fill="x", pady=(18, 0))
        tk.Button(buttons, text="REFRESH PRICING", command=refresh_pricing).pack(side="left")
        tk.Button(buttons, text="CANCEL", command=dialog.destroy).pack(side="right", padx=(8, 0))
        tk.Button(buttons, text="CONFIRM IDENTITY", command=confirm).pack(side="right")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.focus_force()

    def create_draft_for_selected_card(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Listing Draft", "Select an archived card first.")
            return
        values = self.tree.item(selected[0], "values")
        archive_code = str(values[0]) if values else ""
        try:
            draft_path = self.store.create_listing_draft(archive_code)
        except (OSError, ValueError) as error:
            self.draft_var.set(f"{archive_code}: draft unavailable")
            messagebox.showerror("Listing Draft", f"Could not create the local draft.\n\n{error}")
            return
        self.draft_var.set(f"{archive_code}: draft saved")
        messagebox.showinfo("Listing Draft", f"Draft saved locally at:\n\n{draft_path}\n\nNothing was published to eBay.")

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
        if self.closing:
            return
        self.closing = True
        self.server.should_exit = True
        self.root.quit()

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self.server.should_exit = True
            self.root.destroy()
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=3)


def start() -> None:
    app = create_app()
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=app.state.port,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True, name="ezcan-api")
    server_thread.start()
    try:
        DesktopWindow(app, server, server_thread).run()
    finally:
        server.should_exit = True
        if server_thread.is_alive():
            server_thread.join(timeout=3)

if __name__ == "__main__":
    start()
