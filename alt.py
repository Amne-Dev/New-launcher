"""
New Launcher (NLC) - Modular Entry Point
Provides backwards-compatible entry point for PyInstaller, AppImage builds,
and test harnesses while delegating to the modular nlc package.
"""

import os
import sys

# Auto-detect local .venv when run directly via `python alt.py` without activating venv
_script_dir = os.path.dirname(os.path.abspath(__file__))
_venv_python = os.path.join(_script_dir, ".venv", "bin", "python")
if os.path.isfile(_venv_python) and sys.prefix == getattr(sys, "base_prefix", sys.prefix):
    try:
        import certifi  # Quick test for venv packages
    except ImportError:
        os.execv(_venv_python, [_venv_python] + sys.argv)

from nlc.main import main
from nlc.ui.app import MinecraftLauncher
from nlc.net.downloader import download_file as _atomic_download

__all__ = ["MinecraftLauncher", "main", "_atomic_download"]

if __name__ == "__main__":
    sys.exit(main())