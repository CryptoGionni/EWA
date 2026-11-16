"""MarvHub: il cervello di Marv come processo in background (senza finestra).

Lo avviano automaticamente i tool e la shell EWA quando non lo trovano attivo
(vedi ewa.core.launcher.spawn_hub). All'avvio prepara Ollama e scalda il modello.
Si chiude da solo quando nessun client è connesso da EWA_HUB_IDLE_EXIT secondi,
o quando la shell chiede lo spegnimento.

Uso:  python -m ewa.hubd   (oppure MarvHub.exe)
Log:  <temp>/ewa-hub.log
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import time

from ewa.core.bus import HubPortInUse
from ewa.core.config import load_config
from ewa.core.hub import MarvHub
from ewa.core.notifier import Notifier

CHECK_EVERY = 5.0


def _log_line(kind: str, text: str) -> None:
    # stdout è rediretto su ewa-hub.log da launcher.spawn_hub
    try:
        print(f"{time.strftime('%H:%M:%S')} [{kind}] {text}", flush=True)
    except Exception:
        pass


async def run(hub: MarvHub, idle_exit: float) -> int:
    try:
        await hub.start()
    except HubPortInUse:
        _log_line("info", "MarvHub è già attivo: esco.")
        return 0
    _log_line("info", f"MarvHub in ascolto su {hub.cfg.hub_host}:{hub.cfg.hub_port} (pid {os.getpid()})")
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, hub.shutdown_requested.set)
        except (NotImplementedError, RuntimeError):  # Windows: niente signal handler nel loop
            pass
    try:
        while not hub.shutdown_requested.is_set():
            try:
                await asyncio.wait_for(hub.shutdown_requested.wait(), CHECK_EVERY)
            except asyncio.TimeoutError:
                pass
            if idle_exit > 0 and hub.idle_seconds() >= idle_exit:
                _log_line("info", f"Nessun client da {idle_exit:.0f} s: MarvHub si spegne.")
                break
    finally:
        await hub.stop()
    return 0


def main() -> int:
    cfg = load_config()
    hub = MarvHub(cfg, notifier=Notifier(), log=_log_line)
    try:
        return asyncio.run(run(hub, cfg.hub_idle_exit))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
