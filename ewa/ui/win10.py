"""Stile Windows 10 condiviso dai tool EWA (PySide6).

Contenuto:
- PALETTE: colori ufficiali Win10 (tema chiaro/scuro, accento blu predefinito).
- ui_font(size, weight) / mdl2_font(size) / glyph(name): font Segoe UI e icone
  Segoe MDL2 Assets, con fallback automatico se il font non è installato
  (es. Linux): glyph() restituisce allora un carattere Unicode equivalente.
- UwpWindow: finestra senza cornice nativa con barra del titolo stile app UWP
  (titolo a sinistra, pulsanti ─ ☐ ✕ 46x32 a destra, trascinamento, resize dai
  bordi, doppio clic = massimizza). Usarla per Calcolatrice, Sveglie e orologio,
  Fotocamera. Il Blocco note (app Win32) usa invece QMainWindow nativa.
- HubBridge: porta i messaggi del ToolClient nel thread Qt come segnale.
- run_tool(): boilerplate comune (QApplication, HiDPI, font, icona, client hub).
- screenshot(widget, path): utilità per verifiche offscreen.
"""
from __future__ import annotations

import sys
from typing import Any, Callable

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
PALETTE = {
    "accent": "#0078D7",          # blu predefinito Windows 10
    "accent_light": "#429CE3",
    "accent_dark": "#005A9E",
    "light": {
        "bg": "#F2F2F2",          # sfondo app UWP (Calcolatrice/Sveglie)
        "surface": "#FFFFFF",
        "button": "#F9F9F9",       # tasti numerici calcolatrice
        "button_alt": "#F0F0F0",   # tasti operatori calcolatrice
        "hover": "#DADADA",
        "pressed": "#BFBFBF",
        "text": "#000000",
        "text_secondary": "#5D5D5D",
        "border": "#CCCCCC",
        "titlebar": "#F2F2F2",
        "close_hover": "#E81123",
    },
    "dark": {
        "bg": "#1F1F1F",
        "surface": "#2B2B2B",
        "button": "#3B3B3B",
        "button_alt": "#323232",
        "hover": "#4C4C4C",
        "pressed": "#6B6B6B",
        "text": "#FFFFFF",
        "text_secondary": "#A6A6A6",
        "border": "#454545",
        "titlebar": "#1F1F1F",
        "close_hover": "#E81123",
    },
}

UI_FAMILIES = ["Segoe UI", "Selawik", "Noto Sans", "DejaVu Sans", "Arial"]
MONO_FAMILIES = ["Consolas", "Lucida Console", "DejaVu Sans Mono", "Courier New"]

# Codepoint Segoe MDL2 Assets -> fallback Unicode
_GLYPHS: dict[str, tuple[str, str]] = {
    "minimize": ("", "─"),
    "maximize": ("", "☐"),
    "restore": ("", "❐"),
    "close": ("", "✕"),
    "menu": ("", "☰"),           # hamburger
    "history": ("", "🕓"),
    "back": ("", "←"),
    "settings": ("", "⚙"),
    "play": ("", "▶"),
    "pause": ("", "⏸"),
    "reset": ("", "↺"),
    "stop": ("", "■"),
    "add": ("", "+"),
    "delete": ("", "🗑"),
    "edit": ("", "✎"),
    "alarm": ("", "⏰"),
    "clock": ("", "🕓"),
    "timer": ("", "⏱"),          # clessidra/timer
    "stopwatch": ("", "⏱"),
    "world": ("", "🌐"),
    "flag": ("", "⚑"),            # giro cronometro
    "fullscreen": ("", "⛶"),
    "pin": ("", "📌"),
    "camera": ("", "📷"),
    "video": ("", "🎥"),
    "switch_camera": ("", "⟳"),
    "photo_gallery": ("", "🖼"),
    "hdr": ("", "HDR"),
    "self_timer": ("", "⏱"),
    "more": ("", "…"),
    "backspace": ("", "⌫"),
    "check": ("", "✓"),
    "chevron_down": ("", "⌄"),
    "keep_on_top": ("", "⧉"),
}

_mdl2_available: bool | None = None


def has_mdl2() -> bool:
    global _mdl2_available
    if _mdl2_available is None:
        _mdl2_available = "Segoe MDL2 Assets" in QFontDatabase.families()
    return _mdl2_available


def _first_available(families: list[str]) -> str:
    installed = set(QFontDatabase.families())
    for fam in families:
        if fam in installed:
            return fam
    return families[-1]


def ui_font(size: float = 10.5, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Segoe UI (o fallback). size in punti; 'Semilight'/'Light' via weight."""
    f = QFont(_first_available(UI_FAMILIES))
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def mono_font(size: float = 11) -> QFont:
    f = QFont(_first_available(MONO_FAMILIES))
    f.setPointSizeF(size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def mdl2_font(size: float = 10) -> QFont:
    f = QFont("Segoe MDL2 Assets" if has_mdl2() else _first_available(UI_FAMILIES))
    f.setPointSizeF(size)
    return f


def glyph(name: str) -> str:
    """Carattere dell'icona: MDL2 se disponibile, altrimenti fallback Unicode."""
    mdl2, fallback = _GLYPHS[name]
    return mdl2 if has_mdl2() else fallback


def icon_button(name: str, size: float = 11, tooltip: str = "", parent: QWidget | None = None,
                w: int = 40, h: int = 40) -> QPushButton:
    """Pulsante piatto con icona MDL2 (hover grigio, come le toolbar UWP)."""
    b = QPushButton(glyph(name), parent)
    b.setFont(mdl2_font(size))
    b.setFixedSize(w, h)
    b.setFlat(True)
    b.setCursor(Qt.CursorShape.ArrowCursor)
    b.setToolTip(tooltip)
    b.setObjectName("IconButton")
    return b


def base_qss(theme: str = "light") -> str:
    """QSS di base comune; ogni tool aggiunge il proprio."""
    p = PALETTE[theme]
    return f"""
    QWidget {{ color: {p['text']}; }}
    QToolTip {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']};
               padding: 4px 8px; }}
    QPushButton#IconButton {{ background: transparent; border: none; color: {p['text']}; }}
    QPushButton#IconButton:hover {{ background: {p['hover']}; }}
    QPushButton#IconButton:pressed {{ background: {p['pressed']}; }}
    QScrollBar:vertical {{ background: transparent; width: 6px; }}
    QScrollBar::handle:vertical {{ background: {p['text_secondary']}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


# ---------------------------------------------------------------------------
# Barra del titolo UWP + finestra senza cornice
# ---------------------------------------------------------------------------
class TitleBar(QWidget):
    """Barra titolo stile UWP (altezza 32 px)."""
    HEIGHT = 32

    def __init__(self, window: "UwpWindow", title: str, theme: str = "light"):
        super().__init__(window)
        self._win = window
        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("TitleBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(0)
        self.title_label = QLabel(title)
        self.title_label.setFont(ui_font(9))
        self.title_label.setObjectName("TitleLabel")
        lay.addWidget(self.title_label)
        lay.addStretch(1)
        self.btn_min = self._caption_button("minimize", "Riduci a icona")
        self.btn_max = self._caption_button("maximize", "Ingrandisci")
        self.btn_close = self._caption_button("close", "Chiudi")
        self.btn_close.setObjectName("CloseButton")
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(window.close)
        self._drag_pos: QPoint | None = None
        self.set_theme(theme)

    def _caption_button(self, name: str, tip: str) -> QPushButton:
        b = QPushButton(glyph(name))
        b.setFont(mdl2_font(7.5 if has_mdl2() else 10))
        b.setFixedSize(46, self.HEIGHT)
        b.setToolTip(tip)
        b.setFlat(True)
        b.setObjectName("CaptionButton")
        return b

    def set_theme(self, theme: str) -> None:
        p = PALETTE[theme]
        self.setStyleSheet(f"""
            #TitleBar {{ background: transparent; }}
            #TitleLabel {{ color: {p['text']}; }}
            QPushButton#CaptionButton, QPushButton#CloseButton {{
                background: transparent; border: none; color: {p['text']}; }}
            QPushButton#CaptionButton:hover {{ background: {p['hover']}; }}
            QPushButton#CaptionButton:pressed {{ background: {p['pressed']}; }}
            QPushButton#CloseButton:hover {{ background: {p['close_hover']}; color: white; }}
            QPushButton#CloseButton:pressed {{ background: #F1707A; color: white; }}
        """)

    def _toggle_max(self) -> None:
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def update_max_icon(self) -> None:
        self.btn_max.setText(glyph("restore" if self._win.isMaximized() else "maximize"))

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            handle = self._win.windowHandle()
            if handle is not None and handle.startSystemMove():
                return
            self._drag_pos = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_pos is not None and not self._win.isMaximized():
            self._win.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_pos = None


class UwpWindow(QWidget):
    """Finestra stile app UWP Win10: titlebar personalizzata + area `self.content`.

    Uso:
        win = UwpWindow("Calcolatrice", theme="light")
        lay = QVBoxLayout(win.content); ...
        win.titlebar.title_label  # personalizzabile
        win.titlebar_layout()      # per inserire widget nella barra (es. hamburger)
    """
    RESIZE_MARGIN = 6

    def __init__(self, title: str, theme: str = "light", bg: str | None = None):
        super().__init__()
        self.theme = theme
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setMouseTracking(True)
        self.setObjectName("UwpWindow")
        self._bg = bg
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)  # bordo finestra 1 px (colore accento/grigio)
        outer.setSpacing(0)
        self.titlebar = TitleBar(self, title, theme)
        outer.addWidget(self.titlebar)
        self.content = QWidget()
        self.content.setObjectName("UwpContent")
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self.content, 1)
        self.apply_theme(theme)

    def titlebar_layout(self) -> QHBoxLayout:
        return self.titlebar.layout()  # type: ignore[return-value]

    def apply_theme(self, theme: str) -> None:
        self.theme = theme
        p = PALETTE[theme]
        bg = self._bg or p["bg"]
        self.setStyleSheet(base_qss(theme) + f"""
            #UwpWindow {{ background: {bg}; border: 1px solid {p['border']}; }}
            #UwpContent {{ background: {bg}; }}
        """)
        self.titlebar.set_theme(theme)

    def changeEvent(self, e) -> None:  # aggiorna icona massimizza/ripristina
        super().changeEvent(e)
        if hasattr(self, "titlebar"):
            self.titlebar.update_max_icon()

    # --- resize dai bordi (finestra frameless) ---
    def _edges_at(self, pos: QPoint) -> Qt.Edge:
        m, r = self.RESIZE_MARGIN, self.rect()
        edges = Qt.Edge(0)
        if pos.x() <= m:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= r.width() - m:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= m:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= r.height() - m:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, e: QMouseEvent) -> None:
        edges = self._edges_at(e.position().toPoint())
        if edges and not self.isMaximized() and self.windowHandle():
            self.windowHandle().startSystemResize(edges)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        edges = self._edges_at(e.position().toPoint())
        cursors = {
            Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor, Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor, Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
            Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(cursors.get(edges, Qt.CursorShape.ArrowCursor))
        super().mouseMoveEvent(e)


# ---------------------------------------------------------------------------
# Ponte hub -> UI
# ---------------------------------------------------------------------------
class HubBridge(QObject):
    """Rilancia nel thread Qt i messaggi ricevuti dal ToolClient.

        bridge = HubBridge()
        client = ToolClient("notepad", on_message=bridge.deliver)
        bridge.message.connect(self.on_hub_message)   # slot riceve dict
    """
    message = Signal(dict)

    def deliver(self, msg: dict[str, Any]) -> None:
        self.message.emit(msg)


# ---------------------------------------------------------------------------
# Boilerplate di avvio
# ---------------------------------------------------------------------------
def make_app(app_id: str) -> QApplication:
    """Crea la QApplication con impostazioni comuni (chiamare una volta)."""
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if sys.platform == "win32":
        try:  # icona corretta nella taskbar
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"EWA.{app_id}")
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(ui_font(10.5))
    app.setApplicationName(app_id)
    return app  # type: ignore[return-value]


def run_tool(tool: str, build: Callable[[Any], QWidget]) -> int:
    """Avvia un tool: crea app + ToolClient + HubBridge, chiama build(client),
    mostra la finestra, emette tool.close all'uscita.

    `build(client)` riceve il ToolClient (con `client.bridge` già collegato)
    e restituisce la finestra principale.
    """
    from ewa.core.client import ToolClient

    app = make_app(tool)
    bridge = HubBridge()
    client = ToolClient(tool, on_message=bridge.deliver)
    client.bridge = bridge  # type: ignore[attr-defined]
    win = build(client)
    win.show()
    code = app.exec()
    client.close()
    return code


def screenshot(widget: QWidget, path: str) -> None:
    """Salva uno screenshot del widget (funziona con QT_QPA_PLATFORM=offscreen)."""
    QApplication.processEvents()
    widget.grab().save(path)


def qcolor(hex_: str) -> QColor:
    return QColor(hex_)


__all__ = [
    "PALETTE", "ui_font", "mono_font", "mdl2_font", "glyph", "has_mdl2", "icon_button", "base_qss",
    "TitleBar", "UwpWindow", "HubBridge", "make_app", "run_tool", "screenshot", "qcolor", "QRect",
]
