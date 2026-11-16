"""MarvLLM: Ollama locale (default) o endpoint compatibile OpenAI (Groq), con modalità finta offline."""
from __future__ import annotations

import asyncio
import itertools
import re
import time
from typing import AsyncIterator

from .config import Config, load_config
from .ollama_service import norm_keep_alive

TIMEOUT_SECONDS = 20
OLLAMA_TIMEOUT = 180  # il primo caricamento del modello su CPU può essere lento

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_THINK_OPEN, _THINK_CLOSE = "<think>", "</think>"


class LLMError(RuntimeError):
    """Errore leggibile (chiave mancante, rete, ecc.)."""


def strip_think(text: str) -> str:
    """Rimuove i blocchi <think>...</think> (qwen3 via Ollama)."""
    text = _THINK_RE.sub("", text)
    # blocco aperto e mai chiuso (risposta troncata): scarta il resto
    i = text.lower().find(_THINK_OPEN)
    if i != -1:
        text = text[:i]
    return text.strip()


class ThinkFilter:
    """Filtro incrementale per <think>...</think> anche con tag spezzati tra chunk."""

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False
        self._lstrip = False

    @staticmethod
    def _partial(buf: str, tag: str) -> int:
        """Lunghezza del suffisso di buf che potrebbe essere l'inizio di tag."""
        for n in range(min(len(tag) - 1, len(buf)), 0, -1):
            if tag.startswith(buf[-n:].lower()):
                return n
        return 0

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out = ""
        while True:
            low = self._buf.lower()
            if not self._inside:
                i = low.find(_THINK_OPEN)
                if i != -1:
                    out += self._buf[:i]
                    self._buf = self._buf[i + len(_THINK_OPEN):]
                    self._inside = True
                    continue
                keep = self._partial(self._buf, _THINK_OPEN)
                out += self._buf[:len(self._buf) - keep]
                self._buf = self._buf[len(self._buf) - keep:]
                break
            j = low.find(_THINK_CLOSE)
            if j != -1:
                self._buf = self._buf[j + len(_THINK_CLOSE):]
                self._inside = False
                self._lstrip = True
                continue
            keep = self._partial(self._buf, _THINK_CLOSE)
            self._buf = self._buf[len(self._buf) - keep:] if keep else ""
            break
        if self._lstrip and out:
            out = out.lstrip()
            self._lstrip = not out
        return out

    def flush(self) -> str:
        out = "" if self._inside else self._buf
        self._buf = ""
        return out.lstrip() if self._lstrip else out


# Risposte finte (MARV_FAKE_LLM=1)
FAKE_REPLIES = [
    "Ancora non sai fare queste cose a mente?",
    "Che sforzo titanico, davvero. Mi commuovo.",
    "Wow, e io che pensavo di aver visto tutto.",
    "Spero almeno che ti sia servito a qualcosa.",
    "Certo, ti aspettavo proprio per questo.",
    "Bravo. Ora però smettila di guardarmi.",
]


class MarvLLM:
    """Due backend: Ollama locale (default, API nativa per usare options/think/keep_alive)
    oppure un endpoint compatibile OpenAI (Groq). Più la modalità finta offline."""

    def __init__(self, config: Config | None = None):
        self.cfg = config or load_config()
        self._client = None
        self._fake_i = itertools.count()

    @property
    def fake(self) -> bool:
        return self.cfg.fake_llm

    @property
    def model(self) -> str:
        return "finto (MARV_FAKE_LLM)" if self.fake else self.cfg.llm_model

    @property
    def provider(self) -> str:
        if self.fake:
            return "(nessuno, modalità finta)"
        if self.cfg.is_ollama:
            return f"Ollama locale ({self.cfg.ollama_host})"
        return self.cfg.llm_base_url.split("//")[-1].split("/")[0]

    # ---- client ---------------------------------------------------------
    def _get_client(self):
        if self._client is None:
            if self.cfg.is_ollama:
                import ollama

                self._client = ollama.AsyncClient(host=self.cfg.ollama_host, timeout=OLLAMA_TIMEOUT)
            else:
                if not self.cfg.llm_api_key:
                    raise LLMError("Chiave API mancante: imposta LLM_API_KEY (o GROQ_API) nel file .env, "
                                   "oppure usa LLM_PROVIDER=ollama per il modello locale.")
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(base_url=self.cfg.llm_base_url, api_key=self.cfg.llm_api_key,
                                           timeout=TIMEOUT_SECONDS, max_retries=1)
        return self._client

    def _params(self, max_tokens: int | None) -> dict:
        p = {"model": self.cfg.llm_model, "temperature": self.cfg.llm_temperature,
             "max_tokens": max_tokens or self.cfg.llm_max_tokens}
        if self.cfg.llm_reasoning_effort and "gpt-oss" in self.cfg.llm_model.lower():
            p["reasoning_effort"] = self.cfg.llm_reasoning_effort
        return p

    def ollama_params(self, max_tokens: int | None = None) -> dict:
        """Argomenti per ollama.chat (parametri di marv_ollama.py)."""
        options = dict(self.cfg.ollama_options)
        if max_tokens:
            options["num_predict"] = max_tokens
        return {"model": self.cfg.llm_model, "think": self.cfg.ollama_think, "options": options,
                "keep_alive": norm_keep_alive(self.cfg.ollama_keep_alive)}

    def _fake_text(self) -> str:
        return FAKE_REPLIES[next(self._fake_i) % len(FAKE_REPLIES)]

    # ---- chiamate -------------------------------------------------------
    async def complete(self, messages: list[dict], max_tokens: int | None = None) -> str:
        if self.fake:
            await asyncio.sleep(0.01)
            return self._fake_text()
        client = self._get_client()
        try:
            if self.cfg.is_ollama:
                resp = await client.chat(messages=messages, **self.ollama_params(max_tokens))
                return strip_think(resp.message.content or "")
            resp = await client.chat.completions.create(messages=messages, **self._params(max_tokens))
        except Exception as e:
            raise LLMError(f"Chiamata al modello fallita: {e}") from e
        return strip_think(resp.choices[0].message.content or "")

    async def _raw_stream(self, messages: list[dict], max_tokens: int | None) -> AsyncIterator[str]:
        client = self._get_client()
        if self.cfg.is_ollama:
            async for chunk in await client.chat(messages=messages, stream=True, **self.ollama_params(max_tokens)):
                # solo il contenuto finale: l'eventuale campo "thinking" viene ignorato
                yield chunk.message.content or ""
            return
        stream = await client.chat.completions.create(messages=messages, stream=True, **self._params(max_tokens))
        async for chunk in stream:
            if chunk.choices:
                yield chunk.choices[0].delta.content or ""

    async def stream(self, messages: list[dict], max_tokens: int | None = None) -> AsyncIterator[str]:
        if self.fake:
            words = self._fake_text().split(" ")
            for i, w in enumerate(words):
                await asyncio.sleep(0.005)
                yield w + (" " if i < len(words) - 1 else "")
            return
        flt = ThinkFilter()
        try:
            async for raw in self._raw_stream(messages, max_tokens):
                piece = flt.feed(raw)
                if piece:
                    yield piece
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Chiamata al modello fallita: {e}") from e
        tail = flt.flush()
        if tail:
            yield tail

    async def warm_up(self, messages: list[dict]) -> float:
        """Richiesta fittizia: carica il modello in memoria (e, con Ollama, mette in
        cache il prompt di sistema di Marv). Restituisce i secondi impiegati."""
        t0 = time.monotonic()
        if not self.fake:
            await self.complete(messages, max_tokens=1)
        return time.monotonic() - t0

    async def unload(self) -> None:
        """Libera la memoria del modello (solo Ollama). Errori ignorati."""
        if self.fake or not self.cfg.is_ollama or self._client is None:
            return
        try:
            await self._client.chat(model=self.cfg.llm_model, messages=[], keep_alive=0)
        except Exception:
            pass
