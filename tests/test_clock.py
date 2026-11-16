import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from ewa.tools.clock.models import (DONE, StopwatchModel, TimerModel, fmt_hms, fmt_stopwatch,
                                    progress_interval)


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Rec:
    def __init__(self):
        self.events = []

    def emit(self, type_, data=None, priority=None):
        self.events.append((type_, data or {}))

    def types(self):
        return [t for t, _ in self.events]


def run(model, clock, seconds, step=1.0):
    n = int(seconds / step)
    for _ in range(n):
        clock.t += step
        model.tick()


def test_interval_clamp():
    assert progress_interval(60) == 60
    assert progress_interval(2400) == 600
    assert progress_interval(7200) == 600
    assert progress_interval(240) == 60
    assert progress_interval(480) == 120


def test_timer_40min_progress_at_10_20_30():
    c, r = FakeClock(), Rec()
    m = TimerModel(2400, "Timer (1)", r.emit, c)
    m.start()
    run(m, c, 2400 + 5)
    assert r.types() == ["timer.start", "timer.progress", "timer.progress", "timer.progress", "timer.done"]
    prog = [d for t, d in r.events if t == "timer.progress"]
    assert [p["elapsed"] for p in prog] == [600, 1200, 1800]
    assert [p["pct"] for p in prog] == [25, 50, 75]
    assert prog[0]["remaining"] == 1800 and prog[0]["label"] == "Timer (1)"
    assert r.events[-1][1] == {"seconds": 2400, "label": "Timer (1)"}
    assert m.state == DONE


def test_timer_2min_single_progress_and_1min_none():
    c, r = FakeClock(), Rec()
    m = TimerModel(120, "a", r.emit, c)
    m.start()
    run(m, c, 130)
    assert r.types() == ["timer.start", "timer.progress", "timer.done"]
    c2, r2 = FakeClock(), Rec()
    m2 = TimerModel(60, "b", r2.emit, c2)
    m2.start()
    run(m2, c2, 70)
    assert r2.types() == ["timer.start", "timer.done"]


def test_timer_precision_independent_of_ticks():
    c, r = FakeClock(), Rec()
    m = TimerModel(60, "p", r.emit, c)
    m.start()
    c.t += 59.9
    m.tick()
    assert m.state != DONE
    c.t += 0.2          # un solo tick tardivo
    m.tick()
    assert m.state == DONE and r.types()[-1] == "timer.done"


def test_pause_resume_reset():
    c, r = FakeClock(), Rec()
    m = TimerModel(300, "x", r.emit, c)
    m.start()
    run(m, c, 100)
    m.pause()
    assert r.events[-1] == ("timer.pause", {"label": "x", "remaining": 200})
    c.t += 1000                      # in pausa il tempo non scorre
    m.tick()
    assert m.remaining() == pytest.approx(200)
    m.start()                        # ripresa: nessun nuovo start
    assert r.types().count("timer.start") == 1
    run(m, c, 50)
    m.reset()
    assert r.events[-1] == ("timer.reset", {"label": "x", "elapsed": 150})
    assert m.state == "idle"
    m.reset()                        # reset a timer fermo: niente evento
    assert r.types().count("timer.reset") == 1


def test_reset_not_emitted_when_done_or_never_started():
    c, r = FakeClock(), Rec()
    m = TimerModel(5, "d", r.emit, c)
    m.reset()
    m.start()
    run(m, c, 6)
    m.reset()
    assert "timer.reset" not in r.types()


def test_progress_after_resume_counts_effective_time():
    c, r = FakeClock(), Rec()
    m = TimerModel(120, "x", r.emit, c)
    m.start()
    run(m, c, 40)
    m.pause()
    c.t += 500
    m.start()
    run(m, c, 15)       # 55 s effettivi: nessun progress
    assert "timer.progress" not in r.types()
    run(m, c, 10)       # 65 s
    assert r.types().count("timer.progress") == 1


def test_stopwatch_events():
    c, r = FakeClock(), Rec()
    s = StopwatchModel(r.emit, c)
    s.start()
    c.t += 12.345
    s.lap()
    c.t += 7.5
    s.lap()
    c.t += 1
    s.stop()
    s.start()           # ripresa: niente start
    c.t += 2
    s.stop()
    assert r.types() == ["stopwatch.start", "stopwatch.lap", "stopwatch.lap", "stopwatch.stop", "stopwatch.stop"]
    assert r.events[1][1] == {"elapsed": 12.35, "laps": 1, "lap_time": 12.35} or r.events[1][1]["laps"] == 1
    assert r.events[2][1]["lap_time"] == pytest.approx(7.5)
    assert r.events[3][1]["elapsed"] == pytest.approx(20.85, abs=0.011) and r.events[3][1]["laps"] == 2
    s.reset()
    s.start()
    assert r.types().count("stopwatch.start") == 2


def test_stopwatch_extremes():
    c = FakeClock()
    s = StopwatchModel(None, c)
    s.start()
    for d in (10, 5, 20, 8):
        c.t += d
        s.lap()
    assert s.extremes() == (1, 2)


def test_formats():
    assert fmt_hms(2400) == "00:40:00"
    assert fmt_hms(59.2) == "00:01:00"
    assert fmt_stopwatch(0) == "00:00:00,00"
    assert fmt_stopwatch(3725.678) == "01:02:05,67"


def test_window_smoke(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ewa.tools.clock.window import ClockWindow
    app = QApplication.instance() or QApplication([])
    c, r = FakeClock(), Rec()
    w = ClockWindow(r, tab="cronometro", now=c)
    assert r.events[0] == ("clock.open", {"tab": "stopwatch"})
    assert len(w.timer.cards) == 1 and w.timer.cards[0].model.seconds == 60
    w.set_tab("timer")
    w.timer.open_new()
    w.timer.editor.h.set_value(0)
    w.timer.editor.m.set_value(2)
    w.timer.editor.s.set_value(0)
    w.timer.editor._save()
    assert [cd.model.label for cd in w.timer.cards] == ["Timer (1)", "Timer (2)"]
    card = w.timer.cards[1]
    card.btn_play.click()
    c.t += 130
    w.timer.tick()
    assert r.types()[-1] == "timer.done" and "Tempo scaduto" in card.status.text()
    w.stopwatch.btn_play.click()
    c.t += 1.5
    w.stopwatch.btn_lap.click()
    assert w.stopwatch.table.rowCount() == 1
    w.close()
