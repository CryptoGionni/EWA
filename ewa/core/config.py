"""Configurazione EWA letta da .env.

Cerca il file .env, senza sovrascrivere valori già impostati, in quest'ordine:
variabili d'ambiente, cartella dell'exe (se installato), %APPDATA%/EWA/.env,
root del progetto, cartella corrente.
"""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_files() -> list[Path]:
    files = []
    if getattr(sys, "frozen", False):
        files.append(Path(sys.executable).resolve().parent / ".env")
    appdata = os.getenv("APPDATA")
    if appdata:
        files.append(Path(appdata) / "EWA" / ".env")
    files += [PROJECT_ROOT / ".env", Path.cwd() / ".env"]
    return files


for _f in _env_files():
    if _f.is_file():
        load_dotenv(_f)


def _get(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    # consente commenti inline tipo "low   # spiegazione"
    return value.split("#", 1)[0].strip() if value else default


def _float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return _get(name, "1" if default else "0").lower() in ("1", "true", "yes", "si", "sì")


# Parametri di generazione per gemma4:e2b su Ollama (da marv_ollama.py)
OLLAMA_OPTIONS = {
    "temperature": 0.8,
    "top_p": 0.95,
    "top_k": 64,
    "repeat_penalty": 0.9,
    "num_ctx": 8192,
    "num_predict": 512,
}


@dataclass(frozen=True)
class Config:
    llm_provider: str            # "ollama" (default, locale) | "openai" (Groq o altro endpoint compatibile)
    llm_model: str
    # Ollama
    ollama_host: str
    ollama_options: dict = field(default_factory=dict)
    ollama_think: bool = False
    ollama_keep_alive: str = "-1"   # -1 = resta in memoria finché l'hub è attivo
    ollama_autostart: bool = True   # avvia `ollama serve` se non risponde
    ollama_autopull: bool = True    # scarica il modello se manca
    # endpoint compatibile OpenAI (Groq)
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_reasoning_effort: str = ""
    llm_max_tokens: int = 300
    llm_temperature: float = 0.8
    # Marv
    cooldown_seconds: float = 30
    typing_debounce: float = 4
    fake_llm: bool = False
    # Hub
    hub_host: str = "127.0.0.1"
    hub_port: int = 47474
    hub_idle_exit: float = 600   # MarvHub si chiude dopo N secondi senza nessun client

    @property
    def is_ollama(self) -> bool:
        return self.llm_provider == "ollama"


def load_config() -> Config:
    provider = _get("LLM_PROVIDER", "ollama").lower()
    if provider not in ("ollama", "openai"):
        provider = "ollama"
    default_model = "gemma4:e2b" if provider == "ollama" else "openai/gpt-oss-120b"
    options = dict(OLLAMA_OPTIONS)
    for key, env in (("temperature", "OLLAMA_TEMPERATURE"), ("num_ctx", "OLLAMA_NUM_CTX"),
                     ("num_predict", "OLLAMA_NUM_PREDICT")):
        if _get(env):
            options[key] = type(OLLAMA_OPTIONS[key])(_float(env, OLLAMA_OPTIONS[key]))
    return Config(
        llm_provider=provider,
        llm_model=_get("LLM_MODEL", default_model),
        ollama_host=_get("OLLAMA_HOST", "http://localhost:11434"),
        ollama_options=options,
        ollama_think=_bool("OLLAMA_THINK", False),
        ollama_keep_alive=_get("OLLAMA_KEEP_ALIVE", "-1"),
        ollama_autostart=_bool("OLLAMA_AUTOSTART", True),
        ollama_autopull=_bool("OLLAMA_AUTOPULL", True),
        llm_base_url=_get("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        llm_api_key=_get("LLM_API_KEY") or _get("GROQ_API") or _get("GROQ_API_KEY"),
        llm_reasoning_effort=_get("LLM_REASONING_EFFORT", "low"),
        llm_max_tokens=int(_float("LLM_MAX_TOKENS", 300)),
        llm_temperature=_float("LLM_TEMPERATURE", 0.8),
        cooldown_seconds=_float("MARV_COOLDOWN_SECONDS", 30),
        typing_debounce=_float("MARV_TYPING_DEBOUNCE", 4),
        fake_llm=_bool("MARV_FAKE_LLM", False),
        hub_host="127.0.0.1",
        hub_port=int(_float("EWA_HUB_PORT", 47474)),
        hub_idle_exit=_float("EWA_HUB_IDLE_EXIT", 600),
    )
