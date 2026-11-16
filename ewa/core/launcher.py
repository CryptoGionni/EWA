"""Come avviare i componenti di EWA, sia da sorgente sia dagli exe installati.

Da sorgente:  [python, "-m", "ewa.tools.calculator"], [python, "-m", "ewa.hubd"], ...
Da exe (PyInstaller, sys.frozen): gli eseguibili stanno tutti nella stessa
cartella (EXE_NAMES), quindi si avvia il fratello giusto.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# chiave -> (nome exe senza estensione, modulo Python da avviare con -m)
COMPONENTS: dict[str, tuple[str, str]] = {
    "shell": ("EWA", "ewa.shell"),
    "hub": ("MarvHub", "ewa.hubd"),
    "calculator": ("Calcolatrice", "ewa.tools.calculator"),
    "clock": ("Sveglie e orologio", "ewa.tools.clock"),
    "camera": ("Fotocamera", "ewa.tools.camera"),
    "notepad": ("Blocco note", "ewa.tools.notepad"),
}
EXE_NAMES = {k: v[0] for k, v in COMPONENTS.items()}

LOG_DIR = Path(tempfile.gettempdir())
TOOLS_LOG = LOG_DIR / "ewa-tools.log"
HUB_LOG = LOG_DIR / "ewa-hub.log"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def exe_path(key: str) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return Path(sys.executable).resolve().parent / f"{EXE_NAMES[key]}{suffix}"


def command(key: str, args: list[str] | None = None) -> list[str]:
    """Riga di comando per avviare il componente `key`."""
    args = list(args or [])
    if is_frozen():
        return [str(exe_path(key)), *args]
    return [sys.executable, "-m", COMPONENTS[key][1], *args]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _cwd() -> str:
    return str(exe_path("hub").parent) if is_frozen() else str(project_root())


def spawn(key: str, args: list[str] | None = None, log: Path = TOOLS_LOG,
          detached: bool = False) -> subprocess.Popen:
    """Avvia un componente; stdout/stderr vanno nel file di log (niente console extra)."""
    kwargs: dict = {}
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW
        if detached:
            flags |= subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = flags
    elif detached:
        kwargs["start_new_session"] = True
    out = open(log, "ab")
    return subprocess.Popen(command(key, args), cwd=_cwd(), stdout=out, stderr=out,
                            stdin=subprocess.DEVNULL, **kwargs)


def spawn_hub() -> subprocess.Popen | None:
    """Avvia MarvHub in background, staccato dal processo chiamante.

    Se un altro hub è già attivo, quello nuovo trova la porta occupata ed esce da
    solo: la porta TCP fa da lock, quindi è sicuro chiamarla più volte.
    """
    if os.getenv("EWA_HUB_AUTOSTART", "1").strip() in ("0", "false", "no"):
        return None
    try:
        return spawn("hub", log=HUB_LOG, detached=True)
    except OSError:
        return None
