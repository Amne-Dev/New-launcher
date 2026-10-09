"""
nlc.net.mod_icons - Fast asynchronous extraction and caching of mod icons from jar archives.
Extracts icons from Fabric (fabric.mod.json), Quilt (quilt.mod.json), NeoForge/Forge (mods.toml),
and asset fallbacks, caching thumbnails on disk and in-memory for instant rendering.
"""

import os
import io
import json
import hashlib
import zipfile
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Optional, Tuple

from PIL import Image, ImageTk
import tkinter as tk

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = os.path.expanduser("~/.nlc/cache/mod_icons")
_ICON_EXTRACT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ModIconExtract")


def extract_icon_from_jar(
    jar_path: str,
    target_size: Tuple[int, int] = (44, 44),
    cache_dir: Optional[str] = None
) -> Optional[Image.Image]:
    """
    Extract embedded mod icon from a jar file and resize to target_size.
    Returns a PIL Image object or None if no valid icon is found.
    """
    if not os.path.isfile(jar_path):
        return None

    if cache_dir is None:
        cache_dir = _DEFAULT_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)

    try:
        stat = os.stat(jar_path)
        cache_key = hashlib.sha256(
            f"{os.path.basename(jar_path)}_{stat.st_size}_{stat.st_mtime}".encode("utf-8")
        ).hexdigest()[:24]
        cache_path = os.path.join(cache_dir, f"{cache_key}_{target_size[0]}x{target_size[1]}.png")

        # 1. Fast disk cache check
        if os.path.isfile(cache_path):
            try:
                with Image.open(cache_path) as cached:
                    return cached.copy()
            except Exception:
                pass

        # 2. Inspect jar archive
        icon_bytes = None
        with zipfile.ZipFile(jar_path, "r") as z:
            names = set(z.namelist())

            # Fabric mod check
            if "fabric.mod.json" in names:
                try:
                    data = json.loads(z.read("fabric.mod.json").decode("utf-8", errors="ignore"))
                    icon_entry = data.get("icon")
                    if isinstance(icon_entry, dict):
                        icon_entry = (
                            icon_entry.get("64")
                            or icon_entry.get("128")
                            or icon_entry.get("32")
                            or next(iter(icon_entry.values()), None)
                        )
                    if icon_entry:
                        icon_clean = icon_entry.lstrip("/")
                        candidates = [icon_clean, f"assets/{icon_clean}"]
                        for c in candidates:
                            if c in names:
                                icon_bytes = z.read(c)
                                break
                except Exception as ex:
                    logger.debug("Error reading fabric.mod.json in %s: %s", jar_path, ex)

            # Quilt mod check
            if not icon_bytes and "quilt.mod.json" in names:
                try:
                    data = json.loads(z.read("quilt.mod.json").decode("utf-8", errors="ignore"))
                    icon_entry = (data.get("quilt_loader") or {}).get("icon") or data.get("icon")
                    if isinstance(icon_entry, dict):
                        icon_entry = (
                            icon_entry.get("64")
                            or icon_entry.get("128")
                            or next(iter(icon_entry.values()), None)
                        )
                    if icon_entry:
                        icon_clean = icon_entry.lstrip("/")
                        for c in [icon_clean, f"assets/{icon_clean}"]:
                            if c in names:
                                icon_bytes = z.read(c)
                                break
                except Exception as ex:
                    logger.debug("Error reading quilt.mod.json in %s: %s", jar_path, ex)

            # Forge / NeoForge mods.toml check
            if not icon_bytes and "META-INF/mods.toml" in names:
                try:
                    toml_str = z.read("META-INF/mods.toml").decode("utf-8", errors="ignore")
                    for line in toml_str.splitlines():
                        line = line.strip()
                        if line.startswith("logoFile"):
                            parts = line.split("=", 1)
                            if len(parts) == 2:
                                logo_file = parts[1].strip().strip('"').strip("'").lstrip("/")
                                for candidate in [logo_file, f"META-INF/{logo_file}", f"assets/{logo_file}"]:
                                    if candidate in names:
                                        icon_bytes = z.read(candidate)
                                        break
                                if icon_bytes:
                                    break
                except Exception as ex:
                    logger.debug("Error reading mods.toml in %s: %s", jar_path, ex)

            # Universal fallback pattern search
            if not icon_bytes:
                for name in names:
                    if name.startswith("META-INF/"):
                        continue
                    lower = name.lower()
                    if lower.endswith("/icon.png") or lower.endswith("/logo.png") or lower in ("icon.png", "logo.png"):
                        try:
                            icon_bytes = z.read(name)
                            break
                        except Exception:
                            continue

        if not icon_bytes:
            return None

        # 3. Process and downscale to target size with BILINEAR
        with Image.open(io.BytesIO(icon_bytes)) as src:
            img = src.convert("RGBA").resize(target_size, Image.Resampling.BILINEAR)

        # 4. Save to disk cache atomically
        try:
            temp_path = cache_path + f".tmp_{os.getpid()}"
            img.save(temp_path, format="PNG")
            os.replace(temp_path, cache_path)
        except Exception as ex:
            logger.debug("Failed saving mod icon cache: %s", ex)

        return img

    except Exception as ex:
        logger.debug("Failed extracting icon for %s: %s", jar_path, ex)
        return None


import queue

class ModIconManager:
    """
    Manages in-memory LRU cache and background thread pool extraction
    for UI mod icon previews.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self._photo_cache: Dict[str, ImageTk.PhotoImage] = {}
        self._pil_cache: Dict[str, Image.Image] = {}
        self._placeholder_photos: Dict[Tuple[int, int], ImageTk.PhotoImage] = {}
        self._ready_queue: queue.Queue = queue.Queue()
        self._polling_roots = set()

    def get_placeholder_photo(self, size: Tuple[int, int] = (44, 44)) -> ImageTk.PhotoImage:
        """Return a modern neutral icon placeholder PhotoImage."""
        if size in self._placeholder_photos:
            return self._placeholder_photos[size]

        img = Image.new("RGBA", size, (40, 44, 52, 255))
        photo = ImageTk.PhotoImage(img)
        self._placeholder_photos[size] = photo
        return photo

    def _ensure_poll(self, root: tk.Widget):
        try:
            top = root.winfo_toplevel()
            top_id = id(top)
            if top_id in self._polling_roots:
                return
            self._polling_roots.add(top_id)

            def poll_worker():
                try:
                    count = 0
                    while not self._ready_queue.empty() and count < 25:
                        cache_key, widget, callback, pil_img = self._ready_queue.get_nowait()
                        count += 1
                        try:
                            if widget.winfo_exists():
                                photo = ImageTk.PhotoImage(pil_img)
                                self._photo_cache[cache_key] = photo
                                callback(photo)
                        except Exception:
                            pass
                finally:
                    try:
                        if top.winfo_exists():
                            top.after(20, poll_worker)
                        else:
                            self._polling_roots.discard(top_id)
                    except Exception:
                        self._polling_roots.discard(top_id)

            top.after(10, poll_worker)
        except Exception:
            pass

    def get_icon_async(
        self,
        jar_path: str,
        widget,
        callback: Callable[[Optional[ImageTk.PhotoImage]], None],
        size: Tuple[int, int] = (44, 44)
    ) -> Optional[ImageTk.PhotoImage]:
        """
        Retrieve photo asynchronously. If cached in memory, returns PhotoImage immediately.
        Otherwise submits work to thread pool and delivers via main-thread queue.
        """
        cache_key = f"{jar_path}_{size[0]}x{size[1]}"
        if cache_key in self._photo_cache:
            return self._photo_cache[cache_key]

        # Ensure polling loop on root
        self._ensure_poll(widget)

        def worker():
            pil_img = extract_icon_from_jar(jar_path, target_size=size, cache_dir=self.cache_dir)
            if pil_img:
                self._ready_queue.put((cache_key, widget, callback, pil_img))

        _ICON_EXTRACT_POOL.submit(worker)
        return None


_GLOBAL_ICON_MGR: Optional[ModIconManager] = None


def get_mod_icon_manager() -> ModIconManager:
    """Retrieve or create the global ModIconManager instance."""
    global _GLOBAL_ICON_MGR
    if _GLOBAL_ICON_MGR is None:
        _GLOBAL_ICON_MGR = ModIconManager()
    return _GLOBAL_ICON_MGR
