"""Impostazioni comuni dei test: niente MarvHub avviato in automatico dai ToolClient."""
import os

os.environ["EWA_HUB_AUTOSTART"] = "0"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
