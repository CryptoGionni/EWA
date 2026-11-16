"""Test del Blocco note: logica chat, protezione testo Marv, streaming, typing."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ewa.tools.notepad.chat import ChatLogic, TypingTracker, dark_text
from ewa.tools.notepad.window import NotepadWindow
from ewa.ui.win10 import HubBridge


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


class FakeClient:
    def __init__(self, connected=True):
        self.events = []
        self.connected = connected

    def emit(self, type_, data=None, priority=None):
        self.events.append((type_, data or {}))

    def of(self, type_):
        return [d for t, d in self.events if t == type_]


def make(app, connected=True, debounce=0.05):
    client = FakeClient(connected)
    bridge = HubBridge()
    win = NotepadWindow(client, typing_debounce=debounce, bridge=bridge)
    win.show()
    return win, client, bridge


def delta(bridge, text):
    bridge.deliver({"v": 1, "kind": "chat.delta", "text": text})


def end(bridge):
    bridge.deliver({"v": 1, "kind": "chat.end"})


def press_enter(win):
    QTest.keyClick(win.editor, Qt.Key.Key_Return)


# ---------------- logica pura ----------------
def test_separator():
    assert ChatLogic.separator("") == ""
    assert ChatLogic.separator("ciao") == "\n\n"
    assert ChatLogic.separator("ciao\n") == "\n"
    assert ChatLogic.separator("ciao\n\n") == ""


def test_double_enter_and_extract():
    c = ChatLogic()
    c.activate()
    assert not c.is_send_trigger("ciao", "")           # in attesa di Marv
    c.begin_chunk("", 0)
    c.finish(10)
    assert c.anchor == 12 and not c.busy
    assert c.is_send_trigger("ciao\n", "")
    assert not c.is_send_trigger("ciao", "ciao")        # riga non vuota
    assert not c.is_send_trigger("\n", "")              # nessun testo utente
    assert not c.is_send_trigger("  \n ", " ")
    assert c.extract_message("  ciao\ncome va  \n\n") == "ciao\ncome va"


def test_allows_edit():
    c = ChatLogic()
    assert c.allows_edit(0, 0)                          # non attiva: libero
    c.activate()
    assert not c.allows_edit(5, 5)                      # in attesa
    c.begin_chunk("", 0)
    c.finish(8)                                         # ancora a 10
    assert c.allows_edit(10, 10) and c.allows_edit(12, 15)
    assert not c.allows_edit(9, 9)
    assert not c.allows_edit(5, 12)                     # selezione a cavallo
    assert not c.allows_edit(10, 10, backspace=True)
    assert c.allows_edit(11, 11, backspace=True)


def test_dark_text_truncation():
    assert dark_text("abc") == "abc"
    t = dark_text("x" * 5000)
    assert len(t) <= 1501 and t.endswith("x")


def test_typing_tracker():
    t = TypingTracker()
    assert t.event("poco", "a.txt") is None
    ev = t.event("a" * 40, "a.txt")
    assert ev == {"text_excerpt": "a" * 40, "chars": 40, "filename": "a.txt"}
    assert t.event("a" * 40 + "bbbb", "a.txt") is None   # solo 4 caratteri nuovi
    ev = t.event("a" * 40 + "b" * 20, "a.txt")
    assert ev and ev["chars"] == 60
    assert len(t.event("z" * 1000, "a.txt")["text_excerpt"]) == 400


# ---------------- finestra ----------------
def test_title_and_modified(app):
    win, client, _ = make(app)
    assert win.windowTitle() == "Senza nome - Blocco note"
    win.editor.insertPlainText("ciao")
    assert win.windowTitle() == "*Senza nome - Blocco note"
    assert client.of("notepad.open") == [{"filename": "Senza nome"}]


def test_menubar_last_is_dark_checkable(app):
    win, _, _ = make(app)
    acts = win.menuBar().actions()
    assert acts[-1].text() == "Dark" and acts[-1].isCheckable() and acts[-1].menu() is None
    assert [a.text().replace("&", "") for a in acts[:-1]] == ["File", "Modifica", "Formato", "Visualizza", "?"]


def test_save_open_roundtrip(app, tmp_path):
    win, client, _ = make(app)
    win.editor.setPlainText("riga1\nriga2")
    win._ask_save_path = lambda: str(tmp_path / "nota")
    assert win.save()
    f = tmp_path / "nota.txt"
    assert f.read_bytes() == b"riga1\r\nriga2"
    assert win.windowTitle() == "nota.txt - Blocco note"
    assert client.of("notepad.save") == [{"filename": "nota.txt", "chars": 11}]
    win2, _, _ = make(app)
    assert win2.load_file(str(f))
    assert win2.editor.toPlainText() == "riga1\nriga2"
    assert win2.lbl_eol.text() == "Windows (CRLF)"


def test_unsaved_prompt(app):
    win, _, _ = make(app)
    win.editor.insertPlainText("x")
    win._prompt_save = lambda name: "cancel"
    assert not win.maybe_save()
    win._prompt_save = lambda name: "discard"
    assert win.maybe_save()


def test_find_replace_goto_datetime(app):
    win, _, _ = make(app)
    msgs = []
    win._message = lambda text, parent=None, title="": msgs.append(text)
    win.editor.setPlainText("Uno due uno\ntre UNO")
    assert win.find_text("uno")
    assert win.editor.textCursor().selectedText() == "Uno"
    assert win.find_text("uno")
    assert win.editor.textCursor().position() == 11
    assert win.find_text("uno", case=True, forward=True, wrap=False) is False
    assert msgs and 'Impossibile trovare "uno"' in msgs[-1]
    assert win.find_text("uno", case=False, forward=True, wrap=False)   # il terzo
    assert not win.find_text("uno", forward=True, wrap=False)
    assert win.find_text("uno", forward=True, wrap=True)                # riparte da capo
    assert win.replace_all("uno", "1") == 3
    assert win.editor.toPlainText() == "1 due 1\ntre 1"
    win.goto_line(2)
    assert win.lbl_pos.text() == "Rg 2, col 1"
    win.editor.moveCursor(win.editor.textCursor().MoveOperation.End)
    win.insert_datetime()
    import re
    assert re.search(r"\d\d:\d\d \d\d/\d\d/\d{4}$", win.editor.toPlainText())


def test_zoom(app):
    win, _, _ = make(app)
    win._set_zoom(130)
    assert win.lbl_zoom.text() == "130%"
    win._set_zoom(5000)
    assert win.lbl_zoom.text() == "500%"
    win._set_zoom(100)


# ---------------- typing con debounce ----------------
def test_typing_event_debounce(app):
    win, client, _ = make(app, debounce=0.05)
    win.editor.insertPlainText("a" * 30)
    win.editor.insertPlainText("b" * 5)
    assert client.of("notepad.typing") == []                 # ancora in debounce
    QTest.qWait(350)
    ev = client.of("notepad.typing")
    assert len(ev) == 1 and ev[0]["chars"] == 35 and ev[0]["filename"] == "Senza nome"
    win.editor.insertPlainText("c" * 5)                       # solo 5 caratteri: niente
    QTest.qWait(350)
    assert len(client.of("notepad.typing")) == 1
    win.editor.insertPlainText("d" * 20)
    QTest.qWait(350)
    assert len(client.of("notepad.typing")) == 2


def test_no_typing_in_dark(app):
    win, client, bridge = make(app)
    win.act_dark.setChecked(True)
    delta(bridge, "Ciao")
    end(bridge)
    win.editor.insertPlainText("x" * 60)
    QTest.qWait(350)
    assert client.of("notepad.typing") == []


# ---------------- Dark ----------------
def test_dark_on_off_events_and_theme(app):
    win, client, bridge = make(app)
    win.editor.setPlainText("bozza")
    win.act_dark.setChecked(True)
    assert client.of("notepad.dark_on") == [{"text": "bozza"}]
    assert "#1E1E1E" in win.styleSheet()
    delta(bridge, "Ehi")
    end(bridge)
    win.act_dark.setChecked(False)
    assert client.of("notepad.dark_off") == [{}]
    assert "#FFFFFF" in win.styleSheet() and "#1E1E1E" not in win.styleSheet().split("QMenuBar")[0]
    assert win.editor.toPlainText() == "bozza\n\nEhi\n\n"
    win.editor.moveCursor(win.editor.textCursor().MoveOperation.Start)
    QTest.keyClick(win.editor, Qt.Key.Key_X)                   # editing libero
    assert win.editor.toPlainText().startswith("xbozza")


def test_streaming_via_bridge(app):
    win, client, bridge = make(app)
    win.editor.setPlainText("nota mia")
    win.act_dark.setChecked(True)
    for piece in ("Ciao, ", "cosa ", "scrivi?  "):
        delta(bridge, piece)
    assert win.editor.toPlainText() == "nota mia\n\nCiao, cosa scrivi?  "
    assert win.chat.busy
    end(bridge)
    assert win.editor.toPlainText() == "nota mia\n\nCiao, cosa scrivi?\n\n"
    assert not win.chat.busy
    assert win.editor.textCursor().position() == win.chat.anchor == len(win.editor.toPlainText())
    assert win.chat.spans and win.editor.extraSelections()


def test_first_marv_on_empty_doc(app):
    win, _, bridge = make(app)
    win.act_dark.setChecked(True)
    delta(bridge, "\nPrimo")
    end(bridge)
    assert win.editor.toPlainText() == "Primo\n\n"


def test_input_blocked_while_marv_writes(app):
    win, _, bridge = make(app)
    win.act_dark.setChecked(True)
    QTest.keyClicks(win.editor, "abc")                         # in attesa: bloccato
    assert win.editor.toPlainText() == ""
    delta(bridge, "Ciao")
    QTest.keyClicks(win.editor, "abc")
    assert win.editor.toPlainText() == "Ciao"


def test_marv_text_protected(app):
    win, _, bridge = make(app)
    win.act_dark.setChecked(True)
    delta(bridge, "Ciao Marv")
    end(bridge)
    base = win.editor.toPlainText()
    ed = win.editor
    # cursore dentro il testo di Marv: tasti, cancellazione, taglio, incolla non modificano
    c = ed.textCursor()
    c.setPosition(3)
    ed.setTextCursor(c)
    QTest.keyClicks(ed, "zz")
    QTest.keyClick(ed, Qt.Key.Key_Delete)
    QTest.keyClick(ed, Qt.Key.Key_Backspace)
    QTest.keyClick(ed, Qt.Key.Key_Return)
    ed.selectAll()
    QTest.keyClick(ed, Qt.Key.Key_Delete)
    QTest.keyClick(ed, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    QApplication.clipboard().setText("incollato")
    QTest.keyClick(ed, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    win._delete()
    win.act_cut.trigger()
    win.act_paste.trigger()
    win.insert_datetime()
    assert win.replace_all("Ciao", "X") == 0
    assert ed.toPlainText() == base
    # all'ancora: backspace bloccato, scrittura libera
    c = ed.textCursor()
    c.movePosition(c.MoveOperation.End)
    ed.setTextCursor(c)
    QTest.keyClick(ed, Qt.Key.Key_Backspace)
    assert ed.toPlainText() == base
    QTest.keyClicks(ed, "ok")
    assert ed.toPlainText() == base + "ok"
    QTest.keyClick(ed, Qt.Key.Key_Backspace)
    assert ed.toPlainText() == base + "o"


def test_double_enter_sends_and_conversation(app):
    win, client, bridge = make(app)
    win.act_dark.setChecked(True)
    delta(bridge, "Come va?")
    end(bridge)
    ed = win.editor
    QTest.keyClicks(ed, "Bene")
    press_enter(win)                                           # prima riga a capo: niente invio
    assert client.of("chat.user") == []
    press_enter(win)                                           # riga vuota: invio
    assert client.of("chat.user") == [{"text": "Bene"}]
    assert win.chat.busy
    QTest.keyClicks(ed, "zzz")                                 # bloccato mentre Marv risponde
    assert "zzz" not in ed.toPlainText()
    delta(bridge, "Ottimo!")
    end(bridge)
    assert ed.toPlainText() == "Come va?\n\nBene\n\nOttimo!\n\n"
    QTest.keyClicks(ed, "Grazie")
    press_enter(win)
    press_enter(win)
    assert client.of("chat.user")[-1] == {"text": "Grazie"}    # solo il testo dopo l'ultima risposta


def test_enter_on_empty_without_text_does_not_send(app):
    win, client, bridge = make(app)
    win.act_dark.setChecked(True)
    delta(bridge, "Ciao")
    end(bridge)
    press_enter(win)
    press_enter(win)
    assert client.of("chat.user") == []


def test_chat_error_unlocks(app):
    win, _, bridge = make(app)
    win.act_dark.setChecked(True)
    bridge.deliver({"kind": "chat.error", "msg": "rete assente"})
    assert win.editor.toPlainText() == "(Marv non risponde: rete assente)\n\n"
    assert not win.chat.busy
    QTest.keyClicks(win.editor, "ok")
    assert win.editor.toPlainText().endswith("ok")


def test_hub_unreachable(app):
    win, client, _ = make(app, connected=False)
    win.unreachable_delay_ms = 10
    win.act_dark.setChecked(True)
    QTest.qWait(400)
    assert "avvia EWA dalla shell" in win.editor.toPlainText()
    assert not win.chat.busy and win.act_dark.isChecked()
    assert client.of("notepad.dark_on")


def test_messages_ignored_when_not_dark(app):
    win, _, bridge = make(app)
    delta(bridge, "ciao")
    assert win.editor.toPlainText() == ""


def test_marv_text_saved(app, tmp_path):
    win, _, bridge = make(app)
    win.act_dark.setChecked(True)
    delta(bridge, "Ciao")
    end(bridge)
    win._ask_save_path = lambda: str(tmp_path / "chat.txt")
    assert win.save()
    assert (tmp_path / "chat.txt").read_bytes() == b"Ciao\r\n\r\n"
