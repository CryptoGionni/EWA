# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller (>=6): sei eseguibili in UNA sola cartella dist/EWA (PySide6 condiviso).

Uso:  pyinstaller packaging/ewa.spec --noconfirm --clean
"""
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
ENTRIES = ROOT / "packaging" / "entries"
ICONS = ROOT / "ewa" / "assets" / "icons"
VERSION = os.environ.get("EWA_VERSION", "1.0.0")

# (nome exe, script, console, chiave icona)
APPS = [
    ("EWA", "terminale.py", True, "shell"),
    ("MarvHub", "marvhub.py", False, "hub"),
    ("Calcolatrice", "calcolatrice.py", False, "calculator"),
    ("Sveglie e orologio", "sveglie.py", False, "clock"),
    ("Fotocamera", "fotocamera.py", False, "camera"),
    ("Blocco note", "blocconote.py", False, "notepad"),
]

HIDDEN = [
    "ollama", "openai", "httpx", "dotenv", "windows_toasts",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNetwork",
    "PySide6.QtSvg", "PySide6.QtPrintSupport",
    "ewa.shell", "ewa.hubd", "ewa.core.launcher",
    "ewa.tools.calculator.__main__", "ewa.tools.clock.__main__",
    "ewa.tools.camera.__main__", "ewa.tools.notepad.__main__",
]

EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtWebView",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtSerialBus", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
    "PySide6.QtHttpServer", "PySide6.QtStateMachine", "PySide6.QtVirtualKeyboard",
    "tkinter", "pytest", "matplotlib", "pandas", "numpy", "IPython", "scipy",
]


def version_info(name: str):
    # il modulo si importa solo su Windows (su altri sistemi manca win32api)
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo)
    nums = tuple((int(x) if x.isdigit() else 0) for x in (VERSION.split(".") + ["0"] * 4)[:4])
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0, OS=0x40004,
                          fileType=1, subtype=0),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "EWA"),
                StringStruct("FileDescription", name),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", name),
                StringStruct("OriginalFilename", name + ".exe"),
                StringStruct("ProductName", "EWA"),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ])


datas = [(str(ROOT / ".env.example"), ".")]
if any(ICONS.glob("*.ico")):
    datas.append((str(ICONS / "*.ico"), "ewa/assets/icons"))

analyses, exes = [], []
for name, script, console, key in APPS:
    a = Analysis(
        [str(ENTRIES / script)],
        pathex=[str(ROOT)],
        datas=datas,
        hiddenimports=HIDDEN,
        excludes=EXCLUDES,
        noarchive=False,
    )
    pyz = PYZ(a.pure)
    ico = ICONS / f"{key}.ico"
    exes.append(EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,           # i binari vanno nel COLLECT condiviso
        name=name,
        console=console,
        icon=str(ico) if ico.is_file() else None,
        version=version_info(name) if sys.platform == "win32" else None,
        upx=False,
    ))
    analyses.append(a)

collect_args = []
for a, e in zip(analyses, exes):
    collect_args += [e, a.binaries, a.datas]

coll = COLLECT(*collect_args, strip=False, upx=False, name="EWA")
