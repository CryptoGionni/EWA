"""MarvHub: l'unico cervello di EWA.

Riceve gli eventi di tutti i tool (via HubServer), li tiene in una memoria
condivisa, decide se/quando far commentare Marv e consegna il commento come
notifica. Per il Blocco note in modalità Dark apre invece una chat in streaming.

Punto di estensione per future azioni agentiche
-----------------------------------------------
`MarvHub.actions` è un registry (nome -> coroutine) oggi VUOTO. In futuro Marv
potrà chiedere al modello di invocare tool-call (es. "avvia_timer",
"scrivi_nel_blocco_note"): ogni azione si registra con `hub.actions["nome"] = fn`
dove `fn` è una `async def fn(hub, **argomenti)` e si esegue con
`await hub.run_action("nome", **argomenti)`. Nessuna azione è implementata né
invocata dal flusso attuale.
"""
from __future__ import annotations

import asyncio
import collections
import random
import time
from typing import Any, Awaitable, Callable

from . import persona, protocol
from .bus import Connection, HubServer
from .config import Config, load_config
from .llm import LLMError, MarvLLM
from .notifier import Notifier
from .ollama_service import OllamaError, OllamaService
from .protocol import EVENTS, HIGH, TOOLS, Event

MEMORY_EVENTS = 30
MEMORY_COMMENTS = 8
CHAT_HISTORY_MAX = 20
PENDING_MAX_AGE = 60.0
NEVER_COMMENT = {"notepad.dark_off"}

LogCallback = Callable[[str, str], None]  # (kind, testo): kind in event|marv|chat|info|error


class MarvHub:
    def __init__(self, config: Config | None = None, llm: MarvLLM | None = None,
                 notifier: Notifier | None = None, log: LogCallback | None = None):
        self.cfg = config or load_config()
        self.llm = llm or MarvLLM(self.cfg)
        self.notifier = notifier or Notifier()
        self.log_callback = log
        self.log_enabled = True
        self.cooldown = self.cfg.cooldown_seconds
        self.close_comment_probability = 0.1  # tool.close viene commentato "raramente"
        self.server = HubServer(self.handle_event, self.cfg.hub_host, self.cfg.hub_port,
                                on_connect=self._on_connect, on_disconnect=self._on_disconnect,
                                on_control=self._on_control)
        # modello: Ollama avviato/scaldato in background; i commenti aspettano `_ready`
        self.ollama: OllamaService | None = None
        if self.cfg.is_ollama and not self.cfg.fake_llm:
            self.ollama = OllamaService(self.cfg.ollama_host, self.cfg.llm_model,
                                        self.cfg.ollama_autostart, self.cfg.ollama_autopull)
        self.llm_state = "in preparazione"
        self._ready: asyncio.Event | None = None
        self._prepare_task: asyncio.Task | None = None
        self.started_at = time.time()
        self._idle_since: float | None = time.time()
        self.shutdown_requested: asyncio.Event | None = None
        self._muted_shells: set[int] = set()
        # memoria condivisa
        self.events: collections.deque[Event] = collections.deque(maxlen=MEMORY_EVENTS)
        self.comments: collections.deque[str] = collections.deque(maxlen=MEMORY_COMMENTS)
        self.notifications_sent = 0
        # stato notifiche
        self._last_notify = 0.0
        self._pending: Event | None = None
        self._pending_timer: asyncio.TimerHandle | None = None
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        # chat Dark per connessione
        self._dark: set[int] = set()
        self._history: dict[int, list[dict]] = {}
        self._chat_locks: dict[int, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()
        # punto di estensione agentico (vuoto, vedi docstring del modulo)
        self.actions: dict[str, Callable[..., Awaitable[Any]]] = {}

    # ---- ciclo di vita ---------------------------------------------------
    async def start(self, prepare_llm: bool = True) -> None:
        self._ready = asyncio.Event()
        self.shutdown_requested = asyncio.Event()
        await self.server.start()  # solleva HubPortInUse se la porta è occupata
        self._worker = asyncio.create_task(self._notify_worker())
        if prepare_llm:
            self._prepare_task = asyncio.create_task(self._prepare_llm())
        else:
            self.llm_state = "pronto"
            self._ready.set()

    async def stop(self) -> None:
        if self._pending_timer:
            self._pending_timer.cancel()
        for t in [self._worker, self._prepare_task, *self._tasks]:
            if t:
                t.cancel()
        await self.server.stop()
        await self.llm.unload()
        if self.ollama:
            await asyncio.to_thread(self.ollama.stop)

    async def _prepare_llm(self) -> None:
        """Avvia Ollama se serve, scarica il modello se manca, manda la richiesta di riscaldamento."""
        try:
            if self.ollama:
                def progress(msg: str) -> None:
                    self.llm_state = msg
                    self._log("info", msg)
                await asyncio.to_thread(self.ollama.ensure, progress)
            if not self.llm.fake:
                self.llm_state = "riscaldamento del modello"
                self._log("info", f"Marv si sta svegliando ({self.llm.model})…")
                secs = await self.llm.warm_up(persona.warmup_messages())
                self._log("info", f"Marv è sveglio e pronto ({secs:.1f} s).")
            self.llm_state = "pronto"
        except asyncio.CancelledError:
            raise
        except (OllamaError, LLMError) as e:
            self.llm_state = f"errore: {e}"
            self._log("error", str(e))
        except Exception as e:
            self.llm_state = f"errore: {e}"
            self._log("error", f"Preparazione del modello fallita: {e}")
        finally:
            if self._ready:
                self._ready.set()

    async def wait_ready(self) -> None:
        if self._ready is not None:
            await self._ready.wait()

    def idle_seconds(self) -> float:
        """Secondi da quando non c'è più nessun client connesso (0 se ce n'è almeno uno)."""
        if self.server.connections or self._idle_since is None:
            return 0.0
        return time.time() - self._idle_since

    # ---- log / stato -----------------------------------------------------
    def _log(self, kind: str, text: str) -> None:
        if self.log_enabled and self.log_callback:
            try:
                self.log_callback(kind, text)
            except Exception:
                pass
        # inoltro alle shell EWA connesse (se non l'hanno silenziato)
        payload = protocol.log(kind, text)
        for conn in self._shells():
            if conn.id not in self._muted_shells:
                try:
                    asyncio.get_running_loop().create_task(conn.send(payload))
                except RuntimeError:
                    pass

    def _shells(self) -> list[Connection]:
        return [c for c in self.server.tools() if c.tool == protocol.SHELL]

    def _tool_conns(self) -> list[Connection]:
        return [c for c in self.server.tools() if c.tool != protocol.SHELL]

    def status(self) -> dict[str, Any]:
        return {
            "tools": [(c.tool, c.pid) for c in self._tool_conns()],
            "model": self.llm.model,
            "provider": self.llm.provider,
            "llm_state": self.llm_state,
            "ollama": ("avviato da EWA" if self.ollama and self.ollama.started_by_us
                       else "già attivo" if self.ollama else "-"),
            "uptime": int(time.time() - self.started_at),
            "notifications": self.notifications_sent,
            "cooldown": self.cooldown,
            "port": self.cfg.hub_port,
            "dark": len(self._dark),
            "notifier": self.notifier.backend,
        }

    async def run_action(self, name: str, **kwargs: Any) -> Any:
        """Esegue un'azione registrata in `actions` (estensione futura)."""
        if name not in self.actions:
            raise KeyError(f"azione sconosciuta: {name}")
        return await self.actions[name](self, **kwargs)

    # ---- connessioni -----------------------------------------------------
    @staticmethod
    def _name(conn: Connection) -> str:
        return "Terminale EWA" if conn.tool == protocol.SHELL else TOOLS.get(conn.tool, conn.tool)

    def _on_connect(self, conn: Connection) -> None:
        self._idle_since = None
        self._log("info", f"{self._name(conn)} connesso (pid {conn.pid})")
        if conn.tool == protocol.SHELL and self.llm_state != "pronto":
            # la shell si è persa i messaggi di avvio: dille a che punto siamo
            asyncio.get_running_loop().create_task(
                conn.send(protocol.log("info", f"Marv: {self.llm_state}…")))

    def _on_disconnect(self, conn: Connection) -> None:
        self._end_dark(conn.id)
        self._muted_shells.discard(conn.id)
        if not self.server.connections:
            self._idle_since = time.time()
        self._log("info", f"{self._name(conn)} disconnesso")

    async def _on_control(self, conn: Connection, msg: dict) -> None:
        cmd = msg.get("cmd")
        if cmd == "status":
            await conn.send(protocol.status(self.status()))
        elif cmd == "toast":
            text = str(msg.get("text") or "Questo è un toast di prova. Ti è andata bene.")
            await asyncio.to_thread(self.notifier.notify, text, "Prova")
        elif cmd == "log":
            if msg.get("on", True):
                self._muted_shells.discard(conn.id)
            else:
                self._muted_shells.add(conn.id)
        elif cmd == "shutdown":
            if msg.get("only_if_idle") and self._tool_conns():
                return  # ci sono ancora tool aperti: Marv resta
            if self.shutdown_requested:
                self.shutdown_requested.set()

    def _end_dark(self, conn_id: int) -> None:
        self._dark.discard(conn_id)
        self._history.pop(conn_id, None)

    # ---- eventi ----------------------------------------------------------
    async def handle_event(self, conn: Connection, ev: Event) -> None:
        ev.ts = time.time()  # orario di arrivo: base per cooldown e tempi relativi
        if ev.type not in EVENTS:
            self._log("error", f"evento sconosciuto ignorato: {ev.tool}/{ev.type}")
            return
        self._log("event", f"{TOOLS.get(ev.tool, ev.tool)} · {ev.type}: {persona.describe_event(ev)}")
        self.events.append(ev)

        if ev.type == "notepad.dark_on":
            self._dark.add(conn.id)
            self._history[conn.id] = []
            self._spawn(self._chat_turn(conn, persona.build_dark_open_instruction(ev.data.get("text", ""))))
            return
        if ev.type == "chat.user":
            text = str(ev.data.get("text", "")).strip()
            if text:
                self._spawn(self._chat_turn(conn, text))
            return
        if ev.type in ("notepad.dark_off", "tool.close"):
            self._end_dark(conn.id)
        if conn.id in self._dark and ev.tool == "notepad":
            return  # in Dark nessuna notifica dal Blocco note
        self._consider(ev)

    # ---- notifiche -------------------------------------------------------
    def _consider(self, ev: Event) -> None:
        if ev.type in NEVER_COMMENT:
            return
        if ev.type == "tool.close" and random.random() >= self.close_comment_probability:
            return
        now = time.time()
        if ev.priority == HIGH or now - self._last_notify >= self.cooldown:
            self._enqueue(ev)
            return
        # in cooldown: resta in sospeso, verrà commentato alla scadenza se ancora fresco
        self._pending = ev
        if self._pending_timer is None:
            delay = max(0.0, self._last_notify + self.cooldown - now)
            self._pending_timer = asyncio.get_running_loop().call_later(delay, self._fire_pending)

    def _fire_pending(self) -> None:
        self._pending_timer = None
        ev, self._pending = self._pending, None
        if ev is not None and time.time() - ev.ts < PENDING_MAX_AGE:
            self._enqueue(ev)

    def _enqueue(self, ev: Event) -> None:
        self._last_notify = time.time()
        self._pending = None  # superato da questo commento
        if self._pending_timer:
            self._pending_timer.cancel()
            self._pending_timer = None
        self._queue.put_nowait(ev)

    def _recent_before(self, ev: Event) -> list[Event]:
        out: list[Event] = []
        for e in self.events:
            if e is ev:
                break
            out.append(e)
        return out

    async def _notify_worker(self) -> None:
        """Un solo commento LLM in volo per volta; gli altri restano in coda."""
        while True:
            ev = await self._queue.get()
            try:
                await self._comment(ev)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # mai far morire il worker
                self._log("error", f"Marv non riesce a commentare: {e}")

    async def _comment(self, ev: Event) -> None:
        await self.wait_ready()
        messages = persona.build_notification_messages(ev, self._recent_before(ev), list(self.comments))
        try:
            raw = await self.llm.complete(messages)
        except LLMError as e:
            self._log("error", str(e))
            return
        text = persona.clean_comment(raw)
        if not text:
            return
        self.comments.append(text)
        self.notifications_sent += 1
        self._last_notify = time.time()
        self._log("marv", text)
        await asyncio.to_thread(self.notifier.notify, text, TOOLS.get(ev.tool, ev.tool))

    # ---- chat Dark -------------------------------------------------------
    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _chat_turn(self, conn: Connection, user_text: str) -> None:
        lock = self._chat_locks.setdefault(conn.id, asyncio.Lock())
        await self.wait_ready()
        async with lock:
            history = self._history.setdefault(conn.id, [])
            history.append({"role": "user", "content": user_text})
            memory = [e for e in self.events if e.type not in ("chat.user", "notepad.dark_on")]
            messages = persona.build_chat_messages(history, memory)
            reply = ""
            try:
                async for piece in self.llm.stream(messages):
                    reply += piece
                    await conn.send_chat_delta(piece)
                await conn.send_chat_end()
            except LLMError as e:
                history.pop()  # il turno fallito non entra nella cronologia
                self._log("error", str(e))
                await conn.send_chat_error(str(e))
                return
            except Exception as e:
                history.pop()
                self._log("error", f"chat: {e}")
                await conn.send_chat_error(f"Errore inatteso: {e}")
                return
            reply = reply.strip()
            if reply:
                history.append({"role": "assistant", "content": reply})
                self._log("chat", reply)
            del history[:-CHAT_HISTORY_MAX]
