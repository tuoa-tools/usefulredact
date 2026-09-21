Checks whether the redaction in a document actually holds, entirely on your machine.
It is a checker, not a guarantee: read the [README](https://github.com/tuoa-tools/usefulredact#readme) first, above all its limitations.

## Install

Everything is inside each download (the OCR engine and its models, the name model, the UI).
Nothing is downloaded when you install it or when you run it.

- **macOS**: `UsefulRedact-macos-arm64.zip` (Apple Silicon) or `UsefulRedact-macos-x64.zip` (Intel). Unzip, drag to Applications. The app is not notarised by Apple, so clear the quarantine flag macOS put on the download, once, in Terminal: `xattr -d com.apple.quarantine /Applications/UsefulRedact.app`. Then open it as usual. (System Settings → Privacy & Security → Open Anyway is Apple's own route and has proved unreliable on recent macOS.)
- **Windows**: `UsefulRedact-windows-x64-setup.exe`, per-user, no administrator needed. SmartScreen may want "More info → Run anyway" once.
- **Linux**: `UsefulRedact-linux-x64.tar.gz`; unpack and run `UsefulRedact/UsefulRedact`.
- **With Python 3.13**: `pip install` the `.whl` below, then run `usefulredact-app`, or `usefulredact check <files>` for the command line.

It opens in your browser. To stop it, use Quit on the page, or close the tab and it stops by
itself two minutes later. Nothing is uploaded, and nothing is kept when it stops.

Every file here was built by the release workflow and, before it was published, started and
driven end to end on the system it is for: both models loaded, a black box over live text
came back as recoverable, personal information in a picture was found by OCR, and the
temporary folder was gone after Quit.
