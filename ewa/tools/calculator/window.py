"""Finestra della Calcolatrice (stile app UWP Windows 10, tema chiaro)."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QPoint, QPropertyAnimation, QRect, QEasingCurve, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QPainter
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ewa.tools.calculator.engine import Calculator, SCIENTIFIC, STANDARD, format_number
from ewa.ui.win10 import PALETTE, UwpWindow, glyph, icon_button, mdl2_font, ui_font

P = PALETTE["light"]
ACCENT = PALETTE["accent"]
BG = "#E6E6E6"            # sfondo calcolatrice (fra i tasti)
PANEL_BG = "#F2F2F2"
WIDE_WIDTH = 560          # oltre questa larghezza il pannello cronologia sta a destra
PANEL_WIDTH = 320
SEMIBOLD = QFont.Weight.DemiBold


def px(n: float) -> float:
    """Dimensione font UWP (pixel effettivi) -> punti."""
    return n * 0.75


# ---------------------------------------------------------------------------
# Widget di base
# ---------------------------------------------------------------------------
class FitLabel(QWidget):
    """Testo allineato a destra: si rimpicciolisce se non entra (o è troncato a sinistra)."""

    def __init__(self, max_px: float, min_px: float | None = None, color: str = P["text"],
                 weight: QFont.Weight = SEMIBOLD, elide: bool = False, margin: int = 12,
                 height: int | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._max, self._min = max_px, min_px or max_px
        self._color, self._weight, self._elide, self._m = color, weight, elide, margin
        self._text = ""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if height:
            self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def setText(self, t: str) -> None:
        if t != self._text:
            self._text = t
            self.update()

    def text(self) -> str:
        return self._text

    def current_px(self) -> float:
        r = self.width() - 2 * self._m
        size = self._max
        while size > self._min:
            if QFontMetrics(ui_font(px(size), self._weight)).horizontalAdvance(self._text) <= r:
                break
            size -= 2
        return size

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        r = self.rect().adjusted(self._m, 0, -self._m, 0)
        size = self.current_px()
        f = ui_font(px(size), self._weight)
        p.setFont(f)
        p.setPen(QColor(self._color))
        txt = self._text
        if QFontMetrics(f).horizontalAdvance(txt) > r.width():
            txt = QFontMetrics(f).elidedText(txt, Qt.TextElideMode.ElideLeft, r.width())
        p.drawText(r, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), txt)


class CalcButton(QPushButton):
    """Tasto della calcolatrice. kind: digit | op | fn | eq | mem | menu."""

    def __init__(self, text: str, kind: str, key: str, font: QFont | None = None):
        super().__init__(text)
        self.key = key
        self.setProperty("kind", kind)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFont(font or ui_font(px(18)))
        self.setCursor(Qt.CursorShape.ArrowCursor)


QSS = f"""
#CalcRoot, #UwpContent {{ background: {BG}; }}
QPushButton[kind="digit"] {{ background: #FAFAFA; border: none; color: #000; }}
QPushButton[kind="digit"]:hover {{ background: #E5E5E5; }}
QPushButton[kind="digit"]:pressed {{ background: #C8C8C8; }}
QPushButton[kind="op"], QPushButton[kind="fn"] {{ background: #F0F0F0; border: none; color: #000; }}
QPushButton[kind="op"]:hover, QPushButton[kind="fn"]:hover {{ background: #D9D9D9; }}
QPushButton[kind="op"]:pressed, QPushButton[kind="fn"]:pressed {{ background: #BFBFBF; }}
QPushButton[kind="op"]:disabled, QPushButton[kind="fn"]:disabled, QPushButton[kind="digit"]:disabled
    {{ color: #A0A0A0; }}
QPushButton[kind="eq"] {{ background: {ACCENT}; border: none; color: #FFF; }}
QPushButton[kind="eq"]:hover {{ background: {PALETTE['accent_light']}; }}
QPushButton[kind="eq"]:pressed {{ background: {PALETTE['accent_dark']}; }}
QPushButton[kind="eq"]:disabled {{ background: #9CC8EC; color: #E8F1FA; }}
QPushButton[kind="mem"], QPushButton[kind="menu"] {{ background: transparent; border: none; color: #000; }}
QPushButton[kind="mem"]:hover, QPushButton[kind="menu"]:hover {{ background: #D4D4D4; }}
QPushButton[kind="mem"]:pressed, QPushButton[kind="menu"]:pressed {{ background: #BDBDBD; }}
QPushButton[kind="mem"]:disabled {{ color: #A6A6A6; background: transparent; }}
QPushButton[kind="menu"][on="true"] {{ color: {ACCENT}; }}
QPushButton[kind="mem"][on="true"] {{ color: {ACCENT}; }}
QFrame#Popup {{ background: #F2F2F2; border: 1px solid #C8C8C8; }}
"""


# ---------------------------------------------------------------------------
# Pannello Cronologia / Memoria
# ---------------------------------------------------------------------------
class _Row(QFrame):
    """Voce cliccabile con sfondo in hover."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("Row")
        self.setStyleSheet("#Row { background: transparent; } #Row:hover { background: #E1E1E1; }")

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class MemoryRow(_Row):
    action = Signal(str)

    def __init__(self, text: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 4)
        lay.setSpacing(0)
        self.value = FitLabel(24, 16, height=40)
        self.value.setText(text)
        lay.addWidget(self.value)
        self.buttons = QWidget()
        bl = QHBoxLayout(self.buttons)
        bl.setContentsMargins(12, 0, 8, 0)
        bl.setSpacing(2)
        bl.addStretch(1)
        for label, act in (("MC", "mc"), ("M+", "mp"), ("M−", "mm")):
            b = QPushButton(label)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setFont(ui_font(px(13), SEMIBOLD))
            b.setFixedSize(44, 26)
            b.setStyleSheet(f"QPushButton {{ background: #D4D4D4; border: none; }}"
                            f"QPushButton:hover {{ background: #C2C2C2; }}"
                            f"QPushButton:pressed {{ background: {ACCENT}; color: white; }}")
            b.clicked.connect(lambda _=False, a=act: self.action.emit(a))
            bl.addWidget(b)
        lay.addWidget(self.buttons)
        self.buttons.setVisible(False)

    def enterEvent(self, e) -> None:
        self.buttons.setVisible(True)

    def leaveEvent(self, e) -> None:
        self.buttons.setVisible(False)


class HistoryPanel(QWidget):
    """Pannello con schede Cronologia / Memoria (come l'originale)."""
    history_clicked = Signal(int)
    memory_clicked = Signal(int)
    memory_action = Signal(str, int)
    clear_history = Signal()
    clear_memory = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("HistoryPanel")
        self.setStyleSheet(f"#HistoryPanel {{ background: {PANEL_BG}; }}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.tab = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 8, 12, 0)
        head.setSpacing(16)
        self.tab_btns: list[QPushButton] = []
        for i, name in enumerate(("Cronologia", "Memoria")):
            b = QPushButton(name)
            b.setFlat(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setFont(ui_font(px(18), SEMIBOLD))
            b.clicked.connect(lambda _=False, i=i: self.set_tab(i))
            head.addWidget(b)
            self.tab_btns.append(b)
        head.addStretch(1)
        lay.addLayout(head)
        self.lists: list[QVBoxLayout] = []
        self.empties: list[QLabel] = []
        self.scrolls: list[QScrollArea] = []
        for empty in ("Non esiste ancora una cronologia", "Non c'è niente salvato in memoria"):
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
            body = QWidget()
            v = QVBoxLayout(body)
            v.setContentsMargins(0, 8, 0, 0)
            v.setSpacing(0)
            lbl = QLabel(empty)
            lbl.setFont(ui_font(px(16)))
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #000; padding: 0 12px;")
            v.addWidget(lbl)
            v.addStretch(1)
            area.setWidget(body)
            lay.addWidget(area, 1)
            self.lists.append(v)
            self.empties.append(lbl)
            self.scrolls.append(area)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 8, 6)
        bottom.addStretch(1)
        self.trash = icon_button("delete", 12, "Elimina", w=40, h=40)
        self.trash.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.trash.clicked.connect(lambda: (self.clear_history if self.tab == 0 else self.clear_memory).emit())
        bottom.addWidget(self.trash)
        lay.addLayout(bottom)
        self._counts = [0, 0]
        self.set_tab(0)

    def set_tab(self, i: int) -> None:
        self.tab = i
        for j, b in enumerate(self.tab_btns):
            col = "#000" if j == i else "#8A8A8A"
            border = f"border-bottom: 2px solid {ACCENT};" if j == i else "border-bottom: 2px solid transparent;"
            b.setStyleSheet(f"QPushButton {{ color: {col}; background: transparent; border: none; {border}"
                            f" padding: 4px 2px; }}")
        for j, a in enumerate(self.scrolls):
            a.setVisible(j == i)
        self.trash.setVisible(self._counts[i] > 0)

    def refresh(self, history: list[tuple[str, str]], memory: list[str]) -> None:
        """history: [(espressione, risultato)] dal più recente; memory: valori formattati."""
        self._fill(0, history)
        self._fill(1, memory)
        self._counts = [len(history), len(memory)]
        self.trash.setVisible(self._counts[self.tab] > 0)

    def _fill(self, which: int, items: list) -> None:
        lay = self.lists[which]
        while lay.count() > 2:  # [etichetta vuota, stretch, voci...] -> voci inserite prima dello stretch
            w = lay.takeAt(1).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.empties[which].setVisible(not items)
        for idx, it in enumerate(items):
            if which == 0:
                row = _Row()
                rl = QVBoxLayout(row)
                rl.setContentsMargins(0, 6, 0, 6)
                rl.setSpacing(0)
                ex = FitLabel(14, color="#5D5D5D", weight=QFont.Weight.Normal, elide=True, height=22)
                ex.setText(it[0])
                rs = FitLabel(28, 16, height=40)
                rs.setText(it[1])
                rl.addWidget(ex)
                rl.addWidget(rs)
                row.clicked.connect(lambda i=idx: self.history_clicked.emit(i))
            else:
                row = MemoryRow(it)
                row.clicked.connect(lambda i=idx: self.memory_clicked.emit(i))
                row.action.connect(lambda a, i=idx: self.memory_action.emit(a, i))
            lay.insertWidget(lay.count() - 1, row)


# ---------------------------------------------------------------------------
# Pannello di navigazione (hamburger)
# ---------------------------------------------------------------------------
class NavItem(QPushButton):
    def __init__(self, text: str, enabled: bool = True):
        super().__init__(text)
        self.selected = False
        self.setFlat(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(40)
        self.setFont(ui_font(px(15)))
        self.setEnabled(enabled)
        self.setStyleSheet("QPushButton { text-align: left; padding-left: 20px; border: none; "
                           "background: transparent; color: #000; }"
                           "QPushButton:hover { background: #D6D6D6; }"
                           "QPushButton:pressed { background: #C4C4C4; }"
                           "QPushButton:disabled { color: #9A9A9A; }")

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        if self.selected:
            p = QPainter(self)
            p.fillRect(QRect(0, 10, 4, 20), QColor(ACCENT))


class NavPanel(QWidget):
    """Pannello a scorrimento con la lista delle modalità; sfondo oscurato cliccabile."""
    mode_chosen = Signal(str)
    closed = Signal()
    WIDTH = 288

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.scrim = QWidget(self)
        self.scrim.setStyleSheet("background: rgba(0,0,0,70);")
        self.scrim.mousePressEvent = lambda e: self.close_panel()  # type: ignore[assignment]
        self.panel = QWidget(self)
        self.panel.setObjectName("NavBody")
        self.panel.setStyleSheet("#NavBody { background: #E9E9E9; }")
        self.panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        v = QVBoxLayout(self.panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.burger = icon_button("menu", 12, "Chiudi navigazione", w=48, h=48)
        self.burger.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.burger.clicked.connect(self.close_panel)
        v.addWidget(self.burger)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 8)
        bl.setSpacing(0)
        self.items: dict[str, NavItem] = {}
        self._section(bl, "Calcolatrice")
        for label, mode in (("Standard", STANDARD), ("Scientifica", SCIENTIFIC), ("Grafica", None),
                            ("Programmatore", None), ("Calcolo data", None)):
            self._item(bl, label, mode)
        self._section(bl, "Convertitore")
        for label in ("Valuta", "Volume", "Lunghezza", "Peso e massa", "Temperatura", "Energia", "Area",
                      "Velocità", "Tempo", "Potenza", "Dati", "Pressione", "Angolo"):
            self._item(bl, label, None)
        bl.addStretch(1)
        scroll.setWidget(body)
        v.addWidget(scroll, 1)
        bottom = NavItem("Impostazioni", enabled=False)
        v.addWidget(bottom)
        self.anim = QPropertyAnimation(self.panel, b"pos", self)
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.finished.connect(self._anim_done)
        self._opening = False
        self.hide()

    def _section(self, lay: QVBoxLayout, text: str) -> None:
        lbl = QLabel(text)
        lbl.setFont(ui_font(px(13), SEMIBOLD))
        lbl.setStyleSheet("color: #5D5D5D; padding: 14px 20px 6px 20px; background: transparent;")
        lay.addWidget(lbl)

    def _item(self, lay: QVBoxLayout, label: str, mode: str | None) -> None:
        it = NavItem(label, enabled=mode is not None)
        if mode:
            it.clicked.connect(lambda _=False, m=mode: (self.mode_chosen.emit(m), self.close_panel()))
            self.items[mode] = it
        lay.addWidget(it)

    def select(self, mode: str) -> None:
        for m, it in self.items.items():
            it.selected = m == mode
            it.update()

    def relayout(self) -> None:
        r = self.parentWidget().rect()
        self.setGeometry(r)
        self.scrim.setGeometry(r)
        w = min(self.WIDTH, r.width())
        self.panel.setFixedSize(w, r.height())
        if not self.anim.state() == QPropertyAnimation.State.Running:
            self.panel.move(0 if self._opening else -w, 0)

    def open_panel(self) -> None:
        self._opening = True
        self.show()
        self.raise_()
        self.relayout()
        self.anim.stop()
        self.anim.setStartValue(QPoint(-self.panel.width(), 0))
        self.anim.setEndValue(QPoint(0, 0))
        self.anim.start()

    def close_panel(self) -> None:
        if not self._opening:
            return
        self._opening = False
        self.anim.stop()
        self.anim.setStartValue(self.panel.pos())
        self.anim.setEndValue(QPoint(-self.panel.width(), 0))
        self.anim.start()
        self.closed.emit()

    def _anim_done(self) -> None:
        if not self._opening:
            self.hide()

    def is_open(self) -> bool:
        return self._opening


# ---------------------------------------------------------------------------
# Finestra principale
# ---------------------------------------------------------------------------
class CalculatorWindow(UwpWindow):
    STD_ROWS = [
        [("%", "pct", "fn"), ("CE", "ce", "fn"), ("C", "c", "fn"), ("⌫", "back", "fn")],
        [("⅟x", "recip", "fn"), ("x²", "sqr", "fn"), ("²√x", "sqrt", "fn"), ("÷", "div", "op")],
        [("7", "7", "digit"), ("8", "8", "digit"), ("9", "9", "digit"), ("×", "mul", "op")],
        [("4", "4", "digit"), ("5", "5", "digit"), ("6", "6", "digit"), ("−", "sub", "op")],
        [("1", "1", "digit"), ("2", "2", "digit"), ("3", "3", "digit"), ("+", "add", "op")],
        [("⁺⁄₋", "neg", "fn"), ("0", "0", "digit"), (",", ".", "digit"), ("=", "eq", "eq")],
    ]
    SCI_ROWS = [
        [("2ⁿᵈ", "second", "fn"), ("π", "pi", "fn"), ("e", "e", "fn"), ("C", "c", "fn"), ("⌫", "back", "fn")],
        [("x²", "sqr", "fn"), ("⅟x", "recip", "fn"), ("|x|", "abs", "fn"), ("exp", "exp", "fn"), ("mod", "mod", "fn")],
        [("²√x", "sqrt", "fn"), ("(", "lp", "fn"), (")", "rp", "fn"), ("n!", "fact", "fn"), ("÷", "div", "op")],
        [("xʸ", "pow", "fn"), ("7", "7", "digit"), ("8", "8", "digit"), ("9", "9", "digit"), ("×", "mul", "op")],
        [("10ˣ", "pow10", "fn"), ("4", "4", "digit"), ("5", "5", "digit"), ("6", "6", "digit"), ("−", "sub", "op")],
        [("log", "log", "fn"), ("1", "1", "digit"), ("2", "2", "digit"), ("3", "3", "digit"), ("+", "add", "op")],
        [("ln", "ln", "fn"), ("⁺⁄₋", "neg", "fn"), ("0", "0", "digit"), (",", ".", "digit"), ("=", "eq", "eq")],
    ]
    # con "2nd" attivo: chiave -> (etichetta, chiave alternativa)
    SECOND = {"sqr": ("x³", "cube"), "sqrt": ("³√x", "cbrt"), "pow": ("ʸ√x", "yroot"),
              "pow10": ("2ˣ", "pow2"), "log": ("logᵧx", "logbase"), "ln": ("eˣ", "powe")}
    MEM = [("MC", "mc"), ("MR", "mr"), ("M+", "mp"), ("M−", "mm"), ("MS", "ms"), ("M˅", "mem")]
    TITLES = {STANDARD: "Standard", SCIENTIFIC: "Scientifica"}

    def __init__(self, client: Any = None):
        super().__init__("Calcolatrice", theme="light", bg=BG)
        self.client = client
        self.calc = Calculator()
        self.wide = False
        self.setObjectName("UwpWindow")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(322, 502)
        self.setMinimumSize(320, 460)
        self._build()
        self.setStyleSheet(self.styleSheet() + QSS)  # dopo la costruzione, per le proprietà dinamiche
        self._apply_mode(STANDARD, announce=False)
        self._refresh()
        self._emit("calc.open", {})

    # --- costruzione ---------------------------------------------------------
    def _build(self) -> None:
        root = QHBoxLayout(self.content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.left = QWidget()
        self.left.setObjectName("CalcRoot")
        root.addWidget(self.left, 1)
        lv = QVBoxLayout(self.left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(0)
        self.btn_menu = icon_button("menu", 12, "Apri navigazione", w=48, h=48)
        self.btn_menu.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_menu.clicked.connect(lambda: self.nav.open_panel())
        self.title = QLabel("Standard")
        self.title.setFont(ui_font(px(20), SEMIBOLD))
        self.title.setStyleSheet("background: transparent;")
        self.btn_hist = icon_button("history", 12, "Cronologia", w=48, h=48)
        self.btn_hist.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_hist.clicked.connect(self._toggle_flyout)
        head.addWidget(self.btn_menu)
        head.addWidget(self.title, 1)
        head.addWidget(self.btn_hist)
        lv.addLayout(head)

        self.expr = FitLabel(14, color="#5D5D5D", weight=QFont.Weight.Normal, elide=True, height=22)
        lv.addWidget(self.expr)
        self.display = FitLabel(46, 22, height=76)
        lv.addWidget(self.display)

        # riga scientifica: DEG / F-E
        self.sci_top = QWidget()
        st = QHBoxLayout(self.sci_top)
        st.setContentsMargins(4, 0, 4, 0)
        st.setSpacing(0)
        self.btn_angle = self._flat("DEG", "angle", "menu", 13)
        self.btn_fe = self._flat("F-E", "fe", "menu", 13)
        for b in (self.btn_angle, self.btn_fe):
            b.setFixedSize(64, 30)
            st.addWidget(b)
        st.addStretch(1)
        lv.addWidget(self.sci_top)

        # riga memoria
        mrow = QWidget()
        ml = QHBoxLayout(mrow)
        ml.setContentsMargins(4, 0, 4, 2)
        ml.setSpacing(0)
        self.mem_btns: dict[str, CalcButton] = {}
        for label, key in self.MEM:
            b = self._flat(label, key, "mem", 15)
            b.setFixedHeight(32)
            self.mem_btns[key] = b
            ml.addWidget(b)
        lv.addWidget(mrow)

        # parte bassa: menu scientifici + tastierino (copribile dal flyout della cronologia)
        self.lower = QWidget()
        lw = QVBoxLayout(self.lower)
        lw.setContentsMargins(2, 0, 2, 2)
        lw.setSpacing(2)
        self.sci_menus = QWidget()
        sm = QHBoxLayout(self.sci_menus)
        sm.setContentsMargins(0, 0, 0, 0)
        sm.setSpacing(2)
        self.btn_trig = self._flat("Trigonometria  ⌄", "trig_menu", "fn", 13)
        self.btn_func = self._flat("Funzione  ⌄", "func_menu", "fn", 13)
        for b in (self.btn_trig, self.btn_func):
            b.setFixedHeight(32)
            b.setProperty("kind", "fn")
            sm.addWidget(b)
        lw.addWidget(self.sci_menus)
        self.keys: dict[str, dict[str, CalcButton]] = {STANDARD: {}, SCIENTIFIC: {}}
        self.grids: dict[str, QWidget] = {}
        for mode, rows in ((STANDARD, self.STD_ROWS), (SCIENTIFIC, self.SCI_ROWS)):
            w = QWidget()
            g = QGridLayout(w)
            g.setContentsMargins(0, 0, 0, 0)
            g.setSpacing(2)
            for r, row in enumerate(rows):
                g.setRowStretch(r, 1)
                for c, (label, key, kind) in enumerate(row):
                    b = CalcButton(label, kind, key, self._key_font(kind, label, key))
                    if key == "back":
                        b.setText(glyph("backspace"))
                        b.setFont(mdl2_font(13) if glyph("backspace") != "⌫" else ui_font(px(18)))
                    b.clicked.connect(lambda _=False, b=b: self._on_key(b))
                    g.addWidget(b, r, c)
                    g.setColumnStretch(c, 1)
                    self.keys[mode][key] = b
            lw.addWidget(w, 1)
            self.grids[mode] = w
        lv.addWidget(self.lower, 1)

        # pannello laterale (finestra larga) e flyout (finestra stretta)
        self.side = HistoryPanel()
        self.side.setFixedWidth(PANEL_WIDTH)
        root.addWidget(self.side)
        self.flyout = HistoryPanel()
        self.flyout.setParent(self.left)
        self.flyout.hide()
        self.lower.installEventFilter(self)
        for pnl in (self.side, self.flyout):
            pnl.history_clicked.connect(self._history_clicked)
            pnl.memory_clicked.connect(self._memory_clicked)
            pnl.memory_action.connect(self._memory_action)
            pnl.clear_history.connect(self._clear_history)
            pnl.clear_memory.connect(self._clear_memory)

        # popup trigonometria / funzione
        self.trig_popup = self._make_popup(
            [("sin", "sin"), ("cos", "cos"), ("tan", "tan"), ("sec", "sec"), ("csc", "csc"), ("cot", "cot")],
            toggles=True)
        self.func_popup = self._make_popup(
            [("|x|", "abs"), ("⌊x⌋", "floor"), ("⌈x⌉", "ceil"), ("rand", "rand"), ("→dms", "dms"), ("→deg", "deg")])

        # navigazione
        self.nav = NavPanel(self.content)
        self.nav.mode_chosen.connect(self.set_mode)
        self.content.installEventFilter(self)
        self.nav.hide()

    def _key_font(self, kind: str, label: str, key: str) -> QFont:
        if kind == "digit":
            return ui_font(px(22), SEMIBOLD)
        if kind == "eq":
            return ui_font(px(24))
        if kind == "op":
            return ui_font(px(22))
        return ui_font(px(16 if len(label) <= 3 else 14))

    def _flat(self, text: str, key: str, kind: str, size: float) -> CalcButton:
        b = CalcButton(text, kind, key, ui_font(px(size)))
        b.clicked.connect(lambda _=False, b=b: self._on_key(b))
        return b

    def _make_popup(self, items: list[tuple[str, str]], toggles: bool = False) -> QFrame:
        f = QFrame(self, Qt.WindowType.Popup)
        f.setObjectName("Popup")
        f.setStyleSheet(QSS)
        g = QGridLayout(f)
        g.setContentsMargins(4, 4, 4, 4)
        g.setSpacing(2)
        f.buttons = {}  # type: ignore[attr-defined]
        row = 0
        if toggles:
            for c, (label, key) in enumerate((("2ⁿᵈ", "second"), ("hyp", "hyp"))):
                b = self._flat(label, key, "mem", 13)
                b.setFixedSize(80, 32)
                g.addWidget(b, 0, c)
                f.buttons[key] = b  # type: ignore[attr-defined]
            row = 1
        for i, (label, key) in enumerate(items):
            b = CalcButton(label, "fn", key, ui_font(px(15)))
            b.setFixedSize(54, 38)
            b.clicked.connect(lambda _=False, b=b, f=f: (f.hide(), self._on_key(b)))
            g.addWidget(b, row + i // 3, i % 3)
            f.buttons[key] = b  # type: ignore[attr-defined]
        return f

    # --- eventi hub ------------------------------------------------------------
    def _emit(self, type_: str, data: dict) -> None:
        if self.client is not None:
            try:
                self.client.emit(type_, data)
            except Exception:
                pass

    def _flush_events(self) -> None:
        for ev in self.calc.take_events():
            if ev[0] == "result":
                self._emit("calc.result", {"expr": ev[1], "result": ev[2], "mode": ev[3]})
            elif ev[0] == "error":
                self._emit("calc.error", {"expr": ev[1], "error": ev[2]})
            elif ev[0] == "mode":
                self._emit("calc.mode", {"mode": ev[1]})

    # --- azioni ---------------------------------------------------------------------
    def press(self, key: str) -> None:
        """Entrata unica per tasti sullo schermo e da tastiera."""
        c = self.calc
        if key == "mem":
            self._show_memory()
            return
        if key in ("trig_menu", "func_menu"):
            self._open_popup(self.trig_popup if key == "trig_menu" else self.func_popup,
                             self.btn_trig if key == "trig_menu" else self.btn_func)
            return
        if c.second and key in self.SECOND and c.scientific:
            key = self.SECOND[key][1]
        c.press(key)
        self._flush_events()
        self._refresh()

    def _on_key(self, b: CalcButton) -> None:
        self.press(b.key)

    def set_mode(self, mode: str) -> None:
        if mode == self.calc.mode:
            return
        self.calc.set_mode(mode)
        self._apply_mode(mode)
        self._flush_events()
        self._refresh()

    def _apply_mode(self, mode: str, announce: bool = True) -> None:
        sci = mode == SCIENTIFIC
        self.title.setText(self.TITLES[mode])
        self.sci_top.setVisible(sci)
        self.sci_menus.setVisible(sci)
        self.grids[STANDARD].setVisible(not sci)
        self.grids[SCIENTIFIC].setVisible(sci)
        self.nav.select(mode)
        self.flyout.hide()
        self._update_wide()

    def _open_popup(self, popup: QFrame, anchor: QWidget) -> None:
        popup.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height()))
        popup.move(pos)
        popup.show()
        self._refresh_popups()

    def _refresh_popups(self) -> None:
        c = self.calc
        for base, b in self.trig_popup.buttons.items():  # type: ignore[attr-defined]
            if base in ("second", "hyp"):
                b.setProperty("on", "true" if getattr(c, base) else "false")
                b.style().unpolish(b)
                b.style().polish(b)
                continue
            b.setText(base + ("h" if c.hyp else "") + ("⁻¹" if c.second else ""))

    # --- pannello cronologia ------------------------------------------------------
    def _toggle_flyout(self) -> None:
        if self.wide:
            return
        if self.flyout.isVisible():
            self.flyout.hide()
        else:
            self.flyout.set_tab(0)
            self._show_flyout()

    def _show_flyout(self) -> None:
        self.flyout.setGeometry(self.lower.geometry())
        self.flyout.show()
        self.flyout.raise_()

    def _show_memory(self) -> None:
        if self.wide:
            self.side.set_tab(1)
        elif self.flyout.isVisible() and self.flyout.tab == 1:
            self.flyout.hide()
        else:
            self.flyout.set_tab(1)
            self._show_flyout()

    def _history_clicked(self, i: int) -> None:
        item = list(reversed(self.calc.history))[i]
        self.calc.set_value(item.value, item.expr)
        self.flyout.hide()
        self._refresh()

    def _memory_clicked(self, i: int) -> None:
        self.calc.mem_recall(i)
        self.flyout.hide()
        self._refresh()

    def _memory_action(self, act: str, i: int) -> None:
        c = self.calc
        if act == "mc":
            if i < len(c.memory):
                del c.memory[i]
        elif act == "mp":
            c.mem_add(i, c.current_value())
        elif act == "mm":
            c.mem_sub(i, c.current_value())
        self._refresh()

    def _clear_history(self) -> None:
        self.calc.history.clear()
        self._refresh()

    def _clear_memory(self) -> None:
        self.calc.mem_clear()
        self._refresh()

    # --- layout reattivo -------------------------------------------------------------
    def _update_wide(self) -> None:
        wide = self.width() > WIDE_WIDTH
        self.wide = wide
        self.side.setVisible(wide)
        self.btn_hist.setVisible(not wide)
        self.mem_btns["mem"].setVisible(not wide)
        if wide:
            self.flyout.hide()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._update_wide()
        if self.flyout.isVisible():
            self.flyout.setGeometry(self.lower.geometry())
        self.nav.relayout()

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            if obj is self.lower and self.flyout.isVisible():
                self.flyout.setGeometry(self.lower.geometry())
            elif obj is self.content and hasattr(self, "nav"):
                self.nav.relayout()
        return super().eventFilter(obj, ev)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.setFocus()

    # --- aggiornamento vista -----------------------------------------------------------
    def _refresh(self) -> None:
        c = self.calc
        self.display.setText(c.display)
        self.expr.setText(c.expression)
        has_mem = bool(c.memory)
        for k in ("mc", "mr", "mem"):
            self.mem_btns[k].setEnabled(has_mem)
        self.mem_btns["mc"].setEnabled(has_mem)
        err = bool(c.error)
        for key, b in self.mem_btns.items():
            if key in ("mp", "mm", "ms"):
                b.setEnabled(not err)
            elif err:
                b.setEnabled(False)
        keep = {"ce", "c", "back"}
        for mode in self.keys:
            for key, b in self.keys[mode].items():
                if key.isdigit() or key == ".":
                    b.setEnabled(True)
                else:
                    b.setEnabled(not err or key in keep)
        if c.scientific:
            keys = self.keys[SCIENTIFIC]
            for base, (alt_label, _alt) in self.SECOND.items():
                orig = next(l for row in self.SCI_ROWS for (l, k, _) in row if k == base)
                keys[base].setText(alt_label if c.second else orig)
            keys["second"].setProperty("kind", "eq" if c.second else "fn")
            keys["second"].style().unpolish(keys["second"])
            keys["second"].style().polish(keys["second"])
            keys["lp"].setText(f"({c.open_parens}" if c.open_parens else "(")
            self.btn_angle.setText(c.angle)
            self.btn_fe.setProperty("on", "true" if c.fe else "false")
            self.btn_fe.style().unpolish(self.btn_fe)
            self.btn_fe.style().polish(self.btn_fe)
            self.btn_angle.setEnabled(not err)
            self.btn_trig.setEnabled(not err)
            self.btn_func.setEnabled(not err)
        hist = [(h.expr, h.result) for h in reversed(c.history)]
        mem = [format_number(v) for v in c.memory]
        for pnl in (self.side, self.flyout):
            pnl.refresh(hist, mem)
        if self.trig_popup.isVisible():
            self._refresh_popups()

    # --- tastiera ----------------------------------------------------------------------------
    def keyPressEvent(self, e: QKeyEvent) -> None:
        key, text = e.key(), e.text()
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if ctrl:
            m = {Qt.Key.Key_L: "mc", Qt.Key.Key_R: "mr", Qt.Key.Key_M: "ms", Qt.Key.Key_P: "mp",
                 Qt.Key.Key_Q: "mm"}
            if key in m:
                self.press(m[key])
            elif key == Qt.Key.Key_H:
                self._toggle_flyout()
            return
        sci = self.calc.scientific
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or text == "=":
            self.press("eq")
        elif key == Qt.Key.Key_Escape:
            if self.nav.is_open():
                self.nav.close_panel()
            elif self.flyout.isVisible():
                self.flyout.hide()
            else:
                self.press("c")
        elif key == Qt.Key.Key_Backspace:
            self.press("back")
        elif key == Qt.Key.Key_Delete:
            self.press("ce")
        elif key == Qt.Key.Key_F9:
            self.press("neg")
        elif text and text in "0123456789":
            self.press(text)
        elif text in (",", "."):
            self.press(".")
        elif text in ("+", "-", "*", "/"):
            self.press({"+": "add", "-": "sub", "*": "mul", "/": "div"}[text])
        elif text == "%":
            self.press("mod" if sci else "pct")
        elif text == "(" and sci:
            self.press("lp")
        elif text == ")" and sci:
            self.press("rp")
        elif text == "!" and sci:
            self.press("fact")
        elif text == "^" and sci:
            self.press("pow")
        elif text == "@":
            self.press("sqrt")
        elif text in ("r", "R"):
            self.press("recip")
        elif text in ("q", "Q"):
            self.press("sqr")
        elif sci and text in ("p", "P"):
            self.press("pi")
        elif sci and text in ("l", "n"):
            self.press("log" if text == "l" else "ln")
        elif sci and text in ("s", "o", "t"):
            self.press({"s": "sin", "o": "cos", "t": "tan"}[text])
        else:
            super().keyPressEvent(e)
            return
        e.accept()


def build(client: Any) -> CalculatorWindow:
    return CalculatorWindow(client)
