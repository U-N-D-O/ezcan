from __future__ import annotations

import json
import os
import shutil
import subprocess
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


EBAY_SIGN_IN_URL = "https://www.ebay.com/signin/"


@dataclass(frozen=True)
class AccountLaunch:
    url: str
    profile_path: Path
    persistent: bool


class EbayAccountManager:
    def __init__(self, base_path: Path | None = None):
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        self.base_path = base_path or local_app_data / "Ezcan"
        self.profile_path = self.base_path / "browser-profile"
        self.metadata_path = self.base_path / "ebay-account.json"

    def state(self) -> dict[str, str]:
        if not self.metadata_path.is_file():
            return {"status": "not_connected", "profilePath": str(self.profile_path)}
        try:
            data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"status": "login_required", "profilePath": str(self.profile_path)}
        status = str(data.get("status", "login_required"))
        if status not in {"not_connected", "login_required", "connected"}:
            status = "login_required"
        return {"status": status, "profilePath": str(self.profile_path)}

    def begin_sign_in(
        self,
        opener: Callable[[str], bool] = webbrowser.open_new_tab,
    ) -> AccountLaunch:
        self.profile_path.mkdir(parents=True, exist_ok=True)
        self._write_state("login_required")
        launch = self.open_url(EBAY_SIGN_IN_URL, opener=opener)
        return AccountLaunch(EBAY_SIGN_IN_URL, self.profile_path, persistent=launch)

    def open_url(
        self,
        url: str,
        opener: Callable[[str], bool] = webbrowser.open_new_tab,
    ) -> bool:
        browser = self._browser_executable() if self.profile_path.is_dir() else None
        if browser is None:
            if not opener(url):
                raise OSError("The default browser could not be opened")
            return False
        try:
            subprocess.Popen(
                [browser, f"--user-data-dir={self.profile_path}", "--new-window", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            if not opener(url):
                raise OSError("The eBay browser could not be opened")
            return False
        return True

    def mark_connected(self) -> None:
        if not self.profile_path.is_dir():
            raise ValueError("Sign in through the eBay browser profile first")
        self._write_state("connected")

    def mark_login_required(self) -> None:
        self._write_state("login_required")

    def remove_profile(self) -> None:
        if self.profile_path.exists():
            shutil.rmtree(self.profile_path)
        self._write_state("not_connected")

    def _write_state(self, status: str) -> None:
        self.base_path.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": status,
            "profilePath": str(self.profile_path),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        self.metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _browser_executable() -> str | None:
        candidates = [
            shutil.which("msedge.exe"),
            shutil.which("chrome.exe"),
            shutil.which("brave.exe"),
        ]
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = Path(os.environ.get("PROGRAMFILES", ""))
        program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", ""))
        candidates.extend(
            [
                str(local_app_data / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                str(program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                str(program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                str(local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe"),
                str(program_files / "Google" / "Chrome" / "Application" / "chrome.exe"),
                str(program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe"),
            ]
        )
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        return None
