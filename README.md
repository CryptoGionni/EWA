# EWA — Everything in Windows but AI

Quattro app di Windows 10 (Calcolatrice, Sveglie e orologio, Fotocamera, Blocco note) rifatte in PySide6, con un ospite indesiderato: **Marv**, un chatbot scocciato e sarcastico che le osserva mentre le usi e commenta con una notifica di Windows. Nel Blocco note c'è anche la modalità **Dark**, dove Marv ti scrive per primo e puoi rispondergli.

## Setup su Windows

Marv gira **in locale** con [Ollama](https://ollama.com/download) e il modello `gemma4:e2b`: nessuna chiave API, niente esce dal tuo PC.

```powershell
winget install -e --id Ollama.Ollama   # se Ollama non c'è già
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python ewa.py
```

Non serve avviare Ollama a mano né scaricare il modello: al primo avvio EWA lancia `ollama serve` se non risponde, scarica `gemma4:e2b` se manca (circa 5 GB, solo la prima volta) e manda una richiesta fittizia per caricarlo in memoria, così la prima battuta di Marv non deve aspettare. Per preparare tutto in anticipo: `python ewa.py --setup`.

Serve Python 3.11 o superiore. Il `.env` è facoltativo (vedi `.env.example`). Per provare tutto senza modello: `MARV_FAKE_LLM=1` (Marv risponde con battute predefinite).

## Avvio e comandi della shell

`python ewa.py` (o `EWA.exe` se installato) apre una shell colorata (`ewa> `) che mostra il log di Marv. I tool si aprono da lì, ciascuno in un processo separato, ma funzionano anche da soli: aperti dal menu Start, avviano Marv in background.

| Comando | Effetto |
|---|---|
| `calc` · `calcolatrice` | apre la Calcolatrice |
| `timer` · `orologio` · `sveglie` | apre Sveglie e orologio |
| `camera` · `fotocamera` | apre la Fotocamera |
| `notepad [file]` · `blocco [file]` | apre il Blocco note, opzionalmente con un file |
| `status` | tool connessi, modello, stato di Marv e di Ollama, notifiche inviate |
| `log on` / `log off` | mostra o nasconde il log colorato di eventi e commenti |
| `toast [testo]` | notifica di prova |
| `help` · `aiuto` | elenco comandi |
| `exit` · `esci` | chiude i tool aperti dalla shell e la shell (Ctrl+C fa lo stesso, con una battuta di Marv) |

Log nella cartella temporanea: `ewa-hub.log` (Marv), `ewa-tools.log` (tool), `ewa-ollama.log` (`ollama serve` avviato da EWA). I percorsi sono in `status`.

## Provider e modelli

Di default `LLM_PROVIDER=ollama` con `gemma4:e2b` e i parametri consigliati per Gemma 4: `temperature 0.8`, `top_p 0.95`, `top_k 64`, `repeat_penalty 0.9`, `num_ctx 8192`, `num_predict 512`, thinking disattivato. Il modello resta in memoria finché MarvHub è attivo (`OLLAMA_KEEP_ALIVE=-1`) e viene liberato quando si spegne.

| Variabile | Default | Significato |
|---|---|---|
| `LLM_MODEL` | `gemma4:e2b` | qualsiasi modello Ollama |
| `OLLAMA_HOST` | `http://localhost:11434` | server Ollama |
| `OLLAMA_AUTOSTART` / `OLLAMA_AUTOPULL` | `1` | avvia `ollama serve` / scarica il modello se mancano |
| `OLLAMA_TEMPERATURE`, `OLLAMA_NUM_CTX`, `OLLAMA_NUM_PREDICT` | vedi sopra | ritocchi ai parametri |
| `MARV_COOLDOWN_SECONDS` | `30` | pausa minima tra due notifiche (gli eventi ad alta priorità la scavalcano) |
| `EWA_HUB_IDLE_EXIT` | `600` | MarvHub (e l'`ollama serve` avviato da EWA) si spegne dopo N secondi senza tool aperti |

Groq resta disponibile: `LLM_PROVIDER=openai`, `LLM_API_KEY=<chiave>`, `LLM_MODEL=openai/gpt-oss-120b` (con `LLM_REASONING_EFFORT=low`) o `openai/gpt-oss-20b`. Va bene qualsiasi endpoint compatibile OpenAI (`LLM_BASE_URL`).

## Creare l'installer (EWA-Setup.exe)

L'installer si compila **su Windows 10**: le icone di Calcolatrice, Sveglie e orologio, Fotocamera, Blocco note, cmd e notepad non sono nel repository (sono di Microsoft) ma vengono estratte dal tuo sistema al momento della build, così ogni eseguibile ha l'icona identica all'app originale. Su Windows 11 le icone risulteranno quelle di Windows 11.

Prerequisiti: Python 3.11+ e [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install -e --id JRSoftware.InnoSetup`).

```powershell
build.bat                      # icone + PyInstaller + installer -> dist\EWA-Setup.exe
build.bat --skip-icons         # senza estrarre le icone
build.bat --skip-installer     # solo dist\EWA\ (cartella già eseguibile)
```

`build.bat` installa le dipendenze di build (`packaging/requirements-build.txt`), estrae le icone in `ewa/assets/icons/` (ignorata da git), crea con PyInstaller una sola cartella `dist\EWA\` con sei eseguibili che condividono le librerie (`EWA.exe`, `MarvHub.exe`, `Calcolatrice.exe`, `Sveglie e orologio.exe`, `Fotocamera.exe`, `Blocco note.exe`) e infine compila l'installer con Inno Setup. Se un'app UWP non è installata, l'icona manca e l'eseguibile usa quella predefinita (la build prosegue con un avviso).

L'installer non richiede i permessi di amministratore: installa in `%LOCALAPPDATA%\Programs\EWA`, crea il gruppo "EWA" nel menu Start (con Terminale EWA) e, a scelta, le icone sul desktop. Se Ollama non è presente propone di installarlo con winget; al termine può avviare `EWA.exe --setup`, che prepara Marv e scarica il modello `gemma4:e2b` (circa 5 GB). Si disinstalla da Impostazioni > App (o dal menu Start): la disinstallazione chiude anche `MarvHub.exe`.

## Architettura

```
 EWA (shell) ──┐                                   MarvHub (processo in background: hubd.py)
 Calcolatrice ─┤                                  ┌──────────────────────────────────────────┐
 Sveglie       ├─ ToolClient ── TCP localhost ──▶ │ HubServer (bus.py)                       │
 Fotocamera    │   eventi / controllo / log       │ MarvHub (hub.py): memoria · cooldown     │
 Blocco note ──┘                                  │ persona.py · llm.py ──▶ Ollama (gemma4)  │
                                                  │ Notifier: toast Windows                  │
                                                  └──────────────────────────────────────────┘
```

- **MarvHub** è l'unico cervello. Lo avvia il primo tool o la shell che non lo trova (`launcher.spawn_hub`); la porta TCP fa da lock, quindi ne esiste sempre uno solo. All'avvio prepara Ollama (`ollama_service.py`) e scalda il modello; i commenti arrivati nel frattempo aspettano, non si perdono. Si spegne quando non ci sono più client da `EWA_HUB_IDLE_EXIT` secondi, o quando esci dalla shell e non restano tool aperti; se aveva avviato lui `ollama serve`, lo ferma.
- La **shell** è un client come gli altri (`hello` con `tool="shell"`): riceve il log e manda comandi di controllo (`status`, `toast`, `log`, `shutdown`).
- I tool non hanno UI per Marv: emettono solo eventi del catalogo in `ewa/core/protocol.py`.
- L'hub tiene gli ultimi ~30 eventi di tutti i tool e le ultime ~8 battute di Marv (per non ripetersi), e passa tutto al modello, così Marv può collegare ciò che fai nei diversi tool.
- Un solo commento in volo per volta; gli eventi saltati per il cooldown restano in memoria e il più recente viene commentato alla scadenza, se ha meno di 60 secondi.
- `MarvHub.actions` è un registry vuoto: il punto dove innestare in futuro azioni agentiche.

## Aggiungere un nuovo tool

1. Aggiungi il tool e i suoi eventi al catalogo in `ewa/core/protocol.py` (`TOOLS`, `EVENTS`) e, per renderli leggibili a Marv, una riga in `describe_event` di `ewa/core/persona.py`.
2. Crea `ewa/tools/<nome>/` con un `__main__.py` che usa `ewa.ui.win10.run_tool("<tool>", build)` ed emette eventi con `ToolClient("<tool>").emit(tipo, dati)`.
3. Registra il componente in `COMPONENTS` di `ewa/core/launcher.py` (nome exe e modulo), il comando in `TOOL_COMMANDS` di `ewa/shell.py` e l'exe in `packaging/ewa.spec` e `packaging/installer.iss`.
4. Aggiungi test in `tests/test_<nome>.py`.

## Privacy

Con un provider remoto (Groq, `LLM_PROVIDER=openai`) all'LLM vengono inviati la descrizione testuale degli eventi (espressioni calcolate, durata dei timer, ecc.), **l'estratto del testo scritto nel Blocco note** e, in modalità Dark, il testo della nota e la conversazione. La Fotocamera invia solo eventi (scatti, durata video), mai immagini. Con Ollama (il default) tutto resta sul tuo PC.

## Test

```powershell
python -m pytest
```
