# Ezcan iOS App Plan

## 1. Purpose

Ezcan is a small iOS companion app for photographing Pokemon cards and sending each card's media to the Ezcan computer program over the same local Wi-Fi network.

The iOS app is intentionally limited to:

- Connecting to the computer program.
- Creating one media intake per physical card.
- Capturing or selecting photos.
- Recording an optional video.
- Reviewing media.
- Uploading media reliably.
- Displaying the archive code assigned by the computer.

The app does not perform eBay searches, pricing, listing creation, publishing, or permanent inventory management. Those responsibilities belong to the computer program.

## 2. GitHub Repository

Create a GitHub repository named:

```text
ezcan
```

The repository will contain the iOS project and its GitHub Actions workflow. A separate repository may later be created for the Windows computer program, but the iOS app repository is the required first repository.

Recommended top-level structure:

```text
 ezcan/
   Ezcan/
     App/
     Models/
     Networking/
     Screens/
     Services/
     Resources/
   Ezcan.xcodeproj
   .github/
     workflows/
       build-ios.yml
   APP_PLAN.md
   README.md
```

## 3. Technology

- Swift
- SwiftUI
- PhotosUI for selecting existing photos and videos
- AVFoundation for camera and video capture
- URLSession for local-network uploads
- Vision and AVFoundation QR scanning
- CryptoKit for file hashing
- iOS 17 or newer unless an earlier version is required

The app should use Apple's standard frameworks wherever possible and avoid introducing a server or cloud account for media transfer.

## 4. User Workflow

1. Start the computer program and display its pairing QR code.
2. Scan the QR code in Ezcan.
3. Create a new card intake.
4. Capture the front of the card.
5. Capture the back of the card.
6. Capture optional detail photos for corners, edges, holo surface, or defects.
7. Record an optional short video showing the card surface.
8. Review the media and correct its order.
9. Upload the complete intake over local Wi-Fi.
10. Wait for the computer to verify and finalize the files.
11. Display the computer-generated archive code, such as `K4M7`.

The archive code identifies one physical card, not only a card type. Two copies of the same Pokemon card must have different archive codes.

## 5. Screens

### Pairing Screen

Features:

- Scan the computer's QR code.
- Show the computer name and local URL.
- Show paired or disconnected status.
- Allow manual local URL and token entry as a fallback.
- Remove the current pairing.
- Reconnect to the last paired computer.

The QR payload should be versioned and contain data similar to:

```json
{
  "protocol": "ezcan",
  "version": 1,
  "url": "http://192.168.1.25:8765",
  "token": "temporary-pairing-token"
}
```

### New Card Screen

Features:

- Start one intake for one physical card.
- Capture a front photo.
- Capture a back photo.
- Add optional detail photos.
- Record an optional video.
- Continue to media review.

The app should encourage this basic media set:

```text
front image
back image
detail images
optional surface video
```

The number of detail images must remain flexible for cards with unusual defects or valuable surfaces.

### Media Review Screen

Features:

- Show thumbnails for every photo and video.
- Mark one image as the front image.
- Mark one image as the back image.
- Reorder media.
- Delete or retake media.
- Play the video.
- Add an optional note.
- Confirm that all media belongs to one physical card.
- Start the upload.

The app must keep original files until the computer confirms successful receipt.

### Upload Queue Screen

Features:

- Show pending, uploading, completed, and failed files.
- Show per-file and overall progress.
- Retry failed files.
- Resume after a temporary Wi-Fi interruption.
- Prevent duplicate intakes when a completion response is interrupted.
- Display the assigned archive code after finalization.

## 6. Local Network Protocol

The computer program provides a local HTTP API. The first version can use HTTP on the private home network, with pairing-token authentication. HTTPS can be added later if required by the deployment environment.

Expected endpoints:

```text
POST /api/pair
POST /api/intakes
POST /api/intakes/{intakeId}/media
GET  /api/intakes/{intakeId}/status
POST /api/intakes/{intakeId}/complete
```

The app must:

- Use the paired computer URL and token.
- Use request timeouts.
- Retry transient failures with backoff.
- Upload files as multipart data or streamed file uploads.
- Send a SHA-256 hash for every file.
- Use idempotency keys so retries do not create duplicate media.
- Query intake status before retrying finalization.
- Support background URLSession uploads for large videos where practical.

The app must never send media to an external service and must never expose the computer receiver to the public internet.

## 7. Archive Code Display

The computer program generates the permanent archive code. The app never generates or increments archive codes.

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

- The code is randomly generated, not sequential.
- The two letters are different.
- Confusing characters are excluded, such as `I`, `O`, `S`, `Z`, `0`, `1`, and `5`.
- The computer checks the code against its database before assigning it.
- Retired codes are never reused.
- The code is displayed in large, clear text after upload finalization.
- The app may display a QR or barcode representation received from the computer.

The computer should also maintain an internal UUID. The visible archive code is for labels, folders, and people; the UUID is for technical references.

## 8. Media Handling

The app should preserve original iPhone media during transfer.

Expected source formats include:

```text
HEIC or JPEG images
MOV or compatible video
```

The computer program is responsible for creating eBay-compatible derivatives such as JPEG images or converted video. The app should not lower quality unless the user explicitly chooses a reduced-size transfer.

Large videos must be uploaded as files or chunks. They must not be converted to Base64 strings.

## 9. Permissions and Privacy

Request only the permissions required for the current feature:

- Camera access.
- Photo library access.
- Microphone access when recording video with audio.
- Local network access.

The app should explain each permission in the normal iOS permission flow. It must not contain eBay credentials, Apple signing credentials, or computer-program secrets.

## 10. Error Handling

The app must give a clear recovery action for:

- Computer unavailable.
- Phone and computer on different Wi-Fi networks.
- Guest Wi-Fi device isolation.
- Expired pairing token.
- Interrupted upload.
- Duplicate upload retry.
- Low phone storage.
- Camera or photo-library permission denial.
- Computer rejecting a file.
- Computer assigning an archive code while the response is interrupted.

When finalization may have succeeded, the app must query the intake status instead of creating a second intake.

## 11. GitHub Actions IPA Build

Add:

```text
.github/workflows/build-ios.yml
```

The workflow should run on a GitHub-hosted macOS runner, for example `macos-latest`, and should:

1. Check out the repository.
2. Select the required Xcode version.
3. Resolve Swift package dependencies if any are added.
4. Build the project.
5. Run unit tests.
6. Import signing credentials into a temporary keychain.
7. Archive the app.
8. Export an IPA.
9. Upload the IPA as a workflow artifact.
10. Optionally submit to TestFlight only through a separate manually approved job.

The build requires an Apple Developer account and signing configuration. Depending on the chosen distribution method, store these as GitHub Actions secrets or environment secrets:

- Apple Developer Team ID.
- Bundle identifier, such as `com.example.ezcan`.
- Distribution certificate or App Store Connect API key.
- Provisioning profile, unless automatic signing is configured.
- Temporary keychain password.

Never commit certificates, private keys, provisioning profiles, API keys, or passwords to GitHub.

The first CI milestone is an IPA artifact from a successful macOS workflow. TestFlight distribution is a later milestone.

## 12. Testing Milestone

The first release must verify:

- QR pairing with the computer.
- Manual connection fallback.
- Front and back photo capture.
- Multiple detail photos.
- Optional video capture.
- Correct grouping of all media into one intake.
- Upload retry after Wi-Fi interruption.
- No duplicate files or intakes after retry.
- Successful archive-code display.
- Successful IPA creation by GitHub Actions.

The iOS MVP is ready for integration when a real iPhone can send one card's photos and video to the computer and display the same archive code shown by the computer.
