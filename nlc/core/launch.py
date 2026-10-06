"""
nlc.core.launch - Launch command construction and patch helpers for minecraft-launcher-lib
"""

import json
import logging
import os
import zipfile
from typing import Any, Dict, List, Optional
import minecraft_launcher_lib

logger = logging.getLogger(__name__)

def safe_extract_zip(archive_path: str, destination_dir: str):
    """Extract a ZIP archive preventing path traversal."""
    dest_path = os.path.realpath(destination_dir)
    with zipfile.ZipFile(archive_path, "r") as zf:
        for member in zf.infolist():
            is_symlink = ((member.external_attr >> 16) & 0o170000) == 0o120000
            target_path = os.path.realpath(os.path.join(dest_path, member.filename))
            if is_symlink or os.path.commonpath((dest_path, target_path)) != dest_path:
                raise ValueError(f"Unsafe zip archive entry rejected: {member.filename}")
        zf.extractall(dest_path)

def _get_lib_name_without_version(lib: Dict[str, Any]) -> str:
    return ":".join(str(lib.get("name", "")).split(":")[:-1])

def safe_inherit_json(original_data: Dict[str, Any], path: str) -> Dict[str, Any]:
    """Inherit version JSON safely without corrupting library lists."""
    inherit_version = original_data.get("inheritsFrom")
    if not inherit_version:
        return original_data

    parent_json_path = os.path.join(path, "versions", inherit_version, f"{inherit_version}.json")
    with open(parent_json_path, encoding="utf-8") as f:
        new_data = json.load(f)

    original_libs = {}
    for current_lib in original_data.get("libraries", []):
        lib_name = _get_lib_name_without_version(current_lib)
        original_libs[lib_name] = True

    lib_list = list(original_data.get("libraries", []))
    for current_lib in new_data.get("libraries", []):
        lib_name = _get_lib_name_without_version(current_lib)
        if lib_name not in original_libs:
            lib_list.append(current_lib)

    new_data["libraries"] = lib_list

    for key, value in original_data.items():
        if key == "libraries":
            continue
        if isinstance(value, list) and isinstance(new_data.get(key), list):
            new_data[key] = value + new_data[key]
        elif isinstance(value, dict) and isinstance(new_data.get(key), dict):
            target_dict = new_data[key]
            for child_key, child_value in value.items():
                if isinstance(child_value, list):
                    existing = target_dict.get(child_key, [])
                    if not isinstance(existing, list):
                        existing = []
                    target_dict[child_key] = existing + child_value
                else:
                    target_dict[child_key] = child_value
        else:
            new_data[key] = value

    return new_data

def safe_get_minecraft_arguments(data, version_data, path, options, classpath) -> List[str]:
    """Parse launch arguments with protection against malformed rule values."""
    arglist = []
    version_id = version_data.get("id", "<unknown>")

    for entry in data:
        if isinstance(entry, str):
            arglist.append(
                minecraft_launcher_lib.command.replace_arguments(
                    entry, version_data, path, options, classpath
                )
            )
            continue

        if "compatibilityRules" in entry and not minecraft_launcher_lib.command.parse_rule_list(entry["compatibilityRules"], options):
            continue

        if "rules" in entry and not minecraft_launcher_lib.command.parse_rule_list(entry["rules"], options):
            continue

        if "value" not in entry:
            logger.warning("Skipping argument without 'value' for %s: %s", version_id, entry)
            continue

        arg_val = entry.get("value")
        if isinstance(arg_val, str):
            arglist.append(
                minecraft_launcher_lib.command.replace_arguments(
                    arg_val, version_data, path, options, classpath
                )
            )
            continue

        if isinstance(arg_val, list):
            for v in arg_val:
                arglist.append(
                    minecraft_launcher_lib.command.replace_arguments(
                        v, version_data, path, options, classpath
                    )
                )
            continue

        logger.warning("Skipping malformed argument value for %s: %r", version_id, arg_val)

    return arglist

def apply_launcher_lib_patches():
    """Apply safety patches to minecraft_launcher_lib."""
    try:
        minecraft_launcher_lib.command.inherit_json = safe_inherit_json
        minecraft_launcher_lib.command.get_arguments = safe_get_minecraft_arguments
        logger.debug("Patched minecraft_launcher_lib command helpers successfully.")
    except Exception as e:
        logger.exception("Failed to apply launcher lib patches: %s", e)
