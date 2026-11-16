"""Test del core Marv: hub, cooldown, chat Dark, filtro <think>, prompt."""
import asyncio
import dataclasses
import socket
import threading
import time

import pytest

from ewa.core import persona
from ewa.core.bus import HubPortInUse, HubServer
from ewa.core.client import ToolClient
from ewa.core.config import load_config
from ewa.core.hub import MarvHub
from ewa.core.llm import MarvLLM, ThinkFilter, strip_think
from ewa.core.protocol import Event


class FakeNotifier:
    backend = "finto"

    def __init__(self):
        self.calls = []

    def notify(self, text, tool_title=""):
        self.calls.append((text, tool_title))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_hub(cooldown=30.0):
    cfg = dataclasses.replace(load_config(), fake_llm=True, cooldown_seconds=cooldown, hub_port=free_port())
    notifier = FakeNotifier()
    return MarvHub(cfg, notifier=notifier), notifier


class FakeConn:
    id = 1
    tool = "calc"
    pid = 1
    alive = True

    async def send(self, payload):
        return True

    async def send_chat_delta(self, t):
        return True

    send_chat_end = send_chat_error = send_chat_delta


def run(coro):
    return asyncio.run(coro)


async def settle(t=0.15):
    await asyncio.sleep(t)


def calc_ev(expr="2+2", res="4", **kw):
    return Event("calc", "calc.result", {"expr": expr, "result": res, "mode": "standard"}, **kw)


# ---- hub: notifiche ----------------------------------------------------------
def test_event_gives_one_notification():
    async def go():
        hub, n = make_hub()
        await hub.start()
        try:
            await hub.handle_event(FakeConn(), calc_ev())
            await settle()
            assert len(n.calls) == 1
            assert n.calls[0][1] == "Calcolatrice"
        finally:
            await hub.stop()
    run(go())


def test_cooldown_and_pending_recovered():
    async def go():
        hub, n = make_hub(cooldown=0.5)
        await hub.start()
        try:
            c = FakeConn()
            await hub.handle_event(c, calc_ev("1+1", "2"))
            await settle()
            assert len(n.calls) == 1
            await hub.handle_event(c, calc_ev("2+2", "4"))
            await hub.handle_event(c, calc_ev("3+3", "6"))
            await settle()
            assert len(n.calls) == 1  # in cooldown
            await asyncio.sleep(0.6)
            assert len(n.calls) == 2  # uno solo, quello in sospeso
            assert len(hub.events) == 3  # tutti restano in memoria
        finally:
            await hub.stop()
    run(go())


def test_high_bypasses_cooldown_and_is_not_lost():
    async def go():
        hub, n = make_hub(cooldown=60)
        await hub.start()
        try:
            c = FakeConn()
            await hub.handle_event(c, calc_ev())
            await hub.handle_event(c, Event("clock", "timer.start", {"seconds": 2400, "label": ""}, priority="high"))
            await hub.handle_event(c, Event("clock", "timer.done", {"seconds": 2400, "label": ""}, priority="high"))
            await settle(0.4)
            assert len(n.calls) == 3
        finally:
            await hub.stop()
    run(go())


def test_never_commented_events():
    async def go():
        hub, n = make_hub()
        await hub.start()
        try:
            hub.close_comment_probability = 0
            await hub.handle_event(FakeConn(), Event("notepad", "notepad.dark_off"))
            await hub.handle_event(FakeConn(), Event("calc", "tool.close"))
            await settle()
            assert n.calls == []
        finally:
            await hub.stop()
    run(go())


# ---- end-to-end: chat Dark con ToolClient reale --------------------------------
def test_dark_chat_end_to_end():
    async def go():
        hub, n = make_hub()
        await hub.start()
        port = hub.cfg.hub_port
        got: list[list[dict]] = [[], []]

        def mk(i, tool):
            return ToolClient(tool, on_message=got[i].append, port=port)

        loop = asyncio.get_running_loop()
        notepad = await loop.run_in_executor(None, mk, 0, "notepad")
        other = await loop.run_in_executor(None, mk, 1, "notepad")
        try:
            for _ in range(60):
                if len(hub.server.tools()) == 2:
                    break
                await asyncio.sleep(0.05)
            notepad.emit("notepad.open", {"filename": ""})
            await settle(0.2)
            base = len(n.calls)
            notepad.emit("notepad.dark_on", {"text": "ciao"})
            await settle(0.4)
            kinds = [m["kind"] for m in got[0]]
            assert "chat.delta" in kinds and kinds[-1] == "chat.end"
            assert got[1] == []  # l'altra connessione non riceve nulla
            # in Dark: nessuna notifica notepad
            notepad.emit("notepad.typing", {"text_excerpt": "x", "chars": 1, "filename": ""})
            notepad.emit("notepad.save", {"filename": "a.txt", "chars": 1})
            await settle(0.2)
            assert len(n.calls) == base
            got[0].clear()
            notepad.emit("chat.user", {"text": "come stai?"})
            await settle(0.4)
            kinds = [m["kind"] for m in got[0]]
            assert "chat.delta" in kinds and kinds[-1] == "chat.end"
            assert got[1] == []
            # cronologia: apertura + risposta + utente + risposta
            assert len(next(iter(hub._history.values()))) == 4
            # uscita da Dark: le notifiche tornano
            notepad.emit("notepad.dark_off")
            await settle(0.1)
            assert hub._dark == set()
        finally:
            await loop.run_in_executor(None, notepad.close, False)
            await loop.run_in_executor(None, other.close, False)
            await hub.stop()
    run(go())


def test_port_in_use_clear_error():
    async def go():
        port = free_port()
        a = HubServer(lambda c, e: None, port=port)
        await a.start()
        try:
            with pytest.raises(HubPortInUse, match="EWA_HUB_PORT"):
                await HubServer(lambda c, e: None, port=port).start()
        finally:
            await a.stop()
    run(go())


# ---- llm ----------------------------------------------------------------------
def test_strip_think():
    assert strip_think("<think>ragiono\nun po'</think>\n\nCiao.") == "Ciao."
    assert strip_think("Ciao <think>boh") == "Ciao"


def test_think_filter_streaming_split_tags():
    text = "<think>pensiero lungo</think>\nRisposta finale."
    for size in (1, 2, 3, 5, 100):
        f = ThinkFilter()
        out = "".join(f.feed(text[i:i + size]) for i in range(0, len(text), size)) + f.flush()
        assert out == "Risposta finale.", (size, out)


def test_fake_llm_stream_and_complete():
    async def go():
        llm = MarvLLM(dataclasses.replace(load_config(), fake_llm=True))
        assert await llm.complete([]) 
        parts = [p async for p in llm.stream([])]
        assert len(parts) > 1
    run(go())


def test_missing_api_key_readable_error():
    from ewa.core.llm import LLMError

    async def go():
        llm = MarvLLM(dataclasses.replace(load_config(), llm_provider="openai", fake_llm=False, llm_api_key=""))
        with pytest.raises(LLMError, match="LLM_API_KEY"):
            await llm.complete([{"role": "user", "content": "x"}])
    run(go())


def test_reasoning_effort_only_for_gpt_oss():
    base = dataclasses.replace(load_config(), llm_reasoning_effort="low")
    assert MarvLLM(dataclasses.replace(base, llm_model="openai/gpt-oss-120b"))._params(None)["reasoning_effort"] == "low"
    assert "reasoning_effort" not in MarvLLM(dataclasses.replace(base, llm_model="qwen3:8b"))._params(None)


# ---- persona ------------------------------------------------------------------
def test_notification_prompt_contains_event_and_memory():
    now = 1000.0
    old = Event("calc", "calc.result", {"expr": "7*6", "result": "42", "mode": "standard"}, ts=now - 120)
    cur = Event("clock", "timer.start", {"seconds": 2400, "label": ""}, ts=now)
    msgs = persona.build_notification_messages(cur, [old], ["Che noia."], now=now)
    assert msgs[0]["role"] == "system" and "18 parole" in msgs[0]["content"]
    last = msgs[-1]["content"]
    assert "40 minuti" in last
    assert "7*6 = 42" in last and "2 minuti fa" in last
    assert "Che noia." in last
    assert msgs[-1]["role"] == "user"


def test_chat_prompt_has_memory_and_history():
    now = 1000.0
    ev = Event("camera", "camera.photo", {"count": 3}, ts=now - 30)
    hist = [{"role": "user", "content": "ciao"}]
    msgs = persona.build_chat_messages(hist, [ev], now=now)
    assert "foto" in msgs[0]["content"] and "markdown" in msgs[0]["content"]
    assert msgs[-1] == hist[0]
    assert "vuota" in persona.build_dark_open_instruction("")
    assert "bella giornata" in persona.build_dark_open_instruction("bella giornata")


def test_clean_comment():
    assert persona.clean_comment('Marv: "Che bello 😀"') == "Che bello"
    assert persona.humanize_seconds(5400) == "1 ora e 30 minuti"


def test_agent_actions_registry_empty():
    hub, _ = make_hub()
    assert hub.actions == {}
