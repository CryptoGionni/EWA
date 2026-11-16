"""Gestione di Ollama per Marv: trova l'eseguibile, avvia `ollama serve` se il
server non risponde, scarica il modello se manca, lo ferma all'uscita (solo se
l'abbiamo avviato noi).

Tutto sincrono e senza Qt: l'hub lo usa da un thread, la shell `EWA --setup`
direttamente.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .launcher import LOG_DIR

OLLAMA_LOG = LOG_DIR / "ewa-ollama.log"
Progress = Callable[[str], None]


class OllamaError(RuntimeError):
    """Problema leggibile dall'utente (Ollama non installato, download fallito, ...)."""


def find_ollama() -> str | None:
    """Percorso di ollama(.exe): PATH, poi le cartelle d'installazione standard."""
    found = shutil.which("ollama")
    if found:
        return found
    candidates: list[Path] = []
    if sys.platform == "win32":
        for var, sub in (("LOCALAPPDATA", r"Programs\Ollama"), ("ProgramFiles", "Ollama"),
                         ("ProgramFiles(x86)", "Ollama")):
            base = os.getenv(var)
            if base:
                candidates.append(Path(base) / sub / "ollama.exe")
    else:
        candidates += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama"),
                       Path.home() / ".local/bin/ollama", Path("/Applications/Ollama.app/Contents/Resources/ollama")]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


def is_running(host: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/version", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _host_env(host: str) -> str:
    """Valore di OLLAMA_HOST per `ollama serve` (senza schema)."""
    return host.split("://", 1)[-1].rstrip("/")


def norm_keep_alive(value: str) -> int | str:
    """'-1' -> -1 (Ollama vuole un numero o una durata con unità tipo '30m')."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


class OllamaService:
    def __init__(self, host: str, model: str, autostart: bool = True, autopull: bool = True):
        self.host = host
        self.model = model
        self.autostart = autostart
        self.autopull = autopull
        self.proc: subprocess.Popen | None = None   # solo se l'abbiamo avviato noi
        self.state = "non avviato"

    @property
    def started_by_us(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # ---- server -----------------------------------------------------------
    def ensure_server(self, progress: Progress = lambda s: None, wait: float = 45.0) -> None:
        if is_running(self.host):
            self.state = "server attivo"
            return
        if not self.autostart:
            raise OllamaError(f"Ollama non risponde su {self.host} e l'avvio automatico è disattivato "
                              "(OLLAMA_AUTOSTART=0).")
        exe = find_ollama()
        if not exe:
            raise OllamaError("Ollama non è installato. Scaricalo da https://ollama.com/download "
                              "(oppure: winget install -e --id Ollama.Ollama) e riavvia EWA.")
        progress("Avvio ollama serve…")
        env = dict(os.environ, OLLAMA_HOST=_host_env(self.host))
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        log = open(OLLAMA_LOG, "ab")
        self.proc = subprocess.Popen([exe, "serve"], env=env, stdout=log, stderr=log,
                                     stdin=subprocess.DEVNULL, **kwargs)
        deadline = time.time() + wait
        while time.time() < deadline:
            if is_running(self.host):
                self.state = "server avviato da EWA"
                return
            if self.proc.poll() is not None:
                raise OllamaError(f"`ollama serve` è terminato subito (codice {self.proc.returncode}); "
                                  f"dettagli in {OLLAMA_LOG}")
            time.sleep(0.3)
        raise OllamaError(f"`ollama serve` non risponde dopo {wait:.0f} s; dettagli in {OLLAMA_LOG}")

    def stop(self) -> None:
        """Ferma `ollama serve` solo se l'ha avviato EWA."""
        if self.started_by_us:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    # ---- modello ----------------------------------------------------------
    def _client(self):
        import ollama
        return ollama.Client(host=self.host)

    def has_model(self) -> bool:
        names = set()
        for m in self._client().list().models:
            names.add(m.model)
        want = self.model if ":" in self.model else f"{self.model}:latest"
        return want in names

    def ensure_model(self, progress: Progress = lambda s: None) -> None:
        if self.has_model():
            return
        if not self.autopull:
            raise OllamaError(f"Il modello {self.model} non è scaricato. Scaricalo con: ollama pull {self.model}")
        progress(f"Scarico il modello {self.model} (solo la prima volta)…")
        self.state = "download del modello"
        last_pct = -10
        try:
            for st in self._client().pull(self.model, stream=True):
                total, done = st.total or 0, st.completed or 0
                if total:
                    pct = int(done * 100 / total)
                    if pct >= last_pct + 10:
                        last_pct = pct - pct % 10
                        progress(f"Download {self.model}: {pct}% ({done / 1e9:.1f}/{total / 1e9:.1f} GB)")
                        self.state = f"download del modello {pct}%"
        except Exception as e:
            raise OllamaError(f"Download di {self.model} fallito: {e}") from e
        progress(f"Modello {self.model} scaricato.")

    def ensure(self, progress: Progress = lambda s: None) -> None:
        """Server attivo + modello presente (sincrono, può durare minuti al primo avvio)."""
        self.ensure_server(progress)
        self.ensure_model(progress)
        self.state = "pronto"

