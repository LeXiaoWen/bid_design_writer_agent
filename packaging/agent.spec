# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, get_module_file_attribute


project_root = Path(SPECPATH).parent
entry_script = Path(SPECPATH) / "agent_entry.py"


hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "rapidocr",
    "onnxruntime",
    "fitz",
    "pymupdf",
    "openpyxl",
]

onnxruntime_capi_dir = Path(get_module_file_attribute("onnxruntime")).parent / "capi"
ocr_binaries = collect_dynamic_libs("pymupdf") + [
    (str(path), "onnxruntime/capi")
    for path in onnxruntime_capi_dir.glob("onnxruntime_pybind11_state.*")
]
ocr_datas = collect_data_files("rapidocr", includes=["*.yaml", "models/*"])

if sys.platform == "win32":
    hiddenimports.extend([
        "asyncio.windows_events",
        "selectors",
    ])

a = Analysis(
    [str(entry_script)],
    pathex=[str(project_root)],
    binaries=ocr_binaries,
    datas=[
        (
            str(project_root / "package.json"),
            "build",
        ),
        (
            str(project_root / "backend" / "bundled_skills"),
            "backend/bundled_skills",
        ),
    ] + ocr_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "backend.tests",
        "pytest",
        "IPython",
        "jedi",
        "matplotlib",
        "sphinx",
        "notebook",
        "nbformat",
        "black",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="ai-workbench-agent",
    exclude_binaries=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Electron 通过 stdout 读取随机端口；Windows 端由 spawn 的 windowsHide 隐藏控制台窗口。
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ai-workbench-agent",
)
