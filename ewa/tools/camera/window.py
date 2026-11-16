"""Fotocamera (stile app UWP Windows 10): anteprima, scatto foto, registrazione video."""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
                            QUrl)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QImage, QLinearGradient, QPainter, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ewa.ui.win10 import UwpWindow, glyph, mdl2_font, ui_font

from .logic import (CameraSession, camera_roll_dir, capture_filename, latest_capture, unique_path)

SIDEBAR_W = 96
ERR_TITLE = "Non riusciamo a trovare la fotocamera"
ERR_BODY = ("Verifica che sia connessa e installata correttamente, che non sia bloccata dal software "
            "antivirus e che i driver della fotocamera siano aggiornati.")
ERR_CODE = "Se ti serve, ecco il codice di errore: 0xA00F4244<NoCamerasAreAttached>"
TIMER_STEPS = [0, 2, 5, 10]
GRIDS = ["Nessuna", "Regola dei terzi", "Rapporto aureo", "Croce", "Quadrato"]
QUALITIES = ["Alta", "Media", "Bassa"]


# ---------------------------------------------------------------------------
class PreviewWidget(QWidget):
    """Anteprima: disegna i fotogrammi, la griglia e la schermata 'nessuna fotocamera'."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image: QImage | None = None
        self.no_camera = False
        self.grid = 0
        self.countdown = 0
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def set_image(self, img: QImage) -> None:
        self._image = img
        self.update()

    def current_image(self) -> QImage | None:
        return self._image

    def _video_rect(self) -> QRectF:
        if not self._image or self._image.isNull():
            return QRectF(self.rect())
        iw, ih = self._image.width(), self._image.height()
        s = min(self.width() / iw, self.height() / ih)
        w, h = iw * s, ih * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#000000"))
        if self.no_camera:
            self._paint_no_camera(p)
            return
        if self._image and not self._image.isNull():
            p.drawImage(self._video_rect(), self._image)
        self._paint_grid(p)
        if self.countdown:
            p.setPen(QColor(255, 255, 255, 235))
            p.setFont(ui_font(80, QFont.Weight.Light))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self.countdown))

    def _paint_grid(self, p: QPainter) -> None:
        if not self.grid:
            return
        r = self._video_rect()
        p.setPen(QPen(QColor(255, 255, 255, 170), 1))
        x0, y0, w, h = r.x(), r.y(), r.width(), r.height()
        if self.grid == 1:      # regola dei terzi
            for i in (1, 2):
                p.drawLine(QPointF(x0 + w * i / 3, y0), QPointF(x0 + w * i / 3, y0 + h))
                p.drawLine(QPointF(x0, y0 + h * i / 3), QPointF(x0 + w, y0 + h * i / 3))
        elif self.grid == 2:    # rapporto aureo
            g = 0.382
            for f in (g, 1 - g):
                p.drawLine(QPointF(x0 + w * f, y0), QPointF(x0 + w * f, y0 + h))
                p.drawLine(QPointF(x0, y0 + h * f), QPointF(x0 + w, y0 + h * f))
        elif self.grid == 3:    # croce
            p.drawLine(QPointF(x0 + w / 2, y0), QPointF(x0 + w / 2, y0 + h))
            p.drawLine(QPointF(x0, y0 + h / 2), QPointF(x0 + w, y0 + h / 2))
        elif self.grid == 4:    # quadrato centrale
            s = min(w, h) * 0.8
            p.drawRect(QRectF(x0 + (w - s) / 2, y0 + (h - s) / 2, s, s))

    def _paint_no_camera(self, p: QPainter) -> None:
        # area utile: esclude la barra laterale
        area = QRect(0, 0, self.width() - SIDEBAR_W, self.height())
        cx = area.center().x()
        cy = area.center().y()
        p.setPen(QColor("#8A8A8A"))
        p.setFont(mdl2_font(44))
        p.drawText(QRect(cx - 80, cy - 150, 160, 80), Qt.AlignmentFlag.AlignCenter, glyph("camera"))
        # barra obliqua "fotocamera non disponibile"
        pen = QPen(QColor("#8A8A8A"), 3)
        p.setPen(pen)
        p.drawLine(cx - 34, cy - 144, cx + 34, cy - 76)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(ui_font(15, QFont.Weight.DemiBold))
        p.drawText(QRect(area.left(), cy - 60, area.width(), 30), Qt.AlignmentFlag.AlignCenter, ERR_TITLE)
        p.setPen(QColor("#CFCFCF"))
        p.setFont(ui_font(10))
        body = QRect(cx - 230, cy - 22, 460, 70)
        p.drawText(body, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                   ERR_BODY)
        p.setPen(QColor("#8A8A8A"))
        p.setFont(ui_font(9))
        p.drawText(QRect(cx - 260, cy + 52, 520, 40),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                   ERR_CODE)


class Sidebar(QWidget):
    """Barra verticale semitrasparente a destra."""

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))


class ShutterButton(QPushButton):
    """Grande pulsante di scatto circolare (foto / video / registrazione)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(76, 76)
        self.mode = "photo"
        self.recording = False
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_state(self, mode: str, recording: bool) -> None:
        self.mode, self.recording = mode, recording
        self.update()

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        c = QPointF(self.width() / 2, self.height() / 2)
        ring = QColor(255, 255, 255, 255 if enabled else 90)
        p.setPen(QPen(ring, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, 35.5, 35.5)
        p.setPen(Qt.PenStyle.NoPen)
        if self.recording:
            fill = QColor("#E81123") if not self.isDown() else QColor("#B50E1C")
        else:
            base = 235 if not self._hover else 255
            if self.isDown():
                base = 190
            fill = QColor(base, base, base, 255 if enabled else 90)
        p.setBrush(fill)
        p.drawEllipse(c, 29, 29)
        if self.recording:
            p.setBrush(QColor("white"))
            p.drawRoundedRect(QRectF(c.x() - 10, c.y() - 10, 20, 20), 2, 2)
        else:
            p.setPen(QColor("#202020") if enabled else QColor(60, 60, 60, 120))
            p.setFont(mdl2_font(18))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       glyph("video" if self.mode == "video" else "camera"))


class ThumbButton(QPushButton):
    """Miniatura dell'ultimo scatto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 52)
        self._pix: QPixmap | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Apri l'ultimo scatto")

    def set_pixmap(self, pix: QPixmap | None) -> None:
        self._pix = pix
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        r = self.rect().adjusted(1, 1, -1, -1)
        if self._pix and not self._pix.isNull():
            scaled = self._pix.scaled(r.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                      Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(r, scaled, QRect((scaled.width() - r.width()) // 2,
                                          (scaled.height() - r.height()) // 2, r.width(), r.height()))
        else:
            p.fillRect(r, QColor(255, 255, 255, 25))
            p.setPen(QColor(255, 255, 255, 120))
            p.setFont(mdl2_font(14))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, glyph("photo_gallery"))
        p.setPen(QPen(QColor(255, 255, 255, 200 if self.isEnabled() else 70), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)


def _round_button(text: str, size: int, font_pt: float) -> QPushButton:
    b = QPushButton(text)
    b.setFixedSize(size, size)
    b.setFont(mdl2_font(font_pt))
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setObjectName("RoundBtn")
    return b


class SettingsPanel(QFrame):
    """Pannello Impostazioni laterale (a sinistra)."""

    def __init__(self, win: "CameraWindow"):
        super().__init__(win.stage)
        self.win = win
        self.setObjectName("SettingsPanel")
        self.setFixedWidth(320)
        self.setStyleSheet("""
            #SettingsPanel { background: rgba(31,31,31,245); }
            #SettingsPanel QLabel { color: white; background: transparent; }
            #SettingsPanel QLabel#Sec { color: #E6E6E6; font-weight: 600; }
            #SettingsPanel QLabel#Hint { color: #A6A6A6; }
            #SettingsPanel QComboBox { background: #333333; color: white; border: 2px solid #555555;
                                       padding: 4px 8px; min-height: 22px; }
            #SettingsPanel QComboBox:hover { border-color: #888888; }
            #SettingsPanel QComboBox QAbstractItemView { background: #2B2B2B; color: white;
                                       selection-background-color: #0078D7; border: 1px solid #555555; }
            #SettingsPanel QPushButton#Back { background: transparent; border: none; color: white; }
            #SettingsPanel QPushButton#Back:hover { background: rgba(255,255,255,40); }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 12, 24, 16)
        lay.setSpacing(6)
        head = QHBoxLayout()
        back = QPushButton(glyph("back"))
        back.setObjectName("Back")
        back.setFont(mdl2_font(11))
        back.setFixedSize(40, 40)
        back.setToolTip("Indietro")
        back.clicked.connect(lambda: win.show_settings(False))
        head.addWidget(back)
        t = QLabel("Impostazioni")
        t.setFont(ui_font(16, QFont.Weight.DemiBold))
        head.addWidget(t, 1)
        lay.addLayout(head)
        lay.addSpacing(10)

        self.cb_grid = self._combo(lay, "Foto", "Griglia di inquadratura", GRIDS, win.set_grid)
        self.cb_timer = self._combo(lay, None, "Timer foto", ["Disattivato", "2 secondi", "5 secondi",
                                                               "10 secondi"],
                                    lambda i: win.set_timer_index(i))
        self.cb_photo_q = self._combo(lay, None, "Qualità foto", QUALITIES, win.set_photo_quality)
        lay.addSpacing(8)
        self.cb_video_q = self._combo(lay, "Video", "Qualità video", QUALITIES, win.set_video_quality)
        lay.addStretch(1)
        hint = QLabel("I file vengono salvati nel Rullino.")
        hint.setObjectName("Hint")
        hint.setFont(ui_font(9))
        lay.addWidget(hint)
        self.hide()

    def _combo(self, lay, section, label, items, slot) -> QComboBox:
        if section:
            s = QLabel(section)
            s.setObjectName("Sec")
            s.setFont(ui_font(12, QFont.Weight.DemiBold))
            lay.addWidget(s)
        lab = QLabel(label)
        lab.setFont(ui_font(10))
        lay.addWidget(lab)
        cb = QComboBox()
        cb.addItems(items)
        cb.setFont(ui_font(10))
        cb.currentIndexChanged.connect(slot)
        lay.addWidget(cb)
        return cb


class Stage(QWidget):
    """Contenitore con livelli sovrapposti, posizionati a mano."""

    def __init__(self, win: "CameraWindow"):
        super().__init__()
        self.win = win

    def resizeEvent(self, e) -> None:
        self.win.layout_stage()


# ---------------------------------------------------------------------------
class CameraWindow(UwpWindow):
    def __init__(self, client=None, fake: bool | None = None):
        super().__init__("Fotocamera", theme="dark", bg="#000000")
        self.resize(900, 560)
        self.client = client
        self.session = CameraSession(self._emit)
        if fake is None:
            fake = os.environ.get("EWA_CAMERA_FAKE", "") not in ("", "0")
        self.fake = fake
        self.mode = "photo"
        self.timer_index = 0
        self.hdr = False
        self.photo_quality = 0
        self.video_quality = 0
        self.last_file: Path | None = None
        self.save_dir = camera_roll_dir()
        self._counting = False
        self._count_left = 0
        self._cam_index = 0
        self._phase = 0.0
        self.camera = self.capture = self.recorder = self.msession = self.sink = None
        self.devices: list = []
        self._fake_names: list[str] = []

        lay = QVBoxLayout(self.content)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stage = Stage(self)
        lay.addWidget(self.stage)
        self._build_ui()
        self.setStyleSheet(self.styleSheet())  # riapplica il QSS ai figli creati dopo
        self._init_camera()
        self.layout_stage()
        self._load_last_thumb()

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_second)
        self._tick.start()
        self.session.open(self.available)

    # ---- UI ----------------------------------------------------------
    def _build_ui(self) -> None:
        st = self.stage
        self.setStyleSheet(self.styleSheet() + """
            QPushButton#RoundBtn { background: rgba(255,255,255,45); color: white;
                border: 2px solid #E6E6E6; border-radius: 21px; }
            QPushButton#RoundBtn:hover { background: rgba(255,255,255,90); }
            QPushButton#RoundBtn:pressed { background: rgba(255,255,255,140); }
            QPushButton#RoundBtn:checked { background: rgba(255,255,255,110); }
            QPushButton#RoundBtn:disabled { color: rgba(255,255,255,90);
                border-color: #5A5A5A; background: rgba(255,255,255,15); }
            QPushButton#TopBtn { background: transparent; color: white; border: none; }
            QPushButton#TopBtn:hover { background: rgba(255,255,255,50); }
            QPushButton#TopBtn:pressed { background: rgba(255,255,255,90); }
            QPushButton#TopBtn:disabled { color: rgba(255,255,255,80); }
        """)
        self.preview = PreviewWidget(st)

        # pulsanti in alto
        def top(name_glyph: str, tip: str) -> QPushButton:
            b = QPushButton(glyph(name_glyph), st)
            b.setObjectName("TopBtn")
            b.setFont(mdl2_font(13))
            b.setFixedSize(48, 48)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            return b

        self.btn_settings = top("settings", "Impostazioni")
        self.btn_settings.clicked.connect(lambda: self.show_settings(not self.panel.isVisible()))
        self.btn_timer = top("self_timer", "Timer foto: disattivato")
        self.btn_timer.setFixedWidth(64)
        self.btn_timer.clicked.connect(self.cycle_timer)
        self.btn_hdr = top("hdr", "HDR")
        self.btn_hdr.setFont(ui_font(9, QFont.Weight.DemiBold))
        self.btn_hdr.setText("HDR")
        self.btn_hdr.clicked.connect(self.toggle_hdr)
        self.btn_switch = top("switch_camera", "Cambia fotocamera")
        self.btn_switch.clicked.connect(self.switch_camera)

        # barra laterale
        self.sidebar = Sidebar(st)
        self.sidebar.setFixedWidth(SIDEBAR_W)
        sl = QVBoxLayout(self.sidebar)
        sl.setContentsMargins(0, 16, 0, 16)
        sl.setSpacing(14)
        sl.addStretch(1)
        self.btn_video = _round_button(glyph("video"), 42, 12)
        self.btn_video.setCheckable(True)
        self.btn_video.setToolTip("Video")
        self.btn_video.clicked.connect(lambda: self.set_mode("video"))
        self.shutter = ShutterButton()
        self.shutter.clicked.connect(self.on_shutter)
        self.btn_photo = _round_button(glyph("camera"), 42, 12)
        self.btn_photo.setCheckable(True)
        self.btn_photo.setToolTip("Foto")
        self.btn_photo.clicked.connect(lambda: self.set_mode("photo"))
        sl.addWidget(self.btn_video, 0, Qt.AlignmentFlag.AlignHCenter)
        sl.addWidget(self.shutter, 0, Qt.AlignmentFlag.AlignHCenter)
        sl.addWidget(self.btn_photo, 0, Qt.AlignmentFlag.AlignHCenter)
        sl.addStretch(1)
        self.thumb = ThumbButton()
        self.thumb.clicked.connect(self.open_last)
        sl.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignHCenter)

        # timer di registrazione
        self.rec_label = QLabel("00:00", st)
        self.rec_label.setFont(ui_font(14, QFont.Weight.DemiBold))
        self.rec_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rec_label.setStyleSheet("color: white; background: rgba(0,0,0,150); padding: 4px 14px;"
                                     "border-radius: 4px;")
        self.rec_label.hide()

        self.panel = SettingsPanel(self)

        # flash
        self.flash = QWidget(st)
        self.flash.setStyleSheet("background: white;")
        self.flash.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._flash_fx = QGraphicsOpacityEffect(self.flash)
        self.flash.setGraphicsEffect(self._flash_fx)
        self._flash_fx.setOpacity(0.0)
        self._flash_anim = QPropertyAnimation(self._flash_fx, b"opacity", self)
        self._flash_anim.setDuration(280)
        self._flash_anim.setStartValue(0.9)
        self._flash_anim.setEndValue(0.0)
        self._flash_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.flash.hide()
        self._flash_anim.finished.connect(self.flash.hide)

        self._refresh_mode_ui()

    def layout_stage(self) -> None:
        if not hasattr(self, "preview"):
            return
        w, h = self.stage.width(), self.stage.height()
        self.preview.setGeometry(0, 0, w, h)
        self.flash.setGeometry(0, 0, w, h)
        self.sidebar.setGeometry(w - SIDEBAR_W, 0, SIDEBAR_W, h)
        self.btn_settings.move(4, 4)
        self.btn_timer.move(56, 4)
        self.btn_hdr.move(124, 4)
        self.btn_switch.move(w - SIDEBAR_W - 52, 4)
        self.panel.setGeometry(0, 0, self.panel.width(), h)
        self.rec_label.adjustSize()
        pw = w - SIDEBAR_W
        self.rec_label.move((pw - self.rec_label.width()) // 2, h - self.rec_label.height() - 22)
        for wdg in (self.btn_settings, self.btn_timer, self.btn_hdr, self.btn_switch, self.sidebar,
                    self.rec_label):
            wdg.raise_()
        self.panel.raise_()
        self.flash.raise_()

    # ---- camera ------------------------------------------------------
    @property
    def available(self) -> bool:
        return self.fake or bool(self.devices)

    def camera_names(self) -> list[str]:
        if self.fake:
            return self._fake_names
        return [d.description() for d in self.devices]

    def _init_camera(self) -> None:
        if self.fake:
            n = 2 if os.environ.get("EWA_CAMERA_FAKE") == "2" else 1
            self._fake_names = ["Fotocamera simulata"] + [f"Fotocamera simulata {i}" for i in range(2, n + 1)]
            self._fake_timer = QTimer(self)
            self._fake_timer.setInterval(40)
            self._fake_timer.timeout.connect(self._fake_frame)
            self._fake_timer.start()
            self._fake_frame()
        else:
            try:
                from PySide6.QtMultimedia import QMediaDevices
                self.devices = list(QMediaDevices.videoInputs())
            except Exception:
                self.devices = []
            if self.devices:
                self._start_real_camera(0)
        self.preview.no_camera = not self.available
        self.btn_switch.setVisible(len(self.camera_names()) > 1)
        self._set_enabled(self.available)

    def _start_real_camera(self, index: int) -> None:
        from PySide6.QtMultimedia import (QCamera, QImageCapture, QMediaCaptureSession, QMediaRecorder,
                                          QVideoSink)
        if self.camera is not None:
            self.camera.stop()
        self.camera = QCamera(self.devices[index])
        if self.msession is None:
            self.msession = QMediaCaptureSession(self)
            self.sink = QVideoSink(self)
            self.sink.videoFrameChanged.connect(self._on_frame)
            self.capture = QImageCapture(self)
            self.capture.imageSaved.connect(self._on_image_saved)
            self.capture.errorOccurred.connect(lambda *_: None)
            self.recorder = QMediaRecorder(self)
            self.msession.setImageCapture(self.capture)
            self.msession.setRecorder(self.recorder)
            self.msession.setVideoOutput(self.sink)
        self.msession.setCamera(self.camera)
        self.camera.start()
        self._cam_index = index
        self.set_photo_quality(self.photo_quality)

    def _on_frame(self, frame) -> None:
        img = frame.toImage()
        if not img.isNull():
            self.preview.set_image(img)

    def _fake_frame(self) -> None:
        """Finta anteprima: gradiente animato con un cerchio in movimento."""
        self._phase += 0.02
        img = QImage(1280, 720, QImage.Format.Format_RGB32)
        p = QPainter(img)
        g = QLinearGradient(0, 0, 1280, 720)
        t = (math.sin(self._phase) + 1) / 2
        g.setColorAt(0, QColor.fromHsvF((0.58 + 0.08 * t) % 1, 0.35, 0.42))
        g.setColorAt(1, QColor.fromHsvF((0.85 - 0.1 * t) % 1, 0.30, 0.22))
        p.fillRect(img.rect(), g)
        cx = 640 + 260 * math.sin(self._phase * 1.3)
        rg = QRadialGradient(cx, 340, 260)
        rg.setColorAt(0, QColor(255, 255, 255, 90))
        rg.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(img.rect(), rg)
        p.end()
        self.preview.set_image(img)

    def _set_enabled(self, on: bool) -> None:
        for b in (self.btn_video, self.btn_photo, self.shutter, self.thumb if False else self.btn_timer,
                  self.btn_hdr):
            b.setEnabled(on)
        self.shutter.setEnabled(on)
        # barra visibile ma disabilitata; il pulsante Impostazioni resta attivo

    # ---- azioni ------------------------------------------------------
    def _emit(self, type_: str, data: dict | None = None) -> None:
        if self.client is not None:
            self.client.emit(type_, data or {})

    def set_mode(self, mode: str) -> None:
        if self.session.recording or self._counting:
            return
        self.session.user_action()
        self.mode = mode
        self._refresh_mode_ui()

    def _refresh_mode_ui(self) -> None:
        self.btn_photo.setChecked(self.mode == "photo")
        self.btn_video.setChecked(self.mode == "video")
        self.shutter.set_state(self.mode, self.session.recording if hasattr(self, "session") else False)
        self.btn_timer.setVisible(self.mode == "photo")
        self.btn_hdr.setVisible(self.mode == "photo")
        recording = self.session.recording if hasattr(self, "session") else False
        self.btn_photo.setEnabled(self.available and not recording)
        self.btn_video.setEnabled(self.available and not recording)

    def on_shutter(self) -> None:
        if not self.available:
            return
        if self.mode == "photo":
            if self._counting:
                self._cancel_countdown()
                return
            secs = TIMER_STEPS[self.timer_index]
            if secs:
                self._start_countdown(secs)
            else:
                self.take_photo()
        else:
            self.stop_video() if self.session.recording else self.start_video()

    def _start_countdown(self, secs: int) -> None:
        self._counting = True
        self._count_left = secs
        self.preview.countdown = secs
        self.preview.update()
        self._cd = QTimer(self)
        self._cd.setInterval(1000)
        self._cd.timeout.connect(self._countdown_step)
        self._cd.start()
        self.session.user_action()

    def _countdown_step(self) -> None:
        self._count_left -= 1
        self.preview.countdown = max(self._count_left, 0)
        self.preview.update()
        if self._count_left <= 0:
            self._cancel_countdown()
            self.take_photo()

    def _cancel_countdown(self) -> None:
        self._counting = False
        self._count_left = 0
        self.preview.countdown = 0
        self.preview.update()
        if hasattr(self, "_cd"):
            self._cd.stop()

    def do_flash(self) -> None:
        self.flash.show()
        self.flash.raise_()
        self._flash_anim.stop()
        self._flash_anim.start()

    def take_photo(self) -> None:
        path = unique_path(self.save_dir, capture_filename("photo"))
        self.do_flash()
        if self.fake or self.capture is None:
            img = self.preview.current_image()
            if img is not None:
                img.save(str(path), "JPG", (95, 80, 60)[self.photo_quality])
            self._on_image_saved(0, str(path))
        else:
            self.capture.captureToFile(str(path))

    def _on_image_saved(self, _id: int, filename: str) -> None:
        self.last_file = Path(filename)
        pix = QPixmap(filename)
        self.thumb.set_pixmap(pix if not pix.isNull() else None)
        self.session.photo()

    def start_video(self) -> None:
        path = unique_path(self.save_dir, capture_filename("video"))
        self.last_video_path = path
        if not self.fake and self.recorder is not None:
            self.recorder.setOutputLocation(QUrl.fromLocalFile(str(path)))
            self.recorder.record()
        self.session.video_start()
        self.rec_label.setText("00:00")
        self.rec_label.setStyleSheet("color: white; background: rgba(0,0,0,150); padding: 4px 14px;"
                                     "border-radius: 4px;")
        self.rec_label.show()
        self._refresh_mode_ui()
        self.layout_stage()

    def stop_video(self) -> None:
        path = getattr(self, "last_video_path", None)
        if not self.fake and self.recorder is not None:
            self.recorder.stop()
        elif path is not None:
            try:
                path.write_bytes(b"")  # segnaposto in modalità finta
            except OSError:
                pass
        self.session.video_stop()
        self.rec_label.hide()
        if path is not None:
            self.last_file = path
        img = self.preview.current_image()
        if img is not None:
            self.thumb.set_pixmap(QPixmap.fromImage(img))
        self._refresh_mode_ui()

    def _on_second(self) -> None:
        if self.session.recording:
            s = self.session.recording_seconds()
            self.rec_label.setText(f"{s // 60:02d}:{s % 60:02d}")
            red = s % 2 == 0
            self.rec_label.setStyleSheet(
                f"color: {'#FF4B5C' if red else 'white'}; background: rgba(0,0,0,150); padding: 4px 14px;"
                "border-radius: 4px;")
            self.rec_label.adjustSize()
        self.session.tick()

    def cycle_timer(self) -> None:
        self.set_timer_index((self.timer_index + 1) % len(TIMER_STEPS))

    def set_timer_index(self, i: int) -> None:
        self.timer_index = i
        secs = TIMER_STEPS[i]
        self.btn_timer.setText(glyph("self_timer") + (f" {secs}" if secs else ""))
        self.btn_timer.setToolTip("Timer foto: " + (f"{secs} secondi" if secs else "disattivato"))
        if self.panel.cb_timer.currentIndex() != i:
            self.panel.cb_timer.setCurrentIndex(i)
        self.session.user_action()

    def toggle_hdr(self) -> None:
        self.hdr = not self.hdr
        self.btn_hdr.setStyleSheet("background: rgba(255,255,255,70);" if self.hdr else "")
        self.btn_hdr.setToolTip("HDR attivo" if self.hdr else "HDR")
        self.session.user_action()

    def set_grid(self, i: int) -> None:
        self.preview.grid = i
        self.preview.update()
        self.session.user_action()

    def set_photo_quality(self, i: int) -> None:
        self.photo_quality = i
        if self.capture is not None:
            from PySide6.QtMultimedia import QImageCapture
            q = (QImageCapture.Quality.VeryHighQuality, QImageCapture.Quality.NormalQuality,
                 QImageCapture.Quality.LowQuality)[i]
            self.capture.setQuality(q)

    def set_video_quality(self, i: int) -> None:
        self.video_quality = i
        if self.recorder is not None:
            from PySide6.QtMultimedia import QMediaRecorder
            self.recorder.setQuality((QMediaRecorder.Quality.VeryHighQuality, QMediaRecorder.Quality.NormalQuality,
                                      QMediaRecorder.Quality.LowQuality)[i])

    def show_settings(self, on: bool) -> None:
        self.panel.setVisible(on)
        if on:
            self.panel.raise_()
            self.flash.raise_()
        self.session.user_action()

    def switch_camera(self) -> None:
        names = self.camera_names()
        if len(names) < 2 or self.session.recording:
            return
        self._cam_index = (self._cam_index + 1) % len(names)
        if not self.fake:
            self._start_real_camera(self._cam_index)
        self.session.switch(names[self._cam_index])

    # ---- ultimo scatto -----------------------------------------------
    def _load_last_thumb(self) -> None:
        f = latest_capture(self.save_dir)
        if f is None:
            return
        self.last_file = f
        pix = QPixmap(str(f)) if f.suffix.lower() != ".mp4" else QPixmap()
        self.thumb.set_pixmap(pix if not pix.isNull() else None)

    def open_last(self) -> None:
        self.session.user_action()
        target = self.last_file if self.last_file and self.last_file.exists() else self.save_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.on_shutter()
        elif e.key() == Qt.Key.Key_Escape and self.panel.isVisible():
            self.show_settings(False)
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e) -> None:
        if self.session.recording:
            self.stop_video()
        if self.camera is not None:
            self.camera.stop()
        super().closeEvent(e)


def build(client) -> QWidget:
    return CameraWindow(client)
