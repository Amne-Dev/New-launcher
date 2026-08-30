"""Fast, background-safe installed-mod discovery for the QML UI."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable


ModsCallback = Callable[[list[dict[str, str]], str], None]


def _read_mod_label(jar: Path) -> dict[str, str]:
    fallback = jar.stem
    result = {"name": fallback, "id": "", "file": jar.name, "loader": ""}
    try:
        with zipfile.ZipFile(jar) as archive:
            names = set(archive.namelist())
            if "fabric.mod.json" in names:
                data = json.loads(archive.read("fabric.mod.json").decode("utf-8", "replace"))
                result.update({"name": str(data.get("name") or data.get("id") or fallback), "id": str(data.get("id") or ""), "loader": "Fabric"})
            elif "META-INF/mods.toml" in names or "META-INF/neoforge.mods.toml" in names:
                manifest = "META-INF/mods.toml" if "META-INF/mods.toml" in names else "META-INF/neoforge.mods.toml"
                text = archive.read(manifest).decode("utf-8", "replace")
                name = re.search(r'^\s*displayName\s*=\s*["\']([^"\']+)', text, re.MULTILINE)
                mod_id = re.search(r'^\s*modId\s*=\s*["\']([^"\']+)', text, re.MULTILINE)
                result.update({"name": name.group(1) if name else fallback, "id": mod_id.group(1) if mod_id else "", "loader": "Forge"})
            elif "mcmod.info" in names:
                info = json.loads(archive.read("mcmod.info").decode("utf-8", "replace"))
                entry = info[0] if isinstance(info, list) and info and isinstance(info[0], dict) else {}
                result.update({"name": str(entry.get("name") or entry.get("modid") or fallback), "id": str(entry.get("modid") or ""), "loader": "Legacy"})
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError):
        pass
    return result


class ModScanner:
    """Reads jar metadata in a worker without materialising a QML row per file."""

    def __init__(self, callback: ModsCallback) -> None:
        self._callback = callback
        self._lock = Lock()
        self._running = False

    def start(self, directory: Path) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
        Thread(target=self._run, args=(directory,), daemon=True).start()
        return True

    def _run(self, directory: Path) -> None:
        try:
            if not directory.is_dir():
                self._callback([], "No mods folder for this installation")
                return
            jars = sorted(directory.glob("*.jar"), key=lambda path: path.name.casefold())
            entries = [_read_mod_label(jar) for jar in jars]
            self._callback(entries, f"{len(entries)} mods")
        except OSError as error:
            self._callback([], f"Could not read mods: {error}")
        finally:
            with self._lock:
                self._running = False
