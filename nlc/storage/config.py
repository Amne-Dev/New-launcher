"""
nlc.storage.config - Safe configuration persistence with atomic writes and .bak recovery
"""

import json
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from nlc.storage.paths import get_config_path

logger = logging.getLogger(__name__)

DEFAULT_RAM = 4096
DEFAULT_USERNAME = "Steve"
CURRENT_VERSION = "3.0.1"
INSTALL_MARK = "✅ "

LOADERS = ["Vanilla", "Forge", "Fabric", "BatMod", "LabyMod", "Lunar Client"]
MOD_COMPATIBLE_LOADERS = {"Forge", "Fabric"}

DEFAULT_INSTALLATION = {
    "id": "default-vanilla",
    "name": "Latest Release",
    "version": "latest-release",
    "loader": "Vanilla",
    "icon": "icons/grass_block_side.png",
    "java_executable": "",
    "resolution_width": None,
    "resolution_height": None,
    "game_directory": "",
    "last_played": "Never",
    "created": "2024-01-01"
}

def get_default_config() -> Dict[str, Any]:
    """Return default launcher configuration dictionary."""
    return {
        "version": CURRENT_VERSION,
        "first_run_completed": False,
        "ram": DEFAULT_RAM,
        "custom_titlebar": True if os.name == "nt" else False,
        "neo_style": True,
        "theme_id": "dark_slate",
        "custom_accent": None,
        "animations_enabled": True,
        "minimize_to_tray": False,
        "rpc_enabled": True,
        "streamer_mode": False,
        "instances": {
            "share_resourcepacks": True,
            "share_shaderpacks": True,
            "share_worlds": False,
            "share_configs": False
        },
        "profiles": [
            {
                "name": DEFAULT_USERNAME,
                "type": "offline",
                "skin_path": "",
                "skin_model": "classic",
                "uuid": ""
            }
        ],
        "active_profile_index": 0,
        "installations": [
            dict(DEFAULT_INSTALLATION, id=str(uuid.uuid4()))
        ],
        "active_installation_id": None,
        "addons": {
            "gh_sync": False,
            "playtime": {},
            "servers": []
        }
    }

class ConfigManager:
    """Manages reading and writing launcher_config.json with atomic writes and backups."""
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = Path(config_path) if config_path else get_config_path()
        self.backup_path = self.config_path.with_suffix(".json.bak")
        self.corrupt_path = self.config_path.with_suffix(".json.corrupt")

    def load(self) -> Dict[str, Any]:
        """
        Loads configuration from disk.
        Attempts to read main config; on failure or corruption, falls back to .bak;
        if neither is valid, safely preserves the corrupt file and returns defaults.
        """
        data = None

        if self.config_path.exists():
            data = self._read_file(self.config_path)
            if data is None and self.backup_path.exists():
                logger.warning("Config corrupted, attempting recovery from backup: %s", self.backup_path)
                data = self._read_file(self.backup_path)

        if data is None:
            logger.info("Initializing new configuration with defaults.")
            data = get_default_config()
            self.save(data)
            return data

        # Sanitize and migrate fields
        return self._normalize_config(data)

    def _read_file(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, dict):
                    return content
                logger.error("Config at %s is not a JSON object.", path)
        except Exception as e:
            logger.error("Failed to read JSON config at %s: %s", path, e)
            if path == self.config_path:
                try:
                    shutil.copy2(self.config_path, self.corrupt_path)
                    logger.warning("Preserved corrupt config at %s", self.corrupt_path)
                except Exception:
                    pass
        return None

    def _normalize_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all required root keys exist with valid types."""
        defaults = get_default_config()

        if not isinstance(data.get("profiles"), list) or not data["profiles"]:
            data["profiles"] = defaults["profiles"]

        if not isinstance(data.get("installations"), list) or not data["installations"]:
            data["installations"] = defaults["installations"]

        if not isinstance(data.get("addons"), dict):
            data["addons"] = defaults["addons"]

        # Ensure active installation is selected
        if not data.get("active_installation_id") and data["installations"]:
            data["active_installation_id"] = data["installations"][0].get("id")

        return data

    def save(self, data: Dict[str, Any]) -> bool:
        """
        Atomically saves configuration to disk.
        Rotates current good file to .bak before replacing.
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix="nlc_cfg_",
            suffix=".tmp",
            dir=str(self.config_path.parent)
        )
        tmp_path = Path(tmp_path_str)

        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            # Make a backup of the current valid config before replacing
            if self.config_path.exists() and self.config_path.stat().st_size > 0:
                try:
                    shutil.copy2(self.config_path, self.backup_path)
                except Exception as e:
                    logger.warning("Could not create config backup: %s", e)

            # Atomic rename into place
            os.replace(tmp_path, self.config_path)
            return True
        except Exception as e:
            logger.error("Failed to atomically save config: %s", e)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            return False
