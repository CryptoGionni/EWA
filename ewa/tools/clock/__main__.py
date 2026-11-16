"""Avvio: python -m ewa.tools.clock [--tab alarm|clock|timer|stopwatch]"""
import argparse
import sys

from ewa.ui.win10 import run_tool

from .window import ALIASES, TABS, ClockWindow


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ewa.tools.clock")
    ap.add_argument("--tab", default="timer",
                    choices=[k for k, _t, _i in TABS] + list(ALIASES), help="scheda iniziale")
    args = ap.parse_args(argv)
    return run_tool("clock", lambda client: ClockWindow(client, tab=args.tab))


if __name__ == "__main__":
    sys.exit(main())
