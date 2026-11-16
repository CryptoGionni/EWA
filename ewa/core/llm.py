"""MarvLLM: client OpenAI-compatibile (Groq, Ollama, ...) con modalità finta offline."""
from __future__ import annotations

import asyncio
import itertools
import re
from typing import AsyncIterator

from .config import Config, load_config

TIMEOUT_SECONDS = 20

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

    def _get_client(self):
        if self._client is None:
            if not self.cfg.llm_api_key:
                raise LLMError("Chiave API mancante: imposta LLM_API_KEY (o GROQ_API) nel file .env, "
                               "oppure usa MARV_FAKE_LLM=1 per provare senza rete.")
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

    def _fake_text(self) -> str:
        return FAKE_REPLIES[next(self._fake_i) % len(FAKE_REPLIES)]

    async def complete(self, messages: list[dict], max_tokens: int | None = None) -> str:
        if self.fake:
            await asyncio.sleep(0.01)
            return self._fake_text()
        client = self._get_client()
        try:
            resp = await client.chat.completions.create(messages=messages, **self._params(max_tokens))
        except Exception as e:
            raise LLMError(f"Chiamata al modello fallita: {e}") from e
        return strip_think(resp.choices[0].message.content or "")

    async def stream(self, messages: list[dict], max_tokens: int | None = None) -> AsyncIterator[str]:
        if self.fake:
            words = self._fake_text().split(" ")
            for i, w in enumerate(words):
                await asyncio.sleep(0.005)
                yield w + (" " if i < len(words) - 1 else "")
            return
        client = self._get_client()
        flt = ThinkFilter()
        try:
            stream = await client.chat.completions.create(messages=messages, stream=True,
                                                          **self._params(max_tokens))
            async for chunk in stream:
                if not chunk.choices:
                    continue
                piece = flt.feed(chunk.choices[0].delta.content or "")
                if piece:
                    yield piece
        except Exception as e:
            raise LLMError(f"Chiamata al modello fallita: {e}") from e
        tail = flt.flush()
        if tail:
            yield tail
