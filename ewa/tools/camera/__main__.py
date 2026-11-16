import sys

from ewa.tools.camera.window import build
from ewa.ui.win10 import run_tool

if __name__ == "__main__":
    sys.exit(run_tool("camera", build))
