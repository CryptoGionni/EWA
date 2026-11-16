"""Configurazione EWA letta da .env (nella root del progetto o nella cwd)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()  # anche dalla cwd, senza sovrascrivere


def _get(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    # consente commenti inline tipo "low   # spiegazione"
    return value.split("#", 1)[0].strip() if value else default


def _float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_reasoning_effort: str
    llm_max_tokens: int
    llm_temperature: float
    cooldown_seconds: float
    typing_debounce: float
    fake_llm: bool
    hub_host: str
    hub_port: int


def load_config() -> Config:
    return Config(
        llm_base_url=_get("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        llm_api_key=_get("LLM_API_KEY") or _get("GROQ_API") or _get("GROQ_API_KEY"),
        llm_model=_get("LLM_MODEL", "openai/gpt-oss-120b"),
        llm_reasoning_effort=_get("LLM_REASONING_EFFORT", "low"),
        llm_max_tokens=int(_float("LLM_MAX_TOKENS", 300)),
        llm_temperature=_float("LLM_TEMPERATURE", 0.8),
        cooldown_seconds=_float("MARV_COOLDOWN_SECONDS", 30),
        typing_debounce=_float("MARV_TYPING_DEBOUNCE", 4),
        fake_llm=_get("MARV_FAKE_LLM", "0") in ("1", "true", "yes"),
        hub_host="127.0.0.1",
        hub_port=int(_float("EWA_HUB_PORT", 47474)),
    )
