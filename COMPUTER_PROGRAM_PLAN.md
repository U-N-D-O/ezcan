# Ezcan Computer Program Plan

## 1. Purpose

Ezcan Computer is a Windows program that receives Pokemon card photos and videos from the Ezcan iOS app, archives each physical card, uses eBay Picture Search to find likely matches, researches market prices, prepares listing drafts, and later manages shelf locations.

The first version should create complete listing drafts and require human approval before anything is published to eBay.

## 2. Target and Packaging

- Windows 10 or Windows 11
- Packaged as an `.exe`
- Local-only operation by default
- SQLite database
- Local browser dashboard
- User data stored outside the installation folder
- PyInstaller for the first executable build

The executable should start the local server and open the dashboard in the default browser.

## 3. Technology

Recommended initial stack:

- Python
- FastAPI for the local HTTP API
- Uvicorn for the local server
- SQLite
- SQLAlchemy or another structured database layer
- Jinja2 and a small local frontend for the dashboard
- Pillow and OpenCV for image preparation
- QR-code generation library
- PyInstaller for Windows packaging
- FFmpeg only if video conversion becomes necessary

Use official eBay APIs where they provide the required capability. If eBay Picture Search is not available through a supported public API, use an assisted browser workflow or open the supported eBay search page for user confirmation. Do not base the system on bypassing authentication, CAPTCHAs, rate limits, or access controls.

## 4. Recommended Project Structure

```text
 ezcan-computer/
   app/
     api/
     database/
     intake/
     media/
     ebay/
     pricing/
     listings/
     inventory/
     templates/
     static/
   tests/
   scripts/
   .github/
     workflows/
       build-windows.yml
   COMPUTER_PROGRAM_PLAN.md
   README.md
   requirements.txt
```

The computer program can initially be a separate repository from the iOS repository. The iOS repository is named `ezcan`; choose a clear separate name for this repository when implementation begins, such as `ezcan-computer`.

## 5. Local Folder Structure

```text
PokemonShop/
  Incoming/
  Cards/
    K4M7/
      original/
        front.heic
        back.heic
        detail-1.heic
        card-video.mov
      generated/
      screenshots/
      manifest.json
  Exports/
  Backups/
  Logs/
```

The permanent folder for every finalized card must be named exactly with its archive code. Temporary uploads must use a temporary name until the files have been completely received and verified:

```text
PokemonShop/Incoming/uploading-<temporary-id>/
```

## 6. Archive Code System

The computer program owns archive-code generation. The iOS app only displays the code returned by the computer.

Recommended format:

```text
letter-digit-letter-digit
```

Examples:

```text
K4M7
R8C3
T2W9
```

Rules:

- Generate codes randomly.
- Use an alphabet that excludes confusing letters and digits, such as `I`, `O`, `S`, `Z`, `0`, `1`, and `5`.
- Require the two letters to be different.
- Check every candidate against the database.
- Never reuse retired codes.
- Do not calculate a code by counting folders or incrementing the previous code.
- Store the code in the database, folder name, manifest, physical label, and listing record.
- Also store a UUID as the internal permanent identifier.

Example:

```text
Human archive code: K4M7
Internal ID: 7f3b1a2e-...
Folder: Cards/K4M7/
```

The code identifies one physical card. A second copy of the same card receives a different code.

## 7. Pairing and Local Receiver

The program should:

- Start a local HTTP server.
- Listen only on the private-network interface as appropriate.
- Display the computer name and local URL.
- Generate a QR code containing the URL and temporary pairing token.
- Require approval before pairing a new phone.
- Expire pairing tokens.
- Show the connected phone and pairing status.
- Provide manual URL and token entry as a fallback.
- Avoid router port forwarding.
- Provide clear instructions when Windows Firewall blocks private-network access.

Example address:

```text
http://192.168.1.25:8765
```

The phone and computer must be on the same normal private Wi-Fi network. Guest Wi-Fi may isolate devices.

## 8. Intake API

Expected endpoints:

```text
POST /api/pair
POST /api/intakes
POST /api/intakes/{intakeId}/media
GET  /api/intakes/{intakeId}/status
POST /api/intakes/{intakeId}/complete
```

The API must:

- Authenticate paired requests.
- Validate media type and file size.
- Stream media to disk.
- Avoid loading complete videos into memory.
- Verify SHA-256 hashes or equivalent file checks.
- Support retry and idempotency keys.
- Reject duplicate files safely.
- Keep incomplete uploads separate from finalized cards.
- Finalize an intake only after all expected media has arrived.
- Return the permanent archive code after successful finalization.

## 9. Intake Finalization

When the iPhone completes an intake:

1. Verify every uploaded file.
2. Verify the manifest and expected media list.
3. Generate a unique archive code.
4. Create the permanent card database record.
5. Rename the temporary folder to the archive code.
6. Create `original`, `generated`, and `screenshots` directories.
7. Write `manifest.json`.
8. Return the archive code to the iPhone.
9. Add the card to the review queue.
10. Offer a printable QR or Code 128 label.

Finalization must be recoverable if the program stops halfway through. On startup, the program should detect incomplete finalizations and either resume or place them in a visible recovery queue.

Example manifest:

```json
{
  "archiveCode": "K4M7",
  "internalId": "7f3b1a2e-...",
  "status": "received",
  "createdAt": "2026-09-01T14:30:00Z",
  "media": [
    {
      "fileName": "front.heic",
      "type": "image",
      "sha256": "..."
    }
  ]
}
```

## 10. Database Records

### Cards

```text
cards
- internal_id
- archive_code
- status
- created_at
- updated_at
- folder_path
- card_name
- set_name
- card_number
- language
- edition
- printing
- finish
- condition
- authenticity_status
- notes
```

### Media

```text
media
- id
- card_internal_id
- file_path
- media_type
- original_name
- file_hash
- file_size
- sort_order
- created_at
```

### Comparables

```text
comparables
- id
- card_internal_id
- source
- market_status
- item_url
- title
- sale_or_listing_date
- price
- shipping_price
- total_buyer_cost
- condition
- grade
- listing_format
- screenshot_path
```

### Listings

```text
listings
- id
- card_internal_id
- ebay_listing_id
- status
- title
- description
- suggested_price
- approved_price
- shipping_price
- actual_sale_price
- fees
- profit
```

### Storage

```text
storage_locations
- id
- card_internal_id
- shelf
- box
- slot
- label
- status
```

## 11. eBay Picture Search

eBay Picture Search is the primary candidate-finding step.

The computer program should:

1. Select the clearest front image.
2. Straighten, crop, and lightly improve the image without hiding defects.
3. Use the supported eBay Picture Search workflow.
4. Display likely matching listings with images, titles, prices, shipping, and URLs where available.
5. Compare repeated card details across the results.
6. Present multiple candidate identities when results disagree.
7. Require the user to confirm the exact card and variant.

The first matching result must never be accepted automatically. For Pokemon cards from the early era, identification must distinguish at least:

- Base Set 1st Edition.
- Base Set Shadowless.
- Base Set Unlimited.
- Holo and non-holo.
- English and Japanese.
- Promo cards.
- Card number and set.
- Raw and graded cards.
- Possible counterfeit or altered cards.

If eBay does not provide an official programmatic Picture Search API, the computer program should prepare the image and open a supported assisted workflow. Browser automation is a fallback and must not bypass login challenges, CAPTCHAs, access controls, or rate limits.

The user must confirm the identity before exact market research begins.

## 12. Market Research

After card identity is confirmed, collect separate groups of comparable listings:

- Recently sold raw cards.
- Current raw listings.
- Graded cards grouped by grading company and grade.
- Different conditions.
- Different printings and variants.

Each comparable should store:

```text
listing URL
title
sale or listing date
sale or asking price
shipping price
total buyer cost
condition
grade
auction or fixed-price format
seller notes
screenshot path when available
```

Screenshots are supporting evidence. Structured data and URLs are the primary records.

Never mix these groups when calculating a recommendation:

```text
raw cards
PSA/BGS/CGC graded cards
different variants
different languages
different conditions
card lots
```

## 13. Pricing Recommendation

The program should display:

```text
number of comparable sales
lowest comparable
median comparable
highest comparable
current active competition
suggested listing range
estimated eBay fees
estimated profit
```

The initial recommendation should normally start with the median of correctly filtered comparable sales and adjust for:

- Card condition.
- Exact variant.
- Sale recency.
- Current competition.
- Shipping treatment.
- Auction versus fixed-price format.
- eBay fees.
- Desired profit margin.

The highest sold price is an upper-bound reference, not automatically the listing price. The user must be able to edit or override the recommendation.

## 14. Listing Drafts

Generate a draft containing:

- Title.
- Category.
- Item specifics.
- Condition.
- Description.
- Suggested price.
- Shipping settings.
- Return settings.
- Selected card images.
- Optional video.
- Archive code.
- Internal notes.

Example title structure:

```text
Pokemon Base Set Charizard 4/102 Holo English [Variant] [Condition]
```

Generate the title from confirmed card fields. Do not rely on a guessed image-search title.

The description must be factual and supported by the photos. It should mention visible whitening, scratches, dents, bends, creases, or other defects recorded during review.

The first release must not publish automatically. It should require explicit user review and approval.

## 15. Review Dashboard

The local dashboard should display:

- Archive code.
- Card photos and video.
- Suggested card identity and confidence.
- eBay Picture Search results.
- Sold comparables.
- Active comparables.
- Suggested price range.
- Estimated fees and profit.
- Generated title.
- Generated description.
- Shipping information.
- Draft status.
- Approve, edit, reject, and retry actions.

The review screen should make variant and condition differences obvious so raw cards are not accidentally compared with graded cards.

## 16. Inventory and Shelf Archiving

Every physical card keeps the same archive code through every status:

```text
K4M7
```

Initial statuses:

```text
received
needs-review
identified
ready-to-list
draft-created
listed
sold
shipped
archived
returned
retired
```

Later features:

- Printable QR or Code 128 sleeve labels.
- Archive-code scanning.
- Shelf, box, and slot locations.
- Duplicate-card searches.
- Moving a card between storage locations.
- Listing-to-card lookup.
- Sold-card history.
- Printable inventory reports.

## 17. Windows GitHub Actions Build

Add:

```text
.github/workflows/build-windows.yml
```

The workflow should run on a GitHub-hosted Windows runner and:

1. Check out the repository.
2. Set up Python.
3. Install dependencies.
4. Run tests.
5. Build the executable with PyInstaller.
6. Upload the `.exe` as a workflow artifact.
7. Optionally create a release only after manual approval.

The build artifact must not contain eBay credentials, API tokens, local databases, private pairing tokens, or user media.

## 18. Development Milestones

### Milestone 1: Receiver

- Start the local server.
- Pair the iPhone.
- Receive front and back photos.
- Receive one video.
- Verify files.
- Assign an archive code.
- Create the correctly named card folder.

### Milestone 2: Archive and Review

- Add SQLite records.
- Display intake history.
- Display media.
- Generate manifests.
- Add retry and recovery behavior.
- Print or export archive labels.

### Milestone 3: eBay Research

- Use eBay Picture Search as the first candidate step.
- Confirm card identity and variant.
- Record sold and active comparables.
- Separate raw, graded, condition, and variant groups.
- Generate pricing reports.

### Milestone 4: Listing Drafts

- Generate title and description.
- Select media.
- Calculate estimated fees and profit.
- Create an eBay draft where supported.
- Require human approval.

### Milestone 5: Storage

- Add shelf, box, and slot fields.
- Scan archive labels.
- Search by archive code.
- Track listed, sold, shipped, returned, and archived cards.

## 19. First Acceptance Test

The first working release must pass this test:

1. Start the Windows program.
2. Pair an iPhone using the QR code.
3. Capture a front photo, back photo, and short video.
4. Upload the intake over local Wi-Fi.
5. Interrupt and restore the connection during upload.
6. Confirm that retries do not create duplicate files or cards.
7. Finalize the intake.
8. Confirm that the computer generates a unique code such as `K4M7`.
9. Confirm that the permanent folder is named `K4M7`.
10. Confirm that the database, manifest, iPhone, and dashboard show the same archive code.
11. Confirm that eBay Picture Search results can be reviewed before market research.
12. Confirm that a listing draft is generated without publishing automatically.
