"""Test della Calcolatrice: motore (puro) e finestra (offscreen)."""
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from ewa.tools.calculator.engine import (Calculator, ERR_DIV0, ERR_INVALID, ERR_UNDEF, format_number)


def run(keys: str, mode: str = "standard") -> Calculator:
    c = Calculator(mode)
    for k in keys.split():
        c.press(k)
    return c


def test_format():
    assert format_number(Decimal("1234567.5")) == "1.234.567,5"
    assert format_number(Decimal("-0.25")) == "-0,25"
    assert format_number(Decimal(10) ** 16) == "1,e+16"
    assert format_number(Decimal(1) / Decimal(3)) == "0,3333333333333333"


def test_standard_chain_is_immediate():
    c = run("1 add 2 mul 3 eq")
    assert c.display == "9"
    assert c.expression == "3 × 3 ="


def test_scientific_precedence():
    assert run("1 add 2 mul 3 eq", "scientifica").display == "7"
    assert run("lp 1 add 2 rp mul 3 eq", "scientifica").display == "9"
    assert run("2 pow 3 pow 2 eq", "scientifica").display == "512"


def test_decimal_exact():
    assert run("0 , 1 add 0 , 2 eq").display == "0,3"


def test_repeat_equals():
    assert run("2 add 3 eq eq eq").display == "11"


def test_percent_standard():
    c = run("2 0 0 add 1 0 pct eq")
    assert c.display == "220"


def test_unary():
    assert run("9 sqrt").display == "3"
    assert run("4 recip").display == "0,25"
    assert run("1 2 sqr").display == "144"
    c = run("5 add 9 sqrt eq")
    assert c.display == "8" and c.expression == "5 + √(9) ="


def test_errors():
    c = run("5 div 0 eq")
    assert c.display == ERR_DIV0
    assert c.take_events() == [("error", "5 ÷ 0 =", ERR_DIV0)]
    assert run("0 div 0 eq").display == ERR_UNDEF
    assert run("0 recip").display == ERR_DIV0
    assert run("2 neg sqrt").display == ERR_INVALID
    c = run("5 div 0 eq 7")
    assert c.display == "7"  # una cifra ripristina


def test_entry_editing():
    c = run("1 2 3 back")
    assert c.display == "12"
    c = run("1 2 3 4 5 6 7")
    assert c.display == "1.234.567"
    c = run("5 neg")
    assert c.display == "-5"
    c = run("0 , 5 0")
    assert c.display == "0,50"
    assert run("1 2 ce").display == "0"


def test_scientific_functions():
    assert run("3 0 sin", "scientifica").display == "0,5"
    assert run("1 8 0 cos", "scientifica").display == "-1"
    assert run("5 fact", "scientifica").display == "120"
    assert run("1 0 0 log", "scientifica").display == "2"
    assert run("8 pow10", "scientifica").display == "100.000.000"
    c = run("angle", "scientifica")
    assert c.angle == "RAD"


def test_mod_operator():
    c = Calculator("scientifica")
    for k in ["1", "0", "mod", "3", "eq"]:
        c.press(k)
    assert c.display == "1"


def test_tan_90_undefined():
    c = run("9 0 tan", "scientifica")
    assert c.error


def test_memory():
    c = run("5 ms 3 add 1 0 eq mp")
    assert c.memory == [Decimal(18)]
    c.press("mr")
    assert c.display == "18"
    c.press("mc")
    assert c.memory == []


def test_history():
    c = run("1 2 mul 7 eq")
    assert [(h.expr, h.result) for h in c.history] == [("12 × 7 =", "84")]


def test_exp_entry():
    c = run("3 exp 2 eq", "scientifica")
    assert c.display == "300"


def test_long_numbers_overflow_to_scientific():
    c = run("9 9 9 9 9 9 9 9 9 9 mul 9 9 9 9 9 9 9 9 9 9 eq")
    assert "e+19" in c.display


# --- finestra ----------------------------------------------------------------
class FakeClient:
    def __init__(self):
        self.calls = []

    def emit(self, type_, data=None, priority=None):
        self.calls.append((type_, data or {}))


@pytest.fixture(scope="module")
def app():
    from ewa.ui.win10 import make_app
    return make_app("calc-test")


def test_window_events(app):
    from ewa.tools.calculator.window import CalculatorWindow
    fc = FakeClient()
    w = CalculatorWindow(fc)
    assert fc.calls[0][0] == "calc.open"
    for k in "12":
        w.press(k)
    w.press("mul")
    w.press("7")
    w.press("eq")
    assert ("calc.result", {"expr": "12 × 7 =", "result": "84", "mode": "standard"}) in fc.calls
    w.press("div")
    w.press("0")
    w.press("eq")
    errs = [c for c in fc.calls if c[0] == "calc.error"]
    assert errs and errs[0][1]["error"] == ERR_DIV0
    w.set_mode("scientifica")
    assert fc.calls[-1] == ("calc.mode", {"mode": "scientifica"})
    assert w.title.text() == "Scientifica"


def test_window_keyboard_and_layout(app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from ewa.tools.calculator.window import CalculatorWindow
    w = CalculatorWindow(FakeClient())
    w.show()
    for ch in "6*7":
        QTest.keyClicks(w, ch)
    QTest.keyClick(w, Qt.Key.Key_Return)
    assert w.display.text() == "42"
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert w.display.text() == "0"
    QTest.keyClicks(w, "1,5")
    assert w.display.text() == "1,5"
    QTest.keyClick(w, Qt.Key.Key_Backspace)
    assert w.display.text() == "1,"
    w.resize(760, 520)
    app.processEvents()
    assert w.wide and w.side.isVisible() and not w.btn_hist.isVisible()
    w.resize(322, 502)
    app.processEvents()
    assert not w.wide and not w.side.isVisible()
    w._toggle_flyout()
    assert w.flyout.isVisible()
    w.close()
