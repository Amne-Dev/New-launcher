"""
nlc.core.instances - Instance directory management, asset link synchronization,
and modpack export engine (.mrpack and .zip).
"""

import json
import logging
import os
import shutil
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SHARED_ASSET_FOLDERS = {
    "share_resourcepacks": "resourcepacks",
    "share_shaderpacks": "shaderpacks",
    "share_worlds": "saves",
    "share_configs": "config",
}


def is_directory_link(path: Path) -> bool:
    """Check if a path is a symlink or Windows directory junction."""
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            import stat
            return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except Exception:
            return False
    return False


def remove_directory_link(link_path: Path) -> None:
    """Safely remove a symlink or junction without deleting target folder contents."""
    if not is_directory_link(link_path):
        return
    try:
        if os.name == "nt" and not link_path.is_symlink():
            # Windows junction directory removal requires os.rmdir without recursion
            os.rmdir(link_path)
        else:
            link_path.unlink()
    except Exception as e:
        logger.warning("Failed to unlink directory %s: %s", link_path, e)


def create_directory_link(target: Path, link: Path) -> bool:
    """
    Create a cross-platform directory link from link -> target.
    Uses POSIX symlinks on Linux/macOS and directory junctions / symlinks on Windows.
    """
    target = target.resolve()
    try:
        if os.name == "nt":
            try:
                # Try directory junction first (doesn't require Windows Developer Mode / Admin privileges)
                import _winapi
                _winapi.CreateJunction(str(target), str(link))
                return True
            except Exception:
                os.symlink(str(target), str(link), target_is_directory=True)
                return True
        else:
            os.symlink(str(target), str(link), target_is_directory=True)
            return True
    except Exception as e:
        logger.warning("Could not create link %s -> %s: %s", link, target, e)
        return False


def link_shared_folder(instance_dir: str, shared_root: str, folder_name: str, enabled: bool) -> None:
    """
    Ensure the instance's subfolder is linked to the shared root or isolated.
    - If enabled: link -> shared_root/folder_name
    - If disabled: ensure an isolated physical directory exists.
    """
    inst_root = Path(instance_dir).resolve()
    shared_base = Path(shared_root).resolve()
    target_dir = shared_base / folder_name
    link_dir = inst_root / folder_name

    inst_root.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    if enabled:
        if is_directory_link(link_dir):
            try:
                # Check if it already points to target_dir
                resolved = link_dir.resolve()
                if resolved == target_dir.resolve():
                    return
            except Exception:
                pass
            remove_directory_link(link_dir)

        if link_dir.exists():
            if link_dir.is_dir():
                # Merge any existing non-duplicate files from instance folder into shared folder
                try:
                    for item in link_dir.iterdir():
                        dest = target_dir / item.name
                        if not dest.exists():
                            if item.is_dir():
                                shutil.copytree(item, dest)
                            else:
                                shutil.copy2(item, dest)
                    shutil.rmtree(link_dir)
                except Exception as e:
                    logger.warning("Error merging instance folder %s before linking: %s", link_dir, e)
                    return
            else:
                try:
                    link_dir.unlink()
                except Exception:
                    return

        create_directory_link(target_dir, link_dir)
    else:
        # Asset sharing disabled: unlink if linked and create independent physical folder
        if is_directory_link(link_dir):
            remove_directory_link(link_dir)
        link_dir.mkdir(parents=True, exist_ok=True)


def sync_instance_assets(instance_dir: str, shared_root: str, settings: Optional[Dict[str, Any]] = None) -> None:
    """
    Sync all shared assets (resourcepacks, shaderpacks, saves, configs) for an instance.
    """
    if settings is None:
        settings = {
            "share_resourcepacks": True,
            "share_shaderpacks": True,
            "share_worlds": False,
            "share_configs": False,
        }

    for setting_key, folder_name in SHARED_ASSET_FOLDERS.items():
        enabled = bool(settings.get(setting_key, False))
        link_shared_folder(instance_dir, shared_root, folder_name, enabled=enabled)


def export_modpack_to_zip(pack_dir: str, pack_meta: Dict[str, Any], target_zip_path: str) -> None:
    """
    Export an instance / modpack directory as a clean .zip archive.
    Omits symlinked shared assets to avoid bundling giant external directories.
    """
    pack_path = Path(pack_dir).resolve()
    target_path = Path(target_zip_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Write metadata
        clean_meta = {
            "name": pack_meta.get("name", "Custom Modpack"),
            "loader": pack_meta.get("loader", "Vanilla"),
            "mc_version": pack_meta.get("mc_version", "1.21.1"),
            "version_name": pack_meta.get("version_name", "1.0.0"),
            "source": pack_meta.get("source", "nlc_export"),
        }
        zf.writestr("modpack.json", json.dumps(clean_meta, indent=2))

        # Bundle files
        for root, dirs, files in os.walk(pack_path, followlinks=False):
            # Exclude symlinks/junctions
            dirs[:] = [d for d in dirs if not is_directory_link(Path(root) / d)]
            for file in files:
                file_path = Path(root) / file
                if not file_path.is_symlink():
                    arcname = file_path.relative_to(pack_path)
                    zf.write(file_path, arcname=str(arcname))


def export_modpack_to_mrpack(pack_dir: str, pack_meta: Dict[str, Any], target_mrpack_path: str) -> None:
    """
    Export an instance / modpack directory as a standard Modrinth .mrpack archive.
    Local mods and configs are packaged into overrides/ according to the Modrinth pack specification.
    """
    pack_path = Path(pack_dir).resolve()
    target_path = Path(target_mrpack_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    name = str(pack_meta.get("name", "Custom Modpack"))
    mc_version = str(pack_meta.get("mc_version", "1.21.1"))
    loader = str(pack_meta.get("loader", "fabric")).lower()
    version_id = str(pack_meta.get("version_id") or uuid.uuid4().hex[:8])

    index_data = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": version_id,
        "name": name,
        "summary": f"Modpack exported from New Launcher (NLC)",
        "files": [],
        "dependencies": {
            "minecraft": mc_version,
            loader: "*"
        }
    }

    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Write modrinth.index.json
        zf.writestr("modrinth.index.json", json.dumps(index_data, indent=2))

        # Pack contents into overrides/
        for root, dirs, files in os.walk(pack_path, followlinks=False):
            dirs[:] = [d for d in dirs if not is_directory_link(Path(root) / d)]
            for file in files:
                file_path = Path(root) / file
                if not file_path.is_symlink():
                    rel = file_path.relative_to(pack_path)
                    arcname = f"overrides/{rel.as_posix()}"
                    zf.write(file_path, arcname=arcname)
