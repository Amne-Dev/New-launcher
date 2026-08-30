"""Local CurseForge export import, kept off the QML event loop."""

from __future__ import annotations

import json
import os
import shutil
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from threading import Thread
from typing import Any, Callable


ImportCallback = Callable[[dict[str, Any] | None, dict[str, Any] | None, str], None]


def _loader_from_manifest(manifest: dict[str, Any]) -> str:
    minecraft = manifest.get("minecraft", {})
    records = minecraft.get("modLoaders", []) if isinstance(minecraft, dict) else []
    ids = [str(record.get("id") or "").lower() for record in records if isinstance(record, dict)]
    if any("fabric" in value for value in ids):
        return "Fabric"
    if any("forge" in value and "neoforge" not in value for value in ids):
        return "Forge"
    return "Vanilla"


def _safe_override_members(archive: zipfile.ZipFile, overrides: str) -> list[zipfile.ZipInfo]:
    prefix = PurePosixPath(overrides.replace("\\", "/").strip("/"))
    if not prefix.parts or any(part in {"", ".", ".."} for part in prefix.parts):
        raise ValueError("The CurseForge overrides path is unsafe.")
    members: list[zipfile.ZipInfo] = []
    for member in archive.infolist():
        path = PurePosixPath(member.filename.replace("\\", "/"))
        if path.is_absolute() or any(part == ".." for part in path.parts):
            raise ValueError("The CurseForge archive contains an unsafe file path.")
        try:
            relative = path.relative_to(prefix)
        except ValueError:
            continue
        if relative.parts and not member.is_dir():
            members.append(member)
    return members


class CurseForgeImport:
    """Imports a CurseForge zip's safe overrides into launcher storage."""

    def __init__(self, config_directory: Path, callback: ImportCallback) -> None:
        self._config_directory = config_directory
        self._callback = callback

    def start(self, archive_path: str) -> None:
        Thread(target=self._run, args=(archive_path,), daemon=True).start()

    def _run(self, archive_path: str) -> None:
        staging: Path | None = None
        try:
            archive_file = Path(archive_path).expanduser().resolve()
            if archive_file.suffix.lower() != ".zip" or not archive_file.is_file():
                raise ValueError("Choose a valid CurseForge .zip export.")
            with zipfile.ZipFile(archive_file) as archive:
                try:
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8-sig"))
                except KeyError as error:
                    raise ValueError("This archive is not a CurseForge export (manifest.json is missing).") from error
                if not isinstance(manifest, dict) or not isinstance(manifest.get("minecraft"), dict):
                    raise ValueError("The CurseForge manifest is malformed.")
                minecraft_version = str(manifest["minecraft"].get("version") or "").strip()
                if not minecraft_version:
                    raise ValueError("The CurseForge manifest does not specify a Minecraft version.")
                pack_id = uuid.uuid4().hex
                root = (self._config_directory / "modpacks").resolve()
                root.mkdir(parents=True, exist_ok=True)
                staging = root / f".import-{pack_id}"
                final = root / pack_id
                staging.mkdir()
                overrides = str(manifest.get("overrides") or "overrides")
                for member in _safe_override_members(archive, overrides):
                    relative = PurePosixPath(member.filename.replace("\\", "/")).relative_to(PurePosixPath(overrides.replace("\\", "/").strip("/")))
                    destination = (staging / Path(*relative.parts)).resolve()
                    if destination.parent != staging and staging not in destination.parents:
                        raise ValueError("The CurseForge archive contains an unsafe file path.")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)
            os.replace(staging, final)
            staging = None
            name = str(manifest.get("name") or archive_file.stem).strip() or "Imported CurseForge Pack"
            loader = _loader_from_manifest(manifest)
            pack = {
                "id": pack_id,
                "name": name,
                "loader": loader,
                "mc_version": minecraft_version,
                "version_name": str(manifest.get("version") or ""),
                "source": "curseforge",
                "curseforge_files": [item for item in manifest.get("files", []) if isinstance(item, dict)],
                "linked_installation_id": pack_id,
            }
            installation = {"id": pack_id, "name": name, "version": minecraft_version, "loader": loader}
            self._callback(pack, installation, f"Imported {name}. CurseForge file downloads need an API key.")
        except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
            if staging and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            self._callback(None, None, f"Import failed: {error}")
