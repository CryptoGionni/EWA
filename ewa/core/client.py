"""ToolClient: connessione di un tool verso il MarvHub.

- Non blocca mai la UI: invio e ricezione su un thread daemon.
- Se l'hub non è attivo il tool funziona lo stesso: gli eventi vengono scartati
  (oltre una piccola coda) e il client ritenta la connessione ogni 2 s.
- I messaggi in arrivo (chat.*) vengono passati a `on_message(dict)` DAL THREAD
  DI RETE: nei tool Qt usare `ewa.ui.win10.HubBridge`, che li rilancia come
  segnale Qt nel thread della UI.

Uso:
    client = ToolClient("calc")
    client.emit("calc.result", {"expr": "2+2", "result": "4", "mode": "standard"})
    ...
    client.close()
"""
from __future__ import annotations

import collections
import os
import socket
import threading
import time
from typing import Any, Callable

from . import protocol
from .config import load_config


class ToolClient:
    MAX_QUEUE = 50

    def __init__(self, tool: str, on_message: Callable[[dict[str, Any]], None] | None = None,
                 host: str | None = None, port: int | None = None):
        cfg = load_config()
        self.tool = tool
        self.host = host or cfg.hub_host
        self.port = port or cfg.hub_port
        self.on_message = on_message
        self._queue: collections.deque[bytes] = collections.deque(maxlen=self.MAX_QUEUE)
        self._cv = threading.Condition()
        self._sock: socket.socket | None = None
        self._closed = False
        self._writer = threading.Thread(target=self._run, name=f"ewa-{tool}-client", daemon=True)
        self._writer.start()

    # ---- API pubblica -------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._sock is not None

    def emit(self, type_: str, data: dict[str, Any] | None = None, priority: str | None = None) -> None:
        """Invia un evento all'hub (non bloccante)."""
        if priority is None:
            priority = protocol.HIGH if type_ in protocol.HIGH_PRIORITY_DEFAULT else protocol.NORMAL
        ev = protocol.Event(tool=self.tool, type=type_, data=data or {}, priority=priority)
        with self._cv:
            self._queue.append((ev.to_json() + "\n").encode("utf-8"))
            self._cv.notify()

    def close(self, send_close_event: bool = True) -> None:
        if send_close_event:
            self.emit("tool.close")
            # breve attesa per far partire l'ultimo evento
            deadline = time.time() + 0.5
            while self._queue and self._sock and time.time() < deadline:
                time.sleep(0.02)
        with self._cv:
            self._closed = True
            self._cv.notify()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    # ---- interni ------------------------------------------------------
    def _connect(self) -> bool:
        try:
            s = socket.create_connection((self.host, self.port), timeout=1.0)
            s.settimeout(None)
            s.sendall(protocol.hello(self.tool, os.getpid()))
            self._sock = s
            threading.Thread(target=self._reader, args=(s,), daemon=True).start()
            return True
        except OSError:
            self._sock = None
            return False

    def _reader(self, s: socket.socket) -> None:
        buf = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    msg = protocol.decode(line)
                    if msg and self.on_message:
                        try:
                            self.on_message(msg)
                        except Exception:
                            pass
        except OSError:
            pass
        if self._sock is s:
            self._sock = None

    def _run(self) -> None:
        last_attempt = 0.0
        while True:
            with self._cv:
                if self._closed:
                    return
                if not self._queue or self._sock is None:
                    self._cv.wait(timeout=0.5)
                if self._closed:
                    return
            if self._sock is None:
                if time.time() - last_attempt >= 2.0:
                    last_attempt = time.time()
                    self._connect()
                continue
            while self._queue and self._sock is not None:
                payload = self._queue[0]
                try:
                    self._sock.sendall(payload)
                    self._queue.popleft()
                except OSError:
                    self._sock = None
