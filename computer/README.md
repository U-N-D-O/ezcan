# Ezcan Computer

Windows companion program for the Ezcan iOS capture app.

## What works now

- Local receiver on the private Wi-Fi network.
- QR pairing payload displayed in the dashboard.
- Bearer-token authentication for phone requests.
- One intake per physical card.
- Streamed photo and video uploads.
- SHA-256 upload verification.
- Safe retry for the same file.
- Sequential archive codes in the `letter-digit-letter-digit` format, starting at `A0A0`.
- Permanent card folders named with the archive code.
- SQLite records and `manifest.json` files.
- Local dashboard at `http://localhost:8765`.

The eBay Picture Search, market research, and listing-draft screens are intentionally the next phase. The receiver is the foundation they use.

## Run from source

From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r computer\requirements.txt
$env:EZCAN_NO_BROWSER = "1"
python computer\ezcan_computer.py
```

Open the displayed address in a browser. The iPhone and computer must be on the same private Wi-Fi network. Do not use router port forwarding.

Data is stored in `%LOCALAPPDATA%\Ezcan` on Windows. Set `EZCAN_DATA_DIR` to choose another location.

## Build the executable locally

```powershell
python -m PyInstaller --clean --noconfirm --onefile --name EzcanComputer computer\ezcan_computer.py
```

The executable is created at `dist\EzcanComputer.exe`.

## GitHub Actions

The repository workflow at `.github/workflows/build-windows.yml` runs tests and builds `EzcanComputer.exe` on a GitHub-hosted Windows runner. The executable is uploaded as a workflow artifact for each push and pull request.

## API contract used by iOS

```text
POST /api/intakes
POST /api/intakes/{intakeId}/media
GET  /api/intakes/{intakeId}/status
POST /api/intakes/{intakeId}/complete
```

The iOS app sends the pairing token as a Bearer token and media as the raw request body with these headers:

```text
X-Ezcan-File-Name
X-Ezcan-Media-Type
X-Ezcan-SHA256
```

Finalization returns:

```json
{
  "archiveCode": "K4M7"
}
```
