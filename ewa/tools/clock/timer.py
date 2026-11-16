"""Scheda Timer: card con anello di avanzamento, editor con colonne ore/minuti/secondi."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from ewa.ui.win10 import PALETTE, glyph, mdl2_font, ui_font

from .models import DONE, IDLE, PAUSED, RUNNING, TimerModel, fmt_hms

P = PALETTE["light"]
ACCENT = PALETTE["accent"]


def round_button(name: str, size: int = 44, accent: bool = False) -> QPushButton:
    """Pulsante circolare con icona (play/pausa/reimposta...)."""
    b = QPushButton(glyph(name))
    b.setFont(mdl2_font(13 if size >= 44 else 11))
    b.setFixedSize(size, size)
    bg = ACCENT if accent else "transparent"
    fg = "white" if accent else P["text"]
    b.setStyleSheet(f"""
        QPushButton {{ border: 2px solid {ACCENT if accent else P['text']}; border-radius: {size // 2}px;
                      background: {bg}; color: {fg}; }}
        QPushButton:hover {{ background: {PALETTE['accent_light'] if accent else 'rgba(0,0,0,25)'}; }}
        QPushButton:pressed {{ background: {PALETTE['accent_dark'] if accent else 'rgba(0,0,0,50)'}; color: white; }}
        QPushButton:disabled {{ border-color: #BDBDBD; color: #BDBDBD; background: transparent; }}
    """)
    return b


class Ring(QWidget):
    """Anello di avanzamento: la parte blu si svuota con il tempo residuo."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.fraction = 1.0
        self.done = False

    def set_fraction(self, f: float, done: bool) -> None:
        if abs(f - self.fraction) > 1e-4 or done != self.done:
            self.fraction, self.done = f, done
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 12
        r = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        track = QColor(255, 255, 255, 90) if self.done else QColor("#D6D6D6")
        pen = QPen(track, 3)
        p.setPen(pen)
        p.drawEllipse(r)
        if self.fraction > 0:
            pen = QPen(QColor("white") if self.done else QColor(ACCENT), 8 if side > 150 else 6)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.drawArc(r, 90 * 16, int(-self.fraction * 360 * 16))


class TimerCard(QWidget):
    """Una scheda-timer: nome, anello con tempo residuo, play/pausa, reimposta, espandi."""
    edit_requested = Signal(object)
    delete_requested = Signal(object)
    expand_toggled = Signal(object)

    def __init__(self, model: TimerModel):
        super().__init__()
        self.model = model
        self.expanded = False
        self._beeped = False
        self.setObjectName("TimerCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(280, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 14)
        v.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(0)
        self.name = QLabel(model.label)
        self.name.setFont(ui_font(11))
        top.addWidget(self.name, 1)
        self.btn_edit = self._mini("edit", "Modifica timer")
        self.btn_del = self._mini("delete", "Elimina timer")
        self.btn_expand = self._mini("fullscreen", "Espandi")
        self.btn_edit.clicked.connect(lambda: self.edit_requested.emit(self))
        self.btn_del.clicked.connect(lambda: self.delete_requested.emit(self))
        self.btn_expand.clicked.connect(self._toggle_expand)
        for b in (self.btn_edit, self.btn_del, self.btn_expand):
            top.addWidget(b)
        v.addLayout(top)
        # anello con tempo e stato sovrapposti
        self.ring = Ring()
        ring_lay = QVBoxLayout(self.ring)
        ring_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time = QLabel("00:01:00")
        self.time.setFont(ui_font(26, QFont.Weight.Light))
        self.time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status = QLabel("")
        self.status.setFont(ui_font(10))
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ring_lay.addWidget(self.time)
        ring_lay.addWidget(self.status)
        v.addWidget(self.ring, 1)
        btns = QHBoxLayout()
        btns.setSpacing(16)
        btns.addStretch(1)
        self.btn_play = round_button("play", 44, accent=False)
        self.btn_reset = round_button("reset", 44)
        self.btn_play.clicked.connect(self._on_play)
        self.btn_reset.clicked.connect(self._on_reset)
        btns.addWidget(self.btn_play)
        btns.addWidget(self.btn_reset)
        btns.addStretch(1)
        v.addSpacing(6)
        v.addLayout(btns)
        self.set_edit_mode(False)
        self.refresh()

    @staticmethod
    def _mini(name: str, tip: str) -> QPushButton:
        b = QPushButton(glyph(name))
        b.setFont(mdl2_font(10))
        b.setFixedSize(36, 32)
        b.setToolTip(tip)
        b.setFlat(True)
        b.setObjectName("MiniButton")
        return b

    def set_edit_mode(self, on: bool) -> None:
        self.btn_edit.setVisible(on)
        self.btn_del.setVisible(on)

    def _toggle_expand(self) -> None:
        self.expanded = not self.expanded
        self.expand_toggled.emit(self)

    def _on_play(self) -> None:
        if self.model.state == DONE:
            return
        self.model.toggle()
        self.refresh()

    def _on_reset(self) -> None:
        self.model.reset()
        self._beeped = False
        self.refresh()

    def refresh(self) -> None:
        m = self.model
        if m.state == DONE and not self._beeped:
            self._beeped = True
            QApplication.beep()
        done = m.state == DONE
        self.name.setText(m.label)
        self.time.setText(fmt_hms(m.remaining()))
        self.status.setText("Tempo scaduto" if done else ("In pausa" if m.state == PAUSED else ""))
        self.ring.set_fraction(m.fraction_left(), done)
        self.btn_play.setText(glyph("pause" if m.state == RUNNING else "play"))
        self.btn_play.setEnabled(not done)
        self.btn_reset.setEnabled(m.state != IDLE)
        self.btn_expand.setText(glyph("fullscreen"))
        self.btn_expand.setToolTip("Riduci" if self.expanded else "Espandi")
        self._style(done)

    def _style(self, done: bool) -> None:
        if getattr(self, "_styled", None) == done:
            return
        self._styled = done
        fg = "white" if done else P["text"]
        sub = "rgba(255,255,255,200)" if done else P["text_secondary"]
        bg = ACCENT if done else P["surface"]
        self.setStyleSheet(f"""
            #TimerCard {{ background: {bg}; border: 1px solid {P['border'] if not done else ACCENT}; }}
            #TimerCard QLabel {{ color: {fg}; background: transparent; }}
            #TimerCard QPushButton#MiniButton {{ background: transparent; border: none; color: {fg}; }}
            #TimerCard QPushButton#MiniButton:hover {{ background: rgba(0,0,0,30); }}
        """)
        self.status.setStyleSheet(f"color: {sub};")
        if done:
            for b in (self.btn_play, self.btn_reset):
                b.setStyleSheet(b.styleSheet().replace(P["text"], "white").replace("rgba(0,0,0,25)", "rgba(255,255,255,50)"))
        else:
            for b, acc in ((self.btn_play, False), (self.btn_reset, False)):
                nb = round_button("play", 44, acc)
                b.setStyleSheet(nb.styleSheet())


# ---------------------------------------------------------------------------
# Editor
# ---------------------------------------------------------------------------
class LoopColumn(QWidget):
    """Colonna scorrevole 'loop' stile UWP: valore precedente, corrente (evidenziato), successivo."""
    ROW = 44
    ARROW = 32
    changed = Signal(int)

    def __init__(self, maximum: int, value: int = 0, caption: str = ""):
        super().__init__()
        self.maximum = maximum
        self.value = value
        self.caption = caption
        self.setFixedSize(96, self.ARROW * 2 + self.ROW * 3)
        self._hover: str | None = None
        self.setMouseTracking(True)

    def set_value(self, v: int) -> None:
        self.value = v % (self.maximum + 1)
        self.update()
        self.changed.emit(self.value)

    def step(self, d: int) -> None:
        self.set_value(self.value + d)

    def wheelEvent(self, e) -> None:
        self.step(-1 if e.angleDelta().y() > 0 else 1)

    def _zone(self, y: float) -> str:
        if y < self.ARROW:
            return "up"
        if y > self.height() - self.ARROW:
            return "down"
        return f"row{int((y - self.ARROW) // self.ROW)}"

    def mouseMoveEvent(self, e) -> None:
        z = self._zone(e.position().y())
        if z != self._hover:
            self._hover = z
            self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = None
        self.update()

    def mousePressEvent(self, e) -> None:
        z = self._zone(e.position().y())
        self.step({"up": -1, "down": 1, "row0": -1, "row2": 1}.get(z, 0))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = self.maximum + 1
        for i in range(3):
            y = self.ARROW + i * self.ROW
            r = QRectF(0, y, self.width(), self.ROW)
            v = (self.value + i - 1) % n
            cur = i == 1
            if cur:
                p.fillRect(r.adjusted(0, 1, 0, -1), QColor(ACCENT))
            elif self._hover == f"row{i}":
                p.fillRect(r.adjusted(0, 1, 0, -1), QColor("#E5E5E5"))
            p.setPen(QColor("white") if cur else QColor(P["text"]))
            p.setFont(ui_font(15 if cur else 13))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, f"{v:02d}")
        p.setFont(mdl2_font(9))
        for zone, y0, ch in (("up", 0, "⌃"), ("down", self.height() - self.ARROW, "⌄")):
            r = QRectF(0, y0, self.width(), self.ARROW)
            if self._hover == zone:
                p.fillRect(r, QColor("#E5E5E5"))
            p.setPen(QColor(P["text_secondary"]))
            p.setFont(ui_font(11))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, ch)


class TimerEditor(QWidget):
    """Pannello 'Nuovo timer' / 'Modifica timer'."""
    saved = Signal(int, str)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        self.title = QLabel("Nuovo timer")
        self.title.setFont(ui_font(14, ui_font().weight()))
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.title)
        outer.addSpacing(10)
        cols = QHBoxLayout()
        cols.setSpacing(14)
        cols.addStretch(1)
        self.h, self.m, self.s = LoopColumn(23), LoopColumn(59), LoopColumn(59)
        for col, cap in ((self.h, "ore"), (self.m, "minuti"), (self.s, "secondi")):
            c = QVBoxLayout()
            c.setSpacing(2)
            c.addWidget(col)
            lab = QLabel(cap)
            lab.setFont(ui_font(10))
            lab.setStyleSheet(f"color: {P['text_secondary']};")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            c.addWidget(lab)
            cols.addLayout(c)
        cols.addStretch(1)
        outer.addLayout(cols)
        outer.addSpacing(14)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Nome timer")
        self.name.setFont(ui_font(11))
        self.name.setFixedSize(332, 34)
        self.name.setStyleSheet(f"""QLineEdit {{ background: {P['surface']}; border: 2px solid #8A8A8A;
            padding: 0 8px; }} QLineEdit:hover {{ border-color: #333; }} QLineEdit:focus {{ border-color: {ACCENT}; }}""")
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.name)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addSpacing(16)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch(1)
        self.btn_save = QPushButton(glyph("check") + "  Salva")
        self.btn_cancel = QPushButton("✕  Annulla" if True else "")
        for b, acc in ((self.btn_save, True), (self.btn_cancel, False)):
            b.setFont(ui_font(10.5))
            b.setFixedSize(162, 36)
            bg, fg, hov = (ACCENT, "white", PALETTE["accent_light"]) if acc else ("#CCCCCC", "black", "#B8B8B8")
            b.setStyleSheet(f"QPushButton {{ background: {bg}; color: {fg}; border: 2px solid transparent; }}"
                            f"QPushButton:hover {{ background: {hov}; }}"
                            f"QPushButton:pressed {{ background: {PALETTE['accent_dark'] if acc else '#999'}; }}")
            btns.addWidget(b)
        btns.addStretch(1)
        outer.addLayout(btns)
        outer.addStretch(2)
        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.cancelled.emit)
        self._default_name = "Timer"

    def open(self, title: str, seconds: int, name: str, default_name: str) -> None:
        self.title.setText(title)
        self.h.set_value(seconds // 3600)
        self.m.set_value(seconds % 3600 // 60)
        self.s.set_value(seconds % 60)
        self.name.setText(name)
        self._default_name = default_name

    def _save(self) -> None:
        total = self.h.value * 3600 + self.m.value * 60 + self.s.value
        self.saved.emit(max(1, total), self.name.text().strip() or self._default_name)


# ---------------------------------------------------------------------------
# Pagina
# ---------------------------------------------------------------------------
class TimerPage(QWidget):
    """Griglia di timer + editor. Possiede i TimerModel (uno per card)."""
    editing_changed = Signal(bool)

    def __init__(self, emit, now):
        super().__init__()
        self._emit, self._now = emit, now
        self.cards: list[TimerCard] = []
        self._counter = 0
        self._editing: TimerCard | None = None
        self.edit_mode = False
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        # lista
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(24, 8, 24, 16)
        self.grid.setSpacing(12)
        self.scroll.setWidget(self.grid_host)
        self.stack.addWidget(self.scroll)
        self.editor = TimerEditor()
        self.editor.saved.connect(self._on_saved)
        self.editor.cancelled.connect(self._close_editor)
        self.stack.addWidget(self.editor)
        self.add_timer(60)   # timer predefinito: 1 minuto

    # --- gestione card ---
    def _next_name(self) -> str:
        self._counter += 1
        return f"Timer ({self._counter})"

    def add_timer(self, seconds: int, label: str | None = None) -> TimerCard:
        m = TimerModel(seconds, label or self._next_name(), self._emit, self._now)
        card = TimerCard(m)
        card.edit_requested.connect(self.open_editor)
        card.delete_requested.connect(self._delete)
        card.expand_toggled.connect(lambda _c: self._relayout())
        card.set_edit_mode(self.edit_mode)
        self.cards.append(card)
        self._relayout()
        return card

    def _delete(self, card: TimerCard) -> None:
        card.model.reset()
        self.cards.remove(card)
        card.setParent(None)
        card.deleteLater()
        if not self.cards:
            self.set_edit_mode(False)
        self._relayout()

    def _relayout(self) -> None:
        for i in reversed(range(self.grid.count())):
            self.grid.takeAt(i)
        expanded = next((c for c in self.cards if c.expanded), None)
        for c in self.cards:
            c.setVisible(expanded is None or c is expanded)
        shown = [expanded] if expanded else self.cards
        for i, c in enumerate(shown):
            self.grid.addWidget(c, i // 2, i % 2) if not expanded else self.grid.addWidget(c, 0, 0, 1, 2)
        for col in (0, 1):
            self.grid.setColumnStretch(col, 1)
        rows = (len(shown) + 1) // 2
        for r in range(rows + 1):
            self.grid.setRowStretch(r, 1 if r < rows else 0)

    def set_edit_mode(self, on: bool) -> None:
        self.edit_mode = on and bool(self.cards)
        for c in self.cards:
            c.set_edit_mode(self.edit_mode)

    def toggle_edit_mode(self) -> None:
        self.set_edit_mode(not self.edit_mode)

    # --- editor ---
    def open_new(self) -> None:
        self._editing = None
        self.editor.open("Nuovo timer", 60, "", f"Timer ({self._counter + 1})")
        self._show_editor(True)

    def open_editor(self, card: TimerCard) -> None:
        self._editing = card
        self.editor.open("Modifica timer", card.model.seconds, card.model.label, card.model.label)
        self._show_editor(True)

    def _show_editor(self, on: bool) -> None:
        self.stack.setCurrentWidget(self.editor if on else self.scroll)
        self.editing_changed.emit(on)

    def _close_editor(self) -> None:
        self._editing = None
        self._show_editor(False)

    def _on_saved(self, seconds: int, name: str) -> None:
        if self._editing is not None:
            self._editing.model.configure(seconds, name)
            self._editing._beeped = False
            self._editing.refresh()
        else:
            if name == f"Timer ({self._counter + 1})":
                name = self._next_name()
            else:
                self._counter += 1
            self.add_timer(seconds, name)
        self._close_editor()

    @property
    def in_editor(self) -> bool:
        return self.stack.currentWidget() is self.editor

    def tick(self) -> None:
        for c in self.cards:
            c.model.tick()
            c.refresh()
