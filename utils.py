import os
import sys
import minecraft_launcher_lib
from PIL import Image

# Detect resampling constant for compatibility with Pillow versions
try:
    RESAMPLE_NEAREST = Image.Resampling.NEAREST  # Pillow >= 9.1
    FLIP_LEFT_RIGHT = Image.Transpose.FLIP_LEFT_RIGHT
    AFFINE = Image.Transform.AFFINE
except AttributeError:
    RESAMPLE_NEAREST = Image.NEAREST  # type: ignore # Older Pillow
    FLIP_LEFT_RIGHT = Image.FLIP_LEFT_RIGHT # type: ignore
    AFFINE = Image.AFFINE # type: ignore

def resource_path(relative_path):
    """Get absolute path to a bundled resource for dev/PyInstaller/AppImage runs."""
    rel = relative_path.lstrip("/\\")

    candidates = []

    # PyInstaller one-file extraction directory (preferred when present).
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(meipass)

    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    module_dir = os.path.dirname(os.path.abspath(__file__))

    if getattr(sys, "frozen", False):
        candidates.extend([
            exe_dir,
            os.path.dirname(exe_dir),
            os.path.join(exe_dir, "..", "share", "new-launcher"),
            os.path.join(exe_dir, "..", "share", "NewLauncher"),
            os.path.join(exe_dir, "..", "resources"),
        ])
    else:
        candidates.extend([
            module_dir,
            os.getcwd(),
        ])

    seen = set()
    for base in candidates:
        if not base:
            continue
        abs_base = os.path.abspath(base)
        if abs_base in seen:
            continue
        seen.add(abs_base)

        candidate = os.path.join(abs_base, rel)
        if os.path.exists(candidate):
            return candidate

    # Final fallback keeps previous behavior for callers that create files later.
    fallback_base = module_dir if not getattr(sys, "frozen", False) else (meipass or exe_dir)
    return os.path.join(os.path.abspath(fallback_base), rel)

_CACHED_MC_DIR = None
def get_minecraft_dir():
    global _CACHED_MC_DIR
    if _CACHED_MC_DIR is None:
        try:
            _CACHED_MC_DIR = minecraft_launcher_lib.utils.get_minecraft_directory()
            # On Windows, sometimes this returns the roaming/.minecraft correctly, 
            # but let's ensure it's absolute
            _CACHED_MC_DIR = os.path.abspath(_CACHED_MC_DIR)
        except:
            # Fallback for some systems
            if os.name == 'nt':
                _CACHED_MC_DIR = os.path.join(os.getenv('APPDATA') or os.path.expanduser("~"), '.minecraft')
            else:
                _CACHED_MC_DIR = os.path.join(os.path.expanduser('~'), '.minecraft')
    return _CACHED_MC_DIR

def is_version_installed(version_id):
    minecraft_dir = get_minecraft_dir()
    version_dir = os.path.join(minecraft_dir, "versions", version_id)
    json_path = os.path.join(version_dir, f"{version_id}.json")
    return os.path.exists(json_path)
