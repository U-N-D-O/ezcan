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
from urllib.parse import urlparse

import qrcode
from PIL import Image, ImageTk
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from ebay import open_picture_search
from ebay_account import EbayAccountManager
from ebay_api import ComputerRefreshTokenStore, EbayConfig, EbayIntegrationError, EbayOAuth, EbaySellClient
from ebay_browser import EbayBrowserError, EbayBrowserWorker, VisualMatch
from archive_labels import build_label_sheet
from description_templates import infer_product_template, product_template_choices, product_template_key, render_product_template
from image_processor import IMAGE_SUFFIXES, add_shipping_overlay, find_back_image, find_front_image, prepare_search_image
from listing_drafts import STORE_CATEGORIES, VIDEO_SUFFIXES, build_listing_draft, enforce_condition_disclaimer
from description_html import fill_store_branding, render_description_template
from store_branding import branding_asset_paths, required_description_assets
from pricing import PricingRecommendation, recommend_price


SEQUENTIAL_ARCHIVE_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SEQUENTIAL_ARCHIVE_DIGITS = "0123456789"
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_VIDEO_BYTES = 150 * 1024 * 1024
MAX_SHARED_FILE_BYTES = 1024 * 1024 * 1024
CURRENT_SCHEMA_VERSION = 5
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


def is_ebay_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "ebay.com" or host.endswith(".ebay.com"))


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


def card_action_availability(status: str | None, has_draft: bool) -> dict[str, bool]:
    if status is None or status == "recovery_required":
        return {key: status == "recovery_required" if key == "repair" else False for key in ("search", "match", "identity", "pricing", "make_draft", "review_draft", "repair")}
    return {
        "search": status in {"received", "searching", "identified", "researched"},
        "match": status in {"searching", "identified", "researched"},
        "identity": status in {"searching", "identified", "researched"},
        "pricing": status in {"identified", "researched"},
        "make_draft": status in {"identified", "researched"} and not has_draft,
        "review_draft": status in {"identified", "researched"} and has_draft,
        "repair": False,
    }


def listing_draft_evidence_text(draft: dict[str, object]) -> str:
    research = draft.get("research")
    suggested_price = draft.get("suggestedPrice")
    shipping = draft.get("shipping")
    if not isinstance(research, dict) or not isinstance(suggested_price, dict) or not isinstance(shipping, dict):
        return "RESEARCH EVIDENCE\nUnavailable in this draft"
    return (
        "RESEARCH EVIDENCE\n"
        f"SOLD {research.get('soldComparables', 0)}  |  ACTIVE {research.get('activeComparables', 0)}  |  "
        f"MEDIAN BUYER TOTAL ${research.get('medianSoldBuyerTotal', '0.00')}\n"
        f"SUGGESTED CARD ${suggested_price.get('low', '0.00')}-${suggested_price.get('high', '0.00')}  |  "
        f"BUYER TOTAL ${suggested_price.get('buyerTotalLow', '0.00')}-${suggested_price.get('buyerTotalHigh', '0.00')}\n"
        f"OWNER FIRST-ITEM SHIP ${shipping.get('firstItemCharge', '0.00')}  |  ADDITIONAL CARD SHIP ${shipping.get('additionalItemsCharge', '0.00')}  |  "
        f"ESTIMATED FEES ${research.get('estimatedFeeLow', '0.00')}-${research.get('estimatedFeeHigh', '0.00')}  |  "
        f"PROFIT BEFORE COSTS ${research.get('estimatedProfitBeforeCostsLow', '0.00')}-${research.get('estimatedProfitBeforeCostsHigh', '0.00')}"
    )


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

    @property
    def branding_urls_path(self) -> Path:
        return self.root / "store-branding-urls.json"

    def load_branding_urls(self) -> dict[str, str]:
        try:
            payload = json.loads(self.branding_urls_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in payload.items()
            if isinstance(key, str) and isinstance(value, str) and value.lower().startswith("https://")
        }

    def save_branding_urls(self, urls: dict[str, str]) -> None:
        self.branding_urls_path.parent.mkdir(parents=True, exist_ok=True)
        self.branding_urls_path.write_text(json.dumps(urls, indent=2), encoding="utf-8")

    def _initialize_database(self) -> None:
        existing_database = self.database_path.is_file() and self.database_path.stat().st_size > 0
        needs_backup = False
        if existing_database:
            with sqlite3.connect(self.database_path) as probe:
                tables = {
                    row[0]
                    for row in probe.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                }
                columns = {row[1] for row in probe.execute("PRAGMA table_info(cards)")}
                intake_columns = {row[1] for row in probe.execute("PRAGMA table_info(intakes)")}
                version_row = (
                    probe.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
                    if "schema_meta" in tables
                    else None
                )
                schema_version = int(version_row[0]) if version_row else 1
                if (
                    schema_version < CURRENT_SCHEMA_VERSION
                    or not {"grade_company", "grade"}.issubset(columns)
                    or "details_json" not in intake_columns
                ):
                    needs_backup = True
        if needs_backup:
            self._backup_database()
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS intakes (
                    intake_id TEXT PRIMARY KEY,
                    temporary_path TEXT NOT NULL,
                    note TEXT,
                    status TEXT NOT NULL,
                    archive_code TEXT UNIQUE,
                    internal_id TEXT,
                    created_at TEXT NOT NULL,
                    finalized_at TEXT,
                    details_json TEXT
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
                CREATE TABLE IF NOT EXISTS archive_label_batches (
                    batch_id TEXT PRIMARY KEY,
                    requested_count INTEGER NOT NULL,
                    start_code TEXT NOT NULL,
                    end_code TEXT NOT NULL,
                    codes_json TEXT NOT NULL,
                    output_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS archive_labels (
                    archive_code TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    batch_id TEXT REFERENCES archive_label_batches(batch_id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
                    created_at TEXT NOT NULL,
                    ebay_sku TEXT,
                    ebay_offer_id TEXT,
                    ebay_listing_id TEXT,
                    ebay_publish_status TEXT NOT NULL DEFAULT 'not_started',
                    ebay_publish_error TEXT,
                    ebay_image_urls_json TEXT,
                    ebay_published_at TEXT
                );
                """
            )
            version_row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            schema_version = int(version_row[0]) if version_row else 1
            columns = {row[1] for row in connection.execute("PRAGMA table_info(cards)")}
            if "grade_company" not in columns:
                connection.execute("ALTER TABLE cards ADD COLUMN grade_company TEXT")
            if "grade" not in columns:
                connection.execute("ALTER TABLE cards ADD COLUMN grade TEXT")
            intake_columns = {row[1] for row in connection.execute("PRAGMA table_info(intakes)")}
            if "details_json" not in intake_columns:
                connection.execute("ALTER TABLE intakes ADD COLUMN details_json TEXT")
            listing_columns = {row[1] for row in connection.execute("PRAGMA table_info(listings)")}
            for name, definition in (
                ("ebay_sku", "TEXT"),
                ("ebay_offer_id", "TEXT"),
                ("ebay_listing_id", "TEXT"),
                ("ebay_publish_status", "TEXT NOT NULL DEFAULT 'not_started'"),
                ("ebay_publish_error", "TEXT"),
                ("ebay_image_urls_json", "TEXT"),
                ("ebay_published_at", "TEXT"),
            ):
                if name not in listing_columns:
                    connection.execute(f"ALTER TABLE listings ADD COLUMN {name} {definition}")
            connection.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(CURRENT_SCHEMA_VERSION),),
            )
        self._recover_interrupted_finalizations()

    def _backup_database(self) -> Path:
        backup_path = self.backups / f"ezcan-before-migration-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3"
        shutil.copy2(self.database_path, backup_path)
        return backup_path

    def _recover_interrupted_finalizations(self) -> None:
        recovered_manifests: list[tuple[Path, dict[str, object]]] = []
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM intakes WHERE status = 'finalizing'").fetchall()
            for intake in rows:
                archive_code = str(intake["archive_code"] or "")
                temporary_path = Path(intake["temporary_path"])
                final_path = self.cards / archive_code
                if temporary_path.exists() and not final_path.exists():
                    connection.execute(
                        "UPDATE intakes SET status = 'uploading' WHERE intake_id = ?",
                        (intake["intake_id"],),
                    )
                    continue
                if not final_path.exists():
                    connection.execute(
                        "UPDATE intakes SET status = 'recovery_required' WHERE intake_id = ?",
                        (intake["intake_id"],),
                    )
                    continue
                existing_card = connection.execute(
                    "SELECT internal_id FROM cards WHERE archive_code = ?", (archive_code,)
                ).fetchone()
                if existing_card is not None:
                    connection.execute(
                        "UPDATE intakes SET status = 'finalized', finalized_at = COALESCE(finalized_at, ?) WHERE intake_id = ?",
                        (utc_now(), intake["intake_id"]),
                    )
                    continue
                try:
                    stored_details = json.loads(str(intake["details_json"] or "{}"))
                    if not isinstance(stored_details, dict):
                        raise TypeError("Stored card details must be an object")
                    card_details = validate_card_details(stored_details)
                except (TypeError, json.JSONDecodeError, HTTPException):
                    card_details = validate_card_details({})
                internal_id = str(intake["internal_id"] or uuid.uuid4())
                media = connection.execute(
                    "SELECT * FROM media WHERE intake_id = ? ORDER BY id", (intake["intake_id"],)
                ).fetchall()
                manifest_media = []
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
                    "UPDATE intakes SET status = 'finalized', internal_id = ?, finalized_at = ? WHERE intake_id = ?",
                    (internal_id, now, intake["intake_id"]),
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
                connection.execute(
                    "INSERT INTO archive_sequence (id, latest_code) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET latest_code = excluded.latest_code",
                    (archive_code,),
                )
                recovered_manifests.append(
                    (
                        final_path,
                        {
                            "archiveCode": archive_code,
                            "internalId": internal_id,
                            "intakeId": intake["intake_id"],
                            "status": "received",
                            "createdAt": intake["created_at"],
                            "listingDetails": card_details,
                            "media": manifest_media,
                        },
                    )
                )
            cards_without_manifests = connection.execute(
                """
                SELECT cards.*, intakes.intake_id AS source_intake_id, intakes.created_at AS intake_created_at
                FROM cards
                LEFT JOIN intakes ON intakes.internal_id = cards.internal_id
                WHERE cards.folder_path IS NOT NULL
                """
            ).fetchall()
            for card in cards_without_manifests:
                manifest_path = Path(card["folder_path"]) / "manifest.json"
                if manifest_path.is_file():
                    continue
                media = (
                    connection.execute(
                        "SELECT * FROM media WHERE intake_id = ? ORDER BY id",
                        (card["source_intake_id"],),
                    ).fetchall()
                    if card["source_intake_id"]
                    else []
                )
                recovered_manifests.append(
                    (
                        Path(card["folder_path"]),
                        {
                            "archiveCode": card["archive_code"],
                            "internalId": card["internal_id"],
                            "intakeId": card["source_intake_id"],
                            "status": card["status"],
                            "createdAt": card["intake_created_at"] or card["created_at"],
                            "listingDetails": {
                                "language": card["language"] or "japanese",
                                "condition": card["condition"] or "near_mint",
                                "gradeCompany": card["grade_company"] or "none",
                                "grade": card["grade"] or "",
                                "authenticityStatus": card["authenticity_status"] or "authenticated",
                            },
                            "media": [
                                {
                                    "fileName": item["file_name"],
                                    "type": item["media_type"],
                                    "sha256": item["file_hash"],
                                    "size": item["file_size"],
                                }
                                for item in media
                            ],
                        },
                    )
                )
        for final_path, manifest in recovered_manifests:
            (final_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def create_intake(self, note: str | None) -> tuple[str, Path, str]:
        intake_id = str(uuid.uuid4())
        temporary_path = self.incoming / f"uploading-{intake_id}"
        (temporary_path / "original").mkdir(parents=True)
        archive_code = self.new_archive_code()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO intakes (intake_id, temporary_path, note, status, archive_code, internal_id, created_at, finalized_at, details_json) VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, NULL)",
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
        with self.connection() as connection:
            connection.execute(
                "UPDATE intakes SET status = 'finalizing', archive_code = ?, internal_id = ?, details_json = ? WHERE intake_id = ?",
                (archive_code, internal_id, json.dumps(card_details), intake_id),
            )
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
            printed = connection.execute(
                "SELECT archive_code FROM archive_labels WHERE status = 'printed' ORDER BY created_at, archive_code LIMIT 1"
            ).fetchone()
            if printed is not None:
                code = str(printed["archive_code"])
                connection.execute(
                    "UPDATE archive_labels SET status = 'assigned', updated_at = ? WHERE archive_code = ?",
                    (utc_now(), code),
                )
                return code

            row = connection.execute("SELECT latest_code FROM archive_sequence WHERE id = 1").fetchone()
            candidate = "A0A0" if row is None else increment_archive_code(str(row["latest_code"]))
            for _ in range(26 * 10 * 26 * 10):
                exists = connection.execute(
                    """
                    SELECT 1 FROM cards WHERE archive_code = ?
                    UNION ALL SELECT 1 FROM intakes WHERE archive_code = ?
                    UNION ALL SELECT 1 FROM archive_labels WHERE archive_code = ?
                    """,
                    (candidate, candidate, candidate),
                ).fetchone()
                if exists is None:
                    now = utc_now()
                    connection.execute(
                        "INSERT INTO archive_sequence (id, latest_code) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET latest_code = excluded.latest_code",
                        (candidate,),
                    )
                    connection.execute(
                        "INSERT INTO archive_labels (archive_code, status, batch_id, created_at, updated_at) VALUES (?, 'assigned', NULL, ?, ?)",
                        (candidate, now, now),
                    )
                    return candidate
                candidate = increment_archive_code(candidate)
        raise RuntimeError("Could not generate a unique archive code")

    def reserve_label_batch(self, count: int) -> tuple[str, list[str]]:
        if count < 1 or count > 1000:
            raise ValueError("Choose between 1 and 1000 labels")
        batch_id = f"labels-{uuid.uuid4()}"
        codes: list[str] = []
        with self.connection() as connection:
            pending = connection.execute(
                "SELECT start_code, end_code FROM archive_label_batches b WHERE EXISTS (SELECT 1 FROM archive_labels l WHERE l.batch_id = b.batch_id AND l.status = 'printed') ORDER BY b.created_at LIMIT 1"
            ).fetchone()
            if pending is not None:
                raise ValueError(
                    f"Finish the earlier label session {pending['start_code']} - {pending['end_code']} first, or use its Reprint Remaining button."
                )
            row = connection.execute("SELECT latest_code FROM archive_sequence WHERE id = 1").fetchone()
            candidate = "A0A0" if row is None else increment_archive_code(str(row["latest_code"]))
            for _ in range(count):
                for _ in range(26 * 10 * 26 * 10):
                    exists = connection.execute(
                        """
                        SELECT 1 FROM cards WHERE archive_code = ?
                        UNION ALL SELECT 1 FROM intakes WHERE archive_code = ?
                        UNION ALL SELECT 1 FROM archive_labels WHERE archive_code = ?
                        """,
                        (candidate, candidate, candidate),
                    ).fetchone()
                    if exists is None:
                        break
                    candidate = increment_archive_code(candidate)
                else:
                    raise RuntimeError("Could not reserve a unique archive ID")
                codes.append(candidate)
                candidate = increment_archive_code(candidate)

            now = utc_now()
            connection.execute(
                "INSERT INTO archive_label_batches (batch_id, requested_count, start_code, end_code, codes_json, output_path, created_at) VALUES (?, ?, ?, ?, ?, NULL, ?)",
                (batch_id, count, codes[0], codes[-1], json.dumps(codes), now),
            )
            connection.executemany(
                "INSERT INTO archive_labels (archive_code, status, batch_id, created_at, updated_at) VALUES (?, 'printed', ?, ?, ?)",
                [(code, batch_id, now, now) for code in codes],
            )
            connection.execute(
                "INSERT INTO archive_sequence (id, latest_code) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET latest_code = excluded.latest_code",
                (codes[-1],),
            )
        return batch_id, codes

    def label_batches(self) -> list[sqlite3.Row]:
        with self.connection() as connection:
            return connection.execute(
                """
                SELECT b.*, SUM(CASE WHEN l.status = 'assigned' THEN 1 ELSE 0 END) AS assigned_count,
                       SUM(CASE WHEN l.status = 'printed' THEN 1 ELSE 0 END) AS remaining_count
                FROM archive_label_batches b
                LEFT JOIN archive_labels l ON l.batch_id = b.batch_id
                GROUP BY b.batch_id
                ORDER BY b.created_at DESC
                """
            ).fetchall()

    def reprint_label_batch(self, batch_id: str) -> list[str]:
        """Return the unassigned tail of a session for one-click reprinting."""
        with self.connection() as connection:
            batch = connection.execute(
                "SELECT * FROM archive_label_batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                raise ValueError("That label session no longer exists")
            codes = json.loads(str(batch["codes_json"]))
            if not isinstance(codes, list) or not all(isinstance(code, str) for code in codes):
                raise ValueError("That label session is invalid")
            labels = connection.execute(
                "SELECT archive_code, status FROM archive_labels WHERE batch_id = ? ORDER BY created_at, archive_code",
                (batch_id,),
            ).fetchall()
            status_by_code = {str(row["archive_code"]): str(row["status"]) for row in labels}
            first_remaining = next(
                (index for index, code in enumerate(codes) if status_by_code.get(code) == "printed"),
                len(codes),
            )
            remaining = codes[first_remaining:]
            if any(status_by_code.get(code) != "printed" for code in remaining):
                raise ValueError("This session is not sequentially used; automatic reprinting was stopped for safety")
            if not remaining:
                raise ValueError("This session has no unused labels remaining")
            return remaining

    def record_label_batch_file(self, batch_id: str, output_path: Path) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE archive_label_batches SET output_path = ? WHERE batch_id = ?",
                (str(output_path), batch_id),
            )

    def recent_cards(self) -> list[sqlite3.Row]:
        with self.connection() as connection:
            return connection.execute(
                """
                SELECT * FROM (
                    SELECT * FROM cards
                    UNION ALL
                    SELECT internal_id, archive_code, temporary_path, status, created_at, created_at,
                        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, note
                    FROM intakes
                    WHERE status = 'recovery_required'
                ) activity
                ORDER BY created_at DESC
                LIMIT 25
                """
            ).fetchall()

    def card_by_archive_code(self, archive_code: str) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM cards WHERE archive_code = ?", (archive_code,)
            ).fetchone()

    def recovery_by_archive_code(self, archive_code: str) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM intakes WHERE archive_code = ? AND status = 'recovery_required'",
                (archive_code,),
            ).fetchone()

    def repair_recovery(self, archive_code: str) -> sqlite3.Row:
        recovery = self.recovery_by_archive_code(archive_code)
        if recovery is None:
            raise ValueError("That archive row no longer needs recovery")
        final_path = self.cards / archive_code
        if not final_path.is_dir():
            raise ValueError(f"The recovered archive folder is still missing: {final_path}")
        with self.connection() as connection:
            connection.execute(
                "UPDATE intakes SET status = 'finalizing' WHERE intake_id = ?",
                (recovery["intake_id"],),
            )
        self._recover_interrupted_finalizations()
        card = self.card_by_archive_code(archive_code)
        if card is None:
            raise ValueError("Ezcan could not rebuild the recovered card record")
        return card

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
        if status not in {"awaiting_manual_upload", "matches_found", "match_selected", "sell_draft_ready", "failed"}:
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
        if not is_ebay_url(item_url):
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
            connection.execute(
                "UPDATE cards SET status = 'identified', updated_at = ? WHERE archive_code = ? AND status = 'researched'",
                (utc_now(), search["archive_code"]),
            )
            candidate_id = int(cursor.lastrowid)
        self._mark_latest_draft_research_outdated(str(search["archive_code"]))
        return candidate_id

    def _mark_latest_draft_research_outdated(self, archive_code: str) -> None:
        listing = self.latest_listing_draft(archive_code)
        if listing is None:
            return
        draft_path = Path(listing["draft_path"])
        try:
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(draft, dict) or draft.get("researchStatus") == "outdated":
            return
        draft["researchStatus"] = "outdated"
        draft["researchNote"] = "New market evidence was recorded. Regenerate this draft before relying on its pricing."
        draft_path.write_text(json.dumps(draft, indent=2), encoding="utf-8")

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
        if card["status"] not in {"identified", "researched"}:
            raise ValueError("Confirm the card identity before calculating pricing")
        return recommend_price(dict(candidate) for candidate in self.ebay_candidates(archive_code))

    def mark_prices_researched(self, archive_code: str) -> None:
        card = self.card_by_archive_code(archive_code)
        if card is None:
            raise ValueError("Card was not found")
        if card["status"] not in {"identified", "researched"}:
            raise ValueError("Confirm the card identity before recording pricing research")
        self.market_recommendation(archive_code)
        with self.connection() as connection:
            connection.execute(
                "UPDATE cards SET status = 'researched', updated_at = ? WHERE archive_code = ?",
                (utc_now(), archive_code),
            )

    def create_listing_draft(self, archive_code: str) -> Path:
        card = self.card_by_archive_code(archive_code)
        if card is None:
            raise ValueError("Card was not found")
        if card["status"] not in {"identified", "researched"}:
            raise ValueError("Confirm the card identity before creating a listing draft")
        recommendation = self.market_recommendation(archive_code)
        card_folder = Path(card["folder_path"])
        original_images = [
            path
            for path in sorted((card_folder / "original").iterdir())
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ]
        if not original_images:
            raise ValueError("At least one archived card image is required")
        front_image = find_front_image(card_folder)
        image_paths = [str(front_image)] + [str(path) for path in original_images if path != front_image]
        image_paths[0] = str(
            add_shipping_overlay(
                Path(image_paths[0]),
                card_folder / "generated" / "listing-first.jpg",
            )
        )
        draft = build_listing_draft(dict(card), recommendation, image_paths)
        draft_path = card_folder / "generated" / "listing-draft.json"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
        existing_listing = self.latest_listing_draft(archive_code)
        created_at = utc_now()
        with self.connection() as connection:
            if existing_listing is None:
                connection.execute(
                    """INSERT INTO listings (
                        listing_id, internal_id, archive_code, status, draft_path,
                        suggested_price_low, suggested_price_high, shipping_price, created_at
                    ) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        card["internal_id"],
                        archive_code,
                        str(draft_path),
                        float(recommendation.suggested_item_low),
                        float(recommendation.suggested_item_high),
                        float(recommendation.owner_shipping_charge),
                        created_at,
                    ),
                )
            else:
                connection.execute(
                    """UPDATE listings
                    SET status = 'draft', draft_path = ?, suggested_price_low = ?,
                        suggested_price_high = ?, shipping_price = ?, created_at = ?
                    WHERE listing_id = ?""",
                    (
                        str(draft_path),
                        float(recommendation.suggested_item_low),
                        float(recommendation.suggested_item_high),
                        float(recommendation.owner_shipping_charge),
                        created_at,
                        existing_listing["listing_id"],
                    ),
                )
        return draft_path

    def latest_listing_draft(self, archive_code: str) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM listings WHERE archive_code = ? ORDER BY created_at DESC LIMIT 1",
                (archive_code,),
            ).fetchone()

    def update_ebay_publish_state(
        self,
        archive_code: str,
        status: str,
        *,
        offer_id: str | None = None,
        listing_id: str | None = None,
        image_urls: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in {"not_started", "publishing", "published", "failed"}:
            raise ValueError("Unsupported eBay publish status")
        listing = self.latest_listing_draft(archive_code)
        if listing is None:
            raise ValueError("Create a local listing draft first")
        with self.connection() as connection:
            connection.execute(
                """UPDATE listings SET ebay_sku = COALESCE(ebay_sku, ?),
                    ebay_offer_id = COALESCE(?, ebay_offer_id),
                    ebay_listing_id = COALESCE(?, ebay_listing_id),
                    ebay_publish_status = ?, ebay_publish_error = ?,
                    ebay_image_urls_json = COALESCE(?, ebay_image_urls_json),
                    ebay_published_at = CASE WHEN ? = 'published' THEN ? ELSE ebay_published_at END
                    WHERE listing_id = ?""",
                (
                    archive_code,
                    offer_id,
                    listing_id,
                    status,
                    error,
                    json.dumps(image_urls) if image_urls is not None else None,
                    status,
                    utc_now(),
                    listing["listing_id"],
                ),
            )

    def update_listing_draft(
        self,
        archive_code: str,
        title: str,
        description: str,
        *,
        card_name: str | None = None,
        store_category: str | None = None,
        product_type: str | None = None,
        price: str | float | None = None,
    ) -> Path:
        listing = self.latest_listing_draft(archive_code)
        if listing is None:
            raise ValueError("Create a local listing draft first")
        title = title.strip()
        description = enforce_condition_disclaimer(description)
        if not title or not description:
            raise ValueError("Draft title and description are required")
        draft_path = Path(listing["draft_path"])
        try:
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("The local draft file could not be read") from error
        draft["title"] = title
        draft["description"] = description
        if card_name is not None:
            clean_card_name = card_name.strip()
            if not clean_card_name:
                raise ValueError("Card name is required")
            draft.setdefault("itemSpecifics", {})["cardName"] = clean_card_name
        if store_category is not None:
            if store_category not in STORE_CATEGORIES:
                raise ValueError("Choose a valid Sugimori Gem Archive category")
            draft["storeCategory"] = store_category
            draft["category"] = store_category
        if product_type is not None:
            draft["productType"] = product_template_key(product_type)
        if price is not None:
            try:
                numeric_price = float(str(price).strip())
            except (TypeError, ValueError) as error:
                raise ValueError("Listing price must be a number") from error
            if numeric_price <= 0:
                raise ValueError("Listing price must be greater than zero")
            draft["listingPrice"] = f"{numeric_price:.2f}"
            draft["priceConfirmed"] = True
        else:
            # Saving the review without a replacement price explicitly accepts
            # the draft's suggested amount (legacy callers use this path too).
            draft["priceConfirmed"] = True
        draft["descriptionHtml"] = render_description_template(
            archive_code=archive_code,
            title=title,
            body=description,
            card_name=str(draft.get("itemSpecifics", {}).get("cardName", "")),
            store_category=str(draft.get("storeCategory", "Non-TCG")),
        )
        draft["reviewStatus"] = "reviewed"
        draft["publishing"] = {"published": False, "sellerCredentialsUsed": False}
        draft_path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
        with self.connection() as connection:
            connection.execute(
                "UPDATE listings SET status = 'reviewed' WHERE listing_id = ?",
                (listing["listing_id"],),
            )
        return draft_path

    def set_listing_status(self, archive_code: str, status: str) -> None:
        if status not in {"draft", "reviewed", "approved", "rejected"}:
            raise ValueError("Unsupported local draft status")
        listing = self.latest_listing_draft(archive_code)
        if listing is None:
            raise ValueError("Create a local listing draft first")
        draft_path = Path(listing["draft_path"])
        try:
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("The local draft file could not be read") from error
        if status == "approved" and draft.get("priceConfirmed") is not True:
            raise ValueError("Confirm the suggested price or enter a manual price before approval")
        draft["reviewStatus"] = status
        draft["publishing"] = {"published": False, "sellerCredentialsUsed": False}
        draft_path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
        with self.connection() as connection:
            connection.execute(
                "UPDATE listings SET status = ? WHERE listing_id = ?",
                (status, listing["listing_id"]),
            )

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
    app.state.ebay_oauth = EbayOAuth(EbayConfig.from_environment(), ComputerRefreshTokenStore())
    app.state.ebay_sell = EbaySellClient(app.state.ebay_oauth)
    app.state.ebay_oauth_state: str | None = None

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

    @app.get("/api/ebay/status")
    async def ebay_status() -> dict[str, object]:
        """Computer UI status only; the phone app never needs eBay credentials."""
        oauth = app.state.ebay_oauth
        configured = oauth.config.configured
        connected = False
        if configured:
            try:
                connected = bool(oauth.token_store.load())
            except Exception:
                connected = False
        return {
            "configured": configured,
            "connected": connected,
            "publishingConfigured": oauth.config.publishing_configured,
            "marketplaceId": oauth.config.marketplace_id,
            "environment": oauth.config.environment,
            "browserRequiredForListings": False,
        }

    @app.get("/ebay/oauth/callback")
    async def ebay_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None) -> HTMLResponse:
        """Receive the one-time seller consent redirect on the computer."""
        oauth = app.state.ebay_oauth
        expected_state = app.state.ebay_oauth_state
        if error:
            app.state.ebay_oauth_state = None
            return HTMLResponse(f"<h2>eBay connection cancelled</h2><p>{html.escape(error)}</p><p>You can close this window.</p>", status_code=400)
        if not code or not state or not expected_state or not hmac.compare_digest(state, expected_state):
            return HTMLResponse("<h2>eBay connection could not be verified</h2><p>Return to Ezcan and start the connection again.</p>", status_code=400)
        try:
            oauth.exchange_authorization_code(code)
        except Exception as callback_error:
            app.state.ebay_oauth_state = None
            return HTMLResponse(f"<h2>eBay connection failed</h2><p>{html.escape(str(callback_error))}</p><p>You can close this window.</p>", status_code=502)
        app.state.ebay_oauth_state = None
        return HTMLResponse("<h2>eBay connected to Sugimori Gem Archive</h2><p>You may close this window and return to Ezcan.</p>")

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
        self.ebay_account = EbayAccountManager()
        self.ebay_oauth: EbayOAuth = application.state.ebay_oauth
        self.ebay_sell: EbaySellClient = application.state.ebay_sell
        self.ebay_browser: EbayBrowserWorker | None = None
        self.address_var = tk.StringVar(value=self.address)
        self.connection_var = tk.StringVar(value="ONLINE - PRIVATE NETWORK")
        self.ebay_account_var = tk.StringVar(value="eBay search account: not connected")
        self.ebay_publish_var = tk.StringVar(value="eBay seller API: checking connection")
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
        self.selected_archive_code: str | None = None
        self.selected_card_var = tk.StringVar(value="Select a card from Recent Activity")
        self.selected_details_var = tk.StringVar(value="")
        self.selected_state_var = tk.StringVar(value="")
        self.selected_photo: tk.PhotoImage | None = None
        self.card_action_buttons: dict[str, tk.Canvas] = {}
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
            fill = color if state["enabled"] else "#b8c4d0"
            label_color = foreground if state["enabled"] else "#6d7d8c"
            rounded_shape(2, 6 + offset, width - 2, height - 1 + offset, "#b8c4d0")
            rounded_shape(0, 2 + offset, width - 4, height - 5 + offset, fill, fill)
            rounded_shape(3, 5 + offset, width - 7, height - 8 + offset, fill)
            rounded_shape(5, 7 + offset, width - 9, height - 10 + offset, fill)
            button.create_text(width // 2 - 7, height // 2 - 2 + offset, text=text, fill=label_color, font=("Segoe UI", 10, "bold"), tags="label")
            button.create_text(width - 22, height // 2 - 2 + offset, text="→", fill=label_color, font=("Segoe UI", 16, "bold"), tags="icon")

        def set_enabled(enabled: bool) -> None:
            state["enabled"] = enabled
            state["pressed"] = False
            button.configure(cursor="hand2" if enabled else "arrow")
            paint()

        def press(_event: tk.Event) -> None:
            if not state["enabled"]:
                return
            state["pressed"] = True
            paint()

        def release(_event: tk.Event) -> None:
            if not state["enabled"]:
                return
            state["pressed"] = False
            paint()
            command()

        state["enabled"] = True
        button.set_enabled = set_enabled
        paint()
        button.bind("<ButtonPress-1>", press)
        button.bind("<ButtonRelease-1>", release)
        return button

    def build_layout(self) -> None:
        shell = tk.Frame(self.root, bg=self.background)
        shell.pack(fill="both", expand=True, padx=42, pady=34)
        self.root.bind("<Escape>", lambda _event: self.close())

        header = tk.Frame(shell, bg=self.background)
        header.pack(fill="x", pady=(0, 20))
        heading = tk.Frame(header, bg=self.background)
        heading.pack(side="left")
        tk.Label(heading, text="EZCAN / CARD WORKBENCH", bg=self.background, fg=self.cyan, font=("Consolas", 10, "bold")).pack(anchor="w")
        tk.Label(heading, text="Recent cards, one clear next action", bg=self.background, fg=self.text, font=("Bahnschrift", 22, "bold")).pack(anchor="w", pady=(4, 0))
        tk.Label(header, textvariable=self.connection_var, bg=self.background, fg=self.green, font=("Consolas", 9, "bold")).pack(side="right", anchor="s", pady=(0, 5))

        utilities = tk.Frame(shell, bg=self.background)
        utilities.pack(fill="x", pady=(0, 20))
        tk.Label(utilities, text="UTILITIES", bg=self.background, fg=self.muted, font=("Consolas", 8, "bold")).pack(side="left", padx=(0, 12))
        self.rounded_button(utilities, "OPEN ARCHIVE", self.open_archive, 142, self.blue).pack(side="left", padx=(0, 10))
        self.rounded_button(utilities, "PRINT ID LABELS", self.print_archive_labels, 158, self.cyan, foreground=self.text).pack(side="left", padx=(0, 10))
        self.rounded_button(utilities, "SEND TO IPHONE", self.choose_file_for_iphone, 158, self.magenta).pack(side="left")

        workspace = tk.Frame(shell, bg=self.background)
        workspace.pack(fill="both", expand=True)
        workspace.grid_columnconfigure(0, weight=2)
        workspace.grid_columnconfigure(1, weight=4)
        workspace.grid_columnconfigure(2, weight=4)
        workspace.grid_rowconfigure(0, weight=1)

        self.build_connection_dock(workspace).grid(row=0, column=0, sticky="nsew", padx=(0, 24))
        self.build_archive_surface(workspace).grid(row=0, column=1, sticky="nsew", padx=(0, 24))
        self.build_selected_card_workspace(workspace).grid(row=0, column=2, sticky="nsew")
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
        ebay = tk.Frame(content, bg=self.panel, highlightthickness=1, highlightbackground=self.border)
        ebay.pack(fill="x", pady=(28, 0))
        tk.Label(ebay, text="EBAY SELLER ACCESS", bg=self.panel, fg=self.magenta, font=("Consolas", 9, "bold")).pack(anchor="w", padx=14, pady=(14, 3))
        tk.Label(ebay, textvariable=self.ebay_publish_var, bg=self.panel, fg=self.text, font=("Segoe UI", 9), wraplength=230, justify="left").pack(anchor="w", padx=14)
        self.rounded_button(ebay, "CONNECT SELLER API", self.connect_ebay_seller, 190, self.cyan, foreground=self.text).pack(anchor="w", padx=14, pady=(10, 7))
        tk.Label(ebay, text="PICTURE-SEARCH ACCOUNT", bg=self.panel, fg=self.muted, font=("Consolas", 8, "bold")).pack(anchor="w", padx=14, pady=(4, 2))
        tk.Label(ebay, textvariable=self.ebay_account_var, bg=self.panel, fg=self.text, font=("Segoe UI", 9), wraplength=230, justify="left").pack(anchor="w", padx=14)
        self.rounded_button(ebay, "SIGN IN / OPEN EBAY", self.connect_ebay_account, 190, self.magenta).pack(anchor="w", padx=14, pady=(12, 7))
        controls = tk.Frame(ebay, bg=self.panel)
        controls.pack(fill="x", padx=14, pady=(0, 14))
        tk.Button(controls, text="I'M SIGNED IN", command=self.confirm_ebay_account, relief="flat", cursor="hand2").pack(side="left")
        tk.Button(controls, text="REMOVE SESSION", command=self.remove_ebay_account, relief="flat", cursor="hand2").pack(side="right")
        self.refresh_ebay_account_status()
        self.refresh_ebay_publish_status()
        return frame

    def refresh_ebay_publish_status(self) -> None:
        if not self.ebay_oauth.config.configured:
            self.ebay_publish_var.set("eBay seller API: developer setup required")
            return
        try:
            connected = bool(self.ebay_oauth.token_store.load())
        except Exception:
            connected = False
        if connected:
            if self.ebay_oauth.config.publishing_configured:
                self.ebay_publish_var.set(f"eBay seller API: ready ({self.ebay_oauth.config.marketplace_id}) | browser not needed")
            else:
                self.ebay_publish_var.set("eBay seller API: connected; listing settings still required")
        else:
            self.ebay_publish_var.set("eBay seller API: connect this computer once")

    def connect_ebay_seller(self) -> None:
        try:
            state = secrets.token_urlsafe(24)
            self.application.state.ebay_oauth_state = state
            authorization_url = self.ebay_oauth.authorization_url(state)
            if not webbrowser.open_new_tab(authorization_url):
                raise OSError("The eBay authorization page could not be opened")
        except Exception as error:
            self.application.state.ebay_oauth_state = None
            messagebox.showerror(
                "eBay Seller API",
                f"Could not start the one-time eBay authorization.\n\n{error}\n\n"
                "The computer needs EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, and EBAY_RU_NAME configured first.",
            )
            return
        self.ebay_publish_var.set("eBay authorization opened once; finish it, then return here")
        self.root.after(1500, self.poll_ebay_seller_connection)

    def poll_ebay_seller_connection(self) -> None:
        if self.closing:
            return
        try:
            connected = bool(self.ebay_oauth.token_store.load())
        except Exception:
            connected = False
        if connected:
            self.refresh_ebay_publish_status()
            messagebox.showinfo("eBay Seller API", "This computer is connected. Listings will publish directly through eBay without opening a browser.")
            return
        if self.application.state.ebay_oauth_state:
            self.root.after(1500, self.poll_ebay_seller_connection)

    def refresh_ebay_account_status(self) -> None:
        status = self.ebay_account.state()["status"]
        labels = {
            "not_connected": "eBay search account: not connected",
            "login_required": "eBay search account: sign-in required",
            "connected": "eBay search account: connected",
        }
        self.ebay_account_var.set(labels[status])

    def connect_ebay_account(self) -> None:
        try:
            launch = self.ebay_account.begin_sign_in()
        except OSError as error:
            messagebox.showerror("eBay Search Account", f"Could not open eBay sign-in.\n\n{error}")
            return
        self.refresh_ebay_account_status()
        if launch.persistent:
            messagebox.showinfo(
                "eBay Search Account",
                "A separate eBay browser profile is open. Sign in there, then click I'M SIGNED IN in Ezcan.\n\n"
                "Ezcan stores no username, password, seller credentials, or raw eBay token.",
            )
        else:
            messagebox.showinfo(
                "eBay Search Account",
                "eBay opened in your default browser. Sign in there, then click I'M SIGNED IN in Ezcan.\n\n"
                "A browser with profile support was not found, so this session may not persist separately.",
            )

    def confirm_ebay_account(self) -> None:
        try:
            self.ebay_account.mark_connected()
        except ValueError as error:
            messagebox.showinfo("eBay Search Account", str(error))
            return
        self.refresh_ebay_account_status()

    def remove_ebay_account(self) -> None:
        if not messagebox.askyesno("Remove eBay Session", "Remove Ezcan's separate eBay browser profile from this computer?"):
            return
        try:
            self.ebay_account.remove_profile()
        except OSError as error:
            messagebox.showerror("Remove eBay Session", f"Could not remove the browser profile.\n\n{error}")
            return
        self.refresh_ebay_account_status()

    def build_archive_surface(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.background)
        content = tk.Frame(frame, bg=self.background)
        content.pack(fill="both", expand=True)
        title_row = tk.Frame(content, bg=self.background)
        title_row.pack(fill="x")
        tk.Label(title_row, text="Recent Activity", bg=self.background, fg=self.text, font=("Bahnschrift", 18, "bold")).pack(side="left")
        tk.Label(title_row, text="Select a card to continue", bg=self.background, fg=self.muted, font=("Segoe UI", 9)).pack(side="right", pady=(6, 0))
        tk.Label(content, textvariable=self.updated_var, bg=self.background, fg=self.muted, font=("Consolas", 8)).pack(anchor="w", pady=(4, 16))
        table_frame = tk.Frame(content, bg=self.panel, highlightthickness=1, highlightbackground=self.border)
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table_frame, columns=("code", "identity", "details", "state"), show="headings", style="Ezcan.Treeview", selectmode="browse")
        headings = {"code": "CODE", "identity": "CARD", "details": "DETAILS", "state": "NEXT"}
        widths = {"code": 72, "identity": 160, "details": 160, "state": 120}
        for column, title in headings.items():
            self.tree.heading(column, text=title, anchor="w")
            self.tree.column(column, width=widths[column], anchor="w", stretch=column in {"identity", "details", "state"})
        self.tree.tag_configure("stripe_even", background=self.panel_deep, foreground=self.text)
        self.tree.tag_configure("stripe_odd", background=self.panel_alt, foreground=self.text)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview, style="Ezcan.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_card_selected)
        self.tree.bind("<Double-1>", lambda _event: self.open_selected_card())
        self.tree.bind("<Return>", lambda _event: self.open_selected_card())
        return frame

    def build_selected_card_workspace(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.panel, highlightthickness=1, highlightbackground=self.border)
        heading = tk.Frame(frame, bg=self.panel)
        heading.pack(fill="x", padx=20, pady=(18, 14))
        tk.Frame(heading, bg=self.cyan, width=3, height=20).pack(side="left", padx=(0, 9))
        tk.Label(heading, text="SELECTED CARD", bg=self.panel, fg=self.cyan, font=("Consolas", 11, "bold")).pack(side="left")
        tk.Label(frame, textvariable=self.selected_card_var, bg=self.panel, fg=self.text, font=("Bahnschrift", 17, "bold"), wraplength=360, justify="left").pack(anchor="w", padx=20)
        tk.Label(frame, textvariable=self.selected_state_var, bg=self.panel, fg=self.cyan, font=("Consolas", 9, "bold")).pack(anchor="w", padx=20, pady=(6, 0))
        preview = tk.Frame(frame, bg=self.panel_deep, height=220, highlightthickness=1, highlightbackground=self.border)
        preview.pack(fill="x", padx=20, pady=18)
        preview.pack_propagate(False)
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_columnconfigure(1, weight=1)
        self.selected_preview_front = tk.Label(preview, text="FRONT\nNo preview", bg=self.panel_deep, fg=self.muted, font=("Consolas", 8), justify="center")
        self.selected_preview_front.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        self.selected_preview_back = tk.Label(preview, text="BACK\nNo preview", bg=self.panel_deep, fg=self.muted, font=("Consolas", 8), justify="center")
        self.selected_preview_back.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        tk.Label(frame, textvariable=self.selected_details_var, bg=self.panel, fg=self.muted, font=("Segoe UI", 10), justify="left", anchor="w", wraplength=360).pack(fill="x", padx=20)
        actions = tk.Frame(frame, bg=self.panel)
        actions.pack(fill="x", padx=20, pady=(22, 20))
        action_specs = (
            ("search", "SEARCH EBAY", self.search_selected_card, self.green, "white"),
            ("match", "ADD MATCH", self.record_selected_candidate, self.amber, self.text),
            ("identity", "REVIEW IDENTITY", self.review_selected_matches, self.cyan, self.text),
            ("pricing", "RESEARCH PRICES", self.research_prices_for_selected_card, self.green, "white"),
            ("make_draft", "MAKE DRAFT", self.create_draft_for_selected_card, self.blue, "white"),
            ("review_draft", "REVIEW DRAFT", self.review_draft_for_selected_card, self.magenta, "white"),
            ("repair", "REPAIR ARCHIVE", self.repair_selected_card, self.amber, self.text),
        )
        for index, (key, label, command, color, foreground) in enumerate(action_specs):
            button = self.rounded_button(actions, label, command, 142, color, foreground=foreground)
            button.pack(fill="x", pady=(0, 8 if index < len(action_specs) - 1 else 0))
            self.card_action_buttons[key] = button
        self.update_card_actions(None)
        return frame

    def update_card_actions(self, card: sqlite3.Row | None) -> None:
        has_draft = (
            card is not None
            and card["status"] != "recovery_required"
            and self.store.latest_listing_draft(str(card["archive_code"])) is not None
        )
        enabled = card_action_availability(str(card["status"]) if card is not None else None, has_draft)
        for key, button in self.card_action_buttons.items():
            button.set_enabled(enabled[key])

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
        return self.build_archive_surface(parent)

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
            identity = "Recovery required" if card["status"] == "recovery_required" else str(card["card_name"] or "Needs identity")
            details = self.card_details_text(card)
            self.tree.insert(
                "",
                "end",
                iid=str(card["archive_code"]),
                values=(card["archive_code"], identity, details, self.card_next_action(card)),
                tags=("stripe_even" if index % 2 == 0 else "stripe_odd",),
            )
            if card["archive_code"] == self.selected_archive_code:
                self.tree.selection_set(str(card["archive_code"]))
                self.tree.focus(str(card["archive_code"]))
        self.updated_var.set(f"Updated {datetime.now().strftime('%H:%M:%S')}")
        self.root.after(1500, self.refresh)

    def card_details_text(self, card: sqlite3.Row) -> str:
        if card["status"] == "recovery_required":
            return "Archive move interrupted"
        language = "English" if card["language"] == "english" else "Japanese"
        condition = str(card["condition"] or "").replace("_", " ").title()
        grade = f" / {card['grade_company'].upper()} {card['grade']}" if card["grade_company"] and card["grade_company"] != "none" else ""
        return f"{language} / {condition}{grade}"

    def card_next_action(self, card: sqlite3.Row) -> str:
        state = str(card["status"])
        if state == "received":
            return "Search eBay"
        if state == "searching":
            return "Add match"
        if state == "identified":
            return "Review draft" if self.store.latest_listing_draft(str(card["archive_code"])) else "Research prices"
        if state == "researched":
            return "Review draft" if self.store.latest_listing_draft(str(card["archive_code"])) else "Make draft"
        return state.replace("_", " ").title()

    def on_card_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        self.selected_archive_code = str(selected[0])
        card = self.store.card_by_archive_code(self.selected_archive_code)
        if card is None:
            recovery = self.store.recovery_by_archive_code(self.selected_archive_code)
            if recovery is not None:
                self.selected_card_var.set(f"{recovery['archive_code']}  Recovery required")
                self.selected_state_var.set("RECOVERY REQUIRED")
                self.selected_details_var.set(
                    "The archive move was interrupted before Ezcan could finish the database record.\n"
                    "Open the archive folder and resolve this intake before starting eBay research."
                )
                self.selected_photos = []
                self.selected_preview_front.configure(image="", text="FRONT\nArchive recovery needed")
                self.selected_preview_back.configure(image="", text="BACK\nArchive recovery needed")
            self.update_card_actions(recovery)
            return
        self.update_card_actions(card)
        self.selected_card_var.set(f"{card['archive_code']}  {card['card_name'] or 'Identity not confirmed'}")
        self.selected_state_var.set(str(card["status"]).replace("_", " ").upper())
        self.selected_details_var.set(
            f"{self.card_details_text(card)}\n"
            f"{card['set_name'] or 'Set not confirmed'}"
            f"{(' / ' + str(card['card_number'])) if card['card_number'] else ''}"
        )
        self.selected_photos = []
        try:
            card_folder = Path(card["folder_path"])
            front_path = find_front_image(card_folder)
            back_path = find_back_image(card_folder)
            for label, image_path, title in (
                (self.selected_preview_front, front_path, "FRONT"),
                (self.selected_preview_back, back_path, "BACK"),
            ):
                if image_path is None:
                    label.configure(image="", text=f"{title}\nNo preview")
                    continue
                with Image.open(image_path) as image:
                    image.thumbnail((145, 195), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(image.copy())
                self.selected_photos.append(photo)
                label.configure(image=photo, text="")
        except (FileNotFoundError, OSError, StopIteration):
            self.selected_photos = []
            self.selected_preview_front.configure(image="", text="FRONT\nNo preview")
            self.selected_preview_back.configure(image="", text="BACK\nNo preview")

    def open_selected_card(self) -> None:
        self.on_card_selected()

    def repair_selected_card(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Repair Archive", "Select a recovery-required row first.")
            return
        archive_code = str(selected[0])
        try:
            self.store.repair_recovery(archive_code)
        except ValueError as error:
            messagebox.showinfo("Repair Archive", str(error))
            return
        self.research_var.set(f"{archive_code}: archive repaired")
        self.refresh()
        messagebox.showinfo("Repair Archive", f"Archive {archive_code} was rebuilt and is ready for eBay research.")

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
            if self.ebay_account.state()["status"] != "connected":
                raise EbayBrowserError("Connect the dedicated computer eBay profile once before using automatic visual search.")
            if self.ebay_browser is None:
                self.ebay_browser = EbayBrowserWorker(
                    self.ebay_account.profile_path,
                    browser_path=self.ebay_account._browser_executable(),
                )
            self.research_var.set(f"{archive_code}: eBay visual search running")
            threading.Thread(
                target=self._run_visual_search,
                args=(archive_code, search_id, image_path),
                daemon=True,
                name="ezcan-visual-search",
            ).start()
            return
        except (OSError, FileNotFoundError, ValueError, EbayBrowserError) as error:
            if search_id is not None:
                self.store.finish_ebay_search(search_id, "failed", str(error))
            self.research_var.set(f"{archive_code}: search preparation failed")
            messagebox.showerror("eBay Picture Search", f"Could not prepare the search.\n\n{error}")

    def _run_visual_search(self, archive_code: str, search_id: str, image_path: Path) -> None:
        try:
            if self.ebay_browser is None:
                raise EbayBrowserError("The eBay page session is not available.")
            matches = self.ebay_browser.visual_search(image_path)
        except Exception as error:
            self.root.after(0, self._visual_search_failed, archive_code, search_id, error)
            return
        self.root.after(0, self._visual_search_finished, archive_code, search_id, matches)

    def _visual_search_failed(self, archive_code: str, search_id: str, error: Exception) -> None:
        self.store.finish_ebay_search(search_id, "failed", str(error))
        self.research_var.set(f"{archive_code}: visual search failed")
        messagebox.showerror("eBay Visual Search", str(error))

    def _visual_search_finished(self, archive_code: str, search_id: str, matches: list[VisualMatch]) -> None:
        self.store.finish_ebay_search(search_id, "matches_found")
        self.research_var.set(f"{archive_code}: choose 1 of {len(matches)} visual matches")
        self.show_visual_matches(archive_code, search_id, matches)

    def show_visual_matches(self, archive_code: str, search_id: str, matches: list[VisualMatch]) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(f"eBay Visual Matches - {archive_code}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("900x530")
        dialog.minsize(720, 430)
        body = tk.Frame(dialog, bg=self.panel, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=f"EBAY VISUAL MATCHES  //  {archive_code}", bg=self.panel, fg=self.cyan, font=("Consolas", 11, "bold")).pack(anchor="w")
        tk.Label(body, text="Select the exact product. Ezcan will then activate eBay's 'Sell one like this' page and upload the archive media.", bg=self.panel, fg=self.text, font=("Bahnschrift", 15, "bold"), wraplength=820, justify="left").pack(anchor="w", pady=(5, 16))
        match_list = ttk.Treeview(body, columns=("rank", "title", "url"), show="headings", height=8, style="Ezcan.Treeview")
        match_list.heading("rank", text="#")
        match_list.heading("title", text="VISUAL MATCH")
        match_list.heading("url", text="EBAY URL")
        match_list.column("rank", width=45, anchor="center", stretch=False)
        match_list.column("title", width=470, anchor="w")
        match_list.column("url", width=300, anchor="w")
        for match in matches[:5]:
            match_list.insert("", "end", iid=str(match.rank), values=(match.rank, match.title, match.url))
        match_list.pack(fill="both", expand=True)

        def use_selected() -> None:
            selection = match_list.selection()
            if not selection:
                messagebox.showinfo("Choose Visual Match", "Select one of the five eBay matches first.", parent=dialog)
                return
            match = next((item for item in matches if str(item.rank) == selection[0]), None)
            if match is None:
                return
            dialog.destroy()
            self.use_visual_match(archive_code, search_id, match)

        actions = tk.Frame(body, bg=self.panel)
        actions.pack(fill="x", pady=(16, 0))
        tk.Button(actions, text="USE SELECTED MATCH", command=use_selected, bg=self.cyan, fg=self.text, relief="flat", padx=14, pady=7, cursor="hand2").pack(side="left")
        tk.Button(actions, text="CLOSE", command=dialog.destroy, relief="flat", padx=14, pady=7, cursor="hand2").pack(side="right")
        match_list.selection_set("1")
        dialog.bind("<Return>", lambda _event: use_selected())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.focus_force()

    def use_visual_match(self, archive_code: str, search_id: str, match: VisualMatch) -> None:
        card = self.store.card_by_archive_code(archive_code)
        if card is None:
            return
        try:
            self.store.add_ebay_candidate(
                search_id,
                {
                    "market_status": "active",
                    "item_url": match.url,
                    "title": match.title,
                    "price": 0,
                    "shipping_price": 0,
                    "listing_format": "visual_match",
                    "seller_notes": "Selected from automatic eBay visual search",
                },
            )
            self.store.finish_ebay_search(search_id, "match_selected")
            if self.ebay_browser is None:
                raise EbayBrowserError("The eBay page session is not available.")
            card_folder = Path(card["folder_path"])
            files = [
                path
                for path in sorted((card_folder / "original").iterdir())
                if path.is_file() and (path.suffix.lower() in IMAGE_SUFFIXES or path.suffix.lower() in VIDEO_SUFFIXES)
            ]
            self.research_var.set(f"{archive_code}: opening Sell one like this")
            threading.Thread(
                target=self._run_sell_one_like_this,
                args=(archive_code, search_id, match, files),
                daemon=True,
                name="ezcan-sell-one-like-this",
            ).start()
        except Exception as error:
            self.research_var.set(f"{archive_code}: selected match failed")
            messagebox.showerror("eBay Visual Match", str(error))

    def _run_sell_one_like_this(self, archive_code: str, search_id: str, match: VisualMatch, files: list[Path]) -> None:
        try:
            if self.ebay_browser is None:
                raise EbayBrowserError("The eBay page session is not available.")
            result = self.ebay_browser.prepare_sell_one_like_this(match, files)
        except Exception as error:
            self.root.after(0, self._sell_one_like_this_failed, archive_code, error)
            return
        self.root.after(0, self._sell_one_like_this_finished, archive_code, result)

    def _sell_one_like_this_failed(self, archive_code: str, error: Exception) -> None:
        self.research_var.set(f"{archive_code}: Sell one like this failed")
        messagebox.showerror("eBay Sell One Like This", str(error))

    def _sell_one_like_this_finished(self, archive_code: str, result: object) -> None:
        self.research_var.set(f"{archive_code}: eBay listing draft prepared")
        draft_url = getattr(result, "draft_url", "")
        messagebox.showinfo(
            "eBay Sell One Like This",
            "eBay created the prefilled listing draft and Ezcan uploaded the archived media.\n\n"
            f"Draft page:\n{draft_url}\n\nYour custom title and HTML description will be applied by the category template step.",
        )

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

        def open_candidate() -> None:
            selected_candidate = candidate_tree.selection()
            if not selected_candidate:
                messagebox.showinfo("Open eBay Listing", "Select a saved comparable first.", parent=dialog)
                return
            values = candidate_tree.item(selected_candidate[0], "values")
            item_url = str(values[5]) if len(values) > 5 else ""
            if not is_ebay_url(item_url):
                messagebox.showinfo("Open eBay Listing", "That comparable has no saved listing URL.", parent=dialog)
                return
            opener = self.ebay_account.open_url if self.ebay_account.state()["status"] == "connected" else webbrowser.open_new_tab
            try:
                if not opener(item_url):
                    raise OSError("The browser could not be opened")
            except OSError as error:
                messagebox.showerror("Open eBay Listing", f"Could not open that listing.\n\n{error}", parent=dialog)

        candidate_tree.bind("<Double-1>", lambda _event: open_candidate())
        candidate_buttons = tk.Frame(body, bg=self.panel)
        candidate_buttons.pack(fill="x", pady=(6, 0))
        tk.Button(candidate_buttons, text="OPEN LISTING", command=open_candidate).pack(anchor="e")

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

    def research_prices_for_selected_card(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Research Prices", "Select an archived card first.")
            return
        archive_code = str(selected[0])
        card = self.store.card_by_archive_code(archive_code)
        if card is None:
            messagebox.showinfo("Research Prices", "That row needs archive recovery before pricing can run.")
            return
        try:
            recommendation = self.store.market_recommendation(archive_code)
        except ValueError as error:
            messagebox.showinfo("Research Prices", str(error))
            return
        self.store.mark_prices_researched(archive_code)
        self.refresh()

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Research Prices - {archive_code}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        body = tk.Frame(dialog, bg=self.panel, padx=26, pady=22)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=f"PRICE RESEARCH  //  {archive_code}", bg=self.panel, fg=self.green, font=("Consolas", 11, "bold")).pack(anchor="w")
        tk.Label(body, text=f"{card['card_name']} / {card['set_name']} / {card['card_number']}", bg=self.panel, fg=self.text, font=("Bahnschrift", 16, "bold")).pack(anchor="w", pady=(6, 18))
        summary = (
            f"SOLD COMPARABLES     {recommendation.sold_count}\n"
            f"ACTIVE COMPETITION   {recommendation.active_count}\n"
            f"SOLD BUYER TOTAL     ${recommendation.lowest_sold_total:.2f} - ${recommendation.highest_sold_total:.2f}\n"
            f"MEDIAN BUYER TOTAL   ${recommendation.median_sold_total:.2f}\n\n"
            f"SUGGESTED CARD PRICE ${recommendation.suggested_item_low:.2f} - ${recommendation.suggested_item_high:.2f}\n"
            f"BUYER TOTAL RANGE    ${recommendation.suggested_total_low:.2f} - ${recommendation.suggested_total_high:.2f}\n"
            f"OWNER FIRST-ITEM SHIP ${recommendation.owner_shipping_charge:.2f}\n"
            f"ADDITIONAL CARD SHIP $0.00\n\n"
            f"ESTIMATED FEES       ${recommendation.estimated_fee_low:.2f} - ${recommendation.estimated_fee_high:.2f}\n"
            f"PROFIT BEFORE COSTS  ${recommendation.estimated_profit_before_costs_low:.2f} - ${recommendation.estimated_profit_before_costs_high:.2f}"
        )
        tk.Label(body, text=summary, bg=self.panel_deep, fg=self.text, font=("Consolas", 10), justify="left", anchor="w", padx=18, pady=16).pack(fill="x")
        tk.Label(body, text="Shipping is shown separately from the card price. Sold and active evidence are not combined.", bg=self.panel, fg=self.muted, font=("Segoe UI", 9), wraplength=470, justify="left").pack(anchor="w", pady=(16, 14))
        tk.Button(body, text="CLOSE", command=dialog.destroy).pack(anchor="e")
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

    def review_draft_for_selected_card(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Review Listing Draft", "Select an archived card first.")
            return
        archive_code = str(selected[0])
        card = self.store.card_by_archive_code(archive_code)
        listing = self.store.latest_listing_draft(archive_code)
        if card is None or listing is None:
            messagebox.showinfo("Review Listing Draft", "Create a local listing draft first.")
            return
        try:
            draft = json.loads(Path(listing["draft_path"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            messagebox.showerror("Review Listing Draft", f"Could not read the local draft.\n\n{error}")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Review Listing Draft - {archive_code}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("760x760")
        dialog.minsize(640, 650)
        body = tk.Frame(dialog, bg=self.panel, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=f"LOCAL DRAFT  //  {archive_code}", bg=self.panel, fg=self.magenta, font=("Consolas", 11, "bold")).pack(anchor="w")
        price_state = "Price confirmed" if draft.get("priceConfirmed") is True else "Price requires agreement"
        status_var = tk.StringVar(value=f"Review status: {listing['status']}  |  {price_state}  |  Never published")
        tk.Label(body, textvariable=status_var, bg=self.panel, fg=self.muted, font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 16))
        tk.Label(
            body,
            text=listing_draft_evidence_text(draft),
            bg=self.panel_deep,
            fg=self.cyan,
            font=("Consolas", 9),
            justify="left",
            anchor="w",
            wraplength=700,
            padx=14,
            pady=11,
        ).pack(fill="x", pady=(0, 16))
        if draft.get("researchStatus") == "outdated":
            tk.Label(
                body,
                text="PRICING NEEDS REFRESH  |  New market evidence was recorded after this draft was generated.",
                bg="#fff3d6",
                fg="#7a4d00",
                font=("Consolas", 9, "bold"),
                justify="left",
                anchor="w",
                wraplength=700,
                padx=14,
                pady=9,
            ).pack(fill="x", pady=(0, 16))
            image_strip = tk.Frame(body, bg=self.panel)
            image_strip.pack(fill="x", pady=(0, 16))
            image_strip.grid_columnconfigure(0, weight=1)
            image_strip.grid_columnconfigure(1, weight=1)
            draft_photos = []
            try:
                card_folder = Path(card["folder_path"])
                preview_paths = (find_front_image(card_folder), find_back_image(card_folder))
            except (FileNotFoundError, OSError, StopIteration):
                preview_paths = (None, None)
            for column, (title, image_path) in enumerate(zip(("FRONT", "BACK"), preview_paths)):
                cell = tk.Frame(image_strip, bg=self.panel_deep, height=145, highlightthickness=1, highlightbackground=self.border)
                cell.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 6 if column == 0 else 0))
                cell.grid_propagate(False)
                tk.Label(cell, text=title, bg=self.panel_deep, fg=self.cyan, font=("Consolas", 8, "bold")).pack(anchor="nw", padx=9, pady=(7, 0))
                image_label = tk.Label(cell, text="No preview", bg=self.panel_deep, fg=self.muted, font=("Consolas", 8))
                image_label.pack(expand=True)
                if image_path is not None:
                    try:
                        with Image.open(image_path) as image:
                            image.thumbnail((105, 118), Image.Resampling.LANCZOS)
                            photo = ImageTk.PhotoImage(image.copy())
                        draft_photos.append(photo)
                        image_label.configure(image=photo, text="")
                    except OSError:
                        pass
                dialog.draft_photos = draft_photos
        tk.Label(body, text="TITLE", bg=self.panel, fg=self.muted, font=("Consolas", 8, "bold")).pack(anchor="w")
        title_var = tk.StringVar(value=str(draft.get("title", "")))
        tk.Entry(body, textvariable=title_var, width=80).pack(fill="x", pady=(4, 14))
        listing_rules = tk.Frame(body, bg=self.panel_alt, highlightthickness=1, highlightbackground=self.border)
        listing_rules.pack(fill="x", pady=(0, 14))
        tk.Label(listing_rules, text="LISTING RULES", bg=self.panel_alt, fg=self.magenta, font=("Consolas", 8, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(10, 6))
        card_name_var = tk.StringVar(value=str(draft.get("itemSpecifics", {}).get("cardName", card.get("card_name") or "")))
        category_var = tk.StringVar(value=str(draft.get("storeCategory", "Non-TCG")))
        saved_product_type = str(draft.get("productType", "")).strip()
        product_type_key = product_template_key(saved_product_type) if saved_product_type else (
            infer_product_template(str(draft.get("title", ""))) or "japanese_tcg_old_back"
        )
        product_type_labels = product_template_choices()
        product_type_label_by_key = {
            product_template_key(label): label for label in product_type_labels
        }
        product_type_var = tk.StringVar(value=product_type_label_by_key[product_type_key])
        tk.Label(listing_rules, text="CARD NAME", bg=self.panel_alt, fg=self.muted, font=("Consolas", 8, "bold")).grid(row=1, column=0, sticky="w", padx=(12, 6), pady=(0, 10))
        tk.Entry(listing_rules, textvariable=card_name_var, width=23).grid(row=1, column=1, sticky="ew", pady=(0, 10))
        tk.Label(listing_rules, text="CATEGORY", bg=self.panel_alt, fg=self.muted, font=("Consolas", 8, "bold")).grid(row=1, column=2, sticky="w", padx=(16, 6), pady=(0, 10))
        ttk.Combobox(listing_rules, textvariable=category_var, values=STORE_CATEGORIES, state="readonly", width=12).grid(row=1, column=3, sticky="w", padx=(0, 12), pady=(0, 10))
        tk.Label(listing_rules, text="VINTAGE  ✓", bg=self.panel_alt, fg=self.blue, font=("Consolas", 8, "bold")).grid(row=2, column=0, sticky="w", padx=12, pady=(0, 10))
        tk.Label(listing_rules, text="CONDITION  POOR", bg=self.panel_alt, fg=self.blue, font=("Consolas", 8, "bold")).grid(row=2, column=1, sticky="w", pady=(0, 10))
        tk.Label(listing_rules, text="GRADING  UNGRADED", bg=self.panel_alt, fg=self.blue, font=("Consolas", 8, "bold")).grid(row=2, column=2, columnspan=2, sticky="w", padx=(16, 0), pady=(0, 10))
        tk.Label(listing_rules, text="PRODUCT LINE", bg=self.panel_alt, fg=self.muted, font=("Consolas", 8, "bold")).grid(row=3, column=0, sticky="w", padx=12, pady=(0, 12))
        product_type_box = ttk.Combobox(listing_rules, textvariable=product_type_var, values=product_type_labels, state="readonly", width=28)
        product_type_box.grid(row=3, column=1, columnspan=3, sticky="ew", padx=(0, 12), pady=(0, 12))
        tk.Label(listing_rules, text="INTERNAL DESCRIPTION TEMPLATE  •  EBAY CATEGORY REMAINS TCG", bg=self.panel_alt, fg=self.muted, font=("Segoe UI", 8)).grid(row=4, column=1, columnspan=3, sticky="w", padx=(0, 12), pady=(0, 10))
        listing_rules.grid_columnconfigure(1, weight=1)
        tk.Label(body, text="DESCRIPTION", bg=self.panel, fg=self.muted, font=("Consolas", 8, "bold")).pack(anchor="w")
        description = tk.Text(body, height=12, width=80, wrap="word")
        description.pack(fill="both", expand=True, pady=(4, 14))
        description.insert("1.0", str(draft.get("description", "")))

        def load_product_template(_event: object = None) -> None:
            specifics = draft.get("itemSpecifics", {})
            if not isinstance(specifics, dict):
                specifics = {}
            template_text = render_product_template(
                product_template_key(product_type_var.get()),
                card_name=card_name_var.get(),
                set_name=str(specifics.get("set", card.get("set_name") or "")),
                card_number=str(specifics.get("cardNumber", card.get("card_number") or "")),
            )
            template_text += (
                f"\n\nLanguage: {specifics.get('language', card.get('language') or '')}."
                f"\nCondition: Poor.\nGrading: Ungraded.\nArchive code: {archive_code}."
            )
            description.delete("1.0", "end")
            description.insert("1.0", enforce_condition_disclaimer(template_text))

        product_type_box.bind("<<ComboboxSelected>>", load_product_template)
        suggested = draft.get("suggestedPrice", {})
        suggested_low = str(suggested.get("low", ""))
        suggested_high = str(suggested.get("high", ""))
        price_var = tk.StringVar(value=str(draft.get("listingPrice") or suggested_high))
        price_box = tk.Frame(body, bg=self.panel_alt, highlightthickness=1, highlightbackground=self.border)
        price_box.pack(fill="x", pady=(0, 14))
        tk.Label(price_box, text=f"SUGGESTED PRICE  ${suggested_low} - ${suggested_high}", bg=self.panel_alt, fg=self.green, font=("Consolas", 9, "bold")).pack(side="left", padx=12, pady=10)
        tk.Label(price_box, text="PRICE TO LIST  $", bg=self.panel_alt, fg=self.muted, font=("Consolas", 8, "bold")).pack(side="left", padx=(18, 4), pady=10)
        tk.Entry(price_box, textvariable=price_var, width=12).pack(side="left", pady=10)
        tk.Label(price_box, text="Saving this review confirms the suggested or manual price.", bg=self.panel_alt, fg=self.muted, font=("Segoe UI", 8)).pack(side="left", padx=12, pady=10)
        note = tk.Label(body, text="Approve this draft locally, then publish it directly from the computer through the eBay Seller API.", bg=self.panel, fg=self.cyan, font=("Segoe UI", 9), wraplength=700, justify="left")
        note.pack(anchor="w", pady=(0, 16))

        buttons = tk.Frame(body, bg=self.panel)
        buttons.pack(fill="x")

        def save_review() -> None:
            try:
                self.store.update_listing_draft(
                    archive_code,
                    title_var.get(),
                    description.get("1.0", "end"),
                    card_name=card_name_var.get(),
                    store_category=category_var.get(),
                    product_type=product_type_var.get(),
                    price=price_var.get(),
                )
            except ValueError as error:
                messagebox.showerror("Review Listing Draft", str(error), parent=dialog)
                return
            status_var.set("Review status: reviewed  |  Price confirmed  |  Never published")
            self.draft_var.set(f"{archive_code}: draft reviewed")
            self.refresh()

        def set_status(status: str) -> None:
            try:
                self.store.set_listing_status(archive_code, status)
            except ValueError as error:
                messagebox.showerror("Review Listing Draft", str(error), parent=dialog)
                return
            status_var.set(f"Review status: {status}  |  Never published")
            if status == "approved":
                publish_button.configure(state="normal")
            else:
                publish_button.configure(state="disabled")
            self.draft_var.set(f"{archive_code}: draft {status}")
            self.refresh()

        def regenerate() -> None:
            try:
                self.store.create_listing_draft(archive_code)
            except (OSError, ValueError) as error:
                messagebox.showerror("Review Listing Draft", f"Could not regenerate the local draft.\n\n{error}", parent=dialog)
                return
            dialog.destroy()
            self.draft_var.set(f"{archive_code}: draft regenerated")
            self.refresh()

        def publish() -> None:
            self.publish_selected_card_to_ebay(archive_code, dialog)

        tk.Button(buttons, text="SAVE REVIEW", command=save_review).pack(side="left")
        tk.Button(buttons, text="APPROVE LOCALLY", command=lambda: set_status("approved")).pack(side="left", padx=(8, 0))
        tk.Button(buttons, text="REJECT", command=lambda: set_status("rejected")).pack(side="left", padx=(8, 0))
        tk.Button(buttons, text="REGENERATE", command=regenerate).pack(side="left", padx=(8, 0))
        publish_button = tk.Button(buttons, text="PUBLISH TO EBAY", command=publish, bg=self.cyan, fg=self.text, relief="flat", padx=12, pady=5, cursor="hand2")
        publish_button.pack(side="left", padx=(8, 0))
        if listing["status"] != "approved":
            publish_button.configure(state="disabled")
        tk.Button(buttons, text="CLOSE", command=dialog.destroy).pack(side="right")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.focus_force()

    def print_archive_labels(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Print Archive ID Labels")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("760x590")
        dialog.minsize(680, 520)
        body = tk.Frame(dialog, bg=self.panel, padx=28, pady=24)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="ARCHIVE ID LABELS", bg=self.panel, fg=self.cyan, font=("Consolas", 11, "bold")).pack(anchor="w")
        tk.Label(body, text="Print a numbered session, then use each label in order.", bg=self.panel, fg=self.text, font=("Bahnschrift", 18, "bold")).pack(anchor="w", pady=(5, 2))
        tk.Label(body, text="Ezcan keeps the sequence automatically. Reprinting only offers the unused tail of an earlier session.", bg=self.panel, fg=self.muted, font=("Segoe UI", 9), wraplength=680, justify="left").pack(anchor="w", pady=(0, 20))

        new_panel = tk.Frame(body, bg=self.panel_alt, highlightthickness=1, highlightbackground=self.border)
        new_panel.pack(fill="x", pady=(0, 20))
        tk.Label(new_panel, text="NEW PRINT SESSION", bg=self.panel_alt, fg=self.blue, font=("Consolas", 9, "bold")).grid(row=0, column=0, columnspan=5, sticky="w", padx=16, pady=(14, 9))
        tk.Label(new_panel, text="Labels needed", bg=self.panel_alt, fg=self.muted, font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", padx=(16, 7), pady=(0, 14))
        count_var = tk.StringVar(value="50")
        tk.Spinbox(new_panel, from_=1, to=1000, textvariable=count_var, width=7, font=("Consolas", 11)).grid(row=1, column=1, sticky="w", pady=(0, 14))
        tk.Label(new_panel, text="Paper", bg=self.panel_alt, fg=self.muted, font=("Segoe UI", 9)).grid(row=1, column=2, sticky="e", padx=(20, 7), pady=(0, 14))
        paper_var = tk.StringVar(value="A4")
        ttk.Combobox(new_panel, textvariable=paper_var, values=("A4", "Letter"), state="readonly", width=9).grid(row=1, column=3, sticky="w", padx=(0, 16), pady=(0, 14))

        session_list = tk.Listbox(body, height=8, exportselection=False, font=("Consolas", 10), bg=self.panel_deep, fg=self.text, selectbackground="#d8f5f6", selectforeground=self.text, relief="flat", highlightthickness=1, highlightbackground=self.border)
        session_rows: list[sqlite3.Row] = []

        def refresh_sessions() -> None:
            session_rows.clear()
            session_rows.extend(self.store.label_batches())
            session_list.delete(0, tk.END)
            for row in session_rows:
                session_list.insert(tk.END, f"{str(row['created_at'])[:10]}   {row['start_code']} - {row['end_code']}   {row['assigned_count']}/{row['requested_count']} used   {row['remaining_count']} remaining")
            if not session_rows:
                session_list.insert(tk.END, "No label sessions yet")

        def open_sheet(codes: list[str], batch_id: str | None, label: str) -> None:
            output_dir = self.store.root / "Label Prints"
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            destination = output_dir / f"archive-labels-{label}-{timestamp}.html"
            try:
                build_label_sheet(codes, destination, paper=paper_var.get())
                if batch_id:
                    self.store.record_label_batch_file(batch_id, destination)
                if not webbrowser.open_new_tab(destination.resolve().as_uri()):
                    raise OSError("The print sheet could not be opened in the browser")
            except (OSError, ValueError) as error:
                messagebox.showerror("Print Archive Labels", f"Could not create the print sheet.\n\n{error}", parent=dialog)
                return
            messagebox.showinfo("Print Archive Labels", f"Print sheet ready with {len(codes)} labels.\n\nUse 100% scale and turn off browser headers and footers.\n\nSaved locally at:\n{destination}", parent=dialog)

        def create_session() -> None:
            try:
                count = int(count_var.get())
            except ValueError:
                messagebox.showerror("New Print Session", "Enter a whole number of labels.", parent=dialog)
                return
            try:
                batch_id, codes = self.store.reserve_label_batch(count)
            except (RuntimeError, ValueError) as error:
                messagebox.showerror("New Print Session", str(error), parent=dialog)
                return
            open_sheet(codes, batch_id, f"new-{codes[0]}-{codes[-1]}")
            refresh_sessions()

        tk.Button(new_panel, text="PRINT NEW SESSION", command=create_session, bg=self.blue, fg="white", relief="flat", padx=12, pady=5, cursor="hand2").grid(row=1, column=4, padx=(16, 16), pady=(0, 14))
        new_panel.grid_columnconfigure(2, weight=1)
        tk.Label(body, text="EARLIER PRINT SESSIONS", bg=self.panel, fg=self.magenta, font=("Consolas", 9, "bold")).pack(anchor="w")
        tk.Label(body, text="Select a session to reprint its remaining labels.", bg=self.panel, fg=self.muted, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 8))
        session_list.pack(fill="both", expand=True)

        def reprint_remaining() -> None:
            selection = session_list.curselection()
            if not selection or not session_rows:
                messagebox.showinfo("Reprint Labels", "Select an earlier print session first.", parent=dialog)
                return
            row = session_rows[selection[0]]
            try:
                codes = self.store.reprint_label_batch(str(row["batch_id"]))
            except ValueError as error:
                messagebox.showinfo("Reprint Labels", str(error), parent=dialog)
                return
            open_sheet(codes, str(row["batch_id"]), f"reprint-{codes[0]}-{codes[-1]}")
            refresh_sessions()

        refresh_sessions()
        actions = tk.Frame(body, bg=self.panel)
        actions.pack(fill="x", pady=(14, 0))
        tk.Button(actions, text="REPRINT REMAINING", command=reprint_remaining, bg=self.magenta, fg="white", relief="flat", padx=12, pady=6, cursor="hand2").pack(side="left")
        tk.Button(actions, text="CLOSE", command=dialog.destroy, relief="flat", padx=14, pady=6, cursor="hand2").pack(side="right")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.focus_force()

    def publish_selected_card_to_ebay(self, archive_code: str, dialog: tk.Toplevel | None = None) -> None:
        """Publish one approved local draft through the computer-side API."""
        config = self.ebay_oauth.config
        if not config.publishing_configured:
            messagebox.showinfo(
                "eBay Seller API",
                "The seller API is connected, but listing settings are incomplete.\n\n"
                "Configure EBAY_CATEGORY_ID, EBAY_MERCHANT_LOCATION_KEY, "
                "EBAY_FULFILLMENT_POLICY_ID, EBAY_PAYMENT_POLICY_ID, and "
                "EBAY_RETURN_POLICY_ID on the computer.",
                parent=dialog,
            )
            return
        listing = self.store.latest_listing_draft(archive_code)
        card = self.store.card_by_archive_code(archive_code)
        if listing is None or card is None:
            messagebox.showerror("Publish to eBay", "The local card or draft was not found.", parent=dialog)
            return
        if listing["status"] != "approved":
            messagebox.showinfo("Publish to eBay", "Approve the local draft before publishing it.", parent=dialog)
            return
        if listing["ebay_publish_status"] != "published":
            try:
                draft_preview = json.loads(Path(listing["draft_path"]).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                messagebox.showerror("Publish to eBay", f"The local draft could not be read.\n\n{error}", parent=dialog)
                return
            if draft_preview.get("priceConfirmed") is not True:
                messagebox.showinfo("Publish to eBay", "Confirm the suggested price or enter a manual price before publishing.", parent=dialog)
                return
        if listing["ebay_publish_status"] == "published" and listing["ebay_listing_id"]:
            messagebox.showinfo("Publish to eBay", f"This archive ID is already published as {listing['ebay_listing_id']}.", parent=dialog)
            return
        try:
            draft = json.loads(Path(listing["draft_path"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            messagebox.showerror("Publish to eBay", f"The local draft could not be read.\n\n{error}", parent=dialog)
            return
        image_paths = [Path(str(path)) for path in draft.get("imagePaths", []) if str(path).strip()]
        if not image_paths:
            messagebox.showerror("Publish to eBay", "The local draft contains no card images.", parent=dialog)
            return
        item_specifics = draft.get("itemSpecifics", {})
        aspect_names = {
            "language": "Language",
            "cardName": "Character",
            "set": "Set",
            "cardNumber": "Card Number",
            "edition": "Edition",
            "printing": "Printing",
            "finish": "Finish",
            "condition": "Card Condition",
            "gradeCompany": "Professional Grader",
            "grade": "Grade",
            "vintage": "Vintage",
        }
        aspects = {
            aspect_names[key]: [str(value)]
            for key, value in item_specifics.items()
            if key in aspect_names and str(value or "").strip() and str(value).lower() != "none"
        }
        suggested_price = draft.get("suggestedPrice", {})
        price = str(draft.get("listingPrice") or suggested_price.get("high") or "0").strip()
        if not price or price == "0":
            messagebox.showerror("Publish to eBay", "The draft has no listing price.", parent=dialog)
            return
        store_category = str(draft.get("storeCategory") or config.store_category)
        if store_category not in STORE_CATEGORIES:
            messagebox.showerror("Publish to eBay", "The draft has an invalid store category.", parent=dialog)
            return
        try:
            self.ebay_sell.validate_fixed_item_location(config.merchant_location_key)
            self.ebay_sell.validate_fixed_shipping_policy(config.fulfillment_policy_id)
            branding_urls = self.ensure_store_branding()
            self.store.update_ebay_publish_state(archive_code, "publishing", error=None)
            result = self.ebay_sell.publish_listing(
                archive_code,
                title=str(draft.get("title", "")),
                description_html=fill_store_branding(
                    str(draft.get("descriptionHtml") or draft.get("description", "")),
                    branding_urls,
                ),
                image_paths=image_paths,
                video_paths=[Path(str(path)) for path in draft.get("videoPaths", []) if str(path).strip()],
                aspects=aspects,
                category_id=config.category_id,
                price=price,
                merchant_location_key=config.merchant_location_key,
                fulfillment_policy_id=config.fulfillment_policy_id,
                payment_policy_id=config.payment_policy_id,
                return_policy_id=config.return_policy_id,
                condition="USED",
                store_category_names=[store_category],
            )
            self.store.update_ebay_publish_state(
                archive_code,
                "published",
                offer_id=str(result["offerId"]),
                listing_id=str(result["listingId"]),
                image_urls=[str(url) for url in result["imageUrls"]],
            )
            draft["publishing"] = {"published": True, "sellerCredentialsUsed": True}
            draft["ebay"] = result
            Path(listing["draft_path"]).write_text(json.dumps(draft, indent=2), encoding="utf-8")
        except Exception as error:
            self.store.update_ebay_publish_state(archive_code, "failed", error=str(error))
            messagebox.showerror("Publish to eBay", f"The listing was not published.\n\n{error}", parent=dialog)
            self.refresh()
            return
        self.draft_var.set(f"{archive_code}: published to eBay")
        self.refresh()
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()
        messagebox.showinfo("Publish to eBay", f"Published archive {archive_code} directly to eBay.\n\nListing ID: {result['listingId']}")

    def ensure_store_branding(self) -> dict[str, str]:
        """Upload the supplied store artwork once and reuse eBay HTTPS URLs."""
        paths = branding_asset_paths()
        missing = [str(path) for path in paths.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "Store branding artwork is missing:\n" + "\n".join(missing)
            )
        urls = self.store.load_branding_urls()
        for key, path in paths.items():
            if str(urls.get(key, "")).lower().startswith("https://"):
                continue
            urls[key] = self.ebay_sell.upload_image(path)
        required = required_description_assets()
        if not all(str(urls.get(key, "")).lower().startswith("https://") for key in required):
            raise EbayIntegrationError("Store branding images could not be hosted securely by eBay.")
        self.store.save_branding_urls(urls)
        return urls

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
        if self.ebay_browser is not None:
            self.ebay_browser.close()
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
