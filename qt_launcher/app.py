"""PySide6/QML application entry point for New Launcher."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Running `python qt_launcher/app.py` places only qt_launcher on sys.path.
# Add the repository root so shared launcher modules remain available.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import PySide6

# Microsoft Store Python does not always place PySide's Qt DLL directory on the
# loader search path.  Add it before importing any Qt modules so QML plugins
# such as QtQuick resolve their Qt6 dependencies on Windows.
if os.name == "nt" and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(str(Path(PySide6.__file__).resolve().parent))

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from utils import get_minecraft_dir

try:
    from .launch_service import LaunchService
    from .mod_scan import ModScanner
    from .modpack_import import CurseForgeImport
    from .skin_preview import SkinPreviewer
    from .account_auth import AccountAuthenticator
    from .modrinth_service import ModrinthService
except ImportError:  # Direct `python qt_launcher/app.py` execution.
    from launch_service import LaunchService
    from mod_scan import ModScanner
    from modpack_import import CurseForgeImport
    from skin_preview import SkinPreviewer
    from account_auth import AccountAuthenticator
    from modrinth_service import ModrinthService


DEFAULT_WALLPAPER = PROJECT_ROOT / "wallpapers" / "Island.png"


def _config_path() -> Path:
    local = Path.cwd() / "launcher_config.json"
    if local.is_file():
        return local
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / ".nlc" / "launcher_config.json"
    return Path.home() / ".nlc" / "launcher_config.json"


def _read_config() -> dict[str, Any]:
    try:
        with _config_path().open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
        return config if isinstance(config, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_json_file(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError):
        return None


def _wallpaper_url(value: Any) -> str:
    candidate = Path(str(value)) if value else DEFAULT_WALLPAPER
    if not candidate.is_file():
        candidate = DEFAULT_WALLPAPER
    return QUrl.fromLocalFile(str(candidate.resolve())).toString()


def _format_playtime(seconds: Any) -> str:
    try:
        total = max(0, int(seconds or 0))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{minutes}m"


class LauncherBridge(QObject):
    """Configuration and launch boundary exposed to the QML surface."""

    dataChanged = Signal()
    launchRequested = Signal(dict)
    launchStatusUpdated = Signal(str)
    launchFinished = Signal(bool, str, int)
    modScanFinished = Signal(list, str)
    modpackImportFinished = Signal(object, object, str)
    skinPreviewFinished = Signal(str, str)
    accountAuthStateChanged = Signal(object)
    accountAuthFinished = Signal(object, str)
    modrinthSearchFinished = Signal(list, str)
    modrinthInstallFinished = Signal(object, object, str)
    modrinthDetailsFinished = Signal(object, str)
    modrinthProgressChanged = Signal(str, int, bool)

    def __init__(self) -> None:
        super().__init__()
        self._config_file = _config_path()
        self._config_lock = RLock()
        self._config = _read_config()
        self._installations = [item for item in self._config.get("installations", []) if isinstance(item, dict)]
        raw_modpacks = _read_json_file(self._config_file.parent / "modpacks.json")
        self._modpacks = [item for item in raw_modpacks if isinstance(item, dict)] if isinstance(raw_modpacks, list) else []
        self._selected_index = min(max(0, int(self._config.get("current_installation_index", 0) or 0)), max(0, len(self._installations) - 1))
        self._wallpapers = self._collect_wallpapers()
        self._launch_status = "Ready to play"
        self._is_launching = False
        self._mods: list[dict[str, str]] = []
        self._mods_status = "Open Mods to scan this installation"
        self._mods_scanning = False
        self._modrinth_results: list[dict[str, Any]] = []
        self._modrinth_status = "Search Modrinth to discover compatible content"
        self._modrinth_busy = False
        self._modrinth_detail: dict[str, Any] = {}
        self._modrinth_progress_label = ""
        self._modrinth_progress = 0
        self._modrinth_downloading = False
        self._modrinth_install_project: dict[str, Any] | None = None
        self._modpack_status = "Paste a CurseForge export path to import it"
        self._settings_status = "Changes apply to the next launch"
        self._installation_status = "Select an installation to edit its launch settings"
        self._skin_preview_url = ""
        self._skin_preview_status = "Choose a skin PNG to see a 3D preview"
        self._account_auth = {"provider": "", "status": "Choose an account type to add it.", "busy": False, "deviceCode": "", "verificationUrl": ""}
        self.launchStatusUpdated.connect(self._apply_launch_status)
        self.launchFinished.connect(self._apply_launch_finished)
        self.modScanFinished.connect(self._apply_mod_scan)
        self.modpackImportFinished.connect(self._apply_modpack_import)
        self.skinPreviewFinished.connect(self._apply_skin_preview)
        self.accountAuthStateChanged.connect(self._apply_account_auth_state)
        self.accountAuthFinished.connect(self._apply_account_auth_finished)
        self.modrinthSearchFinished.connect(self._apply_modrinth_search)
        self.modrinthInstallFinished.connect(self._apply_modrinth_install)
        self.modrinthDetailsFinished.connect(self._apply_modrinth_details)
        self.modrinthProgressChanged.connect(self._apply_modrinth_progress)
        self._launcher = LaunchService(
            self._config,
            self._config_file.parent,
            self._modpacks,
            self._save_config,
            self.launchStatusUpdated.emit,
            self.launchFinished.emit,
        )
        self._mod_scanner = ModScanner(self.modScanFinished.emit)
        self._curseforge_importer = CurseForgeImport(self._config_file.parent, self.modpackImportFinished.emit)
        self._skin_previewer = SkinPreviewer(self._config_file.parent / "skin_previews", self.skinPreviewFinished.emit)
        self._account_authenticator = AccountAuthenticator(
            self._config_file.parent,
            self.accountAuthStateChanged.emit,
            self.accountAuthFinished.emit,
        )
        self._modrinth = ModrinthService(
            self._config_file.parent,
            self.modrinthSearchFinished.emit,
            self.modrinthInstallFinished.emit,
            self.modrinthDetailsFinished.emit,
            self.modrinthProgressChanged.emit,
        )
        self.requestSkinPreview()

    def _collect_wallpapers(self) -> list[Path]:
        candidates: list[Path] = []
        for directory in (PROJECT_ROOT / "wallpapers", self._config_file.parent / "wallpapers"):
            if not directory.is_dir():
                continue
            candidates.extend(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"})
        seen: set[str] = set()
        return [path for path in candidates if not (key := str(path.resolve()).lower()) in seen and not seen.add(key)]

    def _save_config(self) -> None:
        with self._config_lock:
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self._config_file.parent, delete=False) as temporary:
                json.dump(self._config, temporary, indent=4)
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, self._config_file)

    def _save_modpacks(self) -> None:
        destination = self._config_file.parent / "modpacks.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False) as temporary:
            json.dump(self._modpacks, temporary, indent=4)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, destination)

    @Slot(str)
    def _apply_launch_status(self, status: str) -> None:
        self._launch_status = status
        self.dataChanged.emit()

    @Slot(bool, str, int)
    def _apply_launch_finished(self, succeeded: bool, message: str, _seconds: int) -> None:
        self._is_launching = False
        self._launch_status = message if succeeded else f"Launch failed: {message}"
        self.dataChanged.emit()

    @Slot(list, str)
    def _apply_mod_scan(self, entries: list[dict[str, str]], status: str) -> None:
        self._mods = entries
        self._mods_status = status
        self._mods_scanning = False
        self._modrinth_results = [self._with_modrinth_install_state(result) for result in self._modrinth_results]
        if self._modrinth_detail:
            self._modrinth_detail = self._with_modrinth_install_state(self._modrinth_detail)
        self.dataChanged.emit()

    @Slot(object, object, str)
    def _apply_modpack_import(self, pack: object, installation: object, status: str) -> None:
        self._modpack_status = status
        if isinstance(pack, dict) and isinstance(installation, dict):
            self._modpacks.append(pack)
            self._installations.append(installation)
            self._selected_index = len(self._installations) - 1
            self._config["current_installation_index"] = self._selected_index
            self._sync_installations()
            if self._modrinth_install_project:
                self._remember_installed_modrinth_project(self._modrinth_install_project)
            self._save_modpacks()
            self._save_config()
        self.dataChanged.emit()

    @Slot(str, str)
    def _apply_skin_preview(self, path: str, status: str) -> None:
        self._skin_preview_url = QUrl.fromLocalFile(str(Path(path).resolve())).toString() if path else ""
        self._skin_preview_status = status
        self.dataChanged.emit()

    @Slot(object)
    def _apply_account_auth_state(self, state: object) -> None:
        if not isinstance(state, dict):
            return
        self._account_auth = {
            "provider": str(state.get("provider") or ""),
            "status": str(state.get("status") or ""),
            "busy": bool(state.get("busy", False)),
            "deviceCode": str(state.get("deviceCode") or ""),
            "verificationUrl": str(state.get("verificationUrl") or ""),
        }
        self._account_status = self._account_auth["status"]
        self.dataChanged.emit()

    @Slot(object, str)
    def _apply_account_auth_finished(self, profile: object, status: str) -> None:
        if isinstance(profile, dict):
            profiles = self._config.setdefault("profiles", [])
            if not isinstance(profiles, list):
                profiles = self._config["profiles"] = []
            profile_type = str(profile.get("type") or "")
            profile_uuid = str(profile.get("uuid") or "")
            existing_index = next(
                (
                    index
                    for index, existing in enumerate(profiles)
                    if isinstance(existing, dict)
                    and str(existing.get("type") or "") == profile_type
                    and profile_uuid
                    and str(existing.get("uuid") or "") == profile_uuid
                ),
                -1,
            )
            if existing_index >= 0:
                profiles[existing_index] = profile
                self._config["current_profile_index"] = existing_index
            else:
                profiles.append(profile)
                self._config["current_profile_index"] = len(profiles) - 1
            self._save_config()
            self.requestSkinPreview()
        self._account_status = status
        self.dataChanged.emit()

    @Slot(list, str)
    def _apply_modrinth_search(self, results: list[dict[str, Any]], status: str) -> None:
        self._modrinth_results = [self._with_modrinth_install_state(result) for result in results]
        self._modrinth_status = status
        self._modrinth_busy = False
        self.dataChanged.emit()

    @Slot(object, object, str)
    def _apply_modrinth_install(self, pack: object, installation: object, status: str) -> None:
        if isinstance(pack, dict) and isinstance(installation, dict):
            self._modpacks.append(pack)
            self._installations.append(installation)
            self._selected_index = len(self._installations) - 1
            self._config["current_installation_index"] = self._selected_index
            self._sync_installations()
            self._save_modpacks()
            self._save_config()
        elif status.startswith("Installed ") and self._modrinth_install_project:
            self._remember_installed_modrinth_project(self._modrinth_install_project)
        self._modrinth_status = status
        self._modrinth_busy = False
        self._modrinth_install_project = None
        self._modrinth_results = [self._with_modrinth_install_state(result) for result in self._modrinth_results]
        if self._modrinth_detail:
            self._modrinth_detail = self._with_modrinth_install_state(self._modrinth_detail)
        self.dataChanged.emit()

    @Slot(object, str)
    def _apply_modrinth_details(self, project: object, status: str) -> None:
        if isinstance(project, dict):
            self._modrinth_detail = self._with_modrinth_install_state(project)
        self._modrinth_status = status
        self.dataChanged.emit()

    @Slot(str, int, bool)
    def _apply_modrinth_progress(self, label: str, percent: int, active: bool) -> None:
        self._modrinth_progress_label = label
        self._modrinth_progress = max(0, min(100, int(percent)))
        self._modrinth_downloading = bool(active)
        self.dataChanged.emit()

    def _selected_installation(self) -> dict[str, Any]:
        if not self._installations:
            return {}
        return self._installations[self._selected_index]

    @staticmethod
    def _project_key(project: dict[str, Any]) -> str:
        return str(project.get("id") or project.get("slug") or "").strip().lower()

    def _modrinth_project_keys_for_selected_installation(self) -> set[str]:
        installation = self._selected_installation()
        installation_id = str(installation.get("id") or "")
        linked = next((pack for pack in self._modpacks if str(pack.get("linked_installation_id") or "") == installation_id), None)
        registry = self._config.get("modrinth_installed_projects", {})
        values = registry.get(installation_id, []) if isinstance(registry, dict) else []
        keys = {str(key).lower() for key in values if str(key).strip()}
        if linked:
            keys.update(str(key).lower() for key in linked.get("modrinth_projects", []) if str(key).strip())
        return keys

    def _with_modrinth_install_state(self, project: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(project)
        key = self._project_key(enriched)
        slug = str(enriched.get("slug") or "").lower().replace("-", "_")
        mod_files = " ".join(str(entry.get("file") or "").lower() for entry in self._mods)
        enriched["installed"] = bool(key and key in self._modrinth_project_keys_for_selected_installation()) or bool(slug and slug in mod_files)
        return enriched

    def _remember_installed_modrinth_project(self, project: dict[str, Any]) -> None:
        key = self._project_key(project)
        if not key:
            return
        installation = self._selected_installation()
        installation_id = str(installation.get("id") or "")
        linked = next((pack for pack in self._modpacks if str(pack.get("linked_installation_id") or "") == installation_id), None)
        if linked:
            values = linked.setdefault("modrinth_projects", [])
            if isinstance(values, list) and key not in values:
                values.append(key)
                self._save_modpacks()
        else:
            registry = self._config.setdefault("modrinth_installed_projects", {})
            if isinstance(registry, dict) and installation_id:
                values = registry.setdefault(installation_id, [])
                if isinstance(values, list) and key not in values:
                    values.append(key)
                    self._save_config()

    @Property("QVariantList", notify=dataChanged)
    def installations(self) -> list[dict[str, Any]]:
        return [
            {
                "index": index,
                "id": str(installation.get("id") or ""),
                "name": str(installation.get("name") or "Unnamed installation"),
                "version": str(installation.get("version") or "Latest release"),
                "loader": str(installation.get("loader") or "Vanilla"),
                "java": str(installation.get("java_executable") or ""),
                "resolution": self._installation_resolution_label(installation),
                "forceUpdate": bool(installation.get("force_update", False)),
                "selected": index == self._selected_index,
            }
            for index, installation in enumerate(self._installations)
        ]

    @staticmethod
    def _installation_resolution_label(installation: dict[str, Any]) -> str:
        width, height = str(installation.get("resolution_width") or ""), str(installation.get("resolution_height") or "")
        return f"{width} × {height}" if width.isdigit() and height.isdigit() else "Auto resolution"

    @Property(int, notify=dataChanged)
    def selectedIndex(self) -> int:
        return self._selected_index

    @Property("QVariantList", notify=dataChanged)
    def modpacks(self) -> list[dict[str, Any]]:
        installations_by_id = {str(item.get("id") or ""): str(item.get("name") or "Unnamed installation") for item in self._installations}
        records: list[dict[str, Any]] = []
        for index, pack in enumerate(self._modpacks):
            pack_id = str(pack.get("id") or "")
            try:
                mods_directory = self._safe_modpack_directory(pack_id, create=False) / "mods" if pack_id else None
            except ValueError:
                mods_directory = None
            try:
                mod_count = len(list(mods_directory.glob("*.jar"))) if mods_directory and mods_directory.is_dir() else 0
            except OSError:
                mod_count = 0
            linked_id = str(pack.get("linked_installation_id") or "")
            records.append({
                "index": index,
                "id": pack_id,
                "name": str(pack.get("name") or "Unnamed modpack"),
                "loader": str(pack.get("loader") or "Vanilla"),
                "version": str(pack.get("mc_version") or pack.get("version_name") or "Unknown version"),
                "source": str(pack.get("source") or "Local"),
                "linkedInstallationId": linked_id,
                "linkedInstallationName": installations_by_id.get(linked_id, "Not linked"),
                "modCount": mod_count,
            })
        return records

    @Property("QVariantMap", notify=dataChanged)
    def selectedInstallation(self) -> dict[str, Any]:
        installation = self._selected_installation()
        if not installation:
            return {"name": "No installation selected", "version": "Create an installation in the current launcher", "loader": ""}
        stats = self._config.get("addons", {}).get("playtime_tracker", {})
        stats = stats if isinstance(stats, dict) else {}
        install_id = str(installation.get("id") or "")
        playtime = stats.get(install_id, {}) if install_id else {}
        playtime = playtime if isinstance(playtime, dict) else {}
        return {
            "name": str(installation.get("name") or "Unnamed installation"),
            "version": str(installation.get("version") or "Latest release"),
            "loader": str(installation.get("loader") or "Vanilla"),
            "playtime": _format_playtime(playtime.get("seconds")),
            "launches": int(playtime.get("launches", 0) or 0),
            "lastPlayed": str(playtime.get("last_played_at") or installation.get("last_played") or "Never"),
            "java": str(installation.get("java_executable") or ""),
            "resolutionWidth": str(installation.get("resolution_width") or ""),
            "resolutionHeight": str(installation.get("resolution_height") or ""),
            "forceUpdate": bool(installation.get("force_update", False)),
        }

    @Property(str, notify=dataChanged)
    def wallpaperUrl(self) -> str:
        return _wallpaper_url(self._config.get("current_wallpaper"))

    @Property("QVariantList", notify=dataChanged)
    def wallpapers(self) -> list[dict[str, str]]:
        selected = str(self._config.get("current_wallpaper") or "")
        return [{"name": path.stem.replace("_", " "), "path": str(path.resolve()), "url": QUrl.fromLocalFile(str(path.resolve())).toString(), "selected": str(path.resolve()) == selected} for path in self._wallpapers]

    @Property(str, notify=dataChanged)
    def profileName(self) -> str:
        profiles = self._config.get("profiles", [])
        profiles = profiles if isinstance(profiles, list) else []
        index = int(self._config.get("current_profile_index", 0) or 0)
        profile = profiles[index] if 0 <= index < len(profiles) and isinstance(profiles[index], dict) else {}
        return str(profile.get("name") or "Offline player")

    def _current_profile(self) -> dict[str, Any]:
        profiles = self._config.get("profiles", [])
        index = self.currentProfileIndex
        if isinstance(profiles, list) and 0 <= index < len(profiles) and isinstance(profiles[index], dict):
            return profiles[index]
        return {}

    @Property(str, notify=dataChanged)
    def profileAvatarUrl(self) -> str:
        skin_path = Path(str(self._current_profile().get("skin_path") or ""))
        return QUrl.fromLocalFile(str(skin_path.resolve())).toString() if skin_path.is_file() else ""

    @Property(int, notify=dataChanged)
    def currentProfileIndex(self) -> int:
        try:
            return int(self._config.get("current_profile_index", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @Property("QVariantList", notify=dataChanged)
    def profiles(self) -> list[dict[str, str]]:
        records = self._config.get("profiles", [])
        selected = self.currentProfileIndex
        return [
            {
                "index": index,
                "name": str(item.get("name") or "Offline player"),
                "type": str(item.get("type") or "offline"),
                "skinPath": str(item.get("skin_path") or ""),
                "avatarUrl": _wallpaper_url(item.get("skin_path")) if Path(str(item.get("skin_path") or "")).is_file() else "",
                "selected": index == selected,
            }
            for index, item in enumerate(records)
            if isinstance(item, dict)
        ]

    @Property(str, notify=dataChanged)
    def accountLabel(self) -> str:
        profiles = self._config.get("profiles", [])
        profiles = profiles if isinstance(profiles, list) else []
        index = int(self._config.get("current_profile_index", 0) or 0)
        profile = profiles[index] if 0 <= index < len(profiles) and isinstance(profiles[index], dict) else {}
        account_type = str(profile.get("type") or "offline")
        return {"microsoft": "Microsoft account", "ely.by": "Ely.by account"}.get(account_type, "Offline account")

    @Property(str, notify=dataChanged)
    def accountStatus(self) -> str:
        return getattr(self, "_account_status", "Local profiles stay on this device")

    @Property("QVariantMap", notify=dataChanged)
    def accountAuth(self) -> dict[str, Any]:
        return dict(self._account_auth)

    @Property("QVariantMap", notify=dataChanged)
    def settings(self) -> dict[str, Any]:
        return {
            "minecraftDirectory": str(self._config.get("minecraft_dir") or get_minecraft_dir()),
            "ramAllocation": str(self._config.get("ram_allocation") or 4096),
            "javaArguments": str(self._config.get("java_args") or ""),
            "rpcEnabled": bool(self._config.get("rpc_enabled", True)),
            "autoUpdates": bool(self._config.get("auto_update_check", True)),
            "customTitlebar": bool(self._config.get("custom_titlebar_enabled", os.name == "nt")),
            "neoStyle": bool(self._config.get("neo_style_enabled", True)),
            "accentColor": str(self._config.get("accent_color") or "Green"),
        }

    @Property(str, notify=dataChanged)
    def settingsStatus(self) -> str:
        return self._settings_status

    @Property(str, notify=dataChanged)
    def skinPreviewUrl(self) -> str:
        return self._skin_preview_url

    @Property(str, notify=dataChanged)
    def skinPreviewStatus(self) -> str:
        return self._skin_preview_status

    @Property(bool, notify=dataChanged)
    def offlineSkinInjectionEnabled(self) -> bool:
        return bool(self._config.get("offline_skin_injection", self._config.get("auto_download_mod", True)))

    @Property(str, notify=dataChanged)
    def accentColor(self) -> str:
        colors = {
            "Green": "#3FD174",
            "Blue": "#63B8FF",
            "Orange": "#FFAE57",
            "Purple": "#B89CFF",
            "Red": "#FF7C7C",
        }
        return colors.get(str(self._config.get("accent_color") or "Green"), colors["Green"])

    @Property(str, notify=dataChanged)
    def installationStatus(self) -> str:
        return self._installation_status

    @Property(str, notify=dataChanged)
    def launchStatus(self) -> str:
        return self._launch_status

    @Property(bool, notify=dataChanged)
    def isLaunching(self) -> bool:
        return self._is_launching

    @Property("QVariantList", notify=dataChanged)
    def mods(self) -> list[dict[str, str]]:
        return self._mods

    @Property(str, notify=dataChanged)
    def modsStatus(self) -> str:
        return self._mods_status

    @Property(bool, notify=dataChanged)
    def modsScanning(self) -> bool:
        return self._mods_scanning

    @Property("QVariantList", notify=dataChanged)
    def modrinthResults(self) -> list[dict[str, Any]]:
        return self._modrinth_results

    @Property(str, notify=dataChanged)
    def modrinthStatus(self) -> str:
        return self._modrinth_status

    @Property(bool, notify=dataChanged)
    def modrinthBusy(self) -> bool:
        return self._modrinth_busy

    @Property("QVariantMap", notify=dataChanged)
    def modrinthDetail(self) -> dict[str, Any]:
        return self._modrinth_detail

    @Property(str, notify=dataChanged)
    def modrinthProgressLabel(self) -> str:
        return self._modrinth_progress_label

    @Property(int, notify=dataChanged)
    def modrinthProgress(self) -> int:
        return self._modrinth_progress

    @Property(bool, notify=dataChanged)
    def modrinthDownloading(self) -> bool:
        return self._modrinth_downloading

    @Property(str, notify=dataChanged)
    def modpackStatus(self) -> str:
        return self._modpack_status

    def _mods_directory_for_selected_installation(self) -> Path:
        installation = self._selected_installation()
        installation_id = str(installation.get("id") or "")
        linked = next(
            (pack for pack in self._modpacks if str(pack.get("linked_installation_id") or "") == installation_id),
            None,
        )
        if linked:
            safe_id = os.path.basename(str(linked.get("id") or "").strip())
            if safe_id and safe_id not in {".", ".."}:
                root = (self._config_file.parent / "modpacks").resolve()
                candidate = (root / safe_id).resolve()
                if candidate.parent == root:
                    return candidate / "mods"
        configured = str(self._config.get("minecraft_dir") or "").strip()
        minecraft_dir = Path(os.path.expanduser(os.path.expandvars(configured))).resolve() if configured else Path(get_minecraft_dir())
        return minecraft_dir / "mods"

    def _safe_modpack_directory(self, pack_id: str, *, create: bool) -> Path:
        safe_id = os.path.basename(pack_id.strip())
        if not safe_id or safe_id in {".", ".."}:
            raise ValueError("Invalid modpack identifier")
        root = (self._config_file.parent / "modpacks").resolve()
        candidate = (root / safe_id).resolve()
        if candidate.parent != root:
            raise ValueError("Modpack path is outside launcher storage")
        if create:
            candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    def _sync_installations(self) -> None:
        self._config["installations"] = self._installations

    @Slot(int)
    def selectInstallation(self, index: int) -> None:
        if 0 <= index < len(self._installations) and index != self._selected_index:
            self._selected_index = index
            self._config["current_installation_index"] = index
            self._mods = []
            self._mods_status = "Open Mods to scan this installation"
            self._installation_status = f"Editing {str(self._installations[index].get('name') or 'installation')}"
            self._save_config()
            self.dataChanged.emit()

    @Slot()
    def requestMods(self) -> None:
        if self._mod_scanner.start(self._mods_directory_for_selected_installation()):
            self._mods_scanning = True
            self._mods_status = "Scanning installed mods…"
            self.dataChanged.emit()

    @Slot(str, str)
    def searchModrinth(self, query: str, project_type: str) -> None:
        installation = self._selected_installation()
        game_version = str(installation.get("version") or "")
        loader = str(installation.get("loader") or "Vanilla")
        if self._modrinth.search(query, project_type, game_version, loader):
            self._modrinth_busy = True
            self._modrinth_status = "Searching Modrinth…"
            self.dataChanged.emit()

    @Slot("QVariantMap", str)
    def installModrinth(self, project: dict[str, Any], project_type: str) -> None:
        if not isinstance(project, dict):
            return
        if self._with_modrinth_install_state(project).get("installed"):
            self._modrinth_status = f"{str(project.get('title') or 'This project')} is already installed for this installation"
            self.dataChanged.emit()
            return
        installation = self._selected_installation()
        if not installation:
            self._modrinth_status = "Create an installation before installing content"
            self.dataChanged.emit()
            return
        configured = str(self._config.get("minecraft_dir") or "").strip()
        minecraft_dir = Path(os.path.expanduser(os.path.expandvars(configured))).resolve() if configured else Path(get_minecraft_dir()).resolve()
        if self._modrinth.install(
            project,
            project_type,
            str(installation.get("version") or ""),
            str(installation.get("loader") or "Vanilla"),
            minecraft_dir,
            self._mods_directory_for_selected_installation(),
        ):
            self._modrinth_busy = True
            self._modrinth_install_project = dict(project)
            self._modrinth_progress_label = f"Preparing {str(project.get('title') or 'content')}"
            self._modrinth_progress = 0
            self._modrinth_downloading = True
            self._modrinth_status = f"Installing {str(project.get('title') or 'content')}…"
            self.dataChanged.emit()

    @Slot("QVariantMap")
    def openModrinthDetails(self, project: dict[str, Any]) -> None:
        if not isinstance(project, dict):
            return
        self._modrinth_detail = self._with_modrinth_install_state(project)
        self._modrinth_status = "Loading project details…"
        self.dataChanged.emit()
        self._modrinth.details(self._modrinth_detail)

    @Slot(str)
    def importCurseForge(self, archive_path: str) -> None:
        path = archive_path.strip()
        if not path:
            return
        self._modpack_status = "Importing CurseForge export…"
        self.dataChanged.emit()
        self._curseforge_importer.start(path)

    @Slot(str, str, str)
    @Slot(str, str, str, str, str, str, bool)
    def createInstallation(
        self, name: str, version: str, loader: str, java: str = "", width: str = "", height: str = "", force_update: bool = False
    ) -> None:
        name = name.strip()[:64]
        version = version.strip()[:64] or "latest-release"
        loader = loader.strip().title()
        if not name:
            return
        if loader not in {"Vanilla", "Fabric", "Forge"}:
            loader = "Vanilla"
        if bool(width.strip()) != bool(height.strip()) or (width and not width.isdigit()) or (height and not height.isdigit()):
            self._installation_status = "Resolution needs both numeric width and height, or neither"
            self.dataChanged.emit()
            return
        installation = {
            "id": uuid.uuid4().hex,
            "name": name,
            "version": version,
            "loader": loader,
            "java_executable": java.strip(),
            "resolution_width": width.strip(),
            "resolution_height": height.strip(),
            "force_update": bool(force_update),
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self._installations.append(installation)
        self._selected_index = len(self._installations) - 1
        self._config["current_installation_index"] = self._selected_index
        self._installation_status = f"Created {name}"
        self._sync_installations()
        self._save_config()
        self.dataChanged.emit()

    @Slot(int, str, str, str, str, str, str, bool)
    def updateInstallation(
        self, index: int, name: str, version: str, loader: str, java: str, width: str, height: str, force_update: bool
    ) -> None:
        if not (0 <= index < len(self._installations)):
            return
        name, version = name.strip()[:64], version.strip()[:64]
        if not name or not version:
            self._installation_status = "Installation name and Minecraft version are required"
            self.dataChanged.emit()
            return
        normalized_loader = loader.strip().title()
        if normalized_loader not in {"Vanilla", "Fabric", "Forge"}:
            normalized_loader = "Vanilla"
        if bool(width.strip()) != bool(height.strip()) or (width and not width.isdigit()) or (height and not height.isdigit()):
            self._installation_status = "Resolution needs both numeric width and height, or neither"
            self.dataChanged.emit()
            return
        installation = self._installations[index]
        installation.update(
            {
                "name": name,
                "version": version,
                "loader": normalized_loader,
                "java_executable": java.strip(),
                "resolution_width": width.strip(),
                "resolution_height": height.strip(),
                "force_update": bool(force_update),
            }
        )
        self._installation_status = f"Saved {name}"
        self._sync_installations()
        self._save_config()
        self.dataChanged.emit()

    @Slot(int)
    def deleteInstallation(self, index: int) -> None:
        if not (0 <= index < len(self._installations)):
            return
        if len(self._installations) <= 1:
            self._installation_status = "Keep at least one installation so Play is always available"
            self.dataChanged.emit()
            return
        removed = self._installations.pop(index)
        removed_id = str(removed.get("id") or "")
        for pack in self._modpacks:
            if str(pack.get("linked_installation_id") or "") == removed_id:
                pack["linked_installation_id"] = None
        self._selected_index = min(self._selected_index, len(self._installations) - 1)
        self._config["current_installation_index"] = self._selected_index
        self._installation_status = f"Deleted {str(removed.get('name') or 'installation')}"
        self._sync_installations()
        self._save_modpacks()
        self._save_config()
        self.dataChanged.emit()

    @Slot(str, str, str)
    def createModpack(self, name: str, version: str, loader: str) -> None:
        name, version = name.strip()[:64], version.strip()[:64]
        loader = loader.strip().title()
        if not name or not version:
            self._modpack_status = "Modpack name and Minecraft version are required"
            self.dataChanged.emit()
            return
        if loader not in {"Vanilla", "Fabric", "Forge"}:
            loader = "Fabric"
        pack_id, installation_id = uuid.uuid4().hex, uuid.uuid4().hex
        try:
            (self._safe_modpack_directory(pack_id, create=True) / "mods").mkdir(exist_ok=True)
        except OSError as error:
            self._modpack_status = f"Could not create modpack storage: {error}"
            self.dataChanged.emit()
            return
        pack = {"id": pack_id, "name": name, "loader": loader, "mc_version": version, "source": "Local", "mods": [], "linked_installation_id": installation_id}
        installation = {"id": installation_id, "name": name, "version": version, "loader": loader, "created": datetime.now().strftime("%Y-%m-%d %H:%M")}
        self._modpacks.append(pack)
        self._installations.append(installation)
        self._selected_index = len(self._installations) - 1
        self._config["current_installation_index"] = self._selected_index
        self._modpack_status = f"Created and linked {name}"
        self._sync_installations()
        self._save_modpacks()
        self._save_config()
        self.dataChanged.emit()

    @Slot(int, int)
    def linkModpack(self, pack_index: int, installation_index: int) -> None:
        if not (0 <= pack_index < len(self._modpacks) and 0 <= installation_index < len(self._installations)):
            return
        pack, installation = self._modpacks[pack_index], self._installations[installation_index]
        pack_version = str(pack.get("mc_version") or "").strip()
        installation_version = str(installation.get("version") or "").strip()
        pack_loader = str(pack.get("loader") or "Vanilla").strip().lower()
        installation_loader = str(installation.get("loader") or "Vanilla").strip().lower()
        if pack_version and installation_version not in {"latest-release", "latest-snapshot", pack_version}:
            self._modpack_status = f"{str(installation.get('name') or 'Installation')} uses {installation_version}, but this pack needs {pack_version}"
            self.dataChanged.emit()
            return
        if pack_loader != installation_loader:
            self._modpack_status = f"{str(installation.get('name') or 'Installation')} uses {installation.get('loader')}, but this pack needs {pack.get('loader')}"
            self.dataChanged.emit()
            return
        pack["linked_installation_id"] = str(installation.get("id") or "")
        self._modpack_status = f"Linked {str(pack.get('name') or 'modpack')} to {str(installation.get('name') or 'installation')}"
        self._save_modpacks()
        self.dataChanged.emit()

    @Slot(int)
    def deleteModpack(self, index: int) -> None:
        if not (0 <= index < len(self._modpacks)):
            return
        pack = self._modpacks.pop(index)
        pack_id = str(pack.get("id") or "")
        try:
            directory = self._safe_modpack_directory(pack_id, create=False)
            if directory.exists():
                shutil.rmtree(directory)
        except (OSError, ValueError) as error:
            self._modpacks.insert(index, pack)
            self._modpack_status = f"Could not delete modpack files: {error}"
            self.dataChanged.emit()
            return
        self._modpack_status = f"Deleted {str(pack.get('name') or 'modpack')}"
        self._save_modpacks()
        self.dataChanged.emit()

    @Slot(int)
    def requestModpackMods(self, index: int) -> None:
        if not (0 <= index < len(self._modpacks)):
            return
        try:
            directory = self._safe_modpack_directory(str(self._modpacks[index].get("id") or ""), create=False) / "mods"
        except ValueError:
            self._mods_status = "This modpack has an invalid storage path"
            self.dataChanged.emit()
            return
        if self._mod_scanner.start(directory):
            self._mods_scanning = True
            self._mods_status = "Scanning modpack mods…"
            self.dataChanged.emit()

    @Slot(int)
    def openModpackFolder(self, index: int) -> None:
        if not (0 <= index < len(self._modpacks)):
            return
        try:
            folder = self._safe_modpack_directory(str(self._modpacks[index].get("id") or ""), create=True)
        except ValueError as error:
            self._modpack_status = str(error)
            self.dataChanged.emit()
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self._modpack_status = "Could not open the modpack folder"
            self.dataChanged.emit()

    @Slot()
    def requestLaunch(self) -> None:
        installation = self._selected_installation()
        if not installation:
            return
        if self._launcher.start(installation):
            self._is_launching = True
            self._launch_status = "Preparing Minecraft…"
            self.dataChanged.emit()
            self.launchRequested.emit(installation)
        else:
            self._launch_status = "Minecraft is already being prepared"
            self.dataChanged.emit()

    @Slot(int)
    def launchInstallation(self, index: int) -> None:
        if not (0 <= index < len(self._installations)):
            return
        self.selectInstallation(index)
        self.requestLaunch()

    @Slot(int)
    def launchModpack(self, pack_index: int) -> None:
        if not (0 <= pack_index < len(self._modpacks)):
            return
        installation_id = str(self._modpacks[pack_index].get("linked_installation_id") or "")
        index = next((position for position, item in enumerate(self._installations) if str(item.get("id") or "") == installation_id), -1)
        if index < 0:
            self._modpack_status = "Link this modpack to an installation before launching"
            self.dataChanged.emit()
            return
        self.launchInstallation(index)

    @Slot(str)
    def selectWallpaper(self, path: str) -> None:
        candidate = Path(path)
        if candidate.is_file() and candidate.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            self._config["current_wallpaper"] = str(candidate.resolve())
            self._save_config()
            self.dataChanged.emit()

    @Slot()
    def startMicrosoftLogin(self) -> None:
        if not self._account_authenticator.start_microsoft():
            self._account_status = "Another account sign-in is already in progress"
            self.dataChanged.emit()

    @Slot()
    def cancelMicrosoftLogin(self) -> None:
        self._account_authenticator.cancel_microsoft()
        self._account_status = "Cancelling Microsoft sign-in…"
        self.dataChanged.emit()

    @Slot()
    def copyMicrosoftCode(self) -> None:
        code = str(self._account_auth.get("deviceCode") or "")
        if not code:
            self._account_status = "Start Microsoft sign-in first to get a code"
        else:
            QGuiApplication.clipboard().setText(code)
            self._account_status = "Microsoft device code copied"
        self.dataChanged.emit()

    @Slot(str, str)
    def loginElyBy(self, username: str, password: str) -> None:
        if not self._account_authenticator.login_elyby(username, password):
            self._account_status = "Another account sign-in is already in progress"
            self.dataChanged.emit()

    @Slot(str)
    def createOfflineProfile(self, name: str) -> None:
        name = name.strip()[:32]
        if not name:
            return
        profiles = self._config.setdefault("profiles", [])
        if not isinstance(profiles, list):
            profiles = self._config["profiles"] = []
        profiles.append({"name": name, "type": "offline", "skin_path": "", "uuid": ""})
        self._config["current_profile_index"] = len(profiles) - 1
        self._account_status = f"Created offline profile for {name}"
        self._save_config()
        self.requestSkinPreview()
        self.dataChanged.emit()

    @Slot(int)
    def selectProfile(self, index: int) -> None:
        profiles = self._config.get("profiles", [])
        if isinstance(profiles, list) and 0 <= index < len(profiles):
            self._config["current_profile_index"] = index
            self._account_status = f"Using {str(profiles[index].get('name') or 'this profile')}"
            self._save_config()
            self.requestSkinPreview()
            self.dataChanged.emit()

    @Slot(int)
    def deleteProfile(self, index: int) -> None:
        profiles = self._config.get("profiles", [])
        if not isinstance(profiles, list) or not (0 <= index < len(profiles)):
            return
        if len(profiles) <= 1:
            self._account_status = "Keep at least one profile so offline play is always available"
            self.dataChanged.emit()
            return
        removed = profiles.pop(index)
        selected = self.currentProfileIndex
        if index < selected:
            selected -= 1
        elif index == selected:
            selected = max(0, min(selected, len(profiles) - 1))
        self._config["current_profile_index"] = selected
        self._account_status = f"Removed {str(removed.get('name') or 'profile')}"
        self._save_config()
        self.requestSkinPreview()
        self.dataChanged.emit()

    @Slot(str)
    def setOfflineSkin(self, path: str) -> None:
        candidate = Path(path.strip()).expanduser()
        profiles = self._config.get("profiles", [])
        index = self.currentProfileIndex
        if not candidate.is_file() or candidate.suffix.lower() != ".png":
            return
        if isinstance(profiles, list) and 0 <= index < len(profiles) and isinstance(profiles[index], dict):
            profiles[index]["skin_path"] = str(candidate.resolve())
            profiles[index].setdefault("skin_model", "classic")
            self._account_status = "Offline skin is ready for your next launch"
            self._save_config()
            self.requestSkinPreview()
            self.dataChanged.emit()

    @Slot(bool)
    def setOfflineSkinInjectionEnabled(self, enabled: bool) -> None:
        self._config["offline_skin_injection"] = bool(enabled)
        self._account_status = "Offline skin injection enabled" if enabled else "Offline skin injection disabled"
        self._save_config()
        self.dataChanged.emit()

    @Slot()
    def requestSkinPreview(self) -> None:
        profile = self._current_profile()
        path = str(profile.get("skin_path") or "")
        model = str(profile.get("skin_model") or "classic")
        if self._skin_previewer.start(path, model):
            self._skin_preview_status = "Rendering skin preview…"
            self.dataChanged.emit()

    @Slot(str, int, str, bool, bool, bool, bool, str)
    def saveSettings(
        self,
        minecraft_directory: str,
        ram_allocation: int,
        java_arguments: str,
        rpc_enabled: bool,
        auto_updates: bool,
        custom_titlebar: bool,
        neo_style: bool,
        accent_color: str,
    ) -> None:
        try:
            ram = max(512, min(32768, int(ram_allocation)))
        except (TypeError, ValueError):
            ram = 4096
        directory = minecraft_directory.strip()
        if directory:
            try:
                candidate = Path(os.path.expandvars(os.path.expanduser(directory))).resolve()
                if candidate.exists() and not candidate.is_dir():
                    raise ValueError("Minecraft directory points to a file")
                candidate.mkdir(parents=True, exist_ok=True)
                directory = str(candidate)
            except (OSError, ValueError) as error:
                self._settings_status = f"Settings were not saved: {error}"
                self.dataChanged.emit()
                return
        self._config.update(
            {
                "minecraft_dir": directory or get_minecraft_dir(),
                "ram_allocation": ram,
                "java_args": java_arguments.strip(),
                "rpc_enabled": bool(rpc_enabled),
                "auto_update_check": bool(auto_updates),
                "custom_titlebar_enabled": bool(custom_titlebar) and os.name == "nt",
                "neo_style_enabled": bool(neo_style),
                "accent_color": accent_color if accent_color in {"Green", "Blue", "Orange", "Purple", "Red"} else "Green",
            }
        )
        self._settings_status = "Settings saved. Launch settings apply next time you press Play."
        self._save_config()
        self.dataChanged.emit()


def main() -> int:
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("New Launcher Qt")
    engine = QQmlApplicationEngine()
    bridge = LauncherBridge()
    engine.rootContext().setContextProperty("launcher", bridge)
    engine.load(QUrl.fromLocalFile(str((Path(__file__).parent / "qml" / "Main.qml").resolve())))
    if not engine.rootObjects():
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
