# EWA — Everything in Windows but AI · Implementation Plan

## Decisioni
| Tema | Scelta |
|---|---|
| UI | **PySide6**, stile Windows 10 (palette, Segoe UI / Segoe MDL2 Assets, QSS), lingua **italiano** |
| Avvio | `python ewa.py` → shell interattiva colorata (`calc`, `timer`, `camera`, `notepad`, `status`, `help`, `exit`) che ospita il **MarvHub** |
| Processi | ogni tool è un processo separato (`python -m ewa.tools.<nome>`), invia eventi all'hub via TCP localhost (JSON lines) |
| Marv | **unico cervello** nell'hub: memoria condivisa tra tool, cooldown, scelta di cosa commentare. Punto di innesto futuro per i tool-call agentici |
| Output Marv | **solo toast Windows** (`windows-toasts`), fallback stampa colorata se non-Windows. Eccezione: Blocco note in modalità *Dark* |
| LLM | client **OpenAI-compatible** (`openai` SDK) → Groq o Ollama cambiando solo `.env`. Default `openai/gpt-oss-120b`, `reasoning_effort=low`, `max_tokens≈300`, risposta ≤ 20 parole |
| Frequenza | event-driven, cooldown globale 30 s (configurabile); eventi `priority: high` lo scavalcano; debounce digitazione 4 s |
| Fotocamera | **solo eventi** (nessuna immagine inviata) |
| Chat Notepad | voce di menu **"Dark"** visibile in barra → tema scuro, Marv scrive per primo; utente risponde, **doppio Invio** = invio |

## Struttura
```
EWA/
  ewa.py                     # entry: shell colorata + avvio hub
  requirements.txt  .env.example  README.md
  ewa/
    core/
      colors.py              # ANSI + abilitazione VT su Windows (da marv.py)
      config.py              # carica .env (provider, modello, cooldown, porta)
      protocol.py            # ★ contratto: Event, messaggi hub→tool, catalogo eventi
      bus.py                 # HubServer (asyncio) + ToolClient (thread, riconnessione, no-op se hub assente)
      llm.py                 # MarvLLM: complete(messages) / stream(messages)
      persona.py             # system prompt Marv + few-shot "notifica" e "chat"
      hub.py                 # MarvHub: memoria eventi, rate-limit, prompt contestuale, dispatch
      notifier.py            # toast Win10 / fallback console
    ui/
      win10.py               # ★ palette, font, QSS base, helper (icone MDL2, finestre)
    tools/
      calculator/  clock/  camera/  notepad/    # ognuno: __main__.py + window.py (+ logica)
  tests/
```
★ = scritto da me in Fase 0, poi congelato.

## Contratto (protocol.py)
- Tool → hub: `{"v":1,"tool":"calc","type":"calc.result","data":{...},"priority":"normal|high","ts":...}`
- Hub → tool (solo notepad): `chat.delta {text}`, `chat.end`, `chat.error {msg}`
- Catalogo eventi:
  - **calc**: `calc.open`, `calc.result {expr, result, mode}`, `calc.error {expr}`, `calc.mode {standard|scientifica}`
  - **clock**: `timer.start {seconds,label}` (high), `timer.progress {elapsed,remaining,pct}` (al 25/50/75% e ogni ~10 min), `timer.pause`, `timer.reset`, `timer.done` (high), `stopwatch.start/lap/stop {elapsed,laps}`
  - **camera**: `camera.open`, `camera.photo {count}`, `camera.video_start`, `camera.video_stop {seconds}`, `camera.switch`, `camera.idle {seconds}` (inquadratura aperta senza scatti ≥60 s)
  - **notepad**: `notepad.open`, `notepad.typing {text_excerpt, chars}` (debounced), `notepad.save {filename}`, `notepad.dark_on {text}` (high), `notepad.dark_off`, `chat.user {text}` (high)

## Task

### Fase 0 — Fondamenta (io, sequenziale)
Scheletro repo, `protocol.py`, `ui/win10.py`, interfacce `ToolClient` (stub funzionante), `requirements.txt`, `.env.example`.

### Fase 1 — In parallelo (subagenti economici)
| # | Task | Dipende da | Done quando |
|---|---|---|---|
| A | **Core Marv**: `bus.py`, `llm.py`, `persona.py`, `notifier.py`, `hub.py`, `ewa.py` (shell colorata, avvio/arresto tool, log eventi colorato) | protocol | test con LLM finto: evento → 1 notifica, cooldown rispettato, chat in streaming |
| B | **Calcolatrice** standard + scientifica (layout Win10, cronologia, motore di calcolo sicuro senza `eval`, tastiera) | win10, protocol | test unitari motore + screenshot offscreen |
| C | **Sveglie e orologio**: schede complete, **Timer** (anello progresso, preset, più timer) e **Cronometro** (giri) funzionanti; Sveglia/Orologio mondiale solo grafica | win10, protocol | emette eventi temporizzati corretti (test con clock accelerato) |
| D | **Fotocamera** (QtMultimedia): live, foto/video, cambio camera, timer scatto, salvataggio in `Immagini/Rullino` | win10, protocol | funziona anche senza webcam (schermata "Non riusciamo a trovare la fotocamera") |
| E | **Blocco note**: menu completi (File/Modifica/Formato/Visualizza/?), apri/salva, trova/sostituisci, barra di stato, **voce "Dark"** + modalità chat (streaming Marv nel testo, doppio Invio, testo Marv non modificabile) | win10, protocol | test chat con hub finto |

### Fase 2 — Integrazione (io)
End-to-end con hub reale e Groq, tuning prompt (brevità, pertinenza, varietà), README con setup Windows, screenshot di confronto.

## Note
- Sviluppo in container Linux: grafica verificata via screenshot offscreen, toast verificati solo nel fallback; il test finale dei toast va fatto da te su Windows.
- Modelli da provare: Groq `openai/gpt-oss-20b` (più rapido/economico), Ollama `qwen3:8b` o `gemma3:12b` (locale, buon italiano).
