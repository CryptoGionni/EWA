"""Punto d'ingresso dell'eseguibile (PyInstaller): ewa.shell."""
import sys

from ewa.shell import main

if __name__ == "__main__":
    sys.exit(main())
