"""HubServer: server TCP asyncio (JSON lines) a cui si collegano i tool EWA.

Il server non conosce la logica di Marv: registra i tool (hello), inoltra gli
eventi alla callback `on_event(conn, event)` e permette di rispondere alla
singola connessione (`conn.send(...)`, `send_chat_delta`, ...).
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Awaitable, Callable

from . import protocol

log = logging.getLogger("ewa.bus")


class HubPortInUse(RuntimeError):
    """La porta dell'hub è occupata (probabilmente un'altra shell EWA è aperta)."""


class Connection:
    """Una connessione di un tool all'hub."""

    _ids = itertools.count(1)

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.id = next(self._ids)
        self.reader = reader
        self.writer = writer
        self.tool: str | None = None  # noto dopo l'hello
        self.pid: int | None = None
        self.alive = True

    async def send(self, payload: bytes) -> bool:
        """Invia una riga già codificata. False se la connessione è caduta."""
        if not self.alive:
            return False
        try:
            self.writer.write(payload)
            await self.writer.drain()
            return True
        except (ConnectionError, OSError):
            self.alive = False
            return False

    async def send_chat_delta(self, text: str) -> bool:
        return await self.send(protocol.chat_delta(text))

    async def send_chat_end(self) -> bool:
        return await self.send(protocol.chat_end())

    async def send_chat_error(self, msg: str) -> bool:
        return await self.send(protocol.chat_error(msg))

    def __repr__(self) -> str:
        return f"<Connection #{self.id} tool={self.tool} pid={self.pid}>"


EventCallback = Callable[[Connection, protocol.Event], Awaitable[None]]
ConnCallback = Callable[[Connection], Awaitable[None] | None]


class HubServer:
    def __init__(self, on_event: EventCallback, host: str = "127.0.0.1", port: int = 47474,
                 on_connect: ConnCallback | None = None, on_disconnect: ConnCallback | None = None):
        self.host = host
        self.port = port
        self.on_event = on_event
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.connections: dict[int, Connection] = {}
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        try:
            self._server = await asyncio.start_server(self._handle, self.host, self.port)
        except OSError as e:
            raise HubPortInUse(
                f"Impossibile usare {self.host}:{self.port} ({e.strerror or e}). "
                "Probabilmente c'è già un'altra shell EWA aperta: chiudila, "
                "oppure cambia EWA_HUB_PORT nel file .env."
            ) from e

    async def stop(self) -> None:
        if self._server:
            self._server.close()
        for conn in list(self.connections.values()):
            conn.alive = False
            try:
                conn.writer.close()
            except Exception:
                pass
        if self._server:
            try:
                await asyncio.wait_for(self._server.wait_closed(), 2)
            except Exception:
                pass
            self._server = None

    def tools(self) -> list[Connection]:
        """Connessioni che hanno già fatto hello."""
        return [c for c in self.connections.values() if c.tool]

    async def _call(self, cb, *args):
        if cb is None:
            return
        try:
            res = cb(*args)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            log.exception("errore nella callback dell'hub")

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn = Connection(reader, writer)
        self.connections[conn.id] = conn
        try:
            while True:
                try:
                    line = await reader.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    continue  # riga troppo lunga: scarta
                if not line:
                    break
                msg = protocol.decode(line)
                if not msg:
                    continue
                kind = msg.get("kind")
                if kind == "hello":
                    conn.tool = str(msg.get("tool") or "?")
                    conn.pid = msg.get("pid")
                    await self._call(self.on_connect, conn)
                elif kind == "event":
                    if conn.tool is None:  # evento senza hello: deduci il tool
                        conn.tool = str(msg.get("tool") or "?")
                    await self._call(self.on_event, conn, protocol.Event.from_dict(msg))
        except (ConnectionError, OSError):
            pass
        finally:
            conn.alive = False
            self.connections.pop(conn.id, None)
            try:
                writer.close()
            except Exception:
                pass
            if conn.tool:
                await self._call(self.on_disconnect, conn)
