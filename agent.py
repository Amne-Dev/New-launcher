import sys
import time
import json
import os
import base64
import requests
import urllib.parse

def handle_gh_skin_sync(payload):
    repo = payload.get("repo")
    token = payload.get("token")
    username = payload.get("username")
    skin_path = payload.get("skin_path")
    do_upload = payload.get("upload", False)
    do_download = payload.get("download", True)
    
    if not repo or not token or not username:
        return {"status": "error", "msg": "Missing configuration"}

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "NewLauncher-Agent"
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
            with open(skin_path, "rb") as f:
                content = base64.b64encode(f.read()).decode("utf-8")
            
            # Check if exists to get SHA
            sha = None
            r_check = requests.get(api_url, headers=headers)
            if r_check.status_code == 200:
                sha = r_check.json().get("sha")
            
            data = {
                "message": f"Update skin for {username}",
                "content": content,
                "branch": "main" # Assume main
            }
            if sha:
                data["sha"] = sha
                
            r_put = requests.put(api_url, headers=headers, json=data)
            if r_put.status_code not in [200, 201]:
                return {"status": "error", "msg": f"Upload failed: {r_put.status_code} {r_put.text}"}

        # 2. Download Friends' Skins
        synced_count = 0
        if do_download:
            r_list = requests.get(base_url, headers=headers)
            if r_list.status_code == 200:
                items = r_list.json()
                if isinstance(items, list):
                    for item in items:
                        name = item.get("name")
                        download_url = item.get("download_url")
                        
                        if name and download_url and name.endswith(".png"):
                            # Skip our own skin if we just uploaded it (optional, but good for caching)
                            # Actually we might want to download it to ensure we have the 'cloud' version
                            
                            local_file = os.path.join(skins_cache_dir, name)
                            
                            # Simple optimization: If file exists, maybe skip? 
                            # For now, let's just re-download to be safe or check SHA if we tracked it.
                            # We'll just download for now.
                            
                            r_img = requests.get(download_url)
                            if r_img.status_code == 200:
                                with open(local_file, "wb") as f:
                                    f.write(r_img.content)
                                synced_count += 1

        return {"status": "success", "msg": f"Skin sync complete. Uploaded: {do_upload}, Downloaded: {synced_count}"}

    except Exception as e:
        return {"status": "error", "msg": str(e)}

def handle_search_mods(payload):
    try:
        query = payload.get("query")
        limit = payload.get("limit", 20)
        offset = payload.get("offset", 0)
        facets = payload.get("facets", [])
        
        params = f"limit={limit}&offset={offset}"
        if query:
            params += f"&query={query}"
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
        headers = {"User-Agent": "AmneDev/NewLauncher/1.6.4"}
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return {"status": "success", "data": response.json()}
        else:
            return {"status": "error", "code": response.status_code, "msg": response.text}
            
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
