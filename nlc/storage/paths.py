"""
nlc.storage.paths - Standardized cross-platform path helpers
"""

import os
import sys
from pathlib import Path
from typing import Optional
from PIL import Image

try:
    RESAMPLE_NEAREST = Image.Resampling.NEAREST
    FLIP_LEFT_RIGHT = Image.Transpose.FLIP_LEFT_RIGHT
    AFFINE = Image.Transform.AFFINE
except AttributeError:
    RESAMPLE_NEAREST = Image.NEAREST  # type: ignore
    FLIP_LEFT_RIGHT = Image.FLIP_LEFT_RIGHT  # type: ignore
    AFFINE = Image.AFFINE  # type: ignore

def get_launcher_data_dir() -> Path:
    """
    Returns the standard per-OS directory where NLC stores its data (config, logs, updates).
    Windows: %APPDATA%/.nlc
    Linux / macOS: ~/.nlc
    """
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        data_dir = base / ".nlc"
    else:
        data_dir = Path.home() / ".nlc"

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

get_nlc_data_dir = get_launcher_data_dir

def get_config_path() -> Path:
    """Return the absolute path to launcher_config.json."""
    return get_launcher_data_dir() / "launcher_config.json"

_CACHED_MC_DIR: Optional[Path] = None

def get_minecraft_dir() -> str:
    """Return the absolute path to the .minecraft directory as string."""
    global _CACHED_MC_DIR
    if _CACHED_MC_DIR is not None:
        return str(_CACHED_MC_DIR)

    try:
        import minecraft_launcher_lib
        dir_str = minecraft_launcher_lib.utils.get_minecraft_directory()
        _CACHED_MC_DIR = Path(dir_str).resolve()
    except Exception:
        if os.name == "nt":
            appdata = os.getenv("APPDATA")
            base = Path(appdata) if appdata else Path.home()
            _CACHED_MC_DIR = (base / ".minecraft").resolve()
        else:
            _CACHED_MC_DIR = (Path.home() / ".minecraft").resolve()

    return str(_CACHED_MC_DIR)

def get_minecraft_path() -> Path:
    """Return the Path to the .minecraft directory."""
    get_minecraft_dir()
    return _CACHED_MC_DIR  # type: ignore

def resource_path(relative_path: str) -> str:
    """Get absolute path to a bundled resource for dev/PyInstaller/AppImage runs."""
    rel = relative_path.lstrip("/\\")
    candidates = []

    # PyInstaller one-file extraction directory
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass))

    exe_dir = Path(sys.executable).resolve().parent
    module_dir = Path(__file__).resolve().parent.parent.parent  # repo root

    if getattr(sys, "frozen", False):
        candidates.extend([
            exe_dir,
            exe_dir.parent,
            exe_dir / ".." / "share" / "new-launcher",
            exe_dir / ".." / "share" / "NewLauncher",
            exe_dir / ".." / "resources",
        ])
    else:
        candidates.extend([
            module_dir,
            Path.cwd(),
        ])

    seen = set()
    for base in candidates:
        if not base:
            continue
        abs_base = base.resolve()
        if abs_base in seen:
            continue
        seen.add(abs_base)

        candidate = abs_base / rel
        if candidate.exists():
            return str(candidate)

    fallback_base = module_dir if not getattr(sys, "frozen", False) else (Path(meipass) if meipass else exe_dir)
    return str((fallback_base / rel).resolve())

def is_version_installed(version_id: str) -> bool:
    """Check if the given Minecraft version json exists."""
    mc_dir = Path(get_minecraft_dir())
    json_path = mc_dir / "versions" / version_id / f"{version_id}.json"
    return json_path.exists()
