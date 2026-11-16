"""Modello locale (Ollama), MarvHub in background, controllo dalla shell."""
import asyncio
import dataclasses
import socket
import sys
import time

import pytest

from ewa.core import launcher, ollama_service, protocol
from ewa.core.client import ToolClient
from ewa.core.config import OLLAMA_OPTIONS, load_config
from ewa.core.hub import MarvHub
from ewa.core.llm import MarvLLM
from ewa.core.ollama_service import OllamaError, OllamaService, norm_keep_alive


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeNotifier:
    backend = "finto"

    def __init__(self):
        self.sent = []

    def notify(self, text, title):
        self.sent.append((text, title))


def make_hub(**cfg_over):
    cfg = dataclasses.replace(load_config(), fake_llm=True, cooldown_seconds=0, hub_port=free_port(), **cfg_over)
    return MarvHub(cfg, notifier=FakeNotifier())


def wait_until(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


# ---- parametri del modello -------------------------------------------------
def test_ollama_is_default_with_marv_ollama_params(monkeypatch):
    for var in ("LLM_PROVIDER", "LLM_MODEL", "OLLAMA_KEEP_ALIVE"):
        monkeypatch.delenv(var, raising=False)
    cfg = load_config()
    assert cfg.is_ollama and cfg.llm_model == "gemma4:e2b"
    p = MarvLLM(cfg).ollama_params()
    assert p["options"] == {"temperature": 0.8, "top_p": 0.95, "top_k": 64, "repeat_penalty": 0.9,
                            "num_ctx": 8192, "num_predict": 512} == OLLAMA_OPTIONS
    assert p["think"] is False and p["keep_alive"] == -1 and p["model"] == "gemma4:e2b"
    assert MarvLLM(cfg).ollama_params(max_tokens=1)["options"]["num_predict"] == 1


def test_norm_keep_alive():
    assert norm_keep_alive("-1") == -1 and norm_keep_alive("0") == 0 and norm_keep_alive("30m") == "30m"


# ---- OllamaService ---------------------------------------------------------
def test_server_already_running_is_not_spawned(monkeypatch):
    monkeypatch.setattr(ollama_service, "is_running", lambda host, timeout=1.0: True)
    monkeypatch.setattr(ollama_service.subprocess, "Popen", lambda *a, **k: pytest.fail("non deve avviare"))
    svc = OllamaService("http://localhost:1", "gemma4:e2b")
    svc.ensure_server()
    assert not svc.started_by_us


def test_missing_ollama_readable_error(monkeypatch):
    monkeypatch.setattr(ollama_service, "is_running", lambda host, timeout=1.0: False)
    monkeypatch.setattr(ollama_service, "find_ollama", lambda: None)
    with pytest.raises(OllamaError, match="non è installato"):
        OllamaService("http://localhost:1", "gemma4:e2b").ensure_server()


def test_spawns_ollama_serve_and_waits(monkeypatch):
    calls = []
    states = iter([False, False, True])
    monkeypatch.setattr(ollama_service, "is_running", lambda host, timeout=1.0: next(states))
    monkeypatch.setattr(ollama_service, "find_ollama", lambda: "/opt/ollama")

    class P:
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, t=None):
            return 0

    def popen(cmd, **kw):
        calls.append((cmd, kw["env"]["OLLAMA_HOST"]))
        return P()

    monkeypatch.setattr(ollama_service.subprocess, "Popen", popen)
    svc = OllamaService("http://127.0.0.1:11999", "gemma4:e2b")
    svc.ensure_server()
    assert calls[0] == (["/opt/ollama", "serve"], "127.0.0.1:11999")
    assert svc.started_by_us
    svc.stop()
    assert calls[-1] == "terminate"


def test_autostart_disabled(monkeypatch):
    monkeypatch.setattr(ollama_service, "is_running", lambda host, timeout=1.0: False)
    with pytest.raises(OllamaError, match="OLLAMA_AUTOSTART"):
        OllamaService("http://localhost:1", "m", autostart=False).ensure_server()


def test_pull_when_model_missing(monkeypatch):
    class St:
        def __init__(self, c, t):
            self.completed, self.total = c, t

    class C:
        def list(self):
            return type("L", (), {"models": [type("M", (), {"model": "altro:latest"})()]})()

        def pull(self, model, stream):
            assert model == "gemma4:e2b"
            return [St(0, 100), St(50, 100), St(100, 100)]

    svc = OllamaService("http://x", "gemma4:e2b")
    monkeypatch.setattr(svc, "_client", lambda: C())
    msgs = []
    svc.ensure_model(msgs.append)
    assert any("50%" in m for m in msgs) and msgs[-1].endswith("scaricato.")
    svc.autopull = False
    with pytest.raises(OllamaError, match="ollama pull"):
        svc.ensure_model()


# ---- launcher ----------------------------------------------------------------
def test_launcher_commands(monkeypatch):
    assert launcher.command("calculator") == [sys.executable, "-m", "ewa.tools.calculator"]
    assert launcher.command("notepad", ["a.txt"])[-1] == "a.txt"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd = launcher.command("clock")
    assert cmd[0].endswith("Sveglie e orologio" + (".exe" if sys.platform == "win32" else ""))
    monkeypatch.setenv("EWA_HUB_AUTOSTART", "0")
    assert launcher.spawn_hub() is None


def test_toolclient_spawns_hub_when_missing(monkeypatch):
    monkeypatch.setenv("EWA_HUB_PORT", str(free_port()))
    spawned = []
    monkeypatch.setattr(launcher, "spawn_hub", lambda: spawned.append(1))
    c = ToolClient("calc")  # porta da config: autostart attivo
    assert wait_until(lambda: spawned, 3)
    c.close(send_close_event=False)
    explicit = ToolClient("calc", port=free_port())  # porta esplicita (test): niente autostart
    time.sleep(1.0)
    explicit.close(send_close_event=False)
    assert len(spawned) == 1


# ---- hub: preparazione, shell, controllo -----------------------------------
def test_comments_wait_for_warm_up():
    async def go():
        hub = make_hub()
        gate = asyncio.Event()

        async def slow_prepare():
            await gate.wait()
            hub.llm_state = "pronto"
            hub._ready.set()

        hub._prepare_llm = slow_prepare
        await hub.start()
        from ewa.core.protocol import Event
        await hub.handle_event(type("C", (), {"id": 1, "tool": "calc"})(),
                               Event("calc", "calc.result", {"expr": "1+1", "result": "2"}, priority="high"))
        await asyncio.sleep(0.2)
        assert hub.notifier.sent == []  # modello non ancora pronto: aspetta, non perde l'evento
        gate.set()
        for _ in range(100):
            if hub.notifier.sent:
                break
            await asyncio.sleep(0.02)
        await hub.stop()
        return hub.notifier.sent

    assert len(asyncio.run(go())) == 1


def test_shell_gets_logs_status_and_can_shutdown():
    async def go():
        hub = make_hub()
        await hub.start()
        port = hub.cfg.hub_port
        got = []
        shell = await asyncio.to_thread(ToolClient, protocol.SHELL, got.append, None, port)
        tool = await asyncio.to_thread(ToolClient, "calc", None, None, port)
        for _ in range(100):
            if len(hub._tool_conns()) == 1 and hub._shells():
                break
            await asyncio.sleep(0.02)
        tool.emit("calc.open")
        shell.send({"kind": "control", "cmd": "status"})
        shell.send({"kind": "control", "cmd": "toast", "text": "ciao"})
        for _ in range(150):
            if any(m.get("kind") == "status" for m in got) and hub.notifier.sent:
                break
            await asyncio.sleep(0.02)
        status = next(m["data"] for m in got if m.get("kind") == "status")
        # shutdown "solo se inattivo" ignorato finché c'è un tool aperto
        shell.send({"kind": "control", "cmd": "shutdown", "only_if_idle": True})
        await asyncio.sleep(0.3)
        ignored = not hub.shutdown_requested.is_set()
        tool.close(send_close_event=False)
        await asyncio.sleep(0.3)
        shell.send({"kind": "control", "cmd": "shutdown", "only_if_idle": True})
        await asyncio.wait_for(hub.shutdown_requested.wait(), 3)
        shell.close(send_close_event=False)
        await hub.stop()
        return got, status, ignored, hub.notifier.sent

    got, status, ignored, sent = asyncio.run(go())
    logs = [m["text"] for m in got if m.get("kind") == "log"]
    assert any("calc.open" in t for t in logs)
    assert status["tools"] == [["calc", status["tools"][0][1]]]  # la shell non conta come tool
    assert status["llm_state"] == "pronto"
    assert ("ciao", "Prova") in sent
    assert ignored


def test_idle_seconds():
    async def go():
        hub = make_hub()
        await hub.start()
        hub._idle_since = time.time() - 50
        idle = hub.idle_seconds()
        await hub.stop()
        return idle

    assert asyncio.run(go()) >= 50


# ---- modello vero (solo se Ollama e gemma4:e2b sono disponibili) -------------
def _real_model_available() -> bool:
    cfg = load_config()
    if not ollama_service.is_running(cfg.ollama_host):
        return False
    try:
        return OllamaService(cfg.ollama_host, cfg.llm_model).has_model()
    except Exception:
        return False


@pytest.mark.skipif(not _real_model_available(), reason="Ollama/gemma4:e2b non disponibile")
def test_real_gemma_warm_up_and_comment():
    from ewa.core import persona
    from ewa.core.protocol import Event

    async def go():
        llm = MarvLLM(dataclasses.replace(load_config(), fake_llm=False))
        await llm.warm_up(persona.warmup_messages())
        ev = Event("calc", "calc.result", {"expr": "2 + 2 =", "result": "4", "mode": "standard"})
        text = persona.clean_comment(await llm.complete(persona.build_notification_messages(ev, [], [])))
        chunks = [p async for p in llm.stream(persona.build_chat_messages(
            [{"role": "user", "content": "Ciao Marv, come stai?"}], []))]
        return text, "".join(chunks)

    comment, chat = asyncio.run(go())
    assert 0 < len(comment.split()) <= 30
    assert chat.strip()
