from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_FILE = PROJECT_ROOT / "computer" / "ezcan_computer.py"
ICON_FILE = PROJECT_ROOT / "icons" / "ezcan_logo.ico"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"


def run_build() -> int:
    if not SOURCE_FILE.is_file():
        print(f"Could not find the computer program: {SOURCE_FILE}")
        return 1

    executable = DIST_DIR / "EzcanComputer.exe"
    if executable.is_file():
        try:
            executable.unlink()
        except PermissionError:
            print(f"Could not replace {executable} because Windows has it open.")
            print("Close EzcanComputer.exe, then run this builder again.")
            print("If it is not visible, end the EzcanComputer.exe process in Task Manager.")
            return 1

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        "EzcanComputer",
        "--icon",
        str(ICON_FILE),
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        str(SOURCE_FILE),
    ]

    print("Building EzcanComputer.exe...")
    print(f"Source: {SOURCE_FILE}")
    try:
        result = subprocess.run(command, cwd=PROJECT_ROOT)
    except FileNotFoundError:
        print("PyInstaller is not installed for this Python installation.")
        print(f"Install it with: {sys.executable} -m pip install pyinstaller")
        return 1

    if result.returncode == 0 and executable.is_file():
        print(f"\nBuild complete:\n{executable}")
        return 0

    print(f"\nBuild failed with exit code {result.returncode}.")
    return result.returncode or 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Ezcan Computer Windows executable.")
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Do not wait for Enter before closing; useful from a terminal or CI.",
    )
    arguments = parser.parse_args()
    exit_code = run_build()
    if not arguments.no_pause:
        input("\nPress Enter to close...")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
