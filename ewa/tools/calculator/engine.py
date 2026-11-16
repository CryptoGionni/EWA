"""Motore della Calcolatrice: logica pura, senza Qt e senza eval().

Semantica ricalcata sulla Calcolatrice di Windows 10:
- Standard: le operazioni sono immediate e a catena (1 + 2 × 3 = 9).
- Scientifica: precedenza degli operatori e parentesi (1 + 2 × 3 = 7).
- Aritmetica Decimal a 34 cifre, visualizzazione a 16 cifre significative.
- Numeri in formato italiano: virgola decimale, punto per le migliaia.
"""
from __future__ import annotations

import decimal
import math
import random
from dataclasses import dataclass
from decimal import Decimal

ERR_DIV0 = "Impossibile dividere per zero"
ERR_INVALID = "Input non valido"
ERR_UNDEF = "Il risultato non è definito"
ERR_OVERFLOW = "Overflow"

MAX_DIGITS = 16
STANDARD, SCIENTIFIC = "standard", "scientifica"

CTX = decimal.Context(prec=34, Emax=999999, Emin=-999999, rounding=decimal.ROUND_HALF_EVEN,
                      traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow])

PI = Decimal("3.141592653589793238462643383279503")
E = Decimal("2.718281828459045235360287471352662")
ZERO = Decimal(0)

# priorità degli operatori binari (modalità scientifica)
PREC = {"+": 1, "−": 1, "×": 2, "÷": 2, "mod": 2, "^": 3, "yroot": 3, "logbase": 3}
RIGHT_ASSOC = {"^", "yroot", "logbase"}


class CalcError(Exception):
    pass


# ---------------------------------------------------------------------------
# Formattazione
# ---------------------------------------------------------------------------
def _round_sig(d: Decimal, n: int) -> Decimal:
    with decimal.localcontext() as c:
        c.prec = n
        c.rounding = decimal.ROUND_HALF_UP
        return +d


def _group(int_digits: str) -> str:
    out = []
    while len(int_digits) > 3:
        out.insert(0, int_digits[-3:])
        int_digits = int_digits[:-3]
    out.insert(0, int_digits)
    return ".".join(out)


def format_number(d: Decimal, fe: bool = False) -> str:
    """Decimal -> stringa italiana (16 cifre significative; notazione scientifica se serve)."""
    if d == 0:
        return "0,e+0" if fe else "0"
    d = _round_sig(d, MAX_DIGITS)
    sign = "-" if d < 0 else ""
    d = abs(d)
    adj = d.adjusted()
    digits = "".join(map(str, d.as_tuple().digits)).rstrip("0") or "0"
    if fe or adj >= MAX_DIGITS or adj < -15:
        return f"{sign}{digits[0]},{digits[1:]}e{adj:+d}"
    txt = format(d.normalize(), "f")
    ip, _, fp = txt.partition(".")
    return f"{sign}{_group(ip)}" + (f",{fp}" if fp else "")


def format_entry(raw: str) -> str:
    """Stringa grezza in digitazione ('-1234.50e+3') -> formato italiano."""
    mant, _, ex = raw.partition("e")
    sign = ""
    if mant.startswith("-"):
        sign, mant = "-", mant[1:]
    ip, point, fp = mant.partition(".")
    out = sign + _group(ip or "0") + ("," + fp if point else "")
    return out + (f"e{ex}" if ex else "") if "e" in raw else out


# ---------------------------------------------------------------------------
# Funzioni numeriche
# ---------------------------------------------------------------------------
def _from_float(x: float, sig: int = 15) -> Decimal:
    if math.isnan(x):
        raise CalcError(ERR_INVALID)
    if math.isinf(x):
        raise CalcError(ERR_OVERFLOW)
    return _round_sig(Decimal(repr(x)), sig)


def _check(d: Decimal) -> Decimal:
    if d != 0 and abs(d).adjusted() >= 10000:
        raise CalcError(ERR_OVERFLOW)
    return d


def _is_int(d: Decimal) -> bool:
    return d == d.to_integral_value()


def _power(a: Decimal, b: Decimal) -> Decimal:
    if a == 0:
        if b == 0:
            raise CalcError(ERR_UNDEF)
        if b < 0:
            raise CalcError(ERR_DIV0)
        return ZERO
    if a < 0 and not _is_int(b):
        raise CalcError(ERR_INVALID)
    if abs(b) * max(abs(a).adjusted(), 1) > 20000:
        raise CalcError(ERR_OVERFLOW)
    return _check(CTX.power(a, b))


def _apply(op: str, a: Decimal, b: Decimal) -> Decimal:
    if op == "+":
        return _check(CTX.add(a, b))
    if op == "−":
        return _check(CTX.subtract(a, b))
    if op == "×":
        return _check(CTX.multiply(a, b))
    if op == "÷":
        if b == 0:
            raise CalcError(ERR_UNDEF if a == 0 else ERR_DIV0)
        return _check(CTX.divide(a, b))
    if op == "mod":
        if b == 0:
            raise CalcError(ERR_DIV0)
        return CTX.remainder(a, b)
    if op == "^":
        return _power(a, b)
    if op == "yroot":  # a ʸ√ b  = a^(1/b)
        if b == 0:
            raise CalcError(ERR_DIV0 if a != 0 else ERR_UNDEF)
        if a < 0:
            if _is_int(b) and int(b) % 2 == 1:
                return -_power(-a, CTX.divide(1, b))
            raise CalcError(ERR_INVALID)
        return _power(a, CTX.divide(1, b))
    if op == "logbase":  # log in base b di a
        if a <= 0 or b <= 0 or b == 1:
            raise CalcError(ERR_INVALID)
        return CTX.divide(CTX.ln(a), CTX.ln(b))
    raise CalcError(ERR_INVALID)


def evaluate(vals: list[Decimal], ops: list[str], precedence: bool = True) -> Decimal:
    """Valuta n valori e n-1 operatori (shunting-yard, niente eval)."""
    out = [vals[0]]
    st: list[str] = []

    def prio(o: str) -> int:
        return PREC[o] if precedence else 0

    def reduce() -> None:
        o = st.pop()
        b = out.pop()
        a = out.pop()
        out.append(_apply(o, a, b))

    for op, v in zip(ops, vals[1:]):
        while st and (prio(st[-1]) > prio(op) or
                      (prio(st[-1]) == prio(op) and not (precedence and op in RIGHT_ASSOC))):
            reduce()
        st.append(op)
        out.append(v)
    while st:
        reduce()
    return out[0]


def _factorial(x: Decimal) -> Decimal:
    if x < 0:
        raise CalcError(ERR_INVALID)
    if _is_int(x):
        if x > 3248:
            raise CalcError(ERR_OVERFLOW)
        return _round_sig(Decimal(math.factorial(int(x))), 34)
    if x > 170:
        raise CalcError(ERR_OVERFLOW)
    return _from_float(math.gamma(float(x) + 1))


def _to_rad(x: Decimal, angle: str) -> float:
    if angle == "DEG":
        return math.radians(float(x % 360))
    if angle == "GRAD":
        return float(x % 400) * math.pi / 200
    return float(x)


def _from_rad(r: float, angle: str) -> Decimal:
    if angle == "DEG":
        return _from_float(math.degrees(r))
    if angle == "GRAD":
        return _from_float(r * 200 / math.pi)
    return _from_float(r)


def _clean(v: float, x: Decimal) -> float:
    # elimina il rumore numerico (sin(180°) = 0) senza toccare ingressi minuscoli
    return 0.0 if abs(v) < 1e-14 and abs(x) > 1e-9 else v


def trig(name: str, x: Decimal, angle: str) -> Decimal:
    """name: sin cos tan sec csc cot, con prefisso 'a' (inversa) e/o suffisso 'h' (iperbolica)."""
    inverse = name.startswith("a")
    base = name[1:] if inverse else name
    hyp = base.endswith("h")
    base = base[:-1] if hyp else base
    try:
        if not inverse:
            t = float(x) if hyp else _to_rad(x, angle)
            if hyp:
                if abs(t) > 700:
                    raise CalcError(ERR_OVERFLOW)
                s, c = math.sinh(t), math.cosh(t)
                t_ = {"sin": s, "cos": c, "tan": math.tanh(t),
                      "sec": 1 / c, "csc": (1 / s if s else None), "cot": (c / s if s else None)}[base]
            else:
                s, c = _clean(math.sin(t), x), _clean(math.cos(t), x)
                t_ = {"sin": s, "cos": c,
                      "tan": (s / c if c else None), "sec": (1 / c if c else None),
                      "csc": (1 / s if s else None), "cot": (c / s if s else None)}[base]
            if t_ is None:
                raise CalcError(ERR_DIV0)
            return _from_float(t_)
        v = float(x)
        if hyp:
            if base == "sin":
                return _from_float(math.asinh(v))
            if base == "cos":
                if v < 1:
                    raise CalcError(ERR_INVALID)
                return _from_float(math.acosh(v))
            if base == "tan":
                if abs(v) >= 1:
                    raise CalcError(ERR_INVALID)
                return _from_float(math.atanh(v))
            if base == "sec":
                if not 0 < v <= 1:
                    raise CalcError(ERR_INVALID)
                return _from_float(math.acosh(1 / v))
            if base == "csc":
                if v == 0:
                    raise CalcError(ERR_INVALID)
                return _from_float(math.asinh(1 / v))
            if v == 0 or abs(v) <= 1:  # acoth
                raise CalcError(ERR_INVALID)
            return _from_float(math.atanh(1 / v))
        if base == "sin":
            if abs(v) > 1:
                raise CalcError(ERR_INVALID)
            return _from_rad(math.asin(v), angle)
        if base == "cos":
            if abs(v) > 1:
                raise CalcError(ERR_INVALID)
            return _from_rad(math.acos(v), angle)
        if base == "tan":
            return _from_rad(math.atan(v), angle)
        if base == "sec":
            if abs(v) < 1:
                raise CalcError(ERR_INVALID)
            return _from_rad(math.acos(1 / v), angle)
        if base == "csc":
            if abs(v) < 1:
                raise CalcError(ERR_INVALID)
            return _from_rad(math.asin(1 / v), angle)
        return _from_rad(math.atan(1 / v) if v else math.pi / 2, angle)  # acot
    except (ValueError, OverflowError, ZeroDivisionError):
        raise CalcError(ERR_INVALID)


def _dms(x: Decimal) -> Decimal:
    s = -1 if x < 0 else 1
    x = abs(x)
    d = x.to_integral_value(decimal.ROUND_FLOOR)
    rem = (x - d) * 60
    m = rem.to_integral_value(decimal.ROUND_FLOOR)
    sec = (rem - m) * 60
    return CTX.multiply(s, CTX.add(CTX.add(d, m / 100), sec / 10000))


def _deg(x: Decimal) -> Decimal:
    s = -1 if x < 0 else 1
    x = abs(x)
    d = x.to_integral_value(decimal.ROUND_FLOOR)
    rem = (x - d) * 100
    m = rem.to_integral_value(decimal.ROUND_FLOOR)
    sec = (rem - m) * 100
    return CTX.multiply(s, CTX.add(CTX.add(d, m / 60), sec / 3600))


# nome funzione -> (testo nell'espressione, calcolo)
def _unary_table(angle: str):
    return {
        "sqr": ("sqr", lambda x: _check(CTX.multiply(x, x))),
        "cube": ("cube", lambda x: _check(CTX.multiply(x, CTX.multiply(x, x)))),
        "recip": ("1/", lambda x: _apply("÷", Decimal(1), x)),
        "sqrt": ("√", lambda x: CTX.sqrt(x) if x >= 0 else (_ for _ in ()).throw(CalcError(ERR_INVALID))),
        "cbrt": ("³√", lambda x: -_power(-x, CTX.divide(1, 3)) if x < 0 else _power(x, CTX.divide(1, 3))),
        "abs": ("abs", lambda x: abs(x)),
        "fact": ("fact", _factorial),
        "log": ("log", lambda x: CTX.log10(x) if x > 0 else (_ for _ in ()).throw(CalcError(ERR_INVALID))),
        "ln": ("ln", lambda x: CTX.ln(x) if x > 0 else (_ for _ in ()).throw(CalcError(ERR_INVALID))),
        "pow10": ("10^", lambda x: _power(Decimal(10), x)),
        "pow2": ("2^", lambda x: _power(Decimal(2), x)),
        "powe": ("e^", lambda x: _check(CTX.exp(x)) if x < 25000 else (_ for _ in ()).throw(CalcError(ERR_OVERFLOW))),
        "floor": ("floor", lambda x: x.to_integral_value(decimal.ROUND_FLOOR)),
        "ceil": ("ceil", lambda x: x.to_integral_value(decimal.ROUND_CEILING)),
        "dms": ("dms", _dms),
        "deg": ("deg", _deg),
    }


# ---------------------------------------------------------------------------
# Stato della calcolatrice
# ---------------------------------------------------------------------------
@dataclass
class HistoryItem:
    expr: str
    result: str
    value: Decimal


class Calculator:
    """Macchina a stati della calcolatrice. Tutti i tasti passano da `press(key)`."""

    def __init__(self, mode: str = STANDARD):
        self.mode = mode
        self.angle = "DEG"
        self.second = False
        self.hyp = False
        self.fe = False
        self.memory: list[Decimal] = []      # indice 0 = voce più recente
        self.history: list[HistoryItem] = []  # in ordine cronologico
        self.events: list[tuple] = []
        self._reset()

    # --- stato -------------------------------------------------------
    def _reset(self) -> None:
        self.tokens: list[tuple] = []     # ("n", valore, testo) | ("o", simbolo) | ("(",)
        self.parens: list[int] = []       # indici dei "(" aperti in tokens
        self.entry: str | None = None     # numero in digitazione (stringa grezza)
        self.value = ZERO                 # operando corrente quando entry è None
        self.cur_text: str | None = None  # testo operando dopo funzioni, es. "√(9)"
        self.has_operand = False
        self.after_equals = False
        self.expr_override: str | None = None
        self.error: str | None = None
        self.last_op: str | None = None
        self.last_operand: Decimal | None = None

    @property
    def scientific(self) -> bool:
        return self.mode == SCIENTIFIC

    def take_events(self) -> list[tuple]:
        ev, self.events = self.events, []
        return ev

    # --- proprietà di visualizzazione --------------------------------
    @property
    def display(self) -> str:
        if self.error:
            return self.error
        if self.entry is not None:
            return format_entry(self.entry)
        return format_number(self.value, self.fe)

    @property
    def expression(self) -> str:
        if self.after_equals and self.expr_override is not None:
            return self.expr_override
        return self._expr_so_far()

    @property
    def open_parens(self) -> int:
        return len(self.parens)

    def current_value(self) -> Decimal:
        if self.entry is not None:
            return Decimal(self.entry)
        return self.value

    def _expr_so_far(self) -> str:
        s = ""
        for t in self.tokens:
            s += t[2] if t[0] == "n" else (f" {t[1]} " if t[0] == "o" else "(")
        if self.has_operand and self.cur_text and self.entry is None:
            s += self.cur_text
        return s.rstrip()

    # --- errori ------------------------------------------------------
    def _fail(self, msg: str, expr: str) -> None:
        self.error = msg
        self.tokens, self.parens = [], []
        self.entry, self.cur_text = None, None
        self.has_operand = False
        self.after_equals = False
        self.events.append(("error", expr, msg))

    def _unlock(self) -> None:
        if self.error:
            self._reset()

    # --- immissione numeri --------------------------------------------
    def _begin_operand(self) -> None:
        """Prepara un nuovo operando digitato (dopo risultato, operatore o funzione)."""
        if self.after_equals:
            self.tokens, self.parens, self.expr_override = [], [], None
            self.after_equals = False
        if self.tokens and self.tokens[-1][0] == "n":  # gruppo ")" sostituito
            self.tokens.pop()
        self.cur_text = None

    def digit(self, d: str) -> None:
        self._unlock()
        if self.entry is None:
            self._begin_operand()
            self.entry = d
            self.has_operand = True
            return
        mant, _, ex = self.entry.partition("e")
        if "e" in self.entry:
            sign, digs = ex[0], ex[1:]
            digs = d if digs == "0" else (digs + d if len(digs) < 4 else digs)
            self.entry = f"{mant}e{sign}{digs}"
            return
        if sum(c.isdigit() for c in mant) >= MAX_DIGITS:
            return
        if mant in ("0", "-0"):
            self.entry = mant[:-1] + d
        else:
            self.entry += d

    def decimal_point(self) -> None:
        self._unlock()
        if self.entry is None:
            self._begin_operand()
            self.entry = "0."
            self.has_operand = True
        elif "." not in self.entry and "e" not in self.entry:
            self.entry += "."

    def backspace(self) -> None:
        if self.error:
            return
        if self.entry is None:
            return
        if "e" in self.entry:
            mant, _, ex = self.entry.partition("e")
            digs = ex[1:][:-1]
            self.entry = f"{mant}e{ex[0]}{digs}" if digs else mant
            return
        self.entry = self.entry[:-1]
        if self.entry in ("", "-"):
            self.entry = "0"

    def exp(self) -> None:
        if self.error or not self.scientific:
            return
        if self.entry is None:
            self._begin_operand()
            txt = format(self.value, "f") if self.has_operand else "0"
            self.entry = txt + "e+0"
            self.has_operand = True
        elif "e" not in self.entry:
            self.entry += "e+0"

    def negate(self) -> None:
        if self.error:
            return
        if self.entry is not None:
            mant, e, ex = self.entry.partition("e")
            if e:
                self.entry = f"{mant}e{'-' if ex[0] == '+' else '+'}{ex[1:]}"
            elif mant.lstrip("-") not in ("0", ""):
                self.entry = mant[1:] if mant.startswith("-") else "-" + mant
            return
        self._unary_apply("neg", "negate", lambda x: -x if x != 0 else x)

    def percent(self) -> None:
        if self.error:
            return
        cur = self.current_value()
        if self.tokens and self.tokens[-1][0] == "o" and len(self.tokens) >= 2 and not self.scientific:
            acc = self.tokens[-2][1]
            res = CTX.divide(CTX.multiply(acc, cur), 100)
        else:
            res = ZERO
        self._set_operand(res, format_number(res))

    def _set_operand(self, v: Decimal, text: str | None = None) -> None:
        if self.after_equals:
            self.tokens, self.parens, self.expr_override = [], [], None
            self.after_equals = False
        if self.tokens and self.tokens[-1][0] == "n":
            self.tokens.pop()
        self.value, self.entry, self.cur_text = v, None, text
        self.has_operand = True

    def constant(self, name: str) -> None:
        self._unlock()
        v = {"pi": PI, "e": E}[name]
        self._set_operand(v, None)

    def rand(self) -> None:
        self._unlock()
        self._set_operand(_round_sig(Decimal(repr(random.random())), 16), None)

    def set_value(self, v: Decimal, expr: str | None = None) -> None:
        """Carica un valore (da cronologia/memoria) come nuovo operando."""
        self._unlock()
        self._set_operand(v, None)
        if expr is not None:
            self.expr_override = expr
            self.after_equals = True

    # --- funzioni unarie -----------------------------------------------
    def _take_operand(self) -> tuple[Decimal, str]:
        """Rimuove e restituisce l'operando corrente (valore, testo)."""
        if self.entry is not None:
            v = Decimal(self.entry)
            self.entry = None
            return v, format_number(v)
        if self.after_equals:
            self.tokens, self.parens, self.expr_override = [], [], None
            self.after_equals = False
            return self.value, format_number(self.value)
        if not self.has_operand and self.tokens and self.tokens[-1][0] == "n":
            t = self.tokens.pop()
            return t[1], t[2]
        return self.value, self.cur_text or format_number(self.value)

    def _unary_apply(self, key: str, label: str, fn) -> None:
        x, text = self._take_operand()
        new_text = f"{label}({text})"
        try:
            r = fn(x)
        except (CalcError, decimal.DecimalException) as exc:
            msg = str(exc) if isinstance(exc, CalcError) else (
                ERR_OVERFLOW if isinstance(exc, decimal.Overflow) else ERR_INVALID)
            self._fail(msg, (self._expr_so_far() + (" " if self.tokens and self.tokens[-1][0] == "o" else "")
                             + new_text).strip())
            return
        self.value, self.cur_text, self.has_operand = r, new_text, True

    def unary(self, name: str) -> None:
        if self.error:
            return
        label, fn = _unary_table(self.angle)[name]
        self._unary_apply(name, label, fn)

    def trig(self, base: str) -> None:
        """base: sin cos tan sec csc cot; usa i flag 2nd (inversa) e hyp."""
        if self.error:
            return
        name = ("a" if self.second else "") + base + ("h" if self.hyp else "")
        label = base + ("h" if self.hyp else "")
        if self.second:
            label = (base + "⁻¹") if not self.hyp else (base + "h⁻¹")
        self._unary_apply(name, label, lambda x: trig(name, x, self.angle))

    # --- operatori binari e parentesi ----------------------------------
    def _push_operand_if_any(self) -> None:
        """Mette nei token l'operando corrente, se presente."""
        if self.has_operand:
            v = self.current_value()
            text = self.cur_text if (self.entry is None and self.cur_text) else format_number(v)
            self.tokens.append(("n", v, text))
            self.value, self.entry, self.cur_text = v, None, None
            self.has_operand = False

    def binary(self, op: str) -> None:
        if self.error:
            return
        if self.after_equals:  # prosegue dal risultato
            self.tokens, self.parens, self.expr_override = [], [], None
            self.after_equals = False
            self.has_operand = True
            self.cur_text = None
        if not self.scientific and op in ("^", "yroot", "logbase", "mod"):
            return
        if self.has_operand:
            self._push_operand_if_any()
            self.tokens.append(("o", op))
        elif self.tokens and self.tokens[-1][0] == "o":
            self.tokens[-1] = ("o", op)
        elif self.tokens and self.tokens[-1][0] == "n":
            self.tokens.append(("o", op))
        else:  # inizio o dopo "(": operando implicito = valore a schermo
            if self.tokens and self.tokens[-1][0] == "(":
                self.value = ZERO
            self.tokens.append(("n", self.value, format_number(self.value)))
            self.tokens.append(("o", op))
        self.cur_text = None
        if not self.scientific and not self.parens:
            self._collapse_standard()

    def _collapse_standard(self) -> None:
        """Standard: valuta subito 'a op b' quando arriva il prossimo operatore."""
        nums = [t for t in self.tokens if t[0] == "n"]
        if len(nums) < 2:
            return
        body = self.tokens[:-1]
        try:
            v = self._eval_tokens(body)
        except CalcError as exc:
            self._fail(str(exc), self._expr_so_far())
            return
        op = self.tokens[-1]
        self.tokens = [("n", v, format_number(v)), op]
        self.value = v

    def _eval_tokens(self, toks: list[tuple]) -> Decimal:
        vals = [t[1] for t in toks if t[0] == "n"]
        ops = [t[1] for t in toks if t[0] == "o"]
        if not vals or len(ops) != len(vals) - 1:
            raise CalcError(ERR_INVALID)
        try:
            return evaluate(vals, ops, precedence=self.scientific)
        except decimal.Overflow:
            raise CalcError(ERR_OVERFLOW)
        except decimal.DecimalException:
            raise CalcError(ERR_INVALID)

    def lparen(self) -> None:
        if not self.scientific or self.error:
            return
        if self.after_equals:
            self.tokens, self.expr_override = [], None
            self.after_equals = False
            self.has_operand = False
        if self.has_operand or (self.tokens and self.tokens[-1][0] == "n"):
            return
        if len(self.parens) >= 20:
            return
        self.parens.append(len(self.tokens))
        self.tokens.append(("(",))
        self.value, self.entry, self.cur_text = ZERO, None, None

    def _close_group(self) -> None:
        start = self.parens.pop()
        self._push_operand_if_any()
        body = self.tokens[start + 1:]
        if body and body[-1][0] == "o":
            body.append(("n", self.value, format_number(self.value)))
        if not body:
            body = [("n", ZERO, "0")]
        text = "("
        for t in body:
            text += t[2] if t[0] == "n" else f" {t[1]} "
        text += ")"
        v = self._eval_tokens(body)
        self.tokens = self.tokens[:start] + [("n", v, text)]
        self.value, self.has_operand, self.cur_text = v, False, None

    def rparen(self) -> None:
        if not self.scientific or self.error or not self.parens:
            return
        try:
            self._close_group()
        except CalcError as exc:
            self._fail(str(exc), self._expr_so_far())

    # --- uguale ----------------------------------------------------------
    def equals(self) -> None:
        if self.error:
            return
        if self.after_equals:
            if self.last_op is None or self.last_operand is None:
                return
            a, op, b = self.value, self.last_op, self.last_operand
            expr = f"{format_number(a)} {op} {format_number(b)} ="
            self._finish(lambda: _apply(op, a, b), expr, "keep")
            return
        try:
            while self.parens:
                self._close_group()
            self._push_operand_if_any()
            if self.tokens and self.tokens[-1][0] == "o":
                self.tokens.append(("n", self.value, format_number(self.value)))
            if not self.tokens:
                self.tokens.append(("n", self.value, format_number(self.value)))
        except CalcError as exc:
            self._fail(str(exc), self._expr_so_far())
            return
        toks = self.tokens
        expr = self._expr_so_far() + " ="
        repeat = (toks[1][1], toks[2][1]) if (len(toks) == 3 and toks[1][0] == "o") else None
        if repeat is None and len(toks) != 1:
            repeat = "keep"
        self._finish(lambda: self._eval_tokens(toks), expr, repeat)

    def _finish(self, compute, expr: str, repeat) -> None:
        try:
            r = compute()
        except CalcError as exc:
            self._fail(str(exc), expr)
            return
        if isinstance(repeat, tuple):
            self.last_op, self.last_operand = repeat
        elif repeat is None:
            self.last_op, self.last_operand = None, None
        self.tokens, self.parens = [], []
        self.value, self.entry, self.cur_text = r, None, None
        self.has_operand = True
        self.after_equals = True
        self.expr_override = expr
        res = format_number(r)
        self.history.append(HistoryItem(expr, res, r))
        self.events.append(("result", expr, res, self.mode))

    # --- cancellazione -----------------------------------------------------
    def clear_entry(self) -> None:
        if self.error or self.after_equals:
            self.clear()
            return
        self.entry, self.value, self.cur_text = None, ZERO, None
        self.has_operand = False
        if self.tokens and self.tokens[-1][0] == "n":
            self.tokens.pop()

    def clear(self) -> None:
        self._reset()

    # --- memoria -------------------------------------------------------------
    def mem_clear(self) -> None:
        self.memory.clear()

    def mem_recall(self, index: int = 0) -> None:
        if self.error or not self.memory:
            return
        self._set_operand(self.memory[index], None)

    def mem_store(self) -> None:
        if self.error:
            return
        v = self.current_value()
        self._commit_after_mem(v)
        self.memory.insert(0, v)

    def mem_add(self, index: int = 0, v: Decimal | None = None) -> None:
        if self.error:
            return
        v = self.current_value() if v is None else v
        self._commit_after_mem(v)
        if not self.memory:
            self.memory.append(v)
        else:
            self.memory[index] = CTX.add(self.memory[index], v)

    def mem_sub(self, index: int = 0, v: Decimal | None = None) -> None:
        if self.error:
            return
        v = self.current_value() if v is None else v
        self._commit_after_mem(v)
        if not self.memory:
            self.memory.append(-v)
        else:
            self.memory[index] = CTX.subtract(self.memory[index], v)

    def _commit_after_mem(self, v: Decimal) -> None:
        # il numero resta a schermo, ma il prossimo tasto cifra ne inizia uno nuovo
        if self.entry is not None:
            self.value, self.entry = v, None
            self.has_operand = True

    # --- modalità -----------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        self.second = self.hyp = False
        self._reset()
        self.events.append(("mode", mode))

    def cycle_angle(self) -> str:
        self.angle = {"DEG": "RAD", "RAD": "GRAD", "GRAD": "DEG"}[self.angle]
        return self.angle

    # --- dispatch --------------------------------------------------------------
    BINARY = {"add": "+", "sub": "−", "mul": "×", "div": "÷", "pow": "^", "mod": "mod",
              "yroot": "yroot", "logbase": "logbase"}
    UNARY = {"sqr", "cube", "recip", "sqrt", "cbrt", "abs", "fact", "log", "ln", "pow10", "pow2",
             "powe", "floor", "ceil", "dms", "deg"}
    TRIG = {"sin", "cos", "tan", "sec", "csc", "cot"}

    def press(self, key: str) -> None:
        """Tasti: cifre, '.', ',', add sub mul div pow mod yroot logbase, eq, ce, c, back, neg, pct,
        lp, rp, exp, pi, e, rand, mc mr mp mm ms, sqr cube recip sqrt cbrt abs fact log ln pow10 pow2
        powe floor ceil dms deg, sin cos tan sec csc cot, second, hyp, fe, angle."""
        if key.isdigit() and len(key) == 1:
            self.digit(key)
        elif key in (".", ","):
            self.decimal_point()
        elif key in self.BINARY:
            self.binary(self.BINARY[key])
        elif key in self.UNARY:
            self.unary(key)
        elif key in self.TRIG:
            self.trig(key)
        else:
            {
                "eq": self.equals, "ce": self.clear_entry, "c": self.clear, "back": self.backspace,
                "neg": self.negate, "pct": self.percent, "lp": self.lparen, "rp": self.rparen,
                "exp": self.exp, "pi": lambda: self.constant("pi"), "e": lambda: self.constant("e"),
                "rand": self.rand, "mc": self.mem_clear, "mr": self.mem_recall, "mp": self.mem_add,
                "mm": self.mem_sub, "ms": self.mem_store,
                "second": lambda: setattr(self, "second", not self.second),
                "hyp": lambda: setattr(self, "hyp", not self.hyp),
                "fe": lambda: setattr(self, "fe", not self.fe),
                "angle": self.cycle_angle,
            }[key]()
