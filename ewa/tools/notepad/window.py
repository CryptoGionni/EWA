"""Blocco note di Windows 10 (app Win32: QMainWindow con cornice nativa) + modalità Dark/chat con Marv."""
from __future__ import annotations

import codecs
import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal, QProcess, QUrl
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QGuiApplication, QKeySequence, QShortcut,
                           QTextCursor, QTextDocument)
from PySide6.QtWidgets import (QFileDialog, QFontDialog, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QWidget)
from PySide6.QtWidgets import QTextEdit

from ewa.ui.win10 import mono_font, ui_font

from .chat import (UNREACHABLE_TEXT, ChatLogic, TypingTracker, dark_text, error_text)
from .dialogs import FindReplaceDialog, GoToDialog
from .theme import MARV_COLOR, build_qss

APP_NAME = "Blocco note"
UNTITLED = "Senza nome"
EOL_LABELS = {"\r\n": "Windows (CRLF)", "\n": "Unix (LF)", "\r": "Macintosh (CR)"}
FILE_FILTER = "Documenti di testo (*.txt);;Tutti i file (*.*)"
WATCHDOG_MS = 60000


class _NullClient:
    connected = True

    def emit(self, *_a, **_k) -> None:
        pass


class NotepadEdit(QPlainTextEdit):
    """Editor con protezione del testo di Marv, doppio Invio e zoom con Ctrl+rotella."""
    zoom_step = Signal(int)
    send_requested = Signal()

    def __init__(self, chat: ChatLogic):
        super().__init__()
        self.chat = chat

    # --- helper ---
    def selection_range(self) -> tuple[int, int]:
        c = self.textCursor()
        return c.selectionStart(), c.selectionEnd()

    def edit_allowed(self, backspace: bool = False) -> bool:
        s, e = self.selection_range()
        return self.chat.allows_edit(s, e, backspace)

    def text_from_anchor(self) -> str:
        c = QTextCursor(self.document())
        end = max(0, self.document().characterCount() - 1)
        c.setPosition(min(self.chat.anchor, end))
        c.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        return c.selectedText().replace(" ", "\n").replace(" ", "\n")

    # --- eventi ---
    def keyPressEvent(self, e) -> None:
        if self.chat.active and self._guard_key(e):
            e.accept()
            return
        super().keyPressEvent(e)

    def _guard_key(self, e) -> bool:
        """True se il tasto va consumato (modifica non consentita) o gestito qui."""
        key, mods = e.key(), e.modifiers()
        K = QKeySequence.StandardKey
        if e.matches(K.Undo) or e.matches(K.Redo):
            return self.chat.busy
        is_enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        text = e.text()
        printable = (bool(text) and text.isprintable()
                     and not ((mods & Qt.KeyboardModifier.ControlModifier)
                              and not (mods & Qt.KeyboardModifier.AltModifier)))
        modifying = (is_enter or printable
                     or key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete, Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
                     or any(e.matches(k) for k in (K.Cut, K.Paste, K.Delete, K.DeleteEndOfWord,
                                                   K.DeleteStartOfWord, K.DeleteEndOfLine)))
        if not modifying:
            return False
        if e.matches(K.DeleteStartOfWord) and not self.textCursor().hasSelection():
            # Ctrl+Backspace: cancella la parola ma mai oltre l'ancora
            if self.chat.busy:
                return True
            c = self.textCursor()
            c.movePosition(QTextCursor.MoveOperation.PreviousWord, QTextCursor.MoveMode.KeepAnchor)
            if c.position() < self.chat.anchor:
                c.setPosition(self.chat.anchor, QTextCursor.MoveMode.KeepAnchor)
            if c.hasSelection() and self.textCursor().position() > self.chat.anchor:
                c.removeSelectedText()
            return True
        if not self.edit_allowed(backspace=(key == Qt.Key.Key_Backspace)):
            return True
        if is_enter:
            trig = self.chat.is_send_trigger(self.text_from_anchor(), self.textCursor().block().text())
            super().keyPressEvent(e)
            if trig:
                self.send_requested.emit()
            return True
        return False

    def insertFromMimeData(self, source) -> None:
        if self.chat.active and not self.edit_allowed():
            return
        super().insertFromMimeData(source)

    def inputMethodEvent(self, e) -> None:
        if self.chat.active and not self.edit_allowed():
            e.ignore()
            return
        super().inputMethodEvent(e)

    def wheelEvent(self, e) -> None:
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            dy = e.angleDelta().y()
            if dy:
                self.zoom_step.emit(1 if dy > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)


class NotepadWindow(QMainWindow):
    def __init__(self, client=None, path: str | None = None, typing_debounce: float | None = None,
                 bridge=None):
        super().__init__()
        self.client = client or _NullClient()
        self.path: str | None = None
        self._eol = "\r\n"
        self._enc = "utf-8"
        self._enc_label = "UTF-8"
        self._zoom = 100
        self._base_font = mono_font(11)
        self._find = {"text": "", "case": False, "wrap": False, "forward": True}
        self._find_dlg: FindReplaceDialog | None = None
        self._repl_dlg: FindReplaceDialog | None = None
        self.chat = ChatLogic()
        self.typing = TypingTracker()
        self.watchdog_ms = WATCHDOG_MS
        self.unreachable_delay_ms = 600
        self._actions_enabled_wrap = True

        if typing_debounce is None:
            from ewa.core.config import load_config
            typing_debounce = load_config().typing_debounce
        self._typing_timer = QTimer(self)
        self._typing_timer.setSingleShot(True)
        self._typing_timer.setInterval(int(typing_debounce * 1000))
        self._typing_timer.timeout.connect(self._fire_typing)
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(lambda: self._marv_error("timeout"))

        self.setFont(ui_font(9))
        self.editor = NotepadEdit(self.chat)
        self.editor.setObjectName("Editor")
        self.editor.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.document().setDocumentMargin(3)
        self.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setCentralWidget(self.editor)
        self._apply_font()

        self._build_menus()
        self._build_statusbar()
        self.setStyleSheet(build_qss(False))
        self.resize(900, 600)
        self.setMinimumSize(380, 200)

        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.selectionChanged.connect(self._update_edit_actions)
        self.editor.cursorPositionChanged.connect(self._update_position)
        self.editor.document().modificationChanged.connect(lambda _m: self._update_title())
        self.editor.customContextMenuRequested.connect(self._context_menu)
        self.editor.zoom_step.connect(lambda d: self._set_zoom(self._zoom + 10 * d))
        self.editor.send_requested.connect(self._chat_send)

        bridge = bridge or getattr(self.client, "bridge", None)
        if bridge is not None:
            bridge.message.connect(self.on_hub_message)

        if path:
            self.load_file(path)
        self.editor.document().setModified(False)
        self._update_title()
        self._update_position()
        self._update_edit_actions()
        self.client.emit("notepad.open", {"filename": self.display_name()})

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------
    def _act(self, menu: QMenu, text: str, slot=None, shortcut: str | list[str] | None = None,
             display: str | None = None, checkable: bool = False, enabled: bool = True,
             bind: bool = True) -> QAction:
        keys = [shortcut] if isinstance(shortcut, str) else list(shortcut or [])
        label = text
        if keys:
            label += "\t" + (display or keys[0].replace("Shift", "Maiusc").replace("Del", "Canc"))
        a = QAction(label, self)
        a.setCheckable(checkable)
        a.setEnabled(enabled)
        if slot is not None:
            if checkable:
                a.toggled.connect(slot)
            else:
                a.triggered.connect(lambda _c=False, s=slot: s())
        if bind:
            for k in keys:
                sc = QShortcut(QKeySequence(k), self)
                sc.activated.connect(lambda a=a: a.isEnabled() and a.trigger())
        menu.addAction(a)
        return a

    def _build_menus(self) -> None:
        mb = self.menuBar()
        mb.setNativeMenuBar(False)

        m = mb.addMenu("&File")
        self.act_new = self._act(m, "Nuovo", self.new_document, "Ctrl+N")
        self.act_new_win = self._act(m, "Nuova finestra", self.new_window, "Ctrl+Shift+N")
        self.act_open = self._act(m, "Apri...", self.open_file, "Ctrl+O")
        self.act_save = self._act(m, "Salva", self.save, "Ctrl+S")
        self.act_save_as = self._act(m, "Salva con nome...", self.save_as, "Ctrl+Shift+S")
        m.addSeparator()
        self.act_page = self._act(m, "Imposta pagina...", enabled=False)
        self.act_print = self._act(m, "Stampa...", None, "Ctrl+P", enabled=False, bind=False)
        m.addSeparator()
        self.act_exit = self._act(m, "Esci", self.close)

        m = mb.addMenu("&Modifica")
        self.menu_edit = m
        self.act_undo = self._act(m, "Annulla", lambda: self._guarded(self.editor.undo, undo=True),
                                  "Ctrl+Z", bind=False)
        m.addSeparator()
        self.act_cut = self._act(m, "Taglia", lambda: self._guarded(self.editor.cut), "Ctrl+X", bind=False)
        self.act_copy = self._act(m, "Copia", self.editor.copy, "Ctrl+C", bind=False)
        self.act_paste = self._act(m, "Incolla", lambda: self._guarded(self.editor.paste), "Ctrl+V",
                                   bind=False)
        self.act_delete = self._act(m, "Elimina", self._delete, "Del", bind=False)
        m.addSeparator()
        self.act_bing = self._act(m, "Cerca con Bing...", None, "Ctrl+E", enabled=False, bind=False)
        self.act_find = self._act(m, "Trova...", self.show_find, "Ctrl+F")
        self.act_find_next = self._act(m, "Trova successivo", lambda: self.find_again(True), "F3")
        self.act_find_prev = self._act(m, "Trova precedente", lambda: self.find_again(False), "Shift+F3")
        self.act_replace = self._act(m, "Sostituisci...", self.show_replace, "Ctrl+H")
        self.act_goto = self._act(m, "Vai a...", self.show_goto, "Ctrl+G")
        m.addSeparator()
        self.act_select_all = self._act(m, "Seleziona tutto", self.editor.selectAll, "Ctrl+A", bind=False)
        self.act_datetime = self._act(m, "Ora/data", self.insert_datetime, "F5")
        m.aboutToShow.connect(self._update_edit_actions)

        m = mb.addMenu("F&ormato")
        self.act_wrap = self._act(m, "A capo automatico", self._set_wrap, checkable=True)
        self.act_font = self._act(m, "Carattere...", self.choose_font)

        m = mb.addMenu("&Visualizza")
        zoom = m.addMenu("Zoom")
        self.act_zoom_in = self._act(zoom, "Aumenta", lambda: self._set_zoom(self._zoom + 10),
                                     ["Ctrl++", "Ctrl+="], display="Ctrl+Più")
        self.act_zoom_out = self._act(zoom, "Riduci", lambda: self._set_zoom(self._zoom - 10),
                                      "Ctrl+-", display="Ctrl+Meno")
        self.act_zoom_reset = self._act(zoom, "Ripristina zoom predefinito", lambda: self._set_zoom(100),
                                        "Ctrl+0")
        self.act_status = self._act(m, "Barra di stato", self._toggle_status, checkable=True)
        self.act_status.setChecked(True)

        m = mb.addMenu("&?")
        self.act_help = self._act(m, "Visualizza la Guida", lambda: QDesktopServices.openUrl(
            QUrl("https://go.microsoft.com/fwlink/?LinkId=834783")))
        self.act_feedback = self._act(m, "Invia feedback", enabled=False)
        m.addSeparator()
        self.act_about = self._act(m, "Informazioni su Blocco note", self.show_about)

        # Easter egg: azione checkable direttamente sulla barra, sempre ultima
        self.act_dark = QAction("Dark", self)
        self.act_dark.setCheckable(True)
        self.act_dark.toggled.connect(self.set_dark)
        mb.addAction(self.act_dark)

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.lbl_pos = QLabel("Rg 1, col 1")
        self.lbl_zoom = QLabel("100%")
        self.lbl_eol = QLabel(EOL_LABELS["\r\n"])
        self.lbl_enc = QLabel("UTF-8")
        for lbl, w in ((self.lbl_pos, 170), (self.lbl_zoom, 60), (self.lbl_eol, 150), (self.lbl_enc, 100)):
            lbl.setFixedWidth(w)
            sb.addPermanentWidget(lbl)

    def _context_menu(self, pos: QPoint) -> None:
        self._update_edit_actions()
        m = QMenu(self)
        for a in (self.act_undo, None, self.act_cut, self.act_copy, self.act_paste, self.act_delete, None,
                  self.act_select_all):
            if a is None:
                m.addSeparator()
            else:
                m.addAction(a)
        m.exec(self.editor.mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Stato / titolo / barra di stato
    # ------------------------------------------------------------------
    def display_name(self) -> str:
        return os.path.basename(self.path) if self.path else UNTITLED

    def _update_title(self) -> None:
        mark = "*" if self.editor.document().isModified() else ""
        self.setWindowTitle(f"{mark}{self.display_name()} - {APP_NAME}")

    def _update_position(self) -> None:
        c = self.editor.textCursor()
        self.lbl_pos.setText(f"Rg {c.blockNumber() + 1}, col {c.positionInBlock() + 1}")

    def _update_edit_actions(self) -> None:
        doc = self.editor.document()
        has_sel = self.editor.textCursor().hasSelection()
        has_text = doc.characterCount() > 1
        self.act_undo.setEnabled(doc.isUndoAvailable())
        self.act_cut.setEnabled(has_sel)
        self.act_copy.setEnabled(has_sel)
        self.act_delete.setEnabled(has_sel)
        self.act_paste.setEnabled(bool(QGuiApplication.clipboard().text()))
        for a in (self.act_find, self.act_find_next, self.act_find_prev, self.act_replace):
            a.setEnabled(has_text)
        self.act_goto.setEnabled(self.editor.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap)

    def _apply_font(self) -> None:
        f = QFont(self._base_font)
        f.setPointSizeF(max(1.0, self._base_font.pointSizeF() * self._zoom / 100))
        self.editor.setFont(f)
        self.editor.setTabStopDistance(self.editor.fontMetrics().horizontalAdvance(" ") * 8)

    def _set_zoom(self, pct: int) -> None:
        self._zoom = max(10, min(500, int(pct)))
        self._apply_font()
        self.lbl_zoom.setText(f"{self._zoom}%")

    def choose_font(self) -> None:
        ok, font = QFontDialog.getFont(self._base_font, self, "Carattere")
        if ok:
            self._base_font = font
            self._apply_font()

    def _set_wrap(self, on: bool) -> None:
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if on
                                    else QPlainTextEdit.LineWrapMode.NoWrap)
        # come in Win10: con l'a capo automatico la barra di stato non è disponibile
        self.act_status.setEnabled(not on)
        self.statusBar().setVisible(not on and self.act_status.isChecked())
        self._update_edit_actions()

    def _toggle_status(self, _checked=False) -> None:
        self.statusBar().setVisible(self.act_status.isChecked())

    def _set_eol_enc(self, eol: str, enc: str, enc_label: str) -> None:
        self._eol, self._enc, self._enc_label = eol, enc, enc_label
        self.lbl_eol.setText(EOL_LABELS[eol])
        self.lbl_enc.setText(enc_label)

    # ------------------------------------------------------------------
    # File
    # ------------------------------------------------------------------
    def _ask_open_path(self) -> str:
        p, _ = QFileDialog.getOpenFileName(self, "Apri", "", FILE_FILTER)
        return p

    def _ask_save_path(self) -> str:
        p, _ = QFileDialog.getSaveFileName(self, "Salva con nome", self.path or "", FILE_FILTER)
        return p

    def _prompt_save(self, name: str) -> str:
        """Chiede cosa fare del testo modificato: 'save' | 'discard' | 'cancel'."""
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(f"Vuoi salvare le modifiche a {name}?")
        b_save = box.addButton("Salva", QMessageBox.ButtonRole.AcceptRole)
        b_disc = box.addButton("Non salvare", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(b_save)
        box.exec()
        clicked = box.clickedButton()
        return "save" if clicked is b_save else "discard" if clicked is b_disc else "cancel"

    def _message(self, text: str, parent: QWidget | None = None, title: str = APP_NAME) -> None:
        QMessageBox.information(parent or self, title, text)

    def maybe_save(self) -> bool:
        """True se si può procedere (salvato, scartato o non modificato)."""
        if not self.editor.document().isModified():
            return True
        choice = self._prompt_save(self.path or UNTITLED)
        if choice == "cancel":
            return False
        if choice == "save":
            return self.save()
        return True

    def _reset_document(self, text: str) -> None:
        self.editor.setPlainText(text)
        self.editor.document().setModified(False)
        self.editor.document().clearUndoRedoStacks()
        self.typing.reset(text)
        if self.chat.active:
            self.chat.reset()
            self._refresh_highlight()
        self._update_title()

    def new_document(self) -> None:
        if not self.maybe_save():
            return
        self.path = None
        self._set_eol_enc("\r\n", "utf-8", "UTF-8")
        self._reset_document("")

    def new_window(self) -> None:
        QProcess.startDetached(sys.executable, ["-m", "ewa.tools.notepad"])

    def open_file(self) -> None:
        if not self.maybe_save():
            return
        p = self._ask_open_path()
        if p and self.load_file(p):
            self.client.emit("notepad.open", {"filename": self.display_name()})

    def load_file(self, path: str) -> bool:
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            self._message(f"Impossibile aprire il file.\n{exc.strerror or exc}")
            return False
        if raw.startswith(codecs.BOM_UTF8):
            text, enc, label = raw[3:].decode("utf-8", "replace"), "utf-8-sig", "UTF-8 con BOM"
        elif raw.startswith(codecs.BOM_UTF16_LE):
            text, enc, label = raw[2:].decode("utf-16-le", "replace"), "utf-16-le", "UTF-16 LE"
        elif raw.startswith(codecs.BOM_UTF16_BE):
            text, enc, label = raw[2:].decode("utf-16-be", "replace"), "utf-16-be", "UTF-16 BE"
        else:
            try:
                text, enc, label = raw.decode("utf-8"), "utf-8", "UTF-8"
            except UnicodeDecodeError:
                text, enc, label = raw.decode("cp1252", "replace"), "cp1252", "ANSI"
        eol = "\r\n" if "\r\n" in text else "\n" if "\n" in text else "\r" if "\r" in text else "\r\n"
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.path = os.path.abspath(path)
        self._set_eol_enc(eol, enc, label)
        self._reset_document(text)
        return True

    def _encode(self, text: str) -> bytes:
        text = text.replace("\n", self._eol)
        if self._enc == "utf-16-le":
            return codecs.BOM_UTF16_LE + text.encode("utf-16-le")
        if self._enc == "utf-16-be":
            return codecs.BOM_UTF16_BE + text.encode("utf-16-be")
        if self._enc == "cp1252":
            try:
                return text.encode("cp1252")
            except UnicodeEncodeError:
                self._set_eol_enc(self._eol, "utf-8", "UTF-8")
        return text.encode(self._enc)

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        p = self._ask_save_path()
        if not p:
            return False
        if not os.path.splitext(p)[1]:
            p += ".txt"
        return self._write(p)

    def _write(self, path: str) -> bool:
        text = self.editor.toPlainText()
        try:
            Path(path).write_bytes(self._encode(text))
        except OSError as exc:
            self._message(f"Impossibile salvare il file.\n{exc.strerror or exc}")
            return False
        self.path = os.path.abspath(path)
        self.editor.document().setModified(False)
        self._update_title()
        self.client.emit("notepad.save", {"filename": self.display_name(), "chars": len(text)})
        return True

    def closeEvent(self, e) -> None:
        if self.maybe_save():
            e.accept()
        else:
            e.ignore()

    # ------------------------------------------------------------------
    # Modifica
    # ------------------------------------------------------------------
    def _guarded(self, fn, undo: bool = False) -> None:
        """Esegue un'operazione che modifica il testo solo se la chat lo consente."""
        if self.chat.active:
            ok = (not self.chat.busy) if undo else self.editor.edit_allowed()
            if not ok:
                return
        fn()

    def _delete(self) -> None:
        def do():
            c = self.editor.textCursor()
            c.removeSelectedText() if c.hasSelection() else c.deleteChar()
        self._guarded(do)

    def insert_datetime(self) -> None:
        self._guarded(lambda: self.editor.textCursor().insertText(datetime.now().strftime("%H:%M %d/%m/%Y")))

    def show_about(self) -> None:
        self._message("EWA - Blocco note\nRiproduzione del Blocco note di Windows 10.",
                      title="Informazioni su Blocco note")

    # ---- Trova / Sostituisci ----
    def _selected_single_line(self) -> str:
        t = self.editor.textCursor().selectedText()
        return t if t and " " not in t else ""

    def show_find(self) -> None:
        if self._find_dlg is None:
            self._find_dlg = FindReplaceDialog(self, replace=False)
            self._find_dlg.find_next.connect(self._on_dialog_find)
        f = self._find
        self._find_dlg.open_with(self._selected_single_line() or f["text"], f["case"], f["wrap"], f["forward"])

    def show_replace(self) -> None:
        if self._repl_dlg is None:
            self._repl_dlg = FindReplaceDialog(self, replace=True)
            self._repl_dlg.find_next.connect(self._on_dialog_find)
            self._repl_dlg.replace_one.connect(self.replace_current)
            self._repl_dlg.replace_all.connect(self.replace_all)
        f = self._find
        self._repl_dlg.open_with(self._selected_single_line() or f["text"], f["case"], f["wrap"], f["forward"])

    def _on_dialog_find(self, text: str, case: bool, wrap: bool, forward: bool) -> None:
        self.find_text(text, case, forward, wrap, parent=self.sender())

    def find_again(self, forward: bool) -> None:
        if not self._find["text"]:
            self.show_find()
            return
        f = self._find
        self.find_text(f["text"], f["case"], forward, f["wrap"])

    def find_text(self, text: str, case: bool = False, forward: bool = True, wrap: bool = False,
                  parent: QWidget | None = None) -> bool:
        if not text:
            return False
        self._find.update(text=text, case=case, wrap=wrap, forward=forward)
        flags = QTextDocument.FindFlag(0)
        if case:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward
        ed = self.editor
        if ed.find(text, flags):
            return True
        if wrap:
            saved = ed.textCursor()
            ed.moveCursor(QTextCursor.MoveOperation.Start if forward else QTextCursor.MoveOperation.End)
            if ed.find(text, flags):
                return True
            ed.setTextCursor(saved)
        self._message(f'Impossibile trovare "{text}"', parent=parent if isinstance(parent, QWidget) else None)
        return False

    def replace_current(self, text: str, repl: str, case: bool = False, wrap: bool = False) -> None:
        sel = self.editor.textCursor().selectedText()
        match = sel == text if case else sel.lower() == text.lower()
        if match and sel and self.editor.edit_allowed():
            self.editor.textCursor().insertText(repl)
        self.find_text(text, case, True, wrap, parent=self._repl_dlg)

    def replace_all(self, text: str, repl: str, case: bool = False) -> int:
        """Sostituisce tutte le occorrenze (in Dark solo dopo l'ancora). Restituisce quante."""
        if not text:
            return 0
        flags = QTextDocument.FindFlag.FindCaseSensitively if case else QTextDocument.FindFlag(0)
        doc = self.editor.document()
        pos = self.chat.anchor if self.chat.active else 0
        if self.chat.active and self.chat.busy:
            return 0
        count = 0
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        while True:
            found = doc.find(text, pos, flags)
            if found.isNull():
                break
            found.insertText(repl)
            pos = found.position()
            count += 1
        cur.endEditBlock()
        return count

    # ---- Vai a ----
    def show_goto(self) -> None:
        if self.editor.lineWrapMode() != QPlainTextEdit.LineWrapMode.NoWrap:
            return
        dlg = GoToDialog(self, self.editor.textCursor().blockNumber() + 1)

        def go(n: int) -> None:
            if n > self.editor.blockCount():
                self._message("Il numero di riga è oltre il numero totale di righe.", parent=dlg,
                              title="Blocco note - Vai a riga")
                return
            self.goto_line(n)
            dlg.accept()

        dlg.accepted_line.connect(go)
        dlg.exec()

    def goto_line(self, n: int) -> None:
        block = self.editor.document().findBlockByNumber(max(0, n - 1))
        if block.isValid():
            c = self.editor.textCursor()
            c.setPosition(block.position())
            self.editor.setTextCursor(c)
            self.editor.ensureCursorVisible()

    # ------------------------------------------------------------------
    # Digitazione -> notepad.typing
    # ------------------------------------------------------------------
    def _on_text_changed(self) -> None:
        self._update_edit_actions()
        if not self.chat.active:
            self._typing_timer.start()

    def _fire_typing(self) -> None:
        if self.chat.active:
            return
        ev = self.typing.event(self.editor.toPlainText(), self.display_name())
        if ev:
            self.client.emit("notepad.typing", ev)

    # ------------------------------------------------------------------
    # Modalità Dark / chat
    # ------------------------------------------------------------------
    def _hub_connected(self) -> bool:
        return bool(getattr(self.client, "connected", True))

    def set_dark(self, on: bool) -> None:
        if on == self.chat.active:
            return
        if self.act_dark.isChecked() != on:
            self.act_dark.setChecked(on)
            return  # il toggled richiamerà set_dark
        if on:
            text = dark_text(self.editor.toPlainText())
            self._typing_timer.stop()
            self.chat.activate()
            self.setStyleSheet(build_qss(True))
            self.client.emit("notepad.dark_on", {"text": text})
            self._watchdog.start(self.watchdog_ms)
            self._check_reachable()
        else:
            self._watchdog.stop()
            self.chat.deactivate()
            self._refresh_highlight()
            self.setStyleSheet(build_qss(False))
            self.typing.reset(self.editor.toPlainText())
            self.client.emit("notepad.dark_off", {})

    def _check_reachable(self) -> None:
        if not self._hub_connected():
            QTimer.singleShot(self.unreachable_delay_ms, self._marv_unreachable)

    def _marv_unreachable(self) -> None:
        if self.chat.active and self.chat.busy and not self.chat.started and not self._hub_connected():
            self._write_marv_block(UNREACHABLE_TEXT)

    def _end_pos(self) -> int:
        return max(0, self.editor.document().characterCount() - 1)

    def _append(self, text: str) -> None:
        c = QTextCursor(self.editor.document())
        c.movePosition(QTextCursor.MoveOperation.End)
        c.insertText(text)
        self.editor.setTextCursor(c)
        self.editor.ensureCursorVisible()

    def _tail(self, n: int = 4) -> str:
        c = QTextCursor(self.editor.document())
        c.movePosition(QTextCursor.MoveOperation.End)
        c.movePosition(QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor, n)
        return c.selectedText().replace(" ", "\n")

    def _refresh_highlight(self) -> None:
        sels = []
        if self.chat.active:
            doc = self.editor.document()
            for start, end in self.chat.spans:
                if end <= start:
                    continue
                s = QTextEdit.ExtraSelection()
                s.cursor = QTextCursor(doc)
                s.cursor.setPosition(start)
                s.cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                s.format.setForeground(QColor(MARV_COLOR))
                sels.append(s)
        self.editor.setExtraSelections(sels)

    def on_hub_message(self, msg: dict) -> None:
        kind = msg.get("kind")
        if not self.chat.active:
            return
        if kind == "chat.delta":
            self._marv_delta(str(msg.get("text", "")))
        elif kind == "chat.end":
            self._marv_end()
        elif kind == "chat.error":
            self._marv_error(str(msg.get("msg", "")))

    def _marv_delta(self, text: str) -> None:
        if not text:
            return
        first = not self.chat.started
        if first:
            text = text.lstrip("\n")
            if not text:
                return
        sep = self.chat.begin_chunk(self._tail(), self._end_pos()) if first else ""
        self._append(sep + text)
        self.chat.chunk_written(self._end_pos())
        self._refresh_highlight()
        self._watchdog.start(self.watchdog_ms)

    def _trim_trailing(self) -> None:
        """Toglie spazi/newline finali della risposta (senza intaccare il testo precedente)."""
        if not self.chat.spans:
            return
        start = self.chat.spans[-1][0]
        c = QTextCursor(self.editor.document())
        c.movePosition(QTextCursor.MoveOperation.End)
        while c.position() > start:
            c.movePosition(QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor)
            if c.selectedText() in (" ", "\n", " ", "\t"):
                c.removeSelectedText()
            else:
                break

    def _marv_end(self) -> None:
        if not self.chat.busy:
            return
        if self.chat.started:
            self._trim_trailing()
        term = self.chat.finish(self._end_pos())
        if term:
            self._append(term)
        self._finalize_chat_turn()

    def _finalize_chat_turn(self) -> None:
        self._watchdog.stop()
        # niente undo oltre l'ancora: il testo di Marv non è annullabile
        doc = self.editor.document()
        doc.setUndoRedoEnabled(False)
        doc.setUndoRedoEnabled(True)
        c = QTextCursor(doc)
        c.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(c)
        self.editor.ensureCursorVisible()
        self._refresh_highlight()

    def _write_marv_block(self, text: str) -> None:
        """Scrive un blocco di testo come risposta di Marv e chiude il turno."""
        if self.chat.started:
            prefix = "\n"
        else:
            prefix = self.chat.begin_chunk(self._tail(), self._end_pos())
        self._append(prefix + text)
        self.chat.chunk_written(self._end_pos())
        term = self.chat.finish(self._end_pos())
        self._append(term)
        self._finalize_chat_turn()

    def _marv_error(self, msg: str) -> None:
        if not self.chat.active:
            return
        self._write_marv_block(error_text(msg))

    def _chat_send(self) -> None:
        """Doppio Invio: invia a Marv il testo scritto dopo l'ultima risposta."""
        text = self.chat.extract_message(self.editor.text_from_anchor())
        if not text:
            return
        self.client.emit("chat.user", {"text": text})
        self.chat.await_response()
        self._watchdog.start(self.watchdog_ms)
        self._check_reachable()
