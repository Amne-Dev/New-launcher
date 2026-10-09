"""
New Launcher (NLC) - Modular Entry Point
Provides backwards-compatible entry point for PyInstaller, AppImage builds,
and test harnesses while delegating to the modular nlc package.
"""

import sys
from nlc.main import main
from nlc.ui.app import MinecraftLauncher
from nlc.net.downloader import download_file as _atomic_download

__all__ = ["MinecraftLauncher", "main", "_atomic_download"]

if __name__ == "__main__":
    sys.exit(main())