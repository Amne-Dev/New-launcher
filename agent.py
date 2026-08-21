import sys
import time
import json
import os
import base64
import importlib.util
import requests
import urllib.parse
import hashlib
import uuid
import traceback
from datetime import datetime

# Global session for connection pooling
_session = None
ADDON_MANIFEST = "addon.json"


def get_launcher_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_config_dir():
    if len(sys.argv) > 1 and sys.argv[1]:
        return sys.argv[1]
    return get_launcher_dir()


def get_third_party_addons_dir():
    addons_dir = os.path.join(get_config_dir(), "addons")
    os.makedirs(addons_dir, exist_ok=True)
    return addons_dir

def get_session():
    """Get or create requests session with connection pooling."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": "NewLauncher-Agent"})
    return _session

def get_file_sha(filepath):
    """Calculate SHA hash for file comparison."""
    if not os.path.exists(filepath):
        return None
    try:
        sha1 = hashlib.sha1()
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                sha1.update(data)
        return sha1.hexdigest()
    except Exception:
        return None


def addon_normalize_config(addons_config):
    normalized = dict(addons_config) if isinstance(addons_config, dict) else {}
    normalized.setdefault("p3_reload_menu", False)
    normalized["streamer_mode_enabled"] = bool(normalized.get("streamer_mode_enabled", False))
    normalized["gh_sync_enabled"] = bool(normalized.get("gh_sync_enabled", False))
    normalized["gh_repo"] = str(normalized.get("gh_repo", "") or "")
    normalized["gh_token"] = str(normalized.get("gh_token", "") or "")
    normalized["curseforge_api_key"] = str(normalized.get("curseforge_api_key", "") or "")

    if not isinstance(normalized.get("playtime_tracker"), dict):
        normalized["playtime_tracker"] = {}

    saved_servers = normalized.get("saved_servers", [])
    if not isinstance(saved_servers, list):
        saved_servers = []

    normalized_servers = []
    for server in saved_servers:
        if not isinstance(server, dict):
            continue
        address = str(server.get("address", "")).strip()
        if not address:
            continue
        port = server.get("port", 25565)
        try:
            port = int(port)
        except Exception:
            port = 25565
        normalized_servers.append({
            "id": str(server.get("id") or uuid.uuid4()),
            "name": str(server.get("name") or address),
            "address": address,
            "port": port,
        })
    normalized["saved_servers"] = normalized_servers
    return normalized


def addon_set_streamer_mode(addons_config, enabled):
    normalized = addon_normalize_config(addons_config)
    normalized["streamer_mode_enabled"] = bool(enabled)
    return normalized


def addon_reset_playtime_tracker(addons_config):
    normalized = addon_normalize_config(addons_config)
    normalized["playtime_tracker"] = {}
    return normalized


def addon_record_play_session(addons_config, inst_id, session_seconds, server_address=None, server_port=None):
    normalized = addon_normalize_config(addons_config)
    inst_id = str(inst_id or "").strip()
    if not inst_id:
        return normalized

    tracker = normalized.setdefault("playtime_tracker", {})
    stats = tracker.setdefault(inst_id, {})
    stats["seconds"] = int(stats.get("seconds", 0) or 0) + max(0, int(session_seconds))
    stats["launches"] = int(stats.get("launches", 0) or 0) + 1
    stats["last_session_seconds"] = max(0, int(session_seconds))
    stats["last_played_at"] = datetime.now().isoformat()

    if server_address:
        last_server = str(server_address)
        if server_port:
            last_server = f"{last_server}:{server_port}"
        stats["last_server"] = last_server

    return normalized


def addon_add_saved_server(addons_config, name, address, port):
    normalized = addon_normalize_config(addons_config)
    address = str(address or "").strip()
    port = str(port or "25565").strip()
    name = str(name or "").strip()

    if not address:
        raise ValueError("Enter a server address first.")

    if ":" in address and address.count(":") == 1:
        host_part, maybe_port = address.rsplit(":", 1)
        if maybe_port.isdigit():
            address = host_part
            if not port or port == "25565":
                port = maybe_port

    if not port:
        port = "25565"
    if not port.isdigit():
        raise ValueError("Server port must be a number.")

    normalized.setdefault("saved_servers", []).append({
        "id": str(uuid.uuid4()),
        "name": name or address,
        "address": address,
        "port": int(port),
    })
    return normalized


def addon_remove_saved_server(addons_config, server_id):
    normalized = addon_normalize_config(addons_config)
    normalized["saved_servers"] = [
        server for server in normalized.get("saved_servers", [])
        if str(server.get("id")) != str(server_id)
    ]
    return normalized


def addon_list_screenshot_files(minecraft_dir):
    screenshots_dir = os.path.join(str(minecraft_dir), "screenshots")
    items = []
    if os.path.isdir(screenshots_dir):
        for entry in os.listdir(screenshots_dir):
            path = os.path.join(screenshots_dir, entry)
            if os.path.isfile(path) and os.path.splitext(entry)[1].lower() in {".png", ".jpg", ".jpeg"}:
                items.append(path)
        items.sort(key=lambda item: os.path.getmtime(item), reverse=True)
    return {"dir": screenshots_dir, "items": items}


def addon_delete_screenshot(path, minecraft_dir=None):
    target_path = os.path.abspath(str(path))
    if minecraft_dir:
        screenshots_dir = os.path.realpath(os.path.join(str(minecraft_dir), "screenshots"))
        resolved_target = os.path.realpath(target_path)
        if os.path.commonpath((screenshots_dir, resolved_target)) != screenshots_dir:
            raise ValueError("Screenshot path is outside the configured screenshots folder.")
    if not os.path.exists(target_path):
        raise FileNotFoundError(target_path)
    if os.path.splitext(target_path)[1].lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("Only screenshot image files can be deleted.")
    os.remove(target_path)
    return {"deleted": target_path}


def _sanitize_identifier(value):
    cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(value or "").strip())
    return cleaned.strip("_") or "addon"


def _normalize_addon_input(input_data, index):
    if not isinstance(input_data, dict):
        return None

    input_id = str(input_data.get("id") or f"input_{index + 1}").strip()
    if not input_id:
        return None

    input_type = str(input_data.get("type") or "text").strip().lower()
    if input_type not in {"text", "number", "checkbox", "password"}:
        input_type = "text"

    normalized = {
        "id": input_id,
        "label": str(input_data.get("label") or input_id.replace("_", " ").title()),
        "type": input_type,
        "default": input_data.get("default", False if input_type == "checkbox" else ""),
        "placeholder": str(input_data.get("placeholder") or ""),
    }
    return normalized


def _normalize_addon_action(action_data, index):
    if not isinstance(action_data, dict):
        return None

    action_id = str(action_data.get("id") or f"action_{index + 1}").strip()
    if not action_id:
        return None

    style = str(action_data.get("style") or "secondary").strip().lower()
    if style not in {"primary", "secondary", "danger", "text"}:
        style = "secondary"

    inputs = []
    for input_index, input_data in enumerate(action_data.get("inputs", []) or []):
        normalized_input = _normalize_addon_input(input_data, input_index)
        if normalized_input:
            inputs.append(normalized_input)

    return {
        "id": action_id,
        "label": str(action_data.get("label") or action_id.replace("_", " ").title()),
        "description": str(action_data.get("description") or ""),
        "style": style,
        "inputs": inputs,
    }


def _normalize_addon_manifest(raw_manifest, addon_dir, folder_name):
    manifest = raw_manifest if isinstance(raw_manifest, dict) else {}
    addon_id = str(manifest.get("id") or folder_name).strip() or folder_name
    entrypoint = str(manifest.get("entrypoint") or "main.py").strip() or "main.py"

    actions = []
    for index, action_data in enumerate(manifest.get("actions", []) or []):
        normalized_action = _normalize_addon_action(action_data, index)
        if normalized_action:
            actions.append(normalized_action)

    return {
        "id": addon_id,
        "name": str(manifest.get("name") or folder_name.replace("_", " ").title()),
        "version": str(manifest.get("version") or "1.0.0"),
        "author": str(manifest.get("author") or "Unknown"),
        "description": str(manifest.get("description") or "No description provided."),
        "entrypoint": entrypoint,
        "actions": actions,
        "folder_name": folder_name,
        "addon_dir": addon_dir,
        "entrypoint_path": os.path.join(addon_dir, entrypoint),
    }


def _build_addon_context(addon_record, payload=None):
    addon_dir = addon_record["addon_dir"]
    data_dir = os.path.join(addon_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return {
        "addon_id": addon_record["id"],
        "addon_name": addon_record["name"],
        "addon_dir": addon_dir,
        "data_dir": data_dir,
        "addons_dir": get_third_party_addons_dir(),
        "config_dir": get_config_dir(),
        "launcher_dir": get_launcher_dir(),
        "minecraft_dir": None if payload is None else payload.get("minecraft_dir"),
    }


def _load_addon_module(addon_record):
    entrypoint_path = addon_record.get("entrypoint_path")
    if not entrypoint_path or not os.path.isfile(entrypoint_path):
        return None, f"Missing addon entrypoint: {addon_record.get('entrypoint', 'main.py')}"

    module_name = f"nlc_addon_{_sanitize_identifier(addon_record.get('id'))}_{int(time.time() * 1000)}"
    spec = importlib.util.spec_from_file_location(module_name, entrypoint_path)
    if spec is None or spec.loader is None:
        return None, f"Could not load addon module for {addon_record.get('id')}"

    module = importlib.util.module_from_spec(spec)
    old_sys_path = list(sys.path)
    try:
        sys.path.insert(0, addon_record["addon_dir"])
        spec.loader.exec_module(module)
        return module, None
    except Exception as exc:
        return None, f"{exc}\n{traceback.format_exc()}"
    finally:
        sys.path[:] = old_sys_path


def _merge_addon_registration(addon_record, registration):
    if not isinstance(registration, dict):
        return addon_record

    merged = dict(addon_record)
    for key in ("name", "version", "author", "description"):
        if key in registration:
            merged[key] = str(registration.get(key) or merged[key])

    if "actions" in registration:
        actions = []
        for index, action_data in enumerate(registration.get("actions", []) or []):
            normalized_action = _normalize_addon_action(action_data, index)
            if normalized_action:
                actions.append(normalized_action)
        merged["actions"] = actions

    return merged


def discover_third_party_addons(payload=None):
    addons = []
    addons_dir = get_third_party_addons_dir()

    try:
        folder_names = sorted(os.listdir(addons_dir))
    except Exception:
        folder_names = []

    for folder_name in folder_names:
        addon_dir = os.path.join(addons_dir, folder_name)
        if not os.path.isdir(addon_dir):
            continue

        manifest_path = os.path.join(addon_dir, ADDON_MANIFEST)
        if not os.path.isfile(manifest_path):
            continue

        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                raw_manifest = json.load(handle)
            addon_record = _normalize_addon_manifest(raw_manifest, addon_dir, folder_name)

            module, load_error = _load_addon_module(addon_record)
            addon_record["load_error"] = None
            if load_error:
                addon_record["load_error"] = load_error
            elif hasattr(module, "register"):
                try:
                    registration = module.register(_build_addon_context(addon_record, payload))  # type: ignore[attr-defined]
                    addon_record = _merge_addon_registration(addon_record, registration)
                except Exception as exc:
                    addon_record["load_error"] = f"{exc}\n{traceback.format_exc()}"

            addons.append(addon_record)
        except Exception as exc:
            addons.append({
                "id": folder_name,
                "name": folder_name.replace("_", " ").title(),
                "version": "0.0.0",
                "author": "Unknown",
                "description": "Failed to load addon manifest.",
                "entrypoint": "main.py",
                "actions": [],
                "folder_name": folder_name,
                "addon_dir": addon_dir,
                "entrypoint_path": os.path.join(addon_dir, "main.py"),
                "load_error": f"{exc}\n{traceback.format_exc()}",
            })

    return {"addons_dir": addons_dir, "addons": addons}


def _find_addon_record(addon_id, payload=None):
    listing = discover_third_party_addons(payload)
    for addon_record in listing.get("addons", []):
        if str(addon_record.get("id")) == str(addon_id):
            return addon_record, listing
    return None, listing


def run_third_party_addon_action(addon_id, action_id, payload=None):
    addon_record, listing = _find_addon_record(addon_id, payload)
    if addon_record is None:
        return {
            "status": "error",
            "msg": f"Addon '{addon_id}' was not found in {listing.get('addons_dir')}",
        }

    if addon_record.get("load_error"):
        return {
            "status": "error",
            "msg": f"Addon '{addon_record.get('name')}' failed to load.\n{addon_record.get('load_error')}",
        }

    module, load_error = _load_addon_module(addon_record)
    if load_error:
        return {
            "status": "error",
            "msg": f"Failed to load addon '{addon_record.get('name')}'.\n{load_error}",
        }

    context = _build_addon_context(addon_record, payload)
    inputs = {}
    if isinstance(payload, dict):
        raw_inputs = payload.get("inputs", {})
        if isinstance(raw_inputs, dict):
            inputs = raw_inputs

    try:
        result = None
        if hasattr(module, "handle_action"):
            result = module.handle_action(action_id, inputs, context)  # type: ignore[attr-defined]
        else:
            action_func_name = f"action_{_sanitize_identifier(action_id)}"
            if hasattr(module, action_func_name):
                result = getattr(module, action_func_name)(inputs, context)
            else:
                return {
                    "status": "error",
                    "msg": f"Addon '{addon_record.get('name')}' does not expose action '{action_id}'.",
                }

        if result is None:
            return {"status": "success", "msg": f"{addon_record.get('name')} finished successfully."}
        if isinstance(result, dict):
            result.setdefault("status", "success")
            return result
        return {"status": "success", "msg": str(result)}
    except Exception as exc:
        return {
            "status": "error",
            "msg": f"{exc}\n{traceback.format_exc()}",
        }

def handle_gh_skin_sync(payload):
    repo = payload.get("repo")
    token = payload.get("token")
    username = payload.get("username")
    skin_path = payload.get("skin_path")
    do_upload = payload.get("upload", False)
    do_download = payload.get("download", True)
    
    if not repo or not token or not username:
        return {"status": "error", "msg": "Missing configuration"}

    session = get_session()
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    if len(sys.argv) > 1:
        headers["X-Agent-Base-Dir"] = sys.argv[1]
        skins_cache_dir = os.path.join(sys.argv[1], "skins_cache")
    else:
        skins_cache_dir = "skins_cache"

    if not os.path.exists(skins_cache_dir):
        os.makedirs(skins_cache_dir)
    
    file_name = f"skins/{username}.png"
    api_url = f"https://api.github.com/repos/{repo}/contents/{file_name}"
    base_url = f"https://api.github.com/repos/{repo}/contents/skins"

    try:
        # 1. Upload Current Skin if requested
        if do_upload and skin_path and os.path.exists(skin_path):
            # Validate file size (max 1MB for skins)
            file_size = os.path.getsize(skin_path)
            if file_size > 1048576:  # 1MB
                return {"status": "error", "msg": "Skin file too large (max 1MB)"}
            
            with open(skin_path, "rb") as f:
                content = base64.b64encode(f.read()).decode("utf-8")
            
            # Check if exists to get SHA
            sha = None
            try:
                r_check = session.get(api_url, headers=headers, timeout=10)
                if r_check.status_code == 200:
                    sha = r_check.json().get("sha")
            except requests.RequestException:
                pass  # File might not exist yet
            
            data = {
                "message": f"Update skin for {username}",
                "content": content,
                "branch": "main"
            }
            if sha:
                data["sha"] = sha
                
            r_put = session.put(api_url, headers=headers, json=data, timeout=30)
            if r_put.status_code not in [200, 201]:
                return {"status": "error", "msg": f"Upload failed: {r_put.status_code} {r_put.text}"}

        # 2. Download Friends' Skins
        synced_count = 0
        skipped_count = 0
        if do_download:
            try:
                r_list = session.get(base_url, headers=headers, timeout=15)
                if r_list.status_code == 200:
                    items = r_list.json()
                    if isinstance(items, list):
                        for item in items:
                            name = item.get("name")
                            download_url = item.get("download_url")
                            remote_sha = item.get("sha")  # GitHub provides SHA for files
                            
                            if name and download_url and name.endswith(".png"):
                                local_file = os.path.join(skins_cache_dir, name)
                                
                                # Optimization: Check if file already exists with same SHA
                                if os.path.exists(local_file) and remote_sha:
                                    local_sha = get_file_sha(local_file)
                                    if local_sha and local_sha == remote_sha:
                                        skipped_count += 1
                                        continue  # Skip download, file is identical
                                
                                # Download file
                                try:
                                    r_img = session.get(download_url, timeout=15)
                                    if r_img.status_code == 200:
                                        # Validate it's actually a PNG
                                        if r_img.content[:8] == b'\x89PNG\r\n\x1a\n':
                                            with open(local_file, "wb") as f:
                                                f.write(r_img.content)
                                            synced_count += 1
                                except requests.RequestException:
                                    continue  # Skip failed downloads
            except requests.RequestException as e:
                return {"status": "error", "msg": f"Download failed: {str(e)}"}

        return {"status": "success", "msg": f"Skin sync complete. Uploaded: {do_upload}, Downloaded: {synced_count}, Skipped: {skipped_count}"}

    except Exception as e:
        return {"status": "error", "msg": str(e)}

def handle_search_mods(payload):
    """Search mods on Modrinth API with proper error handling and timeout."""
    try:
        query = payload.get("query")
        limit = payload.get("limit", 20)
        offset = payload.get("offset", 0)
        facets = payload.get("facets", [])
        
        # Build query parameters
        params = f"limit={limit}&offset={offset}"
        if query:
            params += f"&query={urllib.parse.quote(query)}"
        else:
            params += "&index=downloads"

        if facets:
             facet_str = ""
             for f in facets:
                 facet_str += f',["{f}"]'
             facet_str = facet_str.lstrip(',')
             enc = urllib.parse.quote(f'[{facet_str}]')
             params += f'&facets={enc}'

        url = f"https://api.modrinth.com/v2/search?{params}"
        headers = {"User-Agent": "AmneDev/NewLauncher/1.8.2"}
        
        session = get_session()
        response = session.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return {"status": "success", "data": response.json()}
        else:
            return {"status": "error", "code": response.status_code, "msg": response.text}
            
    except requests.Timeout:
        return {"status": "error", "msg": "Request timed out"}
    except requests.RequestException as e:
        return {"status": "error", "msg": f"Network error: {str(e)}"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


def handle_addons_normalize(payload):
    return {"status": "success", "data": addon_normalize_config(payload.get("addons", {}))}


def handle_addons_set_streamer_mode(payload):
    return {
        "status": "success",
        "data": addon_set_streamer_mode(payload.get("addons", {}), payload.get("enabled", False)),
    }


def handle_addons_reset_playtime(payload):
    return {"status": "success", "data": addon_reset_playtime_tracker(payload.get("addons", {}))}


def handle_addons_record_play_session(payload):
    return {
        "status": "success",
        "data": addon_record_play_session(
            payload.get("addons", {}),
            payload.get("inst_id"),
            payload.get("session_seconds", 0),
            server_address=payload.get("server_address"),
            server_port=payload.get("server_port"),
        ),
    }


def handle_addons_add_saved_server(payload):
    try:
        return {
            "status": "success",
            "data": addon_add_saved_server(
                payload.get("addons", {}),
                payload.get("name"),
                payload.get("address"),
                payload.get("port"),
            ),
        }
    except Exception as e:
        return {"status": "error", "msg": str(e)}


def handle_addons_remove_saved_server(payload):
    return {
        "status": "success",
        "data": addon_remove_saved_server(payload.get("addons", {}), payload.get("server_id")),
    }


def handle_addons_list_screenshots(payload):
    return {"status": "success", "data": addon_list_screenshot_files(payload.get("minecraft_dir", ""))}


def handle_addons_delete_screenshot(payload):
    try:
        return {"status": "success", "data": addon_delete_screenshot(payload.get("path", ""), payload.get("minecraft_dir"))}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


def handle_list_third_party_addons(payload):
    return {"status": "success", "data": discover_third_party_addons(payload)}


def handle_run_third_party_addon_action(payload):
    return run_third_party_addon_action(
        payload.get("addon_id"),
        payload.get("action_id"),
        payload,
    )

def main():
    print("Agent process started.")
    sys.stdout.flush()
    
    while True:
        try:
            # Blocking read from stdin
            line = sys.stdin.readline()
            if not line:
                break # EOF
            
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            req_id = request.get("id")
            action = request.get("action")
            payload = request.get("payload", {})
            
            result = None
            
            if action == "search_mods":
                result = handle_search_mods(payload)
            elif action == "gh_skin_sync":
                result = handle_gh_skin_sync(payload)
            elif action == "addons_normalize":
                result = handle_addons_normalize(payload)
            elif action == "addons_set_streamer_mode":
                result = handle_addons_set_streamer_mode(payload)
            elif action == "addons_reset_playtime":
                result = handle_addons_reset_playtime(payload)
            elif action == "addons_record_play_session":
                result = handle_addons_record_play_session(payload)
            elif action == "addons_add_saved_server":
                result = handle_addons_add_saved_server(payload)
            elif action == "addons_remove_saved_server":
                result = handle_addons_remove_saved_server(payload)
            elif action == "addons_list_screenshots":
                result = handle_addons_list_screenshots(payload)
            elif action == "addons_delete_screenshot":
                result = handle_addons_delete_screenshot(payload)
            elif action == "list_third_party_addons":
                result = handle_list_third_party_addons(payload)
            elif action == "run_third_party_addon_action":
                result = handle_run_third_party_addon_action(payload)
            elif action == "ping":
                result = {"status": "success", "data": "pong"}

            else:
                result = {"status": "error", "msg": "Unknown action"}
            
            # Send response
            response = {"id": req_id, "result": result}
            print(json.dumps(response))
            sys.stdout.flush()
            
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(1)

if __name__ == "__main__":
    main()
