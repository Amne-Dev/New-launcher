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
    """ Get absolute path to resource, works for dev and for PyInstaller """
    # PyInstaller creates a temp folder and stores path in _MEIPASS
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)

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
