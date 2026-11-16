#!/usr/bin/env python
"""Crea dist\\EWA\\ (PyInstaller) e dist\\EWA-Setup.exe (Inno Setup). Da eseguire su Windows 10.

Passi: pip install -r packaging/requirements-build.txt -> extract_icons -> pyinstaller -> ISCC.
Opzioni: --skip-icons, --skip-installer, --allow-non-windows (solo per verificare lo spec).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"
INSTALL_HINT = "winget install -e --id JRSoftware.InnoSetup"


def find_iscc(env: dict | None = None, which=shutil.which, exists=os.path.isfile) -> str | None:
    """Percorso di ISCC.exe (PATH, poi le cartelle standard di Inno Setup 6) o None."""
    env = os.environ if env is None else env
    found = which("ISCC") or which("ISCC.exe")
    if found:
        return found
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = env.get(var)
        if not base:
            continue
        sub = ("Programs", "Inno Setup 6") if var == "LOCALAPPDATA" else ("Inno Setup 6",)
        cand = os.path.join(base, *sub, "ISCC.exe")
        if exists(cand):
            return cand
    return None


def iscc_command(iscc: str, version: str | None = None) -> list[str]:
    cmd = [iscc]
    if version:
        cmd.append(f"/DMyAppVersion={version}")
    cmd.append(str(PKG / "installer.iss"))
    return cmd


def pyinstaller_command() -> list[str]:
    return [sys.executable, "-m", "PyInstaller", str(PKG / "ewa.spec"), "--noconfirm", "--clean"]


def run(cmd: list[str]) -> None:
    print("\n>", " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-icons", action="store_true", help="non estrarre le icone")
    ap.add_argument("--skip-installer", action="store_true", help="non creare EWA-Setup.exe")
    ap.add_argument("--allow-non-windows", action="store_true",
                    help="solo per verificare lo spec: salta icone e installer")
    ap.add_argument("--version", help="versione dell'app (default: 1.0.0)")
    args = ap.parse_args(argv)

    if sys.platform != "win32":
        if not args.allow_non_windows:
            print("Questa build funziona solo su Windows 10: le icone vengono estratte dal sistema "
                  "e l'installer usa Inno Setup.\n(--allow-non-windows serve solo a verificare lo spec.)")
            return 1
        args.skip_icons = args.skip_installer = True
        print("[!!] Non-Windows: salto icone e installer (build solo per verifica).")
    if args.version:
        os.environ["EWA_VERSION"] = args.version

    run([sys.executable, "-m", "pip", "install", "-r", str(PKG / "requirements-build.txt")])
    run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    if not args.skip_icons:
        run([sys.executable, str(PKG / "extract_icons.py")])
    run(pyinstaller_command())
    print(f"\nCartella pronta: {ROOT / 'dist' / 'EWA'}")

    if args.skip_installer:
        return 0
    iscc = find_iscc()
    if not iscc:
        print("\n[!!] Inno Setup 6 non trovato: l'installer non e' stato creato.\n"
              f"     Installalo con:  {INSTALL_HINT}\n"
              "     poi rilancia build.bat. Intanto dist\\EWA\\ e' gia' utilizzabile.")
        return 1
    run(iscc_command(iscc, args.version))
    print(f"\nInstaller pronto: {ROOT / 'dist' / 'EWA-Setup.exe'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
