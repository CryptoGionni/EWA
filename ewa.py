"""EWA — Everything in Windows but AI. Avvio da sorgente: python ewa.py [--setup]

La shell vera è in ewa/shell.py (stessa entry dell'exe EWA.exe).
"""
import sys

from ewa.shell import main

if __name__ == "__main__":
    sys.exit(main())
