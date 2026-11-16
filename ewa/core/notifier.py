"""Notifier: toast Windows (windows-toasts) con fallback su stampa colorata."""
from __future__ import annotations

import sys
import threading

from . import colors


class Notifier:
    def __init__(self, force_console: bool = False):
        self._toaster = None
        self._toast_cls = None
        self._lock = threading.Lock()
        self._force_console = force_console
        self.backend = "console"
        if not force_console and sys.platform == "win32":
            try:
                from windows_toasts import Toast, WindowsToaster

                self._toaster = WindowsToaster("Marv")
                self._toast_cls = Toast
                self.backend = "toast Windows"
            except Exception:
                self._toaster = None

    def notify(self, text: str, tool_title: str = "") -> None:
        """Mostra la notifica. Non solleva mai eccezioni."""
        try:
            title = f"Marv · {tool_title}" if tool_title else "Marv"
            if self._toaster is not None:
                try:
                    with self._lock:
                        toast = self._toast_cls()
                        toast.text_fields = [title, text]
                        self._toaster.show_toast(toast)
                    return
                except Exception:
                    pass  # ripiega sul terminale
            self._console(text, tool_title)
        except Exception:
            pass

    @staticmethod
    def _console(text: str, tool_title: str) -> None:
        where = f" ({tool_title})" if tool_title else ""
        print(f"\r\033[K{colors.GIALLO}🔔 Marv{where}:{colors.RESET} {colors.CIANO}{text}{colors.RESET}", flush=True)
