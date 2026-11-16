"""EWA — Everything in Windows but AI. Shell interattiva che ospita il MarvHub.

Uso:  python ewa.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import random
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from ewa.core import colors
from ewa.core.bus import HubPortInUse
from ewa.core.colors import (BLU, CIANO, GIALLO, GRASSETTO, GRIGIO, RESET, ROSSO, VERDE, VIOLA, c)
from ewa.core.config import PROJECT_ROOT, load_config
from ewa.core.hub import MarvHub
from ewa.core.notifier import Notifier

PROMPT = f"{VERDE}ewa> {RESET}"

BANNER = r"""
  _______        ___
 | ____\ \      / / \
 |  _|  \ \ /\ / / _ \
 | |___  \ V  V / ___ \
 |_____|  \_/\_/_/   \_\
"""

TOOL_COMMANDS = {  # comando -> (package, nome mostrato)
    "calc": ("calculator", "Calcolatrice"), "calcolatrice": ("calculator", "Calcolatrice"),
    "timer": ("clock", "Sveglie e orologio"), "orologio": ("clock", "Sveglie e orologio"),
    "sveglie": ("clock", "Sveglie e orologio"),
    "camera": ("camera", "Fotocamera"), "fotocamera": ("camera", "Fotocamera"),
    "notepad": ("notepad", "Blocco note"), "blocco": ("notepad", "Blocco note"),
}

STARTUP_QUIPS = [
    "Eccomi. Non che qualcuno me l'abbia chiesto.",
    "Sono sveglio. Purtroppo.",
    "Sì, sono io. Cercherò di trattenere l'entusiasmo.",
]
EXIT_QUIPS = [
    "Finalmente un po' di pace. Non tornare troppo presto.",
]
INTERRUPT_QUIP = "Mi interrompi a metà? Tipico. Arrivederci."

HELP = f"""{GRASSETTO}Comandi{RESET}
  {CIANO}calc{RESET} | calcolatrice          apre la Calcolatrice
  {CIANO}timer{RESET} | orologio | sveglie   apre Sveglie e orologio
  {CIANO}camera{RESET} | fotocamera          apre la Fotocamera
  {CIANO}notepad{RESET} | blocco [file]      apre il Blocco note (opzionalmente con un file)
  {CIANO}status{RESET}                       tool connessi, modello, notifiche, cooldown
  {CIANO}log{RESET} on|off                   mostra/nasconde il log colorato di eventi e commenti
  {CIANO}toast{RESET} [testo]                invia una notifica di prova
  {CIANO}help{RESET} | aiuto                 questo elenco
  {CIANO}exit{RESET} | esci                  chiude i tool e la shell"""

LOG_COLORS = {"event": GRIGIO, "marv": VIOLA, "chat": CIANO, "info": BLU, "error": ROSSO}
LOG_ICONS = {"event": "·", "marv": "Marv ›", "chat": "Marv (chat) ›", "info": "i", "error": "!"}


def log_line(kind: str, text: str) -> None:
    """Stampa una riga di log senza rovinare il prompt in corso di digitazione."""
    col = LOG_COLORS.get(kind, GRIGIO)
    sys.stdout.write(f"\r\033[K{col}{LOG_ICONS.get(kind, '·')} {text}{RESET}\n{PROMPT}")
    sys.stdout.flush()


class HubThread:
    """Esegue il MarvHub in un thread di background con il suo event loop."""

    def __init__(self, hub: MarvHub):
        self.hub = hub
        self.loop = asyncio.new_event_loop()
        self.error: Exception | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ewa-hub", daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.hub.start())
        except Exception as e:
            self.error = e
            self._ready.set()
            return
        self._ready.set()
        self.loop.run_forever()

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(10)

    def stop(self) -> None:
        if self.error or not self.loop.is_running():
            return
        fut = asyncio.run_coroutine_threadsafe(self.hub.stop(), self.loop)
        try:
            fut.result(3)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


class Shell:
    def __init__(self, hub: MarvHub):
        self.hub = hub
        self.children: list[tuple[str, subprocess.Popen]] = []
        self.tools_log = Path(tempfile.gettempdir()) / "ewa-tools.log"

    # ---- tool figli ------------------------------------------------------
    def launch(self, package: str, title: str, args: list[str]) -> None:
        if importlib.util.find_spec(f"ewa.tools.{package}.__main__") is None:
            print(c(f"{title} non è ancora installato (manca ewa/tools/{package}/__main__.py).", GIALLO))
            return
        try:
            log = open(self.tools_log, "ab")
            proc = subprocess.Popen([sys.executable, "-m", f"ewa.tools.{package}", *args],
                                    cwd=PROJECT_ROOT, stdout=log, stderr=log)
        except OSError as e:
            print(c(f"Impossibile avviare {title}: {e}", ROSSO))
            return
        self.children.append((title, proc))
        print(c(f"Avvio {title}…", GRIGIO))

    def close_children(self) -> None:
        for _, p in self.children:
            if p.poll() is None:
                p.terminate()
        for _, p in self.children:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    # ---- comandi ---------------------------------------------------------
    def status(self) -> None:
        st = self.hub.status()
        tools = ", ".join(f"{t} (pid {p})" for t, p in st["tools"]) or "nessuno"
        print(f"{GRASSETTO}Stato{RESET}")
        rows = [("Tool connessi", tools), ("Modello", st["model"]), ("Provider", st["provider"]),
                ("Notifiche inviate", st["notifications"]), ("Cooldown", f"{st['cooldown']:g} s"),
                ("Blocco note in Dark", st["dark"]), ("Notifiche via", st["notifier"]),
                ("Porta hub", st["port"]), ("Log tool", self.tools_log)]
        for k, v in rows:
            print(f"  {GIALLO}{k:<20}{RESET}{v}")
        dead = [(t, p.returncode) for t, p in self.children if p.poll() not in (None, 0)]
        for t, rc in dead:
            print(c(f"  {t} è terminato con errore (codice {rc}); vedi {self.tools_log}", ROSSO))

    def handle(self, line: str) -> bool:
        """Esegue un comando. False = esci."""
        parts = line.split()
        if not parts:
            return True
        cmd, args = parts[0].lower(), parts[1:]
        if cmd in ("exit", "esci", "quit"):
            return False
        if cmd in TOOL_COMMANDS:
            package, title = TOOL_COMMANDS[cmd]
            self.launch(package, title, args if package == "notepad" else [])
        elif cmd == "status":
            self.status()
        elif cmd == "log":
            if args and args[0].lower() in ("on", "off"):
                self.hub.log_enabled = args[0].lower() == "on"
                print(c(f"Log {'attivato' if self.hub.log_enabled else 'disattivato'}.", GRIGIO))
            else:
                print(c(f"Log: {'on' if self.hub.log_enabled else 'off'}. Uso: log on|off", GRIGIO))
        elif cmd == "toast":
            text = " ".join(args) or "Questo è un toast di prova. Ti è andata bene."
            self.hub.notifier.notify(text, "Prova")
        elif cmd in ("help", "aiuto", "?"):
            print(HELP)
        else:
            print(c(f"Comando sconosciuto: {cmd}. Scrivi 'help' per l'elenco.", ROSSO))
        return True


def marv_say(text: str) -> None:
    print(f"{VIOLA}Marv: {RESET}{CIANO}{text}{RESET}")


def main() -> int:
    colors.enable_terminal()
    cfg = load_config()
    shell_ref: list[Shell] = []
    hub = MarvHub(cfg, notifier=Notifier(), log=log_line)
    ht = HubThread(hub)
    ht.start()
    if ht.error:
        msg = str(ht.error) if isinstance(ht.error, HubPortInUse) else f"Errore all'avvio dell'hub: {ht.error}"
        print(c(msg, ROSSO))
        return 1
    shell = Shell(hub)
    shell_ref.append(shell)

    print(c(BANNER, CIANO))
    print(f"{GRASSETTO}{GIALLO}EWA — Everything in Windows but AI{RESET}")
    print(c("Scrivi 'help' per i comandi.", GRIGIO))
    marv_say(random.choice(STARTUP_QUIPS))
    if not cfg.fake_llm and not cfg.llm_api_key:
        print(c("Attenzione: nessuna chiave API (LLM_API_KEY nel .env): Marv resterà muto. "
                "Per provare senza rete usa MARV_FAKE_LLM=1.", GIALLO))
    print()

    try:
        while True:
            try:
                line = input(PROMPT).strip()
            except EOFError:
                break
            if not shell.handle(line):
                break
        marv_say(random.choice(EXIT_QUIPS))
    except KeyboardInterrupt:
        print()
        marv_say(INTERRUPT_QUIP)
    finally:
        shell.close_children()
        ht.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
