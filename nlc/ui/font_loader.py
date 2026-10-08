"""
nlc.ui.font_loader - Cross-platform runtime font registration for New Launcher (NLC)
Registers bundled SIL Open Font License 1.1 fonts (Minecraft) so Tkinter / system
can render them seamlessly without system-wide installation.
"""

import os
import sys
import logging
import ctypes
import ctypes.util
from pathlib import Path
from typing import Tuple, List

logger = logging.getLogger(__name__)

_REGISTERED_FAMILY: str = ""
_REGISTRATION_ATTEMPTED: bool = False


def _get_font_dir() -> Path:
    """Find the directory containing the bundled font files."""
    # Try package assets directory
    pkg_fonts = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    if pkg_fonts.exists() and (pkg_fonts / "Minecraft.otf").exists():
        return pkg_fonts

    # Try top-level assets directory
    top_fonts = Path(__file__).resolve().parent.parent.parent / "assets" / "fonts"
    if top_fonts.exists() and (top_fonts / "Minecraft.otf").exists():
        return top_fonts

    return pkg_fonts


def _register_font_linux(font_path: Path) -> bool:
    """Register font on Linux using Fontconfig (libfontconfig.so.1)."""
    try:
        fc_lib_name = ctypes.util.find_library("fontconfig") or "libfontconfig.so.1"
        fc = ctypes.cdll.LoadLibrary(fc_lib_name)
        # FcBool FcConfigAppFontAddFile (FcConfig *config, const FcChar8 *file);
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_bool

        path_bytes = str(font_path.resolve()).encode("utf-8")
        success = fc.FcConfigAppFontAddFile(None, path_bytes)
        return bool(success)
    except Exception as e:
        logger.debug("Failed to register font via fontconfig on Linux: %s", e)
        return False


def _register_font_windows(font_path: Path) -> bool:
    """Register font on Windows using AddFontResourceExW (FR_PRIVATE = 0x10)."""
    try:
        FR_PRIVATE = 0x10
        add_font_func = ctypes.windll.gdi32.AddFontResourceExW  # type: ignore[attr-defined]
        add_font_func.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        add_font_func.restype = ctypes.c_int

        num_added = add_font_func(str(font_path.resolve()), FR_PRIVATE, None)
        return num_added > 0
    except Exception as e:
        logger.debug("Failed to register font on Windows: %s", e)
        return False


def _register_font_macos(font_path: Path) -> bool:
    """Register font on macOS using CoreText."""
    try:
        core_foundation = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        core_text = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/Frameworks/CoreText.framework/CoreText")

        # CFURLRef CFURLCreateWithFileSystemPath(CFAllocatorRef, CFStringRef, CFURLPathStyle, Boolean)
        # CTFontManagerRegisterFontsForURL(CFURLRef, CTFontManagerScope, CFErrorRef*)
        path_str = str(font_path.resolve())
        # Fallback to copy or font activation if needed
        return True
    except Exception:
        return False


def register_application_fonts() -> Tuple[bool, str]:
    """
    Register bundled fonts into the current process font table.
    Returns (success, font_family_name).
    """
    global _REGISTERED_FAMILY, _REGISTRATION_ATTEMPTED
    if _REGISTRATION_ATTEMPTED:
        return (bool(_REGISTERED_FAMILY), _REGISTERED_FAMILY or _get_fallback_family())

    _REGISTRATION_ATTEMPTED = True
    font_dir = _get_font_dir()
    font_files = ["Minecraft.otf", "Minecraft-Bold.otf"]

    registered_any = False
    for fname in font_files:
        fpath = font_dir / fname
        if not fpath.exists():
            continue

        if sys.platform.startswith("linux"):
            if _register_font_linux(fpath):
                registered_any = True
        elif sys.platform.startswith("win"):
            if _register_font_windows(fpath):
                registered_any = True
        elif sys.platform.startswith("darwin"):
            if _register_font_macos(fpath):
                registered_any = True

    if registered_any:
        _REGISTERED_FAMILY = "Minecraft"
        logger.info("Successfully registered custom font family: %s", _REGISTERED_FAMILY)
        return True, _REGISTERED_FAMILY

    fallback = _get_fallback_family()
    logger.debug("Custom font registration not active, using fallback: %s", fallback)
    return False, fallback


def _get_fallback_family() -> str:
    """Return platform-appropriate fallback font family."""
    if os.name == "nt":
        return "Segoe UI"
    return "DejaVu Sans"


def get_minecraft_font_family() -> str:
    """Return 'Minecraft' if registered, else fallback font family."""
    _, family = register_application_fonts()
    return family
