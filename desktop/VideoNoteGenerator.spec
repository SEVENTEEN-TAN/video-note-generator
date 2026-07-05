# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path.cwd()

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "backend" / "app" / "local_whisper_worker.py"), "backend/app"),
    (str(ROOT / "backend" / "requirements.txt"), "backend"),
    (str(ROOT / "backend" / "requirements-local.txt"), "backend"),
    (str(ROOT / "backend" / "requirements-cuda.txt"), "backend"),
]
datas += collect_data_files("imageio_ffmpeg")

binaries = []

hiddenimports = [
    "uvicorn.lifespan.on",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
]
for package in ("backend",):
    try:
        hiddenimports += [
            module
            for module in collect_submodules(package)
            if module != "backend.app.local_whisper_worker"
        ]
    except Exception:
        pass

a = Analysis(
    [str(ROOT / "desktop" / "desktop_launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "av",
        "ctranslate2",
        "faster_whisper",
        "fsspec",
        "huggingface_hub",
        "matplotlib",
        "numpy",
        "onnxruntime",
        "pytest",
        "tensorboard",
        "tensorflow",
        "torch",
        "torchvision",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoNoteGenerator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VideoNoteGenerator",
)
