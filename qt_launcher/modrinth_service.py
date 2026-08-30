"""Background Modrinth discovery and installation for the QML launcher."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from threading import Lock, Thread
from typing import Any, Callable

import requests


SearchCallback = Callable[[list[dict[str, Any]], str], None]
InstallCallback = Callable[[dict[str, Any] | None, dict[str, Any] | None, str], None]
DetailsCallback = Callable[[dict[str, Any], str], None]
ProgressCallback = Callable[[str, int, bool], None]


class ModrinthService:
    """Keeps network and archive work off the QML thread."""

    api_root = "https://api.modrinth.com/v2"

    def __init__(
        self,
        config_directory: Path,
        on_search: SearchCallback,
        on_install: InstallCallback,
        on_details: DetailsCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._config_directory = config_directory
        self._on_search = on_search
        self._on_install = on_install
        self._on_details = on_details
        self._on_progress = on_progress
        self._lock = Lock()
        self._searching = False
        self._installing = False

    def _emit_progress(self, label: str, percent: int, active: bool) -> None:
        if self._on_progress:
            self._on_progress(label, max(0, min(100, int(percent))), active)

    def details(self, project: dict[str, Any]) -> None:
        if not self._on_details:
            return
        Thread(target=self._details_worker, args=(dict(project),), daemon=True).start()

    def _details_worker(self, project: dict[str, Any]) -> None:
        try:
            project_id = str(project.get("id") or project.get("slug") or "")
            if not project_id:
                raise RuntimeError("This Modrinth project has no identifier.")
            response = requests.get(
                f"{self.api_root}/project/{project_id}",
                headers={"User-Agent": "NewLauncher/2.8 (Modrinth browser)"},
                timeout=(8, 30),
            )
            response.raise_for_status()
            record = response.json()
            if not isinstance(record, dict):
                raise RuntimeError("Modrinth returned invalid project details.")
            complete = {
                **project,
                "title": str(record.get("title") or project.get("title") or "Untitled project"),
                "description": str(record.get("description") or project.get("description") or ""),
                "body": str(record.get("body") or ""),
                "author": str(record.get("team") or project.get("author") or "Unknown author"),
                "iconUrl": str(record.get("icon_url") or project.get("iconUrl") or ""),
                "slug": str(record.get("slug") or project.get("slug") or ""),
            }
            self._on_details(complete, "Project details loaded")
        except (requests.RequestException, RuntimeError, ValueError) as error:
            self._on_details(project, f"Could not load project details: {error}")

    def search(self, query: str, project_type: str, game_version: str, loader: str) -> bool:
        with self._lock:
            if self._searching:
                return False
            self._searching = True
        Thread(target=self._search_worker, args=(query, project_type, game_version, loader), daemon=True).start()
        return True

    def _search_worker(self, query: str, project_type: str, game_version: str, loader: str) -> None:
        try:
            kind = {"mods": "mod", "textures": "resourcepack", "shaders": "shader", "modpacks": "modpack"}.get(project_type, "mod")
            facets = [[f"project_type:{kind}"]]
            if game_version and game_version not in {"latest-release", "latest-snapshot"}:
                facets.append([f"versions:{game_version}"])
            if kind == "mod" and loader.lower() in {"fabric", "forge", "neoforge", "quilt"}:
                facets.append([f"categories:{loader.lower()}"])
            response = requests.get(
                f"{self.api_root}/search",
                params={"query": query.strip(), "limit": 30, "index": "relevance", "facets": json.dumps(facets)},
                headers={"User-Agent": "NewLauncher/2.8 (Modrinth browser)"},
                timeout=(8, 30),
            )
            response.raise_for_status()
            payload = response.json()
            results = []
            for hit in payload.get("hits", []):
                if not isinstance(hit, dict):
                    continue
                results.append(
                    {
                        "id": str(hit.get("project_id") or ""),
                        "slug": str(hit.get("slug") or ""),
                        "title": str(hit.get("title") or "Untitled project"),
                        "description": str(hit.get("description") or ""),
                        "author": str(hit.get("author") or "Unknown author"),
                        "downloads": int(hit.get("downloads") or 0),
                        "iconUrl": str(hit.get("icon_url") or ""),
                        "projectType": kind,
                    }
                )
            self._on_search(results, f"{len(results)} {project_type} found")
        except (requests.RequestException, ValueError) as error:
            self._on_search([], f"Modrinth search failed: {error}")
        finally:
            with self._lock:
                self._searching = False

    def install(
        self,
        project: dict[str, Any],
        project_type: str,
        game_version: str,
        loader: str,
        minecraft_directory: Path,
        mods_directory: Path,
    ) -> bool:
        with self._lock:
            if self._installing:
                return False
            self._installing = True
        Thread(
            target=self._install_worker,
            args=(dict(project), project_type, game_version, loader, minecraft_directory, mods_directory),
            daemon=True,
        ).start()
        return True

    @staticmethod
    def _primary_file(version: dict[str, Any], suffix: str | None = None) -> dict[str, Any]:
        files = [item for item in version.get("files", []) if isinstance(item, dict) and item.get("url")]
        if suffix:
            files = [item for item in files if str(item.get("filename") or "").lower().endswith(suffix)]
        if not files:
            raise RuntimeError("No compatible downloadable file was found.")
        return next((item for item in files if item.get("primary")), files[0])

    def _versions(self, project_id: str, game_version: str, loader: str, project_type: str) -> list[dict[str, Any]]:
        params: list[tuple[str, str]] = []
        if game_version and game_version not in {"latest-release", "latest-snapshot"}:
            params.append(("game_versions", json.dumps([game_version])))
        if project_type == "mod" and loader.lower() in {"fabric", "forge", "neoforge", "quilt"}:
            params.append(("loaders", json.dumps([loader.lower()])))
        response = requests.get(
            f"{self.api_root}/project/{project_id}/version",
            params=params,
            headers={"User-Agent": "NewLauncher/2.8 (Modrinth browser)"},
            timeout=(8, 30),
        )
        response.raise_for_status()
        records = response.json()
        if not isinstance(records, list):
            raise RuntimeError("Modrinth returned an invalid version list.")
        return [item for item in records if isinstance(item, dict)]

    def _download(self, url: str, destination: Path, expected_sha1: str = "", label: str = "") -> None:
        temporary = destination.with_suffix(destination.suffix + ".download")
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1()
        try:
            with requests.get(url, stream=True, timeout=(8, 90)) as response:
                response.raise_for_status()
                total = max(0, int(response.headers.get("content-length") or 0))
                received = 0
                progress_label = label or f"Downloading {destination.name}"
                self._emit_progress(progress_label, 0, True)
                with temporary.open("wb") as target:
                    for chunk in response.iter_content(128 * 1024):
                        if chunk:
                            target.write(chunk)
                            digest.update(chunk)
                            received += len(chunk)
                            if total:
                                self._emit_progress(progress_label, received * 100 // total, True)
            if expected_sha1 and digest.hexdigest().lower() != expected_sha1.lower():
                raise RuntimeError("The downloaded file did not match Modrinth's SHA-1 hash.")
            os.replace(temporary, destination)
            self._emit_progress(progress_label, 100, True)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def _install_worker(
        self,
        project: dict[str, Any],
        project_type: str,
        game_version: str,
        loader: str,
        minecraft_directory: Path,
        mods_directory: Path,
    ) -> None:
        try:
            project_id = str(project.get("id") or project.get("slug") or "")
            kind = {"mods": "mod", "textures": "resourcepack", "shaders": "shader", "modpacks": "modpack"}.get(project_type, "mod")
            if not project_id:
                raise RuntimeError("This Modrinth project has no identifier.")
            versions = self._versions(project_id, game_version, loader, kind)
            if not versions:
                raise RuntimeError("No compatible Modrinth version is available for this installation.")
            if kind == "modpack":
                pack, installation = self._install_modpack(project, versions)
                self._on_install(pack, installation, f"Installed Modrinth modpack {pack['name']}")
                self._emit_progress(f"Installed {pack['name']}", 100, False)
                return
            file = self._primary_file(versions[0])
            directory = mods_directory if kind == "mod" else minecraft_directory / ("shaderpacks" if kind == "shader" else "resourcepacks")
            destination = directory / str(file.get("filename") or f"{project_id}.jar")
            self._download(str(file["url"]), destination, str((file.get("hashes") or {}).get("sha1") or ""), f"Downloading {str(project.get('title') or project_id)}")
            self._on_install(None, None, f"Installed {str(project.get('title') or project_id)}")
            self._emit_progress(f"Installed {str(project.get('title') or project_id)}", 100, False)
        except (requests.RequestException, OSError, RuntimeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
            self._on_install(None, None, f"Modrinth install failed: {error}")
            self._emit_progress("Modrinth download failed", 0, False)
        finally:
            with self._lock:
                self._installing = False

    def _install_modpack(self, project: dict[str, Any], versions: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        version = next((item for item in versions if any(str(file.get("filename") or "").endswith(".mrpack") for file in item.get("files", []) if isinstance(file, dict))), None)
        if not version:
            raise RuntimeError("No installable .mrpack release was found.")
        file = self._primary_file(version, ".mrpack")
        with tempfile.TemporaryDirectory(prefix="nlc-mrpack-") as temporary_root:
            archive_path = Path(temporary_root) / "pack.mrpack"
            self._download(str(file["url"]), archive_path, str((file.get("hashes") or {}).get("sha1") or ""))
            with zipfile.ZipFile(archive_path) as archive:
                index = json.loads(archive.read("modrinth.index.json").decode("utf-8"))
                dependencies = index.get("dependencies", {}) if isinstance(index, dict) else {}
                minecraft_version = str(dependencies.get("minecraft") or "")
                if not minecraft_version:
                    raise RuntimeError("This modpack does not specify a Minecraft version.")
                loader = "Fabric" if "fabric-loader" in dependencies else ("Forge" if "forge" in dependencies else "Vanilla")
                pack_id = uuid.uuid4().hex
                root = (self._config_directory / "modpacks").resolve()
                root.mkdir(parents=True, exist_ok=True)
                staging, final = root / f".modrinth-{pack_id}", root / pack_id
                staging.mkdir()
                try:
                    for item in index.get("files", []):
                        if not isinstance(item, dict) or str(item.get("env", {}).get("client") or "required") == "unsupported":
                            continue
                        relative = PurePosixPath(str(item.get("path") or ""))
                        if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
                            raise RuntimeError("The modpack contains an unsafe file path.")
                        target = (staging / Path(*relative.parts)).resolve()
                        if staging not in target.parents:
                            raise RuntimeError("The modpack contains an unsafe file path.")
                        downloads = item.get("downloads", [])
                        if not isinstance(downloads, list) or not downloads:
                            raise RuntimeError(f"Modrinth did not provide a download for {relative.name}.")
                        self._download(str(downloads[0]), target, str((item.get("hashes") or {}).get("sha1") or ""))
                    for member in archive.infolist():
                        path = PurePosixPath(member.filename)
                        if member.is_dir() or not path.parts or path.parts[0] != "overrides" or any(part in {"", ".", ".."} for part in path.parts):
                            continue
                        target = (staging / Path(*path.parts[1:])).resolve()
                        if staging not in target.parents:
                            raise RuntimeError("The modpack contains an unsafe override path.")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as source, target.open("wb") as destination:
                            shutil.copyfileobj(source, destination)
                    os.replace(staging, final)
                except Exception:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise
        name = str(project.get("title") or "Modrinth modpack")
        installation_id = uuid.uuid4().hex
        pack = {
            "id": pack_id,
            "name": name,
            "loader": loader,
            "mc_version": minecraft_version,
            "version_name": str(version.get("version_number") or version.get("name") or ""),
            "source": "modrinth",
            "linked_installation_id": installation_id,
            "modrinth_projects": [str(project.get("id") or project.get("slug") or "").lower()],
        }
        installation = {"id": installation_id, "name": name, "version": minecraft_version, "loader": loader}
        return pack, installation
