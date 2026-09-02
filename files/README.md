# Ezcan

Ezcan is a Pokemon card workflow with two parts:

- An iOS capture app that sends one card's photos and optional video over the same private Wi-Fi network.
- A Windows computer program that receives, archives, and later researches cards for eBay listing drafts.

The iOS app is in `files/Ezcan/`. The Windows companion program is in `files/computer/`.

The iOS app uses `ezcan_logo.png` as its bundled welcome-screen logo.

The capture camera has an `AUTO` lens mode that watches focus distance and center-frame sharpness. When a card is too close for the standard lens, it moves to the iPhone's ultra-wide macro camera and returns to the standard camera after the subject is comfortably framed again. `1X` and `MACRO` are also available for manual control. Still photos use the best available virtual camera, quality-priority capture, optical stabilization, and a high-quality JPEG. The saved image is cropped to the four-corner card guide rather than keeping the surrounding camera view. Devices without an ultra-wide camera keep the standard camera active.

## Current MVP

- Pair with the computer using a QR code or manual URL and token.
- Capture photos and up to 30 seconds of video.
- Import existing photos and videos.
- Keep each physical card in a separate intake.
- Upload the intake to the computer.
- Display the sequential archive code returned by the computer.

The computer program owns card identification, eBay Picture Search, pricing, listing drafts, and permanent inventory records. Before archiving, the iPhone records the manual listing details: Japanese is the default language, English must be selected explicitly, and raw condition or grading company/grade is chosen by the owner. Authenticity is assumed after the owner's inspection.

## Build Locally

This repository uses [XcodeGen](https://github.com/yonaskolb/XcodeGen) so the project can be generated consistently on a macOS runner:

```bash
brew install xcodegen
cd files
xcodegen generate
open Ezcan.xcodeproj
```

The project targets iOS 17 or newer and uses the bundle identifier `com.undu.ezcan` by default. The iOS app icon is registered as `AppIcon` from `files/icons/ios`. Change the bundle identifier and signing team in `files/project.yml` before distributing the app.

## GitHub Actions

The workflow at `.github/workflows/build-ios.yml` builds an arm64 iOS IPA on every push to `main`, every pull request, and manual workflow dispatch. The app is packaged without an ad-hoc signature so AltServer can sign it with your Apple ID before installation. Pushes to `main` publish a direct [Ezcan-unsigned.ipa download](https://github.com/U-N-D-O/ezcan/releases/download/ezcan-latest/Ezcan-unsigned.ipa) as well as the `ezcan-ios-ipa` artifact. Use the direct `.ipa` download with AltStore or AltServer; GitHub artifact downloads are outer ZIP files, so they must be extracted before importing the inner `Ezcan-unsigned.ipa`.

### One-command IPA build

The easiest Windows option is the double-clickable Python GUI [build_ios_ipa.pyw](../build_ios_ipa.pyw). It needs only Python, Git, and the GitHub CLI. Double-click the file, press **ACTIVATE BUILD**, and it will show a progress dial and activity log while it commits/pushes changes, runs the macOS build, downloads the `ezcan-ios-ipa` artifact, and displays a completion alert. Authenticate the GitHub CLI once with `gh auth login`.

The downloaded `Ezcan-unsigned.ipa` is placed under `artifacts\ios`. When the worktree is clean, the GUI starts a manual build of the current `main` automatically.

For command-line use, the PowerShell version remains available:

On Windows, [build-ios-ipa.ps1](build-ios-ipa.ps1) stages and commits the current changes, pushes `main`, waits for the matching macOS GitHub Actions build, downloads the `ezcan-ios-ipa` artifact, displays a progress bar, and shows a completion alert. Authenticate the GitHub CLI once with `gh auth login`, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\files\build-ios-ipa.ps1 -CommitMessage "Build latest Ezcan IPA"
```

If there are no local changes, add `-RunEvenIfClean`. The script refuses to stage paths that look like secrets or signing files. The IPA remains unsigned and must be installed through AltStore or AltServer.

The unsigned IPA is not directly installable by iOS until AltStore or AltServer signs it. A future distribution workflow can add Apple Developer signing, but no signing secrets are needed for the current AltServer workflow. Never commit certificates, profiles, private keys, or passwords.

## Repository delivery

Repository-level instructions for future coding chats are in `.github/copilot-instructions.md`. Completed implementation work should be validated, committed, and pushed to `main` unless the user explicitly asks to keep it local.

## iPhone-to-computer connection

The desktop program quietly provides the private connection the iOS app uses to send card media. It does not open a browser. The connection handles:

```text
POST /api/intakes
POST /api/intakes/{intakeId}/media
POST /api/intakes/{intakeId}/complete
```

The pairing token is sent as a Bearer token. Media is uploaded as the raw file body with these headers:

```text
X-Ezcan-File-Name
X-Ezcan-Media-Type
X-Ezcan-SHA256
```

The finalization response must contain:

```json
{
  "archiveCode": "K4M7"
}
```

The computer assigns archive codes sequentially, starting at `A0A0` and advancing the final position first (`A0A0`, `A0A1`, ... `A0A9`, `A0B0`). A manually entered valid code becomes the latest entry for the next automatic code.

## Windows Computer Program

The computer receiver currently supports:

- Local Wi-Fi pairing with a QR code.
- Authenticated intake creation.
- Streamed photo and video uploads.
- SHA-256 verification and safe upload retries.
- Sequential archive codes such as `A0A0` and `A0A1`, with manual overrides supported.
- Permanent card folders named with the archive code.
- SQLite records and JSON manifests.
- A native desktop console with QR pairing, live intake statistics, and recent-card activity.
- A selected-card workbench with a `Recent Activity` list, card preview, metadata, and next-action controls. The list does not expose raw folder paths or precise received timestamps.
- An `Archive` folder beside the running program, with each card stored under `Archive\Cards\<archiveCode>`.
- A `Send to iPhone` file shelf for downloaded IPA files and other files you want to share to the paired phone.
- A separate headed eBay search-account browser profile under `%LOCALAPPDATA%\Ezcan\browser-profile`; Ezcan stores profile state only and never collects the eBay password.

Run it from source with Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r files\computer\requirements.txt
python files\computer\ezcan_computer.py
```

The program opens its own desktop window and quietly keeps the private phone connection running in the background. The phone and computer must be on the same private Wi-Fi network. By default, data is stored beside the running program in `Archive\` and each card gets its own folder under `Archive\Cards\`. Set `EZCAN_DATA_DIR` to override this location.

To transfer the IPA without email, download the direct `.ipa` from the latest release or extract the outer `ezcan-ios-ipa.zip` artifact, open Ezcan Computer, choose `Choose file` under `Send to iPhone`, and select `Ezcan-unsigned.ipa`. In the paired iOS app, open `Files from computer`, download the IPA, then choose AltStore in the iOS share sheet. AltStore still performs the required signing and installation.

Build the executable locally:

```powershell
python make_ezcan_exe.py --no-pause
```

Build `EzcanComputer.exe` locally on the Windows computer with the command above. The output is placed at the repository root. The Windows workflow at `.github/workflows/build-windows.yml` runs the computer tests, builds `EzcanComputer.exe`, and uploads it as the `ezcan-windows-exe` artifact. The computer supports a visible, manual eBay Picture Search handoff, sold and active match recording, identity confirmation, shipping-aware pricing, and unpublished local listing drafts. Market research uses a separate search-only eBay account, retains sold and active prices with shipping separately, and compares total buyer cost. The owner's pricing model is `$34 USD` shipping for the first card in an order and free shipping for additional cards.

Use `SIGN IN / OPEN EBAY` in the desktop pairing panel to open the separate search-only account profile. Sign in manually in the visible browser and confirm with `I'M SIGNED IN`; `REMOVE SESSION` deletes the local profile. Picture Search remains user-assisted at the camera/file chooser and never bypasses login, CAPTCHA, or two-factor challenges. Seller OAuth and live publishing are disabled.
