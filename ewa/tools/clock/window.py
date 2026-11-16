"""Finestra 'Sveglie e orologio': pivot in alto, pagine, barra comandi in basso."""
from __future__ import annotations

import time
from typing import Any, Callable

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ewa.ui.win10 import PALETTE, UwpWindow, glyph, mdl2_font, ui_font

from .alarm import AlarmPage
from .stopwatch import StopwatchPage
from .timer import TimerPage
from .worldclock import ClockPage

P = PALETTE["light"]
ACCENT = PALETTE["accent"]

TABS = [("alarm", "Sveglia", "alarm"), ("clock", "Orologio", "world"),
        ("timer", "Timer", "timer"), ("stopwatch", "Cronometro", "stopwatch")]
ALIASES = {"sveglia": "alarm", "orologio": "clock", "cronometro": "stopwatch"}


class PivotItem(QPushButton):
    """Voce del pivot: icona + testo, sottolineata in accento se selezionata."""

    def __init__(self, icon: str, text: str):
        super().__init__()
        self.setCheckable(True)
        self.setFlat(True)
        self._icon, self._text = icon, text
        self.setFixedHeight(46)
        self.setFixedWidth(52 + self.fontMetrics().horizontalAdvance(text) * 12 // 10 + 14)
        self._hover = False

    def enterEvent(self, _e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = False
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        sel = self.isChecked()
        if self._hover and not sel:
            p.fillRect(self.rect(), QColor(0, 0, 0, 14))
        col = QColor(P["text"] if (sel or self._hover) else "#6B6B6B")
        p.setPen(col)
        p.setFont(mdl2_font(12))
        w = self.width()
        p.drawText(QRectF(14, 0, 28, self.height() - 4), Qt.AlignmentFlag.AlignCenter, glyph(self._icon))
        p.setFont(ui_font(11.5))
        p.drawText(QRectF(46, 0, w - 50, self.height() - 4),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
        if sel:
            p.fillRect(QRectF(10, self.height() - 4, w - 20, 3), QColor(ACCENT))


class CommandBar(QWidget):
    """Barra comandi UWP: azioni a destra, '...' in fondo."""
    HEIGHT = 48

    def __init__(self):
        super().__init__()
        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("CommandBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#CommandBar {{ background: #E6E6E6; border-top: 1px solid #D0D0D0; }}"
                           f"QPushButton {{ background: transparent; border: none; color: {P['text']}; }}"
                           f"QPushButton:hover {{ background: #D4D4D4; }} QPushButton:pressed {{ background: #BFBFBF; }}")
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.lay.addStretch(1)
        self.buttons: dict[str, QPushButton] = {}

    def set_actions(self, actions: list[tuple[str, str, Callable[[], Any] | None]]) -> None:
        for b in self.buttons.values():
            self.lay.removeWidget(b)
            b.hide()
            b.setParent(None)
            b.deleteLater()
        self.buttons.clear()
        for name, tip, cb in actions:
            b = QPushButton(glyph(name))
            b.setFont(mdl2_font(12))
            b.setFixedSize(48, self.HEIGHT - 1)
            b.setToolTip(tip)
            if cb:
                b.clicked.connect(cb)
            self.lay.addWidget(b)
            self.buttons[name] = b


class ClockWindow(UwpWindow):
    def __init__(self, client: Any = None, tab: str = "timer", now: Callable[[], float] = time.monotonic):
        super().__init__("Sveglie e orologio", theme="light")
        self.resize(700, 560)
        self.setMinimumSize(520, 460)
        self.client = client
        emit = client.emit if client is not None else (lambda *a, **k: None)
        lay = QVBoxLayout(self.content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        # pivot
        pivot = QHBoxLayout()
        pivot.setContentsMargins(14, 6, 14, 0)
        pivot.setSpacing(0)
        self.items: dict[str, PivotItem] = {}
        for key, text, icon in TABS:
            it = PivotItem(icon, text)
            it.clicked.connect(lambda _c=False, k=key: self.set_tab(k))
            pivot.addWidget(it)
            self.items[key] = it
        pivot.addStretch(1)
        lay.addLayout(pivot)
        # pagine
        self.stack = QStackedWidget()
        self.alarm = AlarmPage()
        self.clock = ClockPage()
        self.timer = TimerPage(emit, now)
        self.stopwatch = StopwatchPage(emit, now)
        self.pages = {"alarm": self.alarm, "clock": self.clock, "timer": self.timer, "stopwatch": self.stopwatch}
        for key, _t, _i in TABS:
            self.stack.addWidget(self.pages[key])
        lay.addWidget(self.stack, 1)
        self.bar = CommandBar()
        lay.addWidget(self.bar)
        self.timer.editing_changed.connect(lambda _on: self._update_bar())
        # tick unico (timer/cronometro/orologio)
        self._tick = QTimer(self)
        self._tick.setInterval(40)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._last_clock = 0.0
        tab = ALIASES.get(tab, tab)
        self.tab = tab if tab in self.pages else "timer"
        self.set_tab(self.tab)
        emit("clock.open", {"tab": self.tab})

    def set_tab(self, key: str) -> None:
        self.tab = key
        for k, it in self.items.items():
            it.setChecked(k == key)
        self.stack.setCurrentWidget(self.pages[key])
        self._update_bar()

    def _update_bar(self) -> None:
        if self.tab == "timer":
            if self.timer.in_editor:
                self.bar.set_actions([])
            else:
                self.bar.set_actions([("add", "Aggiungi nuovo timer", self.timer.open_new),
                                      ("edit", "Modifica timer", self.timer.toggle_edit_mode),
                                      ("more", "Altro", None)])
        elif self.tab == "stopwatch":
            self.bar.set_actions([("more", "Altro", None)])
        else:
            self.bar.set_actions([("add", "Aggiungi", None), ("edit", "Modifica", None), ("more", "Altro", None)])

    def _on_tick(self) -> None:
        self.timer.tick()
        if self.tab == "stopwatch":
            self.stopwatch.tick()
        t = time.monotonic()
        if self.tab == "clock" and t - self._last_clock > 1:
            self._last_clock = t
            self.clock.tick()
