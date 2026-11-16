"""Scheda Orologio: mappa del mondo stilizzata con ora locale e alcune citta' (solo grafica)."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ewa.ui.win10 import PALETTE, ui_font

ACCENT = PALETTE["accent"]

# Continenti molto stilizzati: poligoni (longitudine, latitudine)
LAND = [
    # Nord America
    [(-168, 66), (-150, 71), (-125, 70), (-95, 72), (-80, 70), (-62, 60), (-55, 50), (-68, 44), (-76, 35),
     (-81, 25), (-90, 29), (-97, 26), (-105, 22), (-95, 16), (-83, 9), (-78, 8), (-88, 14), (-105, 20),
     (-112, 30), (-118, 34), (-124, 42), (-125, 49), (-135, 58), (-150, 60), (-165, 60)],
    # Groenlandia
    [(-55, 60), (-45, 60), (-20, 70), (-20, 82), (-60, 82), (-70, 76)],
    # Sud America
    [(-78, 8), (-62, 11), (-50, 0), (-35, -6), (-40, -22), (-48, -28), (-58, -38), (-66, -47), (-70, -55),
     (-74, -48), (-72, -30), (-70, -18), (-80, -5)],
    # Europa + Asia
    [(-10, 36), (-9, 43), (-2, 48), (5, 52), (8, 57), (12, 56), (18, 60), (25, 66), (30, 70), (45, 68),
     (70, 73), (100, 77), (140, 72), (170, 68), (180, 65), (160, 58), (142, 52), (135, 43), (128, 35),
     (122, 30), (120, 22), (108, 18), (105, 9), (98, 8), (90, 22), (80, 15), (77, 8), (72, 20), (62, 25),
     (57, 24), (50, 28), (43, 13), (35, 28), (35, 36), (26, 38), (22, 36), (15, 40), (8, 44), (3, 42)],
    # Africa
    [(-17, 21), (-10, 33), (10, 37), (32, 31), (35, 28), (43, 12), (51, 11), (40, -3), (40, -15), (33, -26),
     (20, -35), (12, -18), (9, 4), (-8, 4), (-16, 13)],
    # Australia
    [(114, -22), (122, -18), (131, -12), (142, -11), (153, -26), (148, -38), (135, -35), (116, -35)],
    # Indonesia / Giappone (isole)
    [(95, 5), (106, -6), (120, -9), (140, -8), (130, 0), (110, 2)],
    [(130, 31), (141, 36), (142, 44), (137, 37)],
    [(-6, 50), (2, 53), (-2, 58), (-6, 56)],
]

CITIES = [("Roma", 12.5, 41.9, 1), ("New York", -74, 40.7, -5), ("Tokyo", 139.7, 35.7, 9)]


class MapView(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(260)

    def _pt(self, lon: float, lat: float, r: QRectF) -> QPointF:
        return QPointF(r.left() + (lon + 180) / 360 * r.width(), r.top() + (84 - lat) / 150 * r.height())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#C9D6E2"))
        r = QRectF(self.rect())
        # rapporto 360:150 mantenuto, centrato
        h = min(r.height(), r.width() * 150 / 360 * 1.0)
        w = h * 360 / 150
        if w < r.width():
            w, h = r.width(), r.width() * 150 / 360
        mr = QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)
        p.setPen(QColor("#B3C2D1"))
        for lon in range(-180, 181, 30):
            a, b = self._pt(lon, 84, mr), self._pt(lon, -66, mr)
            p.drawLine(a, b)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E9E9E9"))
        for poly in LAND:
            p.drawPolygon(QPolygonF([self._pt(lo, la, mr) for lo, la in poly]))
        # fascia notte stilizzata
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRect(QRectF(mr.left(), r.top(), mr.width() * 0.22, r.height()))
        for i, (name, lon, lat, _off) in enumerate(CITIES):
            c = self._pt(lon, lat, mr)
            p.setBrush(QColor(ACCENT))
            p.setPen(QColor("white"))
            p.drawEllipse(c, 6, 6)
            p.setPen(QColor("#222222"))
            p.setFont(ui_font(9))
            p.drawText(c + QPointF(10, 4), name)


def _city_time(off: int, now: dt.datetime) -> dt.datetime:
    return now.astimezone(dt.timezone(dt.timedelta(hours=off)))


class ClockPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.map = MapView()
        v.addWidget(self.map, 1)
        row = QHBoxLayout()
        row.setContentsMargins(24, 10, 24, 14)
        row.setSpacing(12)
        self.tiles: list[tuple[QLabel, int]] = []
        for i, (name, _lo, _la, off) in enumerate(CITIES):
            w = QWidget()
            w.setObjectName("CityTile")
            w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            w.setStyleSheet(f"#CityTile {{ background: {ACCENT if i == 0 else '#FFFFFF'}; "
                            f"border: 1px solid #CCCCCC; }} QLabel {{ background: transparent; "
                            f"color: {'white' if i == 0 else 'black'}; }}")
            lv = QVBoxLayout(w)
            lv.setContentsMargins(14, 8, 14, 8)
            lv.setSpacing(0)
            t = QLabel("--:--")
            t.setFont(ui_font(22, QFont.Weight.Light))
            n = QLabel(name)
            n.setFont(ui_font(10.5))
            d = QLabel("Ora locale" if i == 0 else "")
            d.setFont(ui_font(9))
            lv.addWidget(t)
            lv.addWidget(n)
            lv.addWidget(d)
            row.addWidget(w, 1)
            self.tiles.append((t, off, d))  # type: ignore[arg-type]
        v.addLayout(row)
        self.tick()

    def tick(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        base = now.astimezone(dt.timezone(dt.timedelta(hours=1)))
        for t, off, d in self.tiles:  # type: ignore[misc]
            c = _city_time(off, now)
            t.setText(c.strftime("%H:%M"))
            if d.text() != "Ora locale":
                delta = off - 1
                day = "oggi" if c.date() == base.date() else ("ieri" if c.date() < base.date() else "domani")
                d.setText(f"{day}, {delta:+d} ore")
