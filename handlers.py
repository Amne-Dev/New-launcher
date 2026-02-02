import http.server
import socketserver
import threading
import json
import uuid
import base64
import time
import os
import urllib.parse
from typing import Any

class MicrosoftLoginHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Suppress logs

    def do_GET(self):
        # Handle the callback: /?code=...&state=...
        if '?' in self.path:
            query = self.path.split('?', 1)[1]
            params = urllib.parse.parse_qs(query)
            
            if 'code' in params:
                self.server.auth_code = params['code'][0] # type: ignore
                self.server.auth_state = params.get('state', [None])[0] # type: ignore
                
                # Success Page
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                html = """
                <html>
                <head><title>Login Successful</title></head>
                <body style="font-family: 'Segoe UI', sans-serif; text-align: center; padding-top: 50px; background-color: #212121; color: white;">
                    <h1>Login Successful!</h1>
                    <p>You can verify the login in the launcher.</p>
                    <p>This window will close automatically.</p>
                    <script>setTimeout(function(){window.close()}, 2000);</script>
                </body>
                </html>
                """
                self.wfile.write(html.encode("utf-8"))
                return
            
            if 'error' in params:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Login failed or cancelled.")
                return

        self.send_error(404)

class LocalSkinHandler(http.server.BaseHTTPRequestHandler):
    """
    Minimal Yggdrasil-compatible Skin Server for Offline Mode.
    Serves the locally selected skin to the game via authlib-injector.
    """
    skin_path = None
    skin_model = "classic"
    player_name = "Player"
    player_uuid = None

    def log_message(self, format, *args):
        pass # Suppress server logs

    def do_POST(self):
        # Handle Auth/Validation requests blindly to satisfy injector
        if self.path.startswith("/authserver/") or self.path == "/authenticate":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')
            return
            
        elif self.path == "/api/profiles/minecraft":
            # Bulk profile lookup
            p_id = self.player_uuid.replace("-", "") if self.player_uuid else uuid.uuid4().hex
            resp = [{
                "id": p_id,
                "name": self.player_name
            }]
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        self.send_error(404)

    def do_GET(self):
        # Root check
        if self.path == '/':
            self.send_response(200)
            self.send_header('X-Authlib-Injector-API-Location', '/')
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            resp = {
                "meta": {
                    "serverName": "Local Skin Server", 
                    "implementationName": "NLC-Local", 
                    "implementationVersion": "1.0.0"
                },
                "skinDomains": ["localhost", "127.0.0.1"],
                "signaturePublicKeys": [] 
            }
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        # Profile request: /sessionserver/session/minecraft/profile/<uuid>
        if self.path.startswith("/sessionserver/session/minecraft/profile/"):
            requested_uuid = self.path.split("/")[-1].split("?")[0]
            # Verify UUID matches (or just serve anyway)
            
            # Read skin file
            if not self.skin_path or not os.path.exists(self.skin_path):
                # Fallback to empty profile to prevent crash
                p_id = requested_uuid or (self.player_uuid.replace("-", "") if self.player_uuid else "")
                resp = {
                    "id": p_id,
                    "name": self.player_name,
                    "properties": []
                }
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode('utf-8'))
                return

            try:
                # We don't read the file here, we just verify it exists
                pass 
            except:
                self.send_error(500)
                return

            # Construct Texture Payload
            texture_model = "default" 
            if hasattr(self, 'skin_model') and self.skin_model == 'slim':
                texture_model = "slim"
            
            host = self.headers.get('Host')
            texture_url = f"http://{host}/textures/skin.png"

            skin_data: dict[str, Any] = {
                "url": texture_url
            }
            if texture_model == "slim":
                skin_data["metadata"] = {"model": "slim"}

            textures = {
                "timestamp": int(time.time() * 1000),
                "profileId": requested_uuid,
                "profileName": self.player_name,
                "textures": {
                    "SKIN": skin_data
                }
            }
            
            json_textures = json.dumps(textures)
            base64_textures = base64.b64encode(json_textures.encode('utf-8')).decode('utf-8')
            
            response = {
                "id": requested_uuid,
                "name": self.player_name,
                "properties": [
                    {
                        "name": "textures",
                        "value": base64_textures
                    }
                ]
            }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return

        # Texture Request
        if self.path == "/textures/skin.png":
             if not self.skin_path or not os.path.exists(self.skin_path):
                self.send_error(404)
                return
             try:
                with open(self.skin_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-type', 'image/png')
                self.end_headers()
                self.wfile.write(data)
             except: self.send_error(500)
             return

        self.send_error(404)

class LocalSkinServer:
    def __init__(self, port=0):
        self.handler = LocalSkinHandler
        # Use ThreadingTCPServer to avoid blocking constraints
        self.httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), self.handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self, skin_path, player_name, player_uuid, skin_model="classic"):
        self.handler.skin_path = skin_path
        self.handler.player_name = player_name
        self.handler.player_uuid = player_uuid
        self.handler.skin_model = skin_model
        self.thread.start()
        print(f"Local Skin Server started on port {self.port}")
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
