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
- Prepared eBay search images generated from the archived front photo.
- Selected-card workbench with a `Recent Activity` list and no raw folder/timestamp columns.
- State-aware selected-card controls that enable only the next valid workflow actions.
- Dedicated `RESEARCH PRICES` summary showing sold evidence, active competition, buyer totals, owner shipping, fees, and profit assumptions separately.
- Successful price research marks the card `researched`; adding another eBay comparable returns it to identity-confirmed status so the report can be refreshed.
- Local draft review shows the stored market evidence and shipping assumptions beside the editable title and description.
- Recording a new comparable marks an existing draft's pricing as outdated and shows a refresh warning without deleting edits.
- Local draft review also shows archived front and back media thumbnails before local approval.
- Selected-card preview presents archived front and back images side by side, with a fallback for older generic filenames.
- Persistent visible eBay search-account sign-in under `%LOCALAPPDATA%\Ezcan\browser-profile`.
- Visible browser-assisted eBay picture search launch from the selected-card workspace.
- Manual eBay match recording with sold/active prices, shipping, URLs, and notes.
- Explicit card-identity confirmation before pricing calculations.
- Sold-comparable pricing summary with separate `$34` first-item shipping.
- Local listing-draft JSON generated only after identity and pricing evidence are confirmed, with local review/edit/approve/reject/regenerate controls.
- Versioned SQLite initialization with backup-before-migration and interrupted-finalization recovery.
- Local dashboard at `http://localhost:8765`.

If a finalization is interrupted, the intake is recovered when possible. A move that needs manual attention appears in `Recent Activity` as `Recovery required` with `Archive move interrupted`; the selected-card workspace offers `REPAIR ARCHIVE` once the expected archive folder has been restored, and no eBay or draft action is run until repair succeeds.

Use `SIGN IN / OPEN EBAY` in the left pairing panel to open a separate headed Edge, Chrome, or Brave profile for the eBay search-only account. Sign in manually in that window, then click `I'M SIGNED IN`. Ezcan stores only profile metadata and connection state, never a username, password, seller credential, or raw cookie. A connected state automatically falls back to `login_required` if that profile is removed. `REMOVE SESSION` clears the local profile. If a supported browser is not installed, Ezcan falls back to the default browser and keeps the manual flow visible.

The eBay picture-search step prepares the front image, opens eBay, copies the prepared image path, and records an `awaiting_manual_upload` search session. In eBay, click the camera icon at the far right of the search field and choose that image manually. Use `ADD MATCH` to record selected sold or active results, then `REVIEW IDENTITY` to confirm the exact card identity. Pricing uses sold buyer-paid totals as its evidence, keeps active results separate, and subtracts `$34` only when showing the suggested one-card item price. `MAKE DRAFT` writes an unpublished `generated/listing-draft.json` file with card metadata, image paths, research, suggested prices, and shipping settings. `REVIEW DRAFT` allows local title/description edits and local `reviewed`, `approved`, or `rejected` status changes; `REGENERATE` creates a fresh local draft. CAPTCHA, two-factor challenges, automated result acceptance, seller credentials, and live publishing remain outside this release.

## Run from source

From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r files\computer\requirements.txt
$env:EZCAN_NO_BROWSER = "1"
python files\computer\ezcan_computer.py
```

Open the displayed address in a browser. The iPhone and computer must be on the same private Wi-Fi network. Do not use router port forwarding.

Data is stored in `%LOCALAPPDATA%\Ezcan` on Windows. Set `EZCAN_DATA_DIR` to choose another location.

## Build the executable locally

```powershell
python make_ezcan_exe.py --no-pause
```

The executable is created at the repository root as `EzcanComputer.exe`.

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
