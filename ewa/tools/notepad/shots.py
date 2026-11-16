"""Genera gli screenshot offscreen: python -m ewa.tools.notepad.shots"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from ewa.ui.win10 import HubBridge, make_app, screenshot

from .window import NotepadWindow

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "screenshots")


class _Client:
    connected = True

    def emit(self, *a, **k):
        pass


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    app = make_app("notepad")
    bridge = HubBridge()
    win = NotepadWindow(_Client(), bridge=bridge, typing_debounce=60)
    win.show()
    win.editor.setPlainText("Lista della spesa\n\n- latte\n- pane integrale\n- uova\n- caffè\n\n"
                            "Ricordarsi di chiamare Marco domani mattina.\n")
    win.editor.moveCursor(win.editor.textCursor().MoveOperation.Start)
    screenshot(win, f"{OUT}/notepad_light.png")

    win.show_find()
    win._find_dlg.edit_find.setText("pane")
    QTest.qWait(50)
    screenshot(win._find_dlg, f"{OUT}/notepad_find.png")
    win._find_dlg.close()
    win.show_replace()
    screenshot(win._repl_dlg, f"{OUT}/notepad_replace.png")
    win._repl_dlg.close()

    # modalità Dark con due scambi simulati
    win.editor.setPlainText("Giornata pesante. Troppe riunioni e poco tempo per me.")
    win.act_dark.setChecked(True)
    def marv(text):
        for i in range(0, len(text), 6):
            bridge.deliver({"kind": "chat.delta", "text": text[i:i + 6]})
        bridge.deliver({"kind": "chat.end"})
    def user(text):
        win.editor.insertPlainText(text)
        QTest.keyClick(win.editor, Qt.Key.Key_Return)
        QTest.keyClick(win.editor, Qt.Key.Key_Return)
    marv("Troppe riunioni? Immagino che almeno il caffè fosse buono.")
    user("Il caffè era terribile, in realtà.")
    marv("Allora sono tre problemi: riunioni, tempo e caffè. Parti dal caffè.")
    user("Ok, domani porto la moka da casa.")
    marv("Finalmente un piano sensato.")
    win.editor.insertPlainText("Quasi quasi ")
    screenshot(win, f"{OUT}/notepad_dark.png")
    win.act_dark.setChecked(False)
    win.editor.document().setModified(False)


if __name__ == "__main__":
    main()
