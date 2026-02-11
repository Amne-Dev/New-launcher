import sys
import time
import json
import os
import base64
import requests
import urllib.parse
import hashlib

# Global session for connection pooling
_session = None

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
