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
- A card cannot enter `researched` without at least one sold comparable; active listings remain separate competition evidence.
- Local draft review shows the stored market evidence and shipping assumptions beside the editable title and description.
- Recording a new comparable marks an existing draft's pricing as outdated and shows a refresh warning without deleting edits.
- Local draft review also shows archived front and back media thumbnails before local approval.
- Selected-card preview presents archived front and back images side by side, with a fallback for older generic filenames.
- Persistent visible eBay search-account sign-in under `%LOCALAPPDATA%\Ezcan\browser-profile`.
- Computer-side eBay visual-search worker that uploads the prepared front image, collects the first five visual matches, and lets the seller choose the exact product.
- Selected visual match can activate eBay's `Sell one like this` page and upload the archived card photos/video without manually typing a search phrase.
- Drafts use responsive, eBay-safe HTML with the archive ID, fixed condition notice, shipping facts, and a gallery filled from eBay-hosted HTTPS image URLs after upload.
- Listing descriptions include the four `cat ...` category graphics, links to the four store sections, the store CTA artwork, an About the Store link, and the thank-you panel. The numbered `1 TCG.png` through `4 Bulk.png` graphics are uploaded and reserved for the eBay storefront's Featured categories.
- `Store logo.png` is kept as the storefront logo, separate from the eBay username/avatar. eBay recommends a 300 x 300 logo under 12 MB; the supplied 2000 x 2000 source is suitable for eBay to resize during upload.
- Suggested Store About text is defined in `store_branding.py` and clearly states that the store specializes specifically in vintage Japanese Pokémon artwork by Ken Sugimori, especially early 1996–1998 releases.
- Plain-text product copy templates are prepared for Japanese TCG old back, Japanese TCG new back, Topsun, Bandai Carddass 1996, Bandai Carddass 1997, Amada stickers 1996, and Amada stickers 1997. The Carddass 1997 starter text records the seller's Part 3/4 manga-style Sugimori provenance and 25 Years art-book reference.
- Listing rules are enforced in the local draft: Vintage is enabled, condition is Poor, grading is Ungraded, and the buyer-facing condition disclaimer always remains present.
- Review exposes only the card name, internal product line, short store category (`TCG`, `Non-TCG`, `PSA`, or `Bulk`), and price decision as the normal manual inputs; the product line selects description copy and is never sent as an eBay marketplace category. The suggested price must be accepted or replaced before approval.
- Every listing carries the fixed shipping profile: Expedited International Shipping, 7 - 15 business days, $35.00 domestic and international flat rate, 2 business days handling, and item location Nuuk, Greenland.
- Manual eBay match recording with sold/active prices, shipping, URLs, and notes.
- Saved comparable rows can open their listing URL in the separate visible eBay profile when connected.
- Comparable URLs are limited to HTTPS eBay hosts before they can be saved or opened.
- Explicit card-identity confirmation before pricing calculations.
- Sold-comparable pricing summary with separate `$35` flat-rate shipping.
- Local listing-draft JSON generated only after identity and pricing evidence are confirmed, with local review/edit/approve/reject/regenerate controls.
- Computer-only official eBay Sell API foundation: OAuth authorization, secure refresh-token storage through Windows Credential Manager, category item-aspect lookup, eBay image upload, inventory-item creation, offer creation, and publishing.
- Computer-side video upload is included: the archive video is registered with eBay, uploaded within eBay's 150 MB limit, and attached to the listing through its video ID.
- Seller listings are designed to publish directly from the computer without opening an eBay browser. The phone app does not log in to eBay and never receives seller credentials.
- Versioned SQLite initialization with backup-before-migration and interrupted-finalization recovery.
- Local dashboard at `http://localhost:8765`.

If a finalization is interrupted, the intake is recovered when possible. A move that needs manual attention appears in `Recent Activity` as `Recovery required` with `Archive move interrupted`; the selected-card workspace offers `REPAIR ARCHIVE` once the expected archive folder has been restored, and no eBay or draft action is run until repair succeeds.

Use `SIGN IN / OPEN EBAY` in the left pairing panel to open a separate headed Edge, Chrome, or Brave profile for the eBay search-only account. Sign in manually in that window, then click `I'M SIGNED IN`. Ezcan stores only profile metadata and connection state, never a username, password, seller credential, or raw cookie. Only a persistent profile launch can become `connected`; a default-browser fallback remains `login_required`. A connected state automatically falls back to `login_required` if that profile is removed. `REMOVE SESSION` clears the local profile. If a supported browser is not installed, Ezcan falls back to the default browser and keeps the manual flow visible.

The eBay picture-search step prepares the front image and sends it to eBay's visual-search page through the computer-side Playwright worker. Ezcan presents up to five visual matches; selecting one records the match and activates that item's `Sell one like this` page, where the archived photos and video are uploaded automatically. eBay supplies the matched category and item specifics. CAPTCHA, two-factor challenges, and other eBay verification screens are never bypassed; the worker stops and asks for normal seller action if eBay presents one. The custom Sugimori Gem Archive title and responsive HTML description are generated locally, with the final card gallery filled from eBay-hosted HTTPS image URLs during API publication.

### One-time computer eBay connection

Direct publishing uses eBay's official OAuth and Sell APIs rather than reusing a browser cookie. An existing eBay sign-in is not itself an API authorization. The computer needs an eBay Developer Program application with these values configured outside the project files:

```powershell
$env:EBAY_CLIENT_ID = "your-app-id"
$env:EBAY_CLIENT_SECRET = "your-cert-id-secret"
$env:EBAY_RU_NAME = "your-registered-redirect-name"
$env:EBAY_MARKETPLACE_ID = "EBAY_US"
$env:EBAY_STORE_URL = "https://www.ebay.com/str/SugimoriGemArchive"
```

Click `CONNECT SELLER API` once in Ezcan and complete eBay's consent page. The long-lived refresh token is stored through Windows Credential Manager when `keyring` is installed. After that, listing creation can upload the archived images and publish through the computer directly. The final publishing screen will also collect the seller's eBay inventory location and business-policy IDs once, then reuse them automatically.

On the first direct publication, Ezcan uploads the supplied store artwork to eBay's HTTPS image hosting and saves the returned URLs under `Archive\store-branding-urls.json`. Later listings reuse that cache. If the final eBay store name or URL differs, set `EBAY_STORE_URL` before publishing; the links are generated from that value.

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
