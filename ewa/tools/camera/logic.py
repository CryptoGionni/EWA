"""Logica della Fotocamera senza dipendenze Qt: eventi, contatori, idle, percorsi, nomi file."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

IDLE_FIRST = 60     # primo camera.idle dopo 60 s di inattività
IDLE_STEP = 120     # poi ogni ulteriori 120 s (180, 300, ...)


class IdleTracker:
    """Calcola le soglie di inattività; il tempo è iniettabile (clock)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 first: int = IDLE_FIRST, step: int = IDLE_STEP):
        self.clock = clock
        self.first = first
        self.step = step
        self.active = False
        self._last = clock()
        self._next = first

    def reset(self) -> None:
        self._last = self.clock()
        self._next = self.first

    def set_active(self, active: bool) -> None:
        self.active = active
        self.reset()

    def poll(self) -> int | None:
        """Restituisce i secondi da emettere se è stata superata una soglia, altrimenti None."""
        if not self.active:
            return None
        elapsed = self.clock() - self._last
        if elapsed < self._next:
            return None
        value = self._next
        while self._next <= elapsed:
            value = self._next
            self._next += self.step
        return int(value)


class CameraSession:
    """Contatori ed emissione eventi `camera.*`."""

    def __init__(self, emit: Callable[..., Any], clock: Callable[[], float] = time.monotonic):
        self._emit = emit
        self.clock = clock
        self.photo_count = 0
        self.recording = False
        self._rec_start = 0.0
        self.idle = IdleTracker(clock)

    def open(self, available: bool) -> None:
        self._emit("camera.open", {"available": bool(available)})
        self.idle.set_active(bool(available))

    def photo(self) -> int:
        self.photo_count += 1
        self.idle.reset()
        self._emit("camera.photo", {"count": self.photo_count})
        return self.photo_count

    def video_start(self) -> None:
        if self.recording:
            return
        self.recording = True
        self._rec_start = self.clock()
        self.idle.reset()
        self._emit("camera.video_start", {})

    def video_stop(self) -> int:
        if not self.recording:
            return 0
        self.recording = False
        seconds = int(self.clock() - self._rec_start)
        self.idle.reset()
        self._emit("camera.video_stop", {"seconds": seconds})
        return seconds

    def switch(self, name: str) -> None:
        self.idle.reset()
        self._emit("camera.switch", {"camera": name})

    def user_action(self) -> None:
        """Qualsiasi azione dell'utente azzera l'inattività."""
        self.idle.reset()

    def tick(self) -> None:
        if self.recording:
            self.idle.reset()
            return
        secs = self.idle.poll()
        if secs is not None:
            self._emit("camera.idle", {"seconds": secs})

    def recording_seconds(self) -> int:
        return int(self.clock() - self._rec_start) if self.recording else 0


# ---------------------------------------------------------------------------
def camera_roll_dir(create: bool = True) -> Path:
    """Cartella di salvataggio: EWA_CAMERA_DIR, altrimenti Immagini/Rullino o Immagini/Camera Roll."""
    override = os.environ.get("EWA_CAMERA_DIR")
    if override:
        p = Path(override)
    else:
        pictures = Path.home() / "Pictures"
        if sys.platform == "win32":
            try:
                from PySide6.QtCore import QStandardPaths
                loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
                if loc:
                    pictures = Path(loc)
            except Exception:
                pass
        p = pictures / "Rullino" if (pictures / "Rullino").is_dir() else pictures / "Camera Roll"
    if create:
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return p


def capture_filename(kind: str = "photo", when: datetime | None = None) -> str:
    """Nome stile Windows: WIN_20261101_14_03_22_Pro.jpg / .mp4"""
    when = when or datetime.now()
    ext = "mp4" if kind == "video" else "jpg"
    return f"WIN_{when:%Y%m%d_%H_%M_%S}_Pro.{ext}"


def unique_path(folder: Path, name: str) -> Path:
    p = folder / name
    n = 1
    while p.exists():
        p = folder / f"{Path(name).stem}_{n}{Path(name).suffix}"
        n += 1
    return p


def latest_capture(folder: Path) -> Path | None:
    try:
        files = [f for f in folder.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".mp4")]
    except OSError:
        return None
    return max(files, key=lambda f: f.stat().st_mtime, default=None)
