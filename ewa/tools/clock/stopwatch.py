"""Scheda Cronometro: tempo grande, play/pausa, giro, reimposta, tabella giri."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ewa.ui.win10 import PALETTE, glyph, ui_font

from .models import StopwatchModel, fmt_stopwatch
from .timer import round_button

P = PALETTE["light"]
FASTEST, SLOWEST = "#107C10", "#C42B1C"


class StopwatchPage(QWidget):
    def __init__(self, emit, now):
        super().__init__()
        self.model = StopwatchModel(emit, now)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 10, 24, 8)
        v.setSpacing(0)
        self.time = QLabel(fmt_stopwatch(0))
        self.time.setFont(ui_font(40, QFont.Weight.Light))
        self.time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.time)
        v.addSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addStretch(1)
        self.btn_play = round_button("play", 48, accent=False)
        self.btn_lap = round_button("flag", 48)
        self.btn_reset = round_button("reset", 48)
        for b in (self.btn_play, self.btn_lap, self.btn_reset):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        v.addSpacing(14)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Giri", "Tempo", "Totale"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setHighlightSections(False)
        hh.setSectionsClickable(False)
        self.table.setFont(ui_font(11))
        self.table.setStyleSheet(f"""
            QTableWidget {{ background: transparent; border: none; }}
            QTableWidget::item {{ border-bottom: 1px solid #E1E1E1; padding-left: 12px; }}
            QHeaderView::section {{ background: transparent; border: none; border-bottom: 1px solid {P['border']};
                color: {P['text_secondary']}; text-align: left; padding: 4px 15px; font-size: 13px; }}
        """)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        v.addWidget(self.table, 1)
        self.btn_play.clicked.connect(self._play)
        self.btn_lap.clicked.connect(self._lap)
        self.btn_reset.clicked.connect(self._reset)
        self.refresh()

    def _play(self) -> None:
        self.model.toggle()
        self.refresh()

    def _lap(self) -> None:
        self.model.lap()
        self._fill_laps()
        self.refresh()

    def _reset(self) -> None:
        if self.model.running:
            return
        self.model.reset()
        self._fill_laps()
        self.refresh()

    def _fill_laps(self) -> None:
        m = self.model
        fast, slow = m.extremes()
        self.table.setRowCount(len(m.laps))
        n_laps = len(m.laps)
        for i, (lap, total) in enumerate(m.laps):
            row = n_laps - 1 - i          # giro piu' recente in alto
            for c, txt in enumerate((f"{i + 1:02d}", fmt_stopwatch(lap), fmt_stopwatch(total))):
                it = QTableWidgetItem(txt)
                if i == fast:
                    it.setForeground(QColor(FASTEST))
                elif i == slow:
                    it.setForeground(QColor(SLOWEST))
                self.table.setItem(row, c, it)
            self.table.setRowHeight(row, 38)
        self.table.scrollToTop()

    def refresh(self) -> None:
        m = self.model
        self.time.setText(fmt_stopwatch(m.elapsed()))
        self.btn_play.setText(glyph("pause" if m.running else "play"))
        self.btn_lap.setEnabled(m.running)
        self.btn_reset.setEnabled(not m.running and (m.elapsed() > 0 or bool(m.laps)))

    def tick(self) -> None:
        if self.model.running:
            self.time.setText(fmt_stopwatch(self.model.elapsed()))
