"""Avvio: python -m ewa.tools.calculator"""
import sys

from ewa.tools.calculator.window import build
from ewa.ui.win10 import run_tool


def main() -> int:
    return run_tool("calc", build)


if __name__ == "__main__":
    sys.exit(main())
