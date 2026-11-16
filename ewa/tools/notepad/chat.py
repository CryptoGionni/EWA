"""Logica pura (senza Qt) della chat Dark del Blocco note e del tracker di digitazione.

Le posizioni sono quelle del QTextDocument (offset di caratteri): la classe non
tocca il documento, dice solo alla finestra cosa scrivere e cosa proteggere.
"""
from __future__ import annotations

MAX_DARK_TEXT = 1500
UNREACHABLE_TEXT = "(Marv non è raggiungibile: avvia EWA dalla shell)"


def error_text(msg: str) -> str:
    return f"(Marv non risponde: {msg})"


def dark_text(text: str, limit: int = MAX_DARK_TEXT) -> str:
    """Testo da inviare con notepad.dark_on: gli ultimi `limit` caratteri."""
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]


class ChatLogic:
    """Stato della conversazione: ancora di input, risposta in corso, doppio Invio."""

    def __init__(self) -> None:
        self.active = False      # modalità Dark attiva
        self.busy = False        # Marv sta scrivendo (o si attende la sua risposta)
        self.started = False     # è già arrivato testo della risposta corrente
        self.anchor = 0          # prima di questa posizione il documento è protetto
        self.spans: list[list[int]] = []   # intervalli [start, end) scritti da Marv
        self._span: list[int] | None = None

    # --- ciclo di vita ---
    def activate(self) -> None:
        """Attiva la chat: Marv scrive per primo, quindi si resta in attesa."""
        self.active = True
        self.anchor = 0
        self.spans = []
        self._span = None
        self.await_response()

    def deactivate(self) -> None:
        self.active = False
        self.busy = False
        self.started = False
        self.anchor = 0
        self.spans = []
        self._span = None

    def reset(self) -> None:
        """Nuovo documento / file aperto mentre la chat è attiva."""
        self.anchor = 0
        self.spans = []
        self._span = None
        self.busy = False
        self.started = False

    def await_response(self) -> None:
        self.busy = True
        self.started = False
        self._span = None

    # --- scrittura della risposta ---
    @staticmethod
    def separator(tail: str) -> str:
        """Newline da inserire per avere una riga vuota tra il testo esistente e Marv."""
        if not tail:
            return ""
        trailing = len(tail) - len(tail.rstrip("\n"))
        return "\n" * max(0, 2 - trailing)

    def begin_chunk(self, tail: str, end_pos: int) -> str:
        """Prima porzione di una risposta: restituisce il separatore da inserire."""
        if self.started:
            return ""
        if not self.busy:
            self.await_response()
        sep = self.separator(tail)
        self.started = True
        self._span = [end_pos + len(sep), end_pos + len(sep)]
        self.spans.append(self._span)
        return sep

    def chunk_written(self, end_pos: int) -> None:
        if self._span is not None:
            self._span[1] = end_pos

    def finish(self, end_pos: int) -> str:
        """Fine risposta: restituisce il terminatore da aggiungere e sposta l'ancora."""
        term = "\n\n" if self.started else ""
        if self._span is not None:
            self._span[1] = end_pos
        self.anchor = end_pos + len(term)
        self.busy = False
        self.started = False
        self._span = None
        return term

    # --- protezione ---
    def allows_edit(self, start: int, end: int, backspace: bool = False) -> bool:
        """True se una modifica che coinvolge [start, end] è consentita."""
        if not self.active:
            return True
        if self.busy:
            return False
        lo = min(start, end)
        if backspace and start == end:
            lo -= 1
        return lo >= self.anchor

    # --- invio messaggio ---
    @staticmethod
    def extract_message(text_after_anchor: str) -> str:
        return text_after_anchor.strip()

    def is_send_trigger(self, text_after_anchor: str, current_line: str) -> bool:
        """Doppio Invio: Invio su riga vuota con testo utente non vuoto dopo l'ancora."""
        return (self.active and not self.busy
                and current_line.strip() == "" and text_after_anchor.strip() != "")


class TypingTracker:
    """Decide se emettere notepad.typing: serve una variazione minima dall'ultimo invio."""

    def __init__(self, min_delta: int = 15, excerpt: int = 400, baseline: str = "") -> None:
        self.min_delta = min_delta
        self.excerpt = excerpt
        self.baseline = baseline

    def reset(self, text: str = "") -> None:
        self.baseline = text

    def changed_chars(self, text: str) -> int:
        a, b = self.baseline, text
        n = min(len(a), len(b))
        p = 0
        while p < n and a[p] == b[p]:
            p += 1
        s = 0
        while s < n - p and a[len(a) - 1 - s] == b[len(b) - 1 - s]:
            s += 1
        return max(len(a), len(b)) - p - s

    def event(self, text: str, filename: str) -> dict | None:
        """Dati dell'evento se la variazione basta (e aggiorna la baseline), altrimenti None."""
        if not text.strip() or self.changed_chars(text) < self.min_delta:
            return None
        self.baseline = text
        return {"text_excerpt": text[-self.excerpt:], "chars": len(text), "filename": filename}
