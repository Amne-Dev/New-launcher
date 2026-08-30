"""Non-UI Minecraft launch pipeline used by the QML launcher.

Keeping this module independent of Qt makes long running install/download work
safe to run off the UI thread and gives the future Linux build the same launch
behaviour as Windows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable

import minecraft_launcher_lib
import requests

from config import DEFAULT_RAM, MSA_CLIENT_ID, MSA_REDIRECT_URI
from handlers import LocalSkinServer
from utils import get_minecraft_dir


StatusCallback = Callable[[str], None]
FinishCallback = Callable[[bool, str, int], None]
SaveCallback = Callable[[], None]


class LaunchService:
    """Prepare, launch, and account for one Minecraft session at a time."""

    def __init__(
        self,
        config: dict[str, Any],
        config_directory: Path,
        modpacks: list[dict[str, Any]],
        save_config: SaveCallback,
        on_status: StatusCallback,
        on_finished: FinishCallback,
    ) -> None:
        self._config = config
        self._config_directory = config_directory
        self._modpacks = modpacks
        self._save_config = save_config
        self._on_status = on_status
        self._on_finished = on_finished
        self._lock = Lock()
        self._running = False

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def start(self, installation: dict[str, Any]) -> bool:
        """Start work in a daemon thread, returning False if already busy."""
        with self._lock:
            if self._running:
                return False
            self._running = True
        Thread(target=self._run, args=(dict(installation),), daemon=True).start()
        return True

    def _status(self, message: str) -> None:
        self._on_status(message)

    def _minecraft_directory(self) -> str:
        configured = str(self._config.get("minecraft_dir") or "").strip()
        if configured:
            return os.path.abspath(os.path.expanduser(os.path.expandvars(configured)))
        return get_minecraft_dir()

    def _current_profile(self) -> dict[str, Any]:
        profiles = self._config.get("profiles", [])
        if not isinstance(profiles, list):
            return {"name": "Steve", "type": "offline"}
        try:
            index = int(self._config.get("current_profile_index", 0) or 0)
        except (TypeError, ValueError):
            index = 0
        if 0 <= index < len(profiles) and isinstance(profiles[index], dict):
            return profiles[index]
        return {"name": "Steve", "type": "offline"}

    def _resolve_java(self, minecraft_dir: str, custom_java: Any) -> str:
        requested = os.path.expanduser(os.path.expandvars(str(custom_java or "").strip()))
        if requested:
            if os.path.isdir(requested):
                names = ("java.exe", "javaw.exe", "java")
                for name in names:
                    candidate = os.path.join(requested, "bin", name)
                    if os.path.isfile(candidate):
                        return candidate
                raise RuntimeError(f"No Java executable was found inside '{requested}'.")
            if os.path.isfile(requested) or shutil.which(requested):
                return requested
            raise RuntimeError(f"Java executable not found: {requested}")

        runtime_root = Path(minecraft_dir) / "runtime"
        if runtime_root.is_dir():
            names = ("java.exe", "java") if os.name == "nt" else ("java", "java.exe")
            for name in names:
                matches = list(runtime_root.rglob(name))
                if matches:
                    return str(matches[0])
        return shutil.which("java") or "java"

    def _callback(self) -> dict[str, Callable[[Any], None]]:
        return {
            "setStatus": lambda value: self._status(str(value)),
            # QML presents a concise indeterminate state for now.  Keeping the
            # callbacks here preserves installer compatibility while a proper
            # transfer queue is moved from the old UI.
            "setProgress": lambda _value: None,
            "setMax": lambda _value: None,
        }

    @staticmethod
    def _loader_name(installation: dict[str, Any]) -> str:
        return str(installation.get("loader") or "Vanilla").strip().lower()

    def _install_or_resolve_version(
        self, installation: dict[str, Any], minecraft_dir: str, callback: dict[str, Callable[[Any], None]]
    ) -> tuple[str, str]:
        version = str(installation.get("version") or "latest-release")
        if version in {"latest-release", "latest-snapshot"}:
            self._status("Resolving Minecraft version…")
            latest = minecraft_launcher_lib.utils.get_latest_version()
            version = str(latest["snapshot" if version == "latest-snapshot" else "release"])

        loader = self._loader_name(installation)
        installed = {str(item.get("id")) for item in minecraft_launcher_lib.utils.get_installed_versions(minecraft_dir)}
        force_update = bool(installation.get("force_update", False))
        java = self._resolve_java(minecraft_dir, installation.get("java_executable"))

        if loader == "fabric":
            existing = next((item for item in installed if "fabric" in item.lower() and version in item.split("-")), None)
            if existing and not force_update:
                return existing, version
            self._status(f"Installing Fabric for {version}…")
            launch_id = minecraft_launcher_lib.fabric.install_fabric(version, minecraft_dir, callback=callback, java=java)
            if launch_id:
                return str(launch_id), version
            loader_version = minecraft_launcher_lib.fabric.get_latest_loader_version()
            return f"fabric-loader-{loader_version}-{version}", version

        if loader == "forge":
            existing = next((item for item in installed if "forge" in item.lower() and version in item.split("-")), None)
            if existing and not force_update:
                return existing, version
            self._status(f"Installing Forge for {version}…")
            forge_version = minecraft_launcher_lib.forge.find_forge_version(version)
            if not forge_version:
                raise RuntimeError(f"No Forge build is available for Minecraft {version}.")
            minecraft_launcher_lib.forge.install_forge_version(forge_version, minecraft_dir, callback=callback, java=java)
            return str(forge_version), version

        if force_update or version not in installed:
            self._status(f"Installing Minecraft {version}…")
            minecraft_launcher_lib.install.install_minecraft_version(version, minecraft_dir, callback=callback)
        return version, version

    def _launch_identity(self, profile: dict[str, Any]) -> tuple[str, str, str]:
        account_type = str(profile.get("type") or "offline").lower()
        username = str(profile.get("name") or "Steve").strip() or "Steve"
        if account_type == "microsoft":
            refresh_token = str(profile.get("refresh_token") or "")
            if not refresh_token:
                raise RuntimeError("Your Microsoft session has expired. Sign in again from Accounts.")
            self._status("Refreshing Microsoft session…")
            refreshed = minecraft_launcher_lib.microsoft_account.complete_refresh(
                MSA_CLIENT_ID, None, MSA_REDIRECT_URI, refresh_token
            )
            if not isinstance(refreshed, dict) or refreshed.get("error"):
                raise RuntimeError("Your Microsoft session has expired. Sign in again from Accounts.")
            profile.update(
                {
                    "name": refreshed["name"],
                    "uuid": refreshed["id"],
                    "access_token": refreshed["access_token"],
                    "refresh_token": refreshed["refresh_token"],
                }
            )
            self._save_config()
            return str(refreshed["name"]), str(refreshed["id"]), str(refreshed["access_token"])
        if account_type == "ely.by":
            token, account_uuid = str(profile.get("token") or ""), str(profile.get("uuid") or "")
            if not token or not account_uuid:
                raise RuntimeError("Your Ely.by account needs to be signed in again.")
            return username, account_uuid, token
        return username, str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{username}")), ""

    def _ensure_authlib_injector(self, minecraft_dir: str) -> str:
        destination = Path(minecraft_dir) / "authlib-injector.jar"
        if destination.is_file() and destination.stat().st_size > 0:
            return str(destination)
        self._status("Downloading offline skin support…")
        response = requests.get("https://api.github.com/repos/yushijinhun/authlib-injector/releases/latest", timeout=(10, 30))
        response.raise_for_status()
        release = response.json()
        asset = next((item for item in release.get("assets", []) if str(item.get("name") or "").endswith(".jar")), None)
        if not isinstance(asset, dict) or not isinstance(asset.get("browser_download_url"), str):
            raise RuntimeError("Could not find an authlib-injector release.")
        temporary = destination.with_suffix(".download")
        try:
            with requests.get(asset["browser_download_url"], stream=True, timeout=(10, 60)) as download:
                download.raise_for_status()
                with temporary.open("wb") as target:
                    for chunk in download.iter_content(128 * 1024):
                        if chunk:
                            target.write(chunk)
            if temporary.stat().st_size == 0:
                raise RuntimeError("Downloaded offline skin support was empty.")
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
        return str(destination)

    def _modpack_directory(self, pack_id: Any) -> Path:
        safe_id = os.path.basename(str(pack_id or "").strip())
        if not safe_id or safe_id in {".", ".."}:
            raise RuntimeError("The linked modpack has an invalid identifier.")
        root = (self._config_directory / "modpacks").resolve()
        candidate = (root / safe_id).resolve()
        if candidate.parent != root:
            raise RuntimeError("The linked modpack is outside launcher storage.")
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    def _activate_linked_modpack(self, installation_id: Any, minecraft_dir: str) -> tuple[Path | None, Path | None]:
        linked = next(
            (pack for pack in self._modpacks if str(pack.get("linked_installation_id") or "") == str(installation_id or "")),
            None,
        )
        if not linked:
            return None, None
        self._status(f"Updating {str(linked.get('name') or 'modpack')}…")
        root = self._modpack_directory(linked.get("id"))
        source = root / "mods"
        target = Path(minecraft_dir).resolve() / "mods"
        stage = Path(minecraft_dir).resolve() / f".nlc_modpack_stage_{uuid.uuid4().hex}"
        backup: Path | None = None
        if source.is_file():
            raise RuntimeError("The linked modpack's mods path is not a folder.")
        if source.is_dir():
            shutil.copytree(source, stage)
        else:
            stage.mkdir(parents=True)
        if target.exists() or target.is_symlink():
            backup = Path(minecraft_dir).resolve() / f".nlc_mods_backup_{uuid.uuid4().hex}"
            os.replace(target, backup)
        try:
            os.replace(stage, target)
        except Exception:
            if backup and backup.exists():
                os.replace(backup, target)
            raise
        return target, backup

    @staticmethod
    def _restore_mods(target: Path | None, backup: Path | None) -> None:
        if target and (target.exists() or target.is_symlink()):
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        if target and backup and backup.exists():
            os.replace(backup, target)

    def _record_session(self, installation_id: Any, seconds: int) -> None:
        if not installation_id:
            return
        addons = self._config.setdefault("addons", {})
        if not isinstance(addons, dict):
            addons = self._config["addons"] = {}
        tracker = addons.setdefault("playtime_tracker", {})
        if not isinstance(tracker, dict):
            tracker = addons["playtime_tracker"] = {}
        key = str(installation_id)
        entry = tracker.get(key)
        if not isinstance(entry, dict):
            entry = tracker[key] = {}
        entry["seconds"] = max(0, int(entry.get("seconds", 0) or 0)) + max(0, seconds)
        entry["launches"] = max(0, int(entry.get("launches", 0) or 0)) + 1
        entry["last_played_at"] = time.strftime("%Y-%m-%d %H:%M")
        self._save_config()

    def _run(self, installation: dict[str, Any]) -> None:
        mods_target: Path | None = None
        mods_backup: Path | None = None
        session_seconds = 0
        succeeded = False
        message = "Minecraft closed"
        skin_server: LocalSkinServer | None = None
        try:
            minecraft_dir = self._minecraft_directory()
            Path(minecraft_dir).mkdir(parents=True, exist_ok=True)
            self._status("Preparing Minecraft…")
            callback = self._callback()
            launch_id, resolved_version = self._install_or_resolve_version(installation, minecraft_dir, callback)
            profile = self._current_profile()
            username, account_uuid, token = self._launch_identity(profile)
            mods_target, mods_backup = self._activate_linked_modpack(installation.get("id"), minecraft_dir)
            try:
                ram = max(512, int(self._config.get("ram_allocation", DEFAULT_RAM) or DEFAULT_RAM))
            except (TypeError, ValueError):
                ram = DEFAULT_RAM
            arguments = [f"-Xmx{ram}M"]
            additional = str(self._config.get("java_args") or "").strip()
            if additional:
                arguments.extend(additional.split())
            account_type = str(profile.get("type") or "offline").lower()
            if account_type == "ely.by":
                injector = self._ensure_authlib_injector(minecraft_dir)
                arguments.append(f"-javaagent:{injector}=https://authserver.ely.by/api/authlib-injector")
            elif account_type == "offline":
                skin_path = Path(str(profile.get("skin_path") or "")).expanduser()
                injection_enabled = bool(self._config.get("offline_skin_injection", self._config.get("auto_download_mod", True)))
                if injection_enabled and skin_path.is_file():
                    skin_server = LocalSkinServer(port=0)
                    skin_url = skin_server.start(str(skin_path), username, account_uuid, str(profile.get("skin_model") or "classic"))
                    if skin_url:
                        injector = self._ensure_authlib_injector(minecraft_dir)
                        arguments.append(f"-javaagent:{injector}={skin_url}")
            options: dict[str, Any] = {
                "username": username,
                "uuid": account_uuid,
                "token": token,
                "jvmArguments": arguments,
                "launcherName": "NewLauncher",
                "gameDirectory": minecraft_dir,
            }
            executable = str(installation.get("java_executable") or "").strip()
            if executable:
                options["executablePath"] = self._resolve_java(minecraft_dir, executable)
            width, height = installation.get("resolution_width"), installation.get("resolution_height")
            if str(width or "").isdigit() and str(height or "").isdigit():
                options.update({"customResolution": True, "resolutionWidth": str(width), "resolutionHeight": str(height)})
            self._status("Starting Minecraft…")
            command = minecraft_launcher_lib.command.get_minecraft_command(launch_id, minecraft_dir, options)
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            started = time.monotonic()
            process = subprocess.Popen(command, cwd=minecraft_dir, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, creationflags=flags)
            self._status(f"Playing {resolved_version}")
            process.wait()
            session_seconds = max(0, int(time.monotonic() - started))
            self._record_session(installation.get("id"), session_seconds)
            succeeded = True
        except Exception as error:
            message = str(error)
        finally:
            try:
                self._restore_mods(mods_target, mods_backup)
            except Exception as error:
                self._status(f"Could not restore global mods: {error}")
            if skin_server:
                skin_server.stop()
            with self._lock:
                self._running = False
            self._on_finished(succeeded, message, session_seconds)
