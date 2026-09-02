# Ezcan repository instructions

- Preserve the existing SwiftUI, UIKit, AVFoundation, FastAPI, and Tkinter architecture unless the task requires a change.
- Keep camera behavior responsive on narrow and tall iPhones, and test changes against devices without an ultra-wide camera when practical.
- After completing requested implementation work, run the narrowest available validation, create a focused commit, and push it to `origin/main` unless the user explicitly says not to push.
- Do not commit certificates, signing profiles, private keys, passwords, API tokens, or other secrets.
- Mention any platform-limited validation, such as an unavailable native Xcode build on Windows, in the final response.