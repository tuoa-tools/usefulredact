Checks whether the redaction in a document actually holds, entirely on your machine.
It is a checker, not a guarantee: read the [README](https://github.com/tuoa-tools/usefulredact#readme) first, above all its limitations.

## Install

Python 3.13 on Windows, macOS or Linux. The wheel below has the app's UI inside it, so
there is nothing to build and no Node to install:

```
python -m venv .venv
.venv/bin/pip install <the address of the .whl file below>        # Windows: .venv\Scripts\pip
.venv/bin/usefulredact-app                                        # the app, in a browser tab
.venv/bin/usefulredact check letters/ --out report/               # or the command line
```

One download in that install comes from GitHub rather than PyPI (the spaCy name model).
If it fails with a gateway error, run the same command again.

Nothing is uploaded, and nothing is kept when the app stops.
