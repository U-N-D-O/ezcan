# Pocket Drop

A separate, small local file receiver for sending files from a phone to this Windows computer. It is intentionally independent from Ezcan's card workflow.

## How to run

1. Put the phone and computer on the same private Wi-Fi network.
2. Double-click `run_server.ps1`, or run it from PowerShell:

```powershell
Set-Location "C:\Users\malik\Desktop\eBay Pokemon Shop\SeperateProjectButSimilar"
Set-ExecutionPolicy -Scope Process Bypass
.\run_server.ps1
```

3. The window prints a `Phone` link. Open that link on the phone.
4. Choose files on the phone. They are saved under `received` in this project.
5. Open the printed `Computer` link in the computer browser to watch incoming files.

The first launch creates `.venv` and installs the three dependencies. Keep the PowerShell window open while transferring files.

## What it does

- Sends files only over the local network; no cloud account or internet upload is involved.
- Uses a random access token in the printed links so another device on the Wi-Fi cannot upload without the link.
- Accepts multiple files, including photos, videos, documents, and large files up to 2 GB by default.
- Keeps the original filename and adds `(1)`, `(2)`, and so on when a name already exists.
- Writes uploads to a temporary `.part` file first, then moves the completed file into `received`.
- Shows the SHA-256 digest in the API response for future integrations.

## Configuration

Set these environment variables before launching when needed:

- `PHONE_SHARE_DATA_DIR`: alternate folder for received files.
- `PHONE_SHARE_TOKEN`: a fixed token instead of a random one for a trusted setup.
- `PHONE_SHARE_MAX_FILE_SIZE`: maximum file size in bytes; default is 2 GB.

For example:

```powershell
$env:PHONE_SHARE_DATA_DIR = "D:\Phone Inbox"
.\run_server.ps1
```

## Network notes

Windows may ask to allow Python through the firewall. Allow it on **Private networks** only. The phone and computer must remain on the same private Wi-Fi. This project does not configure firewall rules or expose a public internet endpoint.

The server listens on port `8765`. To use another port, run:

```powershell
.\.venv\Scripts\python.exe app.py --port 8877
```

The app uses FastAPI and Uvicorn, matching the existing repository's Python web stack, but it has no dependency on the existing Ezcan application or database.
