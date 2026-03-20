myPyHaptics Portable Release

Contents:
- publish.exe
- subscribe.exe
- .env.example

Quick test:
1) Copy .env.example to .env and set BHAPTICS_APP_ID / BHAPTICS_API_KEY.
2) Run subscribe.exe (or subscribe.exe --headless).
3) Run publish.exe --ui.

ACK topics:
- subscriber --subscriber-id N publishes ACK on bhaptics/ackN
- publisher default listens to bhaptics/ack+ (all)
