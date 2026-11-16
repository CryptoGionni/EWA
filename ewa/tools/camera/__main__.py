"""Avvio: python -m ewa.tools.camera"""
import sys

from ewa.tools.camera.window import build
from ewa.ui.win10 import run_tool


def main() -> int:
    return run_tool("camera", build)


if __name__ == "__main__":
    sys.exit(main())
