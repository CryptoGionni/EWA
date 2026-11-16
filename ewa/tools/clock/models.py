"""Logica di Timer e Cronometro, indipendente dalla UI.

La sorgente del tempo (`now`) e il canale eventi (`emit`) sono iniettabili:
nei test si usa un orologio finto accelerato e un emit che registra le chiamate.
Il tempo trascorso e' sempre calcolato dalla sorgente (time.monotonic), mai
contando i tick.
"""
from __future__ import annotations

import math
import time
from typing import Any, Callable

Emit = Callable[..., Any]

IDLE, RUNNING, PAUSED, DONE = "idle", "running", "paused", "done"


def _noop(*_a: Any, **_k: Any) -> None:
    pass


def progress_interval(seconds: float) -> float:
    """Intervallo (s) fra due timer.progress: clamp(seconds/4, 60, 600)."""
    return min(600.0, max(60.0, seconds / 4))


class TimerModel:
    def __init__(self, seconds: int, label: str, emit: Emit | None = None,
                 now: Callable[[], float] = time.monotonic):
        self.seconds = max(1, int(seconds))
        self.label = label
        self._emit = emit or _noop
        self._now = now
        self._clear()

    def _clear(self) -> None:
        self.state = IDLE
        self._acc = 0.0
        self._t0 = 0.0
        self._started = False   # evento start gia' inviato dall'ultimo reset
        self._next_k = 1        # prossima soglia di progress (k * intervallo)

    # --- stato ---
    @property
    def interval(self) -> float:
        return progress_interval(self.seconds)

    def elapsed(self) -> float:
        e = self._acc
        if self.state == RUNNING:
            e += self._now() - self._t0
        return min(max(e, 0.0), float(self.seconds))

    def remaining(self) -> float:
        return self.seconds - self.elapsed()

    def fraction_left(self) -> float:
        return self.remaining() / self.seconds

    # --- azioni ---
    def start(self) -> None:
        if self.state == IDLE:
            self._started = True
            self._t0 = self._now()
            self.state = RUNNING
            self._emit("timer.start", {"seconds": self.seconds, "label": self.label})
        elif self.state == PAUSED:       # ripresa: nessun evento
            self._t0 = self._now()
            self.state = RUNNING

    def pause(self) -> None:
        if self.state == RUNNING:
            self._acc = self.elapsed()
            self.state = PAUSED
            self._emit("timer.pause", {"label": self.label,
                                       "remaining": int(math.ceil(self.seconds - self._acc))})

    def toggle(self) -> None:
        if self.state == RUNNING:
            self.pause()
        else:
            self.start()

    def reset(self) -> None:
        if self._started and self.state != DONE:
            self._emit("timer.reset", {"label": self.label, "elapsed": int(self.elapsed())})
        self._clear()

    def configure(self, seconds: int, label: str) -> None:
        """Modifica durata/nome: annulla l'esecuzione in corso."""
        self.reset()
        self.seconds = max(1, int(seconds))
        self.label = label

    def tick(self) -> None:
        """Da chiamare periodicamente: rileva scadenza e soglie di progress."""
        if self.state != RUNNING:
            return
        e = self._acc + (self._now() - self._t0)
        if e >= self.seconds:
            self._acc = float(self.seconds)
            self.state = DONE
            self._emit("timer.done", {"seconds": self.seconds, "label": self.label})
            return
        n = int(e // self.interval)
        if n >= self._next_k:
            self._next_k = n + 1
            self._emit("timer.progress", {
                "seconds": self.seconds, "label": self.label, "elapsed": int(e),
                "remaining": int(math.ceil(self.seconds - e)),
                "pct": int(e / self.seconds * 100)})


class StopwatchModel:
    def __init__(self, emit: Emit | None = None, now: Callable[[], float] = time.monotonic):
        self._emit = emit or _noop
        self._now = now
        self.running = False
        self._acc = 0.0
        self._t0 = 0.0
        self.laps: list[tuple[float, float]] = []   # (tempo giro, totale)

    def elapsed(self) -> float:
        return self._acc + (self._now() - self._t0 if self.running else 0.0)

    def start(self) -> None:
        if self.running:
            return
        fresh = self._acc == 0.0 and not self.laps
        self._t0 = self._now()
        self.running = True
        if fresh:
            self._emit("stopwatch.start", {})

    def stop(self) -> None:
        if not self.running:
            return
        self._acc = self.elapsed()
        self.running = False
        self._emit("stopwatch.stop", {"elapsed": round(self._acc, 2), "laps": len(self.laps)})

    def toggle(self) -> None:
        self.stop() if self.running else self.start()

    def lap(self) -> None:
        if not self.running:
            return
        total = self.elapsed()
        last = self.laps[-1][1] if self.laps else 0.0
        self.laps.append((total - last, total))
        self._emit("stopwatch.lap", {"elapsed": round(total, 2), "laps": len(self.laps),
                                     "lap_time": round(total - last, 2)})

    def reset(self) -> None:
        self.running = False
        self._acc = 0.0
        self.laps.clear()

    def extremes(self) -> tuple[int | None, int | None]:
        """Indici (giro piu' veloce, giro piu' lento); None se meno di 3 giri."""
        if len(self.laps) < 3:
            return None, None
        times = [t for t, _ in self.laps]
        return times.index(min(times)), times.index(max(times))


def fmt_hms(seconds: float) -> str:
    """Tempo residuo del timer: HH:MM:SS (arrotondato per eccesso)."""
    s = int(math.ceil(max(0.0, seconds) - 1e-9))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def fmt_stopwatch(seconds: float) -> str:
    """Cronometro: HH:MM:SS,cc (centesimi con la virgola)."""
    cs = int(max(0.0, seconds) * 100 + 1e-6)
    return f"{cs // 360000:02d}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d},{cs % 100:02d}"
