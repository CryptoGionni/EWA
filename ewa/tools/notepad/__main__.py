"""Avvio: python -m ewa.tools.notepad [file.txt]"""
import sys

from ewa.ui.win10 import run_tool


def build(client):
    from .window import NotepadWindow
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    return NotepadWindow(client, path=args[0] if args else None)


def main() -> int:
    return run_tool("notepad", build)


if __name__ == "__main__":
    sys.exit(main())
