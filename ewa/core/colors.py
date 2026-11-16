"""Colori ANSI per il terminale EWA (abilita VT processing e UTF-8 su Windows)."""
import os
import sys

ROSSO = "\033[91m"
VERDE = "\033[92m"
GIALLO = "\033[93m"
BLU = "\033[94m"
VIOLA = "\033[95m"
CIANO = "\033[96m"
GRIGIO = "\033[90m"
GRASSETTO = "\033[1m"
RESET = "\033[0m"


def enable_terminal() -> None:
    """Abilita sequenze ANSI su conhost/PowerShell e forza UTF-8 sugli stream."""
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            for std in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
                handle = kernel32.GetStdHandle(std)
                mode = ctypes.c_uint32()
                if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            if stream and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"
