# PyInstaller spec: onedir, windowed build of the app (server + built UI + the OCR engine with
# its three models + the spaCy name model). Build from the repo root, after `npm run build`
# in frontend/ and `python scripts/prepare_bundle.py`:
#
#     pyinstaller --noconfirm --clean packaging/UsefulRedact.spec
#
# macOS: dist/UsefulRedact.app; Linux: dist/UsefulRedact/. Windows uses scripts/build_windows.py.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))
from usefulredact import __version__  # noqa: E402

ICON = {
    "darwin": ROOT / "packaging" / "icon.icns",
    "win32": ROOT / "packaging" / "icon.ico",
}.get(sys.platform)

datas = [
    (str(ROOT / "app" / "static"), "app/static"),  # `npm run build` output
    (str(ROOT / "packaging" / "models"), "models"),  # scripts/prepare_bundle.py output
]
# rapidocr's config and model index, but not its 260 MB of models (we ship three).
datas += [
    (src, dest)
    for src, dest in collect_data_files("rapidocr")
    if not Path(src).suffix == ".onnx"
]
# The name model is a package whose weights are data files beside its __init__.
datas += collect_data_files("en_core_web_sm")
datas += collect_data_files("spacy")
datas += collect_data_files("thinc")
# spaCy finds its components, architectures and languages through entry points, which are
# read from each distribution's metadata. A frozen app has none unless it is copied in.
for dist in ("spacy", "thinc", "spacy-legacy", "spacy-loggers", "en_core_web_sm", "srsly",
             "catalogue", "confection", "weasel"):
    try:
        datas += copy_metadata(dist)
    except Exception:  # noqa: BLE001 - not every one is present in every spaCy version
        pass

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "en_core_web_sm",
    "spacy_legacy",
    "spacy_loggers",
]
hiddenimports += collect_submodules("rapidocr")
hiddenimports += collect_submodules("spacy")
hiddenimports += collect_submodules("thinc")
hiddenimports += collect_submodules("spacy_legacy")
hiddenimports += collect_submodules("srsly")

a = Analysis(
    [str(ROOT / "app" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "tkinter",
        "pytest",
        "IPython",
        "torch",
        "torchvision",
        "paddle",
        "openvino",
        "matplotlib",  # the evaluation chart: a development tool, not part of the app
        "faker",
        "scipy",
        "pandas",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="UsefulRedact",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # windowed: no terminal. Nothing is logged to a file, by design.
    icon=str(ICON) if ICON and ICON.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="UsefulRedact")
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="UsefulRedact.app",
        icon=str(ICON) if ICON and ICON.exists() else None,
        bundle_identifier="au.com.tuoa.usefulredact",
        info_plist={
            "CFBundleName": "UsefulRedact",
            "CFBundleDisplayName": "UsefulRedact",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "MIT licence · tuoa-tools/usefulredact",
        },
    )
