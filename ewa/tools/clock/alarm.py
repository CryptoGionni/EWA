"""Scheda Sveglia: solo grafica (lista di sveglie di esempio con interruttori)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ewa.ui.win10 import PALETTE, ui_font

P = PALETTE["light"]
ACCENT = PALETTE["accent"]


class ToggleSwitch(QWidget):
    """Interruttore Win10 (40x20): acceso = riempito di accento."""
    toggled = Signal(bool)

    def __init__(self, on: bool = False):
        super().__init__()
        self.on = on
        self.setFixedSize(44, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, _e) -> None:
        self.on = not self.on
        self.update()
        self.toggled.emit(self.on)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(2, 2, 40, 18)
        if self.on:
            p.setBrush(QColor(ACCENT))
            p.setPen(QColor(ACCENT))
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor("#333333"))
            p.setPen(QColor("#333333"))
        p.drawRoundedRect(r, 9, 9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white") if self.on else QColor("#333333"))
        d = 10
        x = 42 - 5 - d if self.on else 7
        p.drawEllipse(QRectF(x, 6, d, d))


class AlarmTile(QWidget):
    def __init__(self, time: str, name: str, days: str, on: bool):
        super().__init__()
        self.setObjectName("AlarmTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(110)
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 10, 16, 10)
        v = QVBoxLayout()
        v.setSpacing(0)
        self.t = QLabel(time)
        self.t.setFont(ui_font(30, QFont.Weight.Light))
        self.n = QLabel(name)
        self.n.setFont(ui_font(11))
        self.d = QLabel(days)
        self.d.setFont(ui_font(10))
        v.addWidget(self.t)
        v.addWidget(self.n)
        v.addWidget(self.d)
        h.addLayout(v, 1)
        self.sw = ToggleSwitch(on)
        self.sw.toggled.connect(self._style)
        h.addWidget(self.sw, 0, Qt.AlignmentFlag.AlignVCenter)
        self._style(on)

    def _style(self, on: bool) -> None:
        sec = P["text_secondary"] if on else "#8A8A8A"
        main = P["text"] if on else "#8A8A8A"
        self.setStyleSheet(f"""#AlarmTile {{ background: {P['surface']}; border: 1px solid {P['border']}; }}
            #AlarmTile QLabel {{ background: transparent; color: {main}; }}""")
        self.d.setStyleSheet(f"color: {sec};")


class AlarmPage(QWidget):
    SAMPLES = [("07:00", "Sveglia", "Lun, Mar, Mer, Gio, Ven", True),
               ("07:30", "Palestra", "Sab", False),
               ("09:15", "Riunione", "Lun, Mer", True),
               ("22:45", "Sveglia", "Una volta", False)]

    def __init__(self):
        super().__init__()
        g = QGridLayout(self)
        g.setContentsMargins(24, 8, 24, 16)
        g.setSpacing(12)
        self.tiles = [AlarmTile(*s) for s in self.SAMPLES]
        for i, t in enumerate(self.tiles):
            g.addWidget(t, i // 2, i % 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        g.setRowStretch(len(self.tiles) // 2 + 1, 1)
