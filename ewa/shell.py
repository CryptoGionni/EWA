"""EWA — Everything in Windows but AI. Shell interattiva colorata.

La shell è un client di MarvHub (il cervello di Marv, processo in background):
se l'hub non è attivo lo avvia, ne mostra il log colorato e lancia i tool.

Uso:  python ewa.py            (oppure EWA.exe)
      python ewa.py --setup    prepara Ollama e il modello, poi esce (usato dall'installer)
"""
from __future__ import annotations

import argparse
import asyncio
import random
import subprocess
import sys
import threading
import time

from ewa.core import colors, launcher, persona, protocol
from ewa.core.client import ToolClient
from ewa.core.colors import (BLU, CIANO, GIALLO, GRASSETTO, GRIGIO, RESET, ROSSO, VERDE, VIOLA, c)
from ewa.core.config import load_config

PROMPT = f"{VERDE}ewa> {RESET}"

BANNER = r"""
  _______        ___
 | ____\ \      / / \
 |  _|  \ \ /\ / / _ \
 | |___  \ V  V / ___ \
 |_____|  \_/\_/_/   \_\
"""

TOOL_COMMANDS = {  # comando -> (chiave in launcher.COMPONENTS, nome mostrato)
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
EXIT_QUIPS = ["Finalmente un po' di pace. Non tornare troppo presto."]
INTERRUPT_QUIP = "Mi interrompi a metà? Tipico. Arrivederci."

HELP = f"""{GRASSETTO}Comandi{RESET}
  {CIANO}calc{RESET} | calcolatrice          apre la Calcolatrice
  {CIANO}timer{RESET} | orologio | sveglie   apre Sveglie e orologio
  {CIANO}camera{RESET} | fotocamera          apre la Fotocamera
  {CIANO}notepad{RESET} | blocco [file]      apre il Blocco note (opzionalmente con un file)
  {CIANO}status{RESET}                       tool connessi, modello, stato di Marv, notifiche
  {CIANO}log{RESET} on|off                   mostra/nasconde il log colorato di eventi e commenti
  {CIANO}toast{RESET} [testo]                invia una notifica di prova
  {CIANO}help{RESET} | aiuto                 questo elenco
  {CIANO}exit{RESET} | esci                  chiude i tool aperti da qui e la shell"""

LOG_COLORS = {"event": GRIGIO, "marv": VIOLA, "chat": CIANO, "info": BLU, "error": ROSSO}
LOG_ICONS = {"event": "·", "marv": "Marv ›", "chat": "Marv (chat) ›", "info": "i", "error": "!"}

_print_lock = threading.Lock()


def log_line(kind: str, text: str) -> None:
    """Stampa una riga di log senza rovinare il prompt in corso di digitazione."""
    col = LOG_COLORS.get(kind, GRIGIO)
    with _print_lock:
        sys.stdout.write(f"\r\033[K{col}{LOG_ICONS.get(kind, '·')} {text}{RESET}\n{PROMPT}")
        sys.stdout.flush()


def marv_say(text: str) -> None:
    print(f"{VIOLA}Marv: {RESET}{CIANO}{text}{RESET}")


class Shell:
    def __init__(self):
        self.children: list[tuple[str, subprocess.Popen]] = []
        self.log_on = True
        self._status: dict | None = None
        self._status_evt = threading.Event()
        self.client = ToolClient(protocol.SHELL, on_message=self._on_message)

    # ---- messaggi dall'hub -----------------------------------------------
    def _on_message(self, msg: dict) -> None:
        kind = msg.get("kind")
        if kind == "log" and self.log_on:
            log_line(str(msg.get("level", "info")), str(msg.get("text", "")))
        elif kind == "status":
            self._status = msg.get("data") or {}
            self._status_evt.set()

    # ---- tool figli ------------------------------------------------------
    def launch(self, key: str, title: str, args: list[str]) -> None:
        try:
            proc = launcher.spawn(key, args)
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
        self._status_evt.clear()
        self.client.send({"kind": "control", "cmd": "status"})
        if not self._status_evt.wait(3):
            print(c("MarvHub non risponde (forse si sta ancora avviando). Riprova tra poco.", GIALLO))
            return
        st = self._status or {}
        tools = ", ".join(f"{t} (pid {p})" for t, p in st.get("tools", [])) or "nessuno"
        print(f"{GRASSETTO}Stato{RESET}")
        rows = [("Tool connessi", tools), ("Modello", st.get("model")), ("Provider", st.get("provider")),
                ("Stato di Marv", st.get("llm_state")), ("Ollama", st.get("ollama")),
                ("Notifiche inviate", st.get("notifications")), ("Cooldown", f"{st.get('cooldown', 0):g} s"),
                ("Blocco note in Dark", st.get("dark")), ("Notifiche via", st.get("notifier")),
                ("Porta hub", st.get("port")), ("Log hub", launcher.HUB_LOG), ("Log tool", launcher.TOOLS_LOG)]
        for k, v in rows:
            print(f"  {GIALLO}{k:<20}{RESET}{v}")
        dead = [(t, p.returncode) for t, p in self.children if p.poll() not in (None, 0)]
        for t, rc in dead:
            print(c(f"  {t} è terminato con errore (codice {rc}); vedi {launcher.TOOLS_LOG}", ROSSO))

    def handle(self, line: str) -> bool:
        """Esegue un comando. False = esci."""
        parts = line.split()
        if not parts:
            return True
        cmd, args = parts[0].lower(), parts[1:]
        if cmd in ("exit", "esci", "quit"):
            return False
        if cmd in TOOL_COMMANDS:
            key, title = TOOL_COMMANDS[cmd]
            self.launch(key, title, args if key == "notepad" else [])
        elif cmd == "status":
            self.status()
        elif cmd == "log":
            if args and args[0].lower() in ("on", "off"):
                self.log_on = args[0].lower() == "on"
                self.client.send({"kind": "control", "cmd": "log", "on": self.log_on})
                print(c(f"Log {'attivato' if self.log_on else 'disattivato'}.", GRIGIO))
            else:
                print(c(f"Log: {'on' if self.log_on else 'off'}. Uso: log on|off", GRIGIO))
        elif cmd == "toast":
            self.client.send({"kind": "control", "cmd": "toast", "text": " ".join(args)})
        elif cmd in ("help", "aiuto", "?"):
            print(HELP)
        else:
            print(c(f"Comando sconosciuto: {cmd}. Scrivi 'help' per l'elenco.", ROSSO))
        return True

    def shutdown(self) -> None:
        """Chiude i tool aperti da qui; MarvHub si spegne se non resta nessun altro tool."""
        self.close_children()
        self.client.send({"kind": "control", "cmd": "shutdown", "only_if_idle": True})
        time.sleep(0.3)
        self.client.close(send_close_event=False)


def setup() -> int:
    """`EWA --setup`: avvia Ollama, scarica il modello se manca e lo scalda. Per l'installer."""
    from ewa.core.llm import MarvLLM
    from ewa.core.ollama_service import OllamaError, OllamaService

    colors.enable_terminal()
    cfg = load_config()
    print(c(BANNER, CIANO))
    print(f"{GRASSETTO}{GIALLO}Preparo Marv ({cfg.llm_model}){RESET}\n")
    if not cfg.is_ollama or cfg.fake_llm:
        print(c("Il provider configurato non è Ollama: niente da preparare.", GRIGIO))
        return 0
    svc = OllamaService(cfg.ollama_host, cfg.llm_model, autostart=True, autopull=True)
    try:
        svc.ensure(lambda m: print(c(m, BLU)))
        print(c("Riscaldo il modello…", BLU))
        secs = asyncio.run(MarvLLM(cfg).warm_up(persona.warmup_messages()))
        print(c(f"Fatto in {secs:.1f} s. Marv è pronto.", VERDE))
        marv_say("Mi hai installato. Non so se congratularmi con te o compatirmi.")
        code = 0
    except OllamaError as e:
        print(c(str(e), ROSSO))
        code = 1
    except Exception as e:
        print(c(f"Errore: {e}", ROSSO))
        code = 1
    finally:
        svc.stop()
    if sys.stdin and sys.stdin.isatty():
        input(c("\nPremi Invio per chiudere.", GRIGIO))
    return code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="EWA", description="EWA — Everything in Windows but AI")
    ap.add_argument("--setup", action="store_true", help="prepara Ollama e il modello, poi esce")
    args = ap.parse_args(argv)
    if args.setup:
        return setup()

    colors.enable_terminal()
    cfg = load_config()
    shell = Shell()  # il client avvia MarvHub se non è già attivo
    print(c(BANNER, CIANO))
    print(f"{GRASSETTO}{GIALLO}EWA — Everything in Windows but AI{RESET}")
    print(c("Scrivi 'help' per i comandi.", GRIGIO))
    marv_say(random.choice(STARTUP_QUIPS))
    if not shell.client.wait_connected(15):
        print(c(f"MarvHub non risponde: i tool funzionano, ma Marv resterà muto. Log: {launcher.HUB_LOG}", GIALLO))
    elif cfg.is_ollama and not cfg.fake_llm:
        print(c(f"Modello locale: {cfg.llm_model} via Ollama.", GRIGIO))
    elif not cfg.fake_llm and not cfg.llm_api_key:
        print(c("Attenzione: nessuna chiave API (LLM_API_KEY nel .env): Marv resterà muto.", GIALLO))
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
        shell.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
