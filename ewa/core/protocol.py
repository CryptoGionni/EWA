"""Contratto di comunicazione tra i tool EWA e il MarvHub.

Trasporto: TCP su 127.0.0.1:<EWA_HUB_PORT>, un messaggio JSON per riga (UTF-8, '\\n').

Tool -> hub
    1) Prima riga dopo la connessione: {"v":1,"kind":"hello","tool":"<nome>","pid":123}
    2) Eventi:  {"v":1,"kind":"event","tool":"calc","type":"calc.result",
                 "data":{...},"priority":"normal"|"high","ts":1730000000.0}

Hub -> tool  (oggi solo il Blocco note in modalità Dark)
    {"v":1,"kind":"chat.delta","text":"pezzo di testo"}
    {"v":1,"kind":"chat.end"}
    {"v":1,"kind":"chat.error","msg":"descrizione"}

Il catalogo EVENTS documenta tipi e campi di `data`. I tool NON devono emettere
tipi fuori catalogo; l'hub ignora (ma registra) eventi sconosciuti.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = 1
NORMAL = "normal"
HIGH = "high"

# Nome tool -> descrizione italiana (usata nei prompt e nella shell)
TOOLS = {
    "calc": "Calcolatrice",
    "clock": "Sveglie e orologio",
    "camera": "Fotocamera",
    "notepad": "Blocco note",
}

# tipo evento -> (campi di data, descrizione per il prompt di Marv)
EVENTS: dict[str, tuple[dict[str, str], str]] = {
    # --- Calcolatrice ---
    "calc.open": ({}, "l'utente ha aperto la calcolatrice"),
    "calc.result": ({"expr": "str", "result": "str", "mode": "standard|scientifica"},
                    "l'utente ha calcolato un'espressione"),
    "calc.error": ({"expr": "str", "error": "str"}, "calcolo non valido (es. divisione per zero)"),
    "calc.mode": ({"mode": "standard|scientifica"}, "l'utente ha cambiato modalità"),
    # --- Sveglie e orologio ---
    "clock.open": ({"tab": "str"}, "l'utente ha aperto Sveglie e orologio"),
    "timer.start": ({"seconds": "int", "label": "str"}, "l'utente ha avviato un timer"),
    "timer.progress": ({"seconds": "int", "label": "str", "elapsed": "int", "remaining": "int", "pct": "int"},
                       "un timer è in corso (aggiornamento periodico)"),
    "timer.pause": ({"label": "str", "remaining": "int"}, "timer messo in pausa"),
    "timer.reset": ({"label": "str", "elapsed": "int"}, "timer azzerato/annullato prima della fine"),
    "timer.done": ({"seconds": "int", "label": "str"}, "il timer è scaduto"),
    "stopwatch.start": ({}, "cronometro avviato"),
    "stopwatch.lap": ({"elapsed": "float", "laps": "int", "lap_time": "float"}, "giro registrato"),
    "stopwatch.stop": ({"elapsed": "float", "laps": "int"}, "cronometro fermato"),
    # --- Fotocamera ---
    "camera.open": ({"available": "bool"}, "l'utente ha aperto la fotocamera"),
    "camera.photo": ({"count": "int"}, "l'utente ha scattato una foto (count = foto in questa sessione)"),
    "camera.video_start": ({}, "l'utente ha iniziato a registrare un video"),
    "camera.video_stop": ({"seconds": "int"}, "registrazione video terminata"),
    "camera.switch": ({"camera": "str"}, "cambio fotocamera"),
    "camera.idle": ({"seconds": "int"}, "l'utente si sta guardando nell'inquadratura senza scattare"),
    # --- Blocco note ---
    "notepad.open": ({"filename": "str"}, "l'utente ha aperto il Blocco note"),
    "notepad.typing": ({"text_excerpt": "str", "chars": "int", "filename": "str"},
                       "l'utente ha scritto qualcosa (estratto, dopo una pausa)"),
    "notepad.save": ({"filename": "str", "chars": "int"}, "l'utente ha salvato il file"),
    "notepad.dark_on": ({"text": "str"}, "l'utente ha attivato la modalità Dark: Marv deve iniziare a parlargli"),
    "notepad.dark_off": ({}, "l'utente ha disattivato la modalità Dark"),
    "chat.user": ({"text": "str"}, "messaggio dell'utente a Marv nella chat del Blocco note"),
    # --- Generici ---
    "tool.close": ({}, "l'utente ha chiuso il tool"),
}

# Eventi che di default scavalcano il cooldown
HIGH_PRIORITY_DEFAULT = {"timer.start", "timer.done", "notepad.dark_on", "chat.user"}


@dataclass
class Event:
    tool: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    priority: str = NORMAL
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps({"v": PROTOCOL_VERSION, "kind": "event", "tool": self.tool, "type": self.type,
                           "data": self.data, "priority": self.priority, "ts": self.ts},
                          ensure_ascii=False)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Event":
        return Event(tool=d.get("tool", "?"), type=d.get("type", "?"), data=d.get("data") or {},
                     priority=d.get("priority", NORMAL), ts=d.get("ts") or time.time())


def encode(msg: dict[str, Any]) -> bytes:
    """Serializza un messaggio generico (aggiunge v) in una riga JSON."""
    return (json.dumps({"v": PROTOCOL_VERSION, **msg}, ensure_ascii=False) + "\n").encode("utf-8")


def decode(line: bytes | str) -> dict[str, Any] | None:
    """Decodifica una riga; None se malformata."""
    try:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        obj = json.loads(line)
        return obj if isinstance(obj, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def hello(tool: str, pid: int) -> bytes:
    return encode({"kind": "hello", "tool": tool, "pid": pid})


def chat_delta(text: str) -> bytes:
    return encode({"kind": "chat.delta", "text": text})


def chat_end() -> bytes:
    return encode({"kind": "chat.end"})


def chat_error(msg: str) -> bytes:
    return encode({"kind": "chat.error", "msg": msg})
