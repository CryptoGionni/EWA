import os
import re
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from ewa.tools.camera.logic import CameraSession, IdleTracker, capture_filename, unique_path


class FakeClient:
    def __init__(self):
        self.events = []

    def emit(self, type_, data=None, priority=None):
        self.events.append((type_, data or {}))

    def types(self):
        return [t for t, _ in self.events]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(avail=True):
    c, clk = FakeClient(), Clock()
    s = CameraSession(c.emit, clk)
    s.open(avail)
    return s, c, clk


def test_filename():
    n = capture_filename("photo", datetime(2026, 11, 1, 14, 3, 22))
    assert n == "WIN_20261101_14_03_22_Pro.jpg"
    assert capture_filename("video", datetime(2026, 11, 1, 14, 3, 22)).endswith(".mp4")
    assert re.match(r"WIN_\d{8}_\d\d_\d\d_\d\d_Pro\.jpg", capture_filename())


def test_unique_path(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"")
    assert unique_path(tmp_path, "a.jpg").name == "a_1.jpg"


def test_open_and_counters():
    s, c, clk = make()
    assert c.events[0] == ("camera.open", {"available": True})
    s.photo()
    s.photo()
    assert c.events[-1] == ("camera.photo", {"count": 2})
    s.video_start()
    clk.t += 12.7
    s.video_stop()
    assert c.events[-2:] == [("camera.video_start", {}), ("camera.video_stop", {"seconds": 12})]
    s.switch("Cam 2")
    assert c.events[-1] == ("camera.switch", {"camera": "Cam 2"})


def test_idle_schedule():
    s, c, clk = make()
    for t in (59, 61, 100, 179, 181, 299, 301, 419):
        clk.t = 1000.0 + t
        s.tick()
    secs = [d["seconds"] for ty, d in c.events if ty == "camera.idle"]
    assert secs == [60, 180, 300]


def test_idle_reset_on_action():
    s, c, clk = make()
    clk.t += 50
    s.photo()
    clk.t += 50
    s.tick()
    assert "camera.idle" not in c.types()
    clk.t += 20
    s.tick()
    assert c.events[-1] == ("camera.idle", {"seconds": 60})
    s.user_action()
    clk.t += 61
    s.tick()
    assert c.events[-1] == ("camera.idle", {"seconds": 60})


def test_no_idle_without_camera_or_while_recording():
    s, c, clk = make(False)
    clk.t += 500
    s.tick()
    assert "camera.idle" not in c.types()
    s, c, clk = make(True)
    s.video_start()
    clk.t += 500
    s.tick()
    assert "camera.idle" not in c.types()


def test_idle_tracker_jump():
    clk = Clock()
    t = IdleTracker(clk)
    t.set_active(True)
    clk.t += 400
    assert t.poll() == 300
    assert t.poll() is None


@pytest.fixture
def qapp():
    from ewa.ui.win10 import make_app
    return make_app("camera-test")


def test_window_no_camera(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("EWA_CAMERA_DIR", str(tmp_path))
    from PySide6.QtMultimedia import QMediaDevices
    monkeypatch.setattr(QMediaDevices, "videoInputs", staticmethod(lambda: []))
    from ewa.tools.camera.window import CameraWindow
    c = FakeClient()
    w = CameraWindow(c, fake=False)
    assert c.events[0] == ("camera.open", {"available": False})
    assert w.preview.no_camera and not w.shutter.isEnabled()
    w.on_shutter()
    assert c.types() == ["camera.open"]
    w.close()


def test_window_fake_photo_video(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("EWA_CAMERA_DIR", str(tmp_path))
    monkeypatch.setenv("EWA_CAMERA_FAKE", "2")
    from ewa.tools.camera.window import CameraWindow
    c = FakeClient()
    w = CameraWindow(c, fake=True)
    w.take_photo()
    assert list(tmp_path.glob("WIN_*_Pro.jpg"))
    assert c.events[-1] == ("camera.photo", {"count": 1})
    w.set_mode("video")
    w.on_shutter()
    assert w.session.recording
    w.on_shutter()
    assert c.types()[-2:] == ["camera.video_start", "camera.video_stop"]
    assert list(tmp_path.glob("*.mp4"))
    w.switch_camera()
    assert c.events[-1][0] == "camera.switch"
    w.close()
