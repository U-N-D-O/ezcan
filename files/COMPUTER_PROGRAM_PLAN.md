# Ezcan Card Workbench

## Product contract

Ezcan moves a card from iPhone capture to a Windows archive, visible eBay research, pricing evidence, and an unpublished local listing draft.

- Japanese is the default language; English requires an explicit iPhone toggle.
- Condition and grade are selected manually on the iPhone.
- Every received card is stored as authenticated.
- Archive folders use sequential four-character codes such as `A0A0`.
- eBay research uses a separate search-only account in a visible browser session.
- Sold and active evidence remain separate, and competitor shipping is included in buyer totals.
- Owner shipping is `$34 USD` for the first card and `$0` for additional cards.
- Listing drafts remain local and unpublished. Seller OAuth and live publishing are out of scope.

## Desktop experience

The Windows EXE is organized around one repeated workflow:

1. Pair the iPhone by scanning the QR code.
2. Choose a card in `Recent Activity`.
3. Review its image, identity metadata, language, condition, grade, and current state.
4. Use the next available action: search eBay, add a match, review identity, or make a draft.
5. Open the archive or send a file to iPhone from the compact utility bar.

The primary list deliberately excludes raw folder paths and precise received timestamps. It shows archive code, card identity, language/condition details, and the next useful action. Selecting a row updates the card workspace; double-click and Enter open the same selected-card context.

## eBay account and research

The EXE provides a `SIGN IN / OPEN EBAY` control for a separate search-only account. It launches a headed Edge, Chrome, or Brave profile at `%LOCALAPPDATA%\\Ezcan\\browser-profile`. The user signs in manually, then confirms the session in Ezcan.

Ezcan stores only browser-profile metadata and connection state. It never collects or stores an eBay username, password, seller credential, or raw cookie in SQLite or source control. The account panel supports sign-in, confirmation, and profile removal, and reports `not connected`, `login required`, or `connected`.

Picture Search remains visible and user-assisted: Ezcan prepares the front image, opens eBay, and tells the user to use the camera control and file chooser. Login, CAPTCHA, two-factor challenges, result selection, and identity confirmation remain explicit user steps. The manual candidate-entry fallback records title, URL, sold/active state, date, item price, shipping, condition, grade, format, notes, and optional screenshot.

## State and data safety

Store methods own transitions through receiving, search, candidate capture, identity confirmation, pricing, and draft creation. Existing archives and iPhone metadata are preserved when the schema grows. Migrations must be versioned and backed up before changing the database. Interrupted finalization must be recoverable and visible in `Recent Activity`.

Identity confirmation is explicit and records card name, set, number, edition, printing, finish, raw/graded state, and grade. A candidate is never accepted merely because it appeared first in a search.

## Pricing and drafts

Pricing keeps sold evidence separate from active competition and includes competitor item price plus competitor shipping. Recommendations show card price, buyer-paid total, estimated fees, and the `$34` first-item shipping rule independently.

A local draft contains factual title, description, item specifics, images, research evidence, shipping, fees, and profit assumptions. Draft review must remain local and support review, edit, approve locally, reject, and regenerate actions. Every draft is marked unpublished.

## Implementation and verification

Relevant modules:

- `computer/ezcan_computer.py`: FastAPI receiver, SQLite store, Tkinter workbench, and card actions.
- `computer/ebay.py`: visible Picture Search handoff and future headed automation boundary.
- `computer/ebay_account.py`: persistent search-account browser profile lifecycle.
- `computer/image_processor.py`: front-image preparation.
- `computer/pricing.py`: sold/active evidence and shipping-aware recommendations.
- `computer/listing_drafts.py`: unpublished local draft payload.
- `computer/test_ezcan_computer.py`: archive, API, identity, pricing, candidate, and draft tests.

Verification should include the computer test suite, Python compilation, workflow YAML parsing, `git diff --check`, and a Windows PyInstaller build. iOS native builds remain macOS/Xcode-limited and should be run in the macOS workflow or on a physical device when available.
