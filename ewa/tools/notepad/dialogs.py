"""Dialoghi del Blocco note: Trova, Sostituisci, Vai a riga."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (QCheckBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QVBoxLayout, QWidget)

from ewa.ui.win10 import ui_font


class FindReplaceDialog(QDialog):
    """Finestra Trova (replace=False) o Sostituisci (replace=True), non modale."""
    find_next = Signal(str, bool, bool, bool)      # testo, maiuscole, continuo, direzione giù
    replace_one = Signal(str, str, bool, bool)     # trova, sostituisci con, maiuscole, continuo
    replace_all = Signal(str, str, bool)

    def __init__(self, parent: QWidget, replace: bool = False):
        super().__init__(parent)
        self.replace_mode = replace
        self.setWindowTitle("Sostituisci" if replace else "Trova")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFont(ui_font(9))

        self.edit_find = QLineEdit()
        self.edit_repl = QLineEdit()
        self.chk_case = QCheckBox("Maiuscole/minuscole")
        self.chk_wrap = QCheckBox("Disponi testo in modo continuo")
        self.rb_up = QRadioButton("Su")
        self.rb_down = QRadioButton("Giù")
        self.rb_down.setChecked(True)
        self.btn_next = QPushButton("Trova successivo")
        self.btn_next.setDefault(True)
        self.btn_cancel = QPushButton("Annulla")

        grid = QGridLayout(self)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel("Trova:"), 0, 0)
        grid.addWidget(self.edit_find, 0, 1)
        grid.addWidget(self.btn_next, 0, 2)
        row = 1
        if replace:
            self.btn_repl = QPushButton("Sostituisci")
            self.btn_repl_all = QPushButton("Sostituisci tutto")
            grid.addWidget(QLabel("Sostituisci con:"), 1, 0)
            grid.addWidget(self.edit_repl, 1, 1)
            grid.addWidget(self.btn_repl, 1, 2)
            grid.addWidget(self.btn_repl_all, 2, 2)
            grid.addWidget(self.btn_cancel, 3, 2)
            checks = QVBoxLayout()
            checks.addWidget(self.chk_case)
            checks.addWidget(self.chk_wrap)
            checks.addStretch(1)
            grid.addLayout(checks, 2, 0, 2, 2, Qt.AlignmentFlag.AlignBottom)
            self.btn_repl.clicked.connect(self._on_replace)
            self.btn_repl_all.clicked.connect(self._on_replace_all)
        else:
            grid.addWidget(self.btn_cancel, 1, 2, Qt.AlignmentFlag.AlignTop)
            bottom = QHBoxLayout()
            checks = QVBoxLayout()
            checks.addWidget(self.chk_case)
            checks.addWidget(self.chk_wrap)
            bottom.addLayout(checks)
            box = QGroupBox("Direzione")
            bl = QHBoxLayout(box)
            bl.addWidget(self.rb_up)
            bl.addWidget(self.rb_down)
            bottom.addWidget(box)
            bottom.addStretch(1)
            grid.addLayout(bottom, 1, 0, 2, 2)
        self.layout().setSizeConstraint(self.layout().SizeConstraint.SetFixedSize)

        self.btn_next.clicked.connect(self._on_next)
        self.btn_cancel.clicked.connect(self.close)
        self.edit_find.textChanged.connect(self._sync_buttons)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has = bool(self.edit_find.text())
        self.btn_next.setEnabled(has)
        if self.replace_mode:
            self.btn_repl.setEnabled(has)
            self.btn_repl_all.setEnabled(has)

    def set_state(self, text: str, case: bool, wrap: bool, forward: bool) -> None:
        if text:
            self.edit_find.setText(text)
        self.chk_case.setChecked(case)
        self.chk_wrap.setChecked(wrap)
        (self.rb_down if forward else self.rb_up).setChecked(True)

    def _on_next(self) -> None:
        self.find_next.emit(self.edit_find.text(), self.chk_case.isChecked(),
                            self.chk_wrap.isChecked(), self.rb_down.isChecked())

    def _on_replace(self) -> None:
        self.replace_one.emit(self.edit_find.text(), self.edit_repl.text(),
                              self.chk_case.isChecked(), self.chk_wrap.isChecked())

    def _on_replace_all(self) -> None:
        self.replace_all.emit(self.edit_find.text(), self.edit_repl.text(), self.chk_case.isChecked())

    def open_with(self, text: str, case: bool, wrap: bool, forward: bool) -> None:
        self.set_state(text, case, wrap, forward)
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit_find.setFocus()
        self.edit_find.selectAll()


class GoToDialog(QDialog):
    """Vai a riga: restituisce il numero tramite `line_number`."""
    accepted_line = Signal(int)

    def __init__(self, parent: QWidget, current: int = 1):
        super().__init__(parent)
        self.setWindowTitle("Vai a riga")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFont(ui_font(9))
        self.edit = QLineEdit(str(current))
        self.edit.setValidator(QIntValidator(1, 999999999, self))
        self.btn_go = QPushButton("Vai a")
        self.btn_go.setDefault(True)
        self.btn_cancel = QPushButton("Annulla")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(QLabel("Numero riga:"))
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_go)
        row.addWidget(self.btn_cancel)
        lay.addLayout(row)
        self.setFixedWidth(260)
        self.btn_go.clicked.connect(self._go)
        self.btn_cancel.clicked.connect(self.reject)
        self.edit.selectAll()

    def line_number(self) -> int:
        try:
            return int(self.edit.text())
        except ValueError:
            return 0

    def _go(self) -> None:
        n = self.line_number()
        if n > 0:
            self.accepted_line.emit(n)
