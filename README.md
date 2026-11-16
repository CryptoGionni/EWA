# EWA — Everything in Windows but AI

Quattro app di Windows 10 (Calcolatrice, Sveglie e orologio, Fotocamera, Blocco note) rifatte in PySide6, con un ospite indesiderato: **Marv**, un chatbot scocciato e sarcastico che le osserva mentre le usi e commenta con una notifica di Windows. Nel Blocco note c'è anche la modalità **Dark**, dove Marv ti scrive per primo e puoi rispondergli.

## Setup su Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # poi apri .env e inserisci la chiave API
python ewa.py
```

Serve Python 3.11 o superiore. Per provare tutto senza rete e senza chiave: imposta `MARV_FAKE_LLM=1` nel `.env` (Marv risponde con battute predefinite).

## Avvio e comandi della shell

`python ewa.py` apre una shell colorata (`ewa> `) che ospita l'hub di Marv. I tool si aprono da lì, ciascuno in un processo separato.

| Comando | Effetto |
|---|---|
| `calc` · `calcolatrice` | apre la Calcolatrice |
| `timer` · `orologio` · `sveglie` | apre Sveglie e orologio |
| `camera` · `fotocamera` | apre la Fotocamera |
| `notepad [file]` · `blocco [file]` | apre il Blocco note, opzionalmente con un file |
| `status` | tool connessi, modello, provider, notifiche inviate, cooldown |
| `log on` / `log off` | mostra o nasconde il log colorato di eventi e commenti |
| `toast [testo]` | notifica di prova |
| `help` · `aiuto` | elenco comandi |
| `exit` · `esci` | chiude i tool e la shell (Ctrl+C fa lo stesso, con una battuta di Marv) |

Se la porta dell'hub è occupata c'è già un'altra shell EWA aperta: chiudila oppure cambia `EWA_HUB_PORT`. I tool funzionano anche senza hub (semplicemente nessuno li commenta). L'output dei tool figli finisce nel file `ewa-tools.log` nella cartella temporanea (il percorso è in `status`).

## Provider e modelli

Qualsiasi endpoint compatibile OpenAI; si cambia solo il `.env`.

| Provider | `LLM_BASE_URL` | `LLM_MODEL` | Note |
|---|---|---|---|
| Groq (default) | `https://api.groq.com/openai/v1` | `openai/gpt-oss-120b` | con `LLM_REASONING_EFFORT=low`: qualità migliore |
| Groq | idem | `openai/gpt-oss-20b` | più rapido ed economico |
| Ollama (locale) | `http://localhost:11434/v1` | `qwen3:8b` oppure `gemma3:12b` | `LLM_API_KEY=ollama`; i blocchi `<think>` di qwen3 vengono rimossi |

`LLM_REASONING_EFFORT` viene inviato solo ai modelli `gpt-oss`. Altre variabili: `MARV_COOLDOWN_SECONDS` (pausa tra notifiche, default 30; gli eventi ad alta priorità la scavalcano), `MARV_TYPING_DEBOUNCE`, `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`.

## Architettura

```
 Calcolatrice ─┐
 Sveglie       ├─ ToolClient ──TCP localhost, JSON lines──▶  HubServer (bus.py)
 Fotocamera    │   (eventi: calc.result, timer.start, ...)        │
 Blocco note ──┘                                                  ▼
                                                      MarvHub (hub.py)
                                           memoria condivisa · cooldown · priorità
                                                       │             │
                                          persona.py ──┤             └─ Dark: chat in streaming
                                          llm.py (OpenAI-compatibile)   (chat.delta/end ▶ Blocco note)
                                                       ▼
                                              Notifier (notifier.py)
                                        toast Windows  /  fallback terminale
```

- I tool non hanno UI per Marv: emettono solo eventi del catalogo in `ewa/core/protocol.py`.
- L'hub tiene gli ultimi ~30 eventi di tutti i tool e le ultime ~8 battute di Marv (per non ripetersi), e passa tutto al modello, così Marv può collegare ciò che fai nei diversi tool.
- Un solo commento in volo per volta; gli eventi saltati per il cooldown restano in memoria e il più recente viene commentato alla scadenza, se ha meno di 60 secondi.
- `MarvHub.actions` è un registry vuoto: il punto dove innestare in futuro azioni agentiche.

## Aggiungere un nuovo tool

1. Aggiungi il tool e i suoi eventi al catalogo in `ewa/core/protocol.py` (`TOOLS`, `EVENTS`) e, per renderli leggibili a Marv, una riga in `describe_event` di `ewa/core/persona.py`.
2. Crea `ewa/tools/<nome>/` con un `__main__.py` che usa `ewa.ui.win10.run_tool("<tool>", build)` ed emette eventi con `ToolClient("<tool>").emit(tipo, dati)`.
3. Registra il comando in `TOOL_COMMANDS` in `ewa.py`.
4. Aggiungi test in `tests/test_<nome>.py`.

## Privacy

Con un provider remoto (Groq) all'LLM vengono inviati la descrizione testuale degli eventi (espressioni calcolate, durata dei timer, ecc.), **l'estratto del testo scritto nel Blocco note** e, in modalità Dark, il testo della nota e la conversazione. La Fotocamera invia solo eventi (scatti, durata video), mai immagini. Per tenere tutto sul tuo PC usa Ollama in locale.

## Test

```powershell
python -m pytest
```
