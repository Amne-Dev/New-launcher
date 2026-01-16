import tkinter as tk
print("Starting launcher...")
from tkinter import ttk, messagebox, filedialog, scrolledtext
import minecraft_launcher_lib
import subprocess
import threading
import os
import sys
import glob
import json
import shutil
import requests
import webbrowser
try:
    from skinpy import Skin, Perspective, BodyPart
except ImportError:
    pass
from PIL import Image, ImageTk
from datetime import datetime
from typing import Any, cast
import time

import hashlib
import http.server
import socketserver
import base64
import uuid

# --- Helper Classes ---

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
            # For authenticate, we need to return a profile
            response = {}
            if "authenticate" in self.path:
                p_id = self.player_uuid.replace("-", "") if self.player_uuid else uuid.uuid4().hex
                response = {
                    "accessToken": "00000000000000000000000000000000",
                    "clientToken": "00000000000000000000000000000000",
                    "availableProfiles": [{
                        "id": p_id, 
                        "name": self.player_name
                    }],
                    "selectedProfile": {
                         "id": p_id,
                         "name": self.player_name
                    },
                    "user": {
                        "id": p_id
                    }
                }
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))
                return
            
            elif "validate" in self.path:
                # 204 No Content is standard for success in validate
                self.send_response(204)
                self.end_headers()
                return

            elif "refresh" in self.path:
                 # Similar to authenticate
                p_id = self.player_uuid.replace("-", "") if self.player_uuid else uuid.uuid4().hex
                response = {
                    "accessToken": "00000000000000000000000000000000",
                    "clientToken": "00000000000000000000000000000000",
                    "selectedProfile": {
                         "id": p_id,
                         "name": self.player_name
                    }
                }
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))
                return

            self.send_response(200) # Fallback for invalidate/signout
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

class ElyByAuth:
    AUTH_URL = "https://authserver.ely.by/auth/authenticate"
    
    @staticmethod
    def authenticate(username, password):
        payload = {
            "agent": {
                "name": "Minecraft",
                "version": 1
            },
            "username": username,
            "password": password,
            "requestUser": True
        }
        try:
            r = requests.post(ElyByAuth.AUTH_URL, json=payload, timeout=10)
            if r.status_code == 200:
                return r.json()
            else:
                return {"error": f"Authentication failed (Status {r.status_code})"}
        except Exception as e:
            return {"error": str(e)}


try:
    from pypresence import Presence # type: ignore
    RPC_AVAILABLE = True
except ImportError:
    RPC_AVAILABLE = False

# Detect resampling constant for compatibility with Pillow versions
try:
    RESAMPLE_NEAREST = Image.Resampling.NEAREST  # Pillow >= 9.1
    FLIP_LEFT_RIGHT = Image.Transpose.FLIP_LEFT_RIGHT
    AFFINE = Image.Transform.AFFINE
except AttributeError:
    RESAMPLE_NEAREST = Image.NEAREST  # type: ignore # Older Pillow
    FLIP_LEFT_RIGHT = Image.FLIP_LEFT_RIGHT # type: ignore
    AFFINE = Image.AFFINE # type: ignore

CURRENT_VERSION = "1.3"

# --- Helpers ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    # PyInstaller creates a temp folder and stores path in _MEIPASS
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)

# --- Color Scheme (Official Launcher Look) ---
COLORS = {
    'sidebar_bg': '#212121',
    'main_bg': '#313233',
    'tab_bar_bg': '#313233',
    'bottom_bar_bg': '#313233',
    'card_bg': '#3A3B3C',
    'play_btn_green': '#2D8F36',
    'play_btn_hover': '#1E6624',
    'text_primary': '#FFFFFF',
    'text_secondary': '#B0B0B0',
    'input_bg': '#48494A',
    'input_border': '#5A5B5C',
    'active_tab_border': '#2D8F36',
    'separator': '#454545',
    'accent_blue': '#3498DB',
    'button_hover': '#2980B9',
    'error_red': '#E74C3C',
    'success_green': '#2ECC71'
}

# --- Helpers ---
def get_minecraft_dir():
    return minecraft_launcher_lib.utils.get_minecraft_directory()

def is_version_installed(version_id):
    minecraft_dir = get_minecraft_dir()
    path = os.path.join(minecraft_dir, "versions", version_id, f"{version_id}.json")
    return os.path.exists(path)

LOADERS = ["Vanilla", "Forge", "Fabric", "BatMod", "LabyMod", "Lunar Client"]
MOD_COMPATIBLE_LOADERS = {"Forge", "Fabric"}
DEFAULT_USERNAME = "Steve"
INSTALL_MARK = "✅ "
DEFAULT_RAM = 4096

def format_version_display(version_id):
    return f"{INSTALL_MARK}{version_id}" if is_version_installed(version_id) else version_id

def normalize_version_text(value):
    if not value:
        return ""
    return value.replace(INSTALL_MARK, "").strip()

class SkinRenderer3D:
    @staticmethod
    def render(skin_path, model="classic", height=360):
        try:
            if not os.path.exists(skin_path): return None
            
            src = Image.open(skin_path).convert("RGBA")
            if src.size[0] != 64: 
                temp = Image.new("RGBA", (64, 64))
                temp.paste(src.crop((0,0,64,32)), (0,0))
                temp.paste(src.crop((0,16,16,32)), (16,48)) # Flip leg
                src = temp

            # Try using skinpy (Library: https://github.com/t-mart/skinpy)
            try:
                if 'skinpy' in sys.modules:
                    skin = Skin.from_image(src) # type: ignore

                    # Handle Slim (Alex) Model
                    if model == "slim":
                        # Recreate arms with width=3 (Standard is 4)
                        # Left Arm (Viewer Left / MC Right Arm)
                        # We shift model_origin x from 0 to 1 so it touches torso (at x=4)
                        l_arm = BodyPart.new( # type: ignore
                            id_="left_arm",
                            skin_image_color=skin.image_color,
                            part_shape=(3, 4, 12),
                            part_model_origin=(1, 2, 12),
                            part_image_origin=(40, 16)
                        )
                        # Right Arm (Viewer Right / MC Left Arm)
                        # Stays at x=12 (Torso ends at 12)
                        r_arm = BodyPart.new( # type: ignore
                            id_="right_arm",
                            skin_image_color=skin.image_color,
                            part_shape=(3, 4, 12),
                            part_model_origin=(12, 2, 12),
                            part_image_origin=(32, 48)
                        )
                        
                        # Create new skin with modified arms
                        skin = Skin( # type: ignore
                            image_color=skin.image_color,
                            head=skin.head,
                            torso=skin.torso,
                            left_arm=l_arm,
                            right_arm=r_arm,
                            left_leg=skin.left_leg,
                            right_leg=skin.right_leg
                        )

                    # Use standard isometric perspective with high scaling factor for quality
                    p = Perspective(x="right", y="front", z="up", scaling_factor=10) # type: ignore
                    final = skin.to_isometric_image(p)
                    
                    ratio = final.width / final.height
                    new_h = height
                    new_w = int(new_h * ratio)
                    
                    # Use high quality resampling because we are scaling down/adjusting from high-res (scaling_factor=10)
                    # Try LANCZOS/ANTIALIAS
                    try:
                        rs = Image.Resampling.LANCZOS 
                    except AttributeError:
                        rs = getattr(Image, 'LANCZOS', Image.NEAREST) # type: ignore

                    return final.resize((new_w, new_h), rs)
            except Exception as e:
                print(f"Skinpy render failed: {e}")

            # Base Scale for sharpness
            s = 1 
            # We will process at 1x then resize at end to keep math simple, or use s=4 for quality?
            # Let's use s=2
            s = 2
            src = src.resize((src.width * s, src.height * s), RESAMPLE_NEAREST)
            
            def get_part(x, y, w, h):
                return src.crop((x*s, y*s, (x+w)*s, (y+h)*s))

            # --- Extract Parts ---
            # HEAD
            head_f = get_part(8, 8, 8, 8)
            head_r = get_part(0, 8, 8, 8)
            head_t = get_part(8, 0, 8, 8)
            # Overlay
            head_f.alpha_composite(get_part(40, 8, 8, 8))
            head_r.alpha_composite(get_part(32, 8, 8, 8))
            head_t.alpha_composite(get_part(40, 0, 8, 8))

            # BODY
            body_f = get_part(20, 20, 8, 12)
            body_r = get_part(16, 20, 4, 12)
            body_t = get_part(20, 16, 8, 4)
            # Overlay
            body_f.alpha_composite(get_part(20, 36, 8, 12))
            body_r.alpha_composite(get_part(16, 36, 4, 12))
            body_t.alpha_composite(get_part(20, 32, 8, 4))
            
            # ARMS
            aw = 3 if model=="slim" else 4
            ra_f = get_part(44, 20, aw, 12) # Right Arm Front
            ra_r = get_part(40, 20, 4, 12)  # Right Arm Side (Out)
            ra_t = get_part(44, 16, aw, 4)  # Right Arm Top
            # Overlay
            ra_f.alpha_composite(get_part(44, 36, aw, 12))
            ra_r.alpha_composite(get_part(40, 36, 4, 12))
            ra_t.alpha_composite(get_part(44, 32, aw, 4))

            if src.height == 64*s:
                la_f = get_part(36, 52, aw, 12)
                la_t = get_part(36, 48, aw, 4)
                la_r = get_part(32, 52, 4, 12) # Left Arm In?
                # For Left Arm, the "Side" visible in 3D is usually the outer side.
                # In standard layout:
                # Right Arm: 40,20 (Right/Outer), 44,20 (Front), 48,20 (Inner), 52,20 (Back)
                # Left Arm:  32,52 (Right/Inner), 36,52 (Front), 40,52 (Left/Outer), 44,52 (Back)
                # We want Outer side.
                la_out = get_part(40, 52, 4, 12)
                la_out.alpha_composite(get_part(56, 52, 4, 12))
                
                la_f.alpha_composite(get_part(52, 52, aw, 12))
                la_t.alpha_composite(get_part(52, 48, aw, 4))
            else:
                 # Legacy
                 la_f = ra_f.transpose(FLIP_LEFT_RIGHT)
                 la_t = ra_t.transpose(FLIP_LEFT_RIGHT)
                 la_out = ra_r.transpose(FLIP_LEFT_RIGHT)

            # LEGS
            rl_f = get_part(4, 20, 4, 12)
            rl_r = get_part(0, 20, 4, 12) # Outer Right Leg
            # Overlay
            rl_f.alpha_composite(get_part(4, 36, 4, 12))
            rl_r.alpha_composite(get_part(0, 36, 4, 12))
            
            if src.height == 64*s:
                ll_f = get_part(20, 52, 4, 12)
                # Left Leg: 16,52 (Right/Inner), 20,52 (Front), 24,52 (Left/Outer)
                ll_out = get_part(24, 52, 4, 12)
                # Overlay
                ll_f.alpha_composite(get_part(4, 52, 4, 12)) # Wait, overlay pos defined in skin strict
                # Real overlay for LL: 
                # LL Front: 20,52. Overlay: 4,52 on 64x64? 
                # No, texture mapping says:
                # RL: 0,16->4,20 (Top), 4,20 (Front)
                # LL: 16,48->20,52 (Top), 20,52 (Front)
                # Overlay LL: 0,48? 
                # Let's assume standard layout.
                ll_out.alpha_composite(get_part(8, 52, 4, 12))
            else:
                ll_f = rl_f.transpose(FLIP_LEFT_RIGHT)
                ll_out = rl_r.transpose(FLIP_LEFT_RIGHT)

            # --- ISOMETRIC PROJECTION ---
            def make_iso_block(front, side, top):
                # Standard Isometric blocks
                # Front (Left of spine in 2D): Skew Y = +0.5 x
                # Side (Right of spine in 2D): Skew Y = -0.5 x
                # Actually, in PIL AFFINE, we map Dest -> Src.
                # If we want a line that goes Right & Down (Slope 0.5):
                # y_dest = 0.5 * x_dest.
                # In Source, y_src = y_dest - 0.5 * x_dest.
                # Matrix: (1, 0, 0, -0.5, 1, 0)
                
                w, h = front.size
                d_w, d_h = side.size
                t_w, t_h = top.size
                
                # --- Right Face (Side Texture) ---
                # We see this on the RIGHT of the spine.
                # It should go Down-Right.
                # Shear Matrix: x'=x, y'=y-0.5x. (Standard Iso)
                # PIL Transform: (1, 0, 0, -0.5, 1, 0)
                # Bounding box height increases by 0.5 * width
                
                skew = 0.5
                rH = int(d_h + d_w * skew)
                rW = d_w
                # We need to offset Y so we don't crop negative Y in source?
                # No, x is positive. 0.5 * x is positive. y - pos = smaller y.
                # If y_dest = 0, y_src = 0 - 0 = 0.
                # If y_dest = H, y_src = H.
                # Wait, if x_dest increases, y_src decreases.
                # This means to get y_src=0 at x_dest=W, y_dest must comprise +0.5*W.
                # So the image SLANTS UP (lines go up-right).
                
                # We want lines to go DOWN-RIGHT.
                # So as x increases, y_dest increases.
                # y_dest = y_src + 0.5 x.
                # y_src = y_dest - 0.5 * x.
                # This is correct for Down-Right?
                
                # Let's test. At x=0, y_dest=y_src.
                # At x=W, y_dest = y_src + 0.5W.
                # So the right side is LOWER than the left side. Correct.
                
                side_iso = side.transform((d_w, rH), AFFINE, (1, 0, 0, -skew, 1, 0), RESAMPLE_NEAREST)
                
                # --- Left Face (Front Texture) ---
                # We see this on the LEFT of the spine.
                # It should go Down-Left.
                # If we scan X from Left to Right (0 to W).
                # 0 is the "Left Edge", W is the "Right Edge" (Spine).
                # The Right Edge (Spine) matches the Side.
                # Left Edge is Higher? No, Left Edge is Lower, Right Edge is Lower?
                # In simple Iso Cube V shape:
                # Center Spine is Highest X line? No, Center Vertical is closest to user.
                # Top Center is highest point.
                # Left Face goes Down-Left.
                # Right Face goes Down-Right.
                
                # So for Left Face: As distance from spine (to left) increases, Y increases (goes down).
                # Let's just treat it as a Down-Right skew of a Flipped image?
                # Flip Front -> Down-Right Skew -> Flip Back.
                # If we flip, Left becomes Right. Skew Down-Right (Right side drops).
                # Unflip: Right becomes Left. Left side dropped.
                # Correct.
                
                fH = int(h + w * skew)
                fW = w
                
                # Flip
                front_f = front.transpose(FLIP_LEFT_RIGHT)
                # Skew
                front_s = front_f.transform((fW, fH), AFFINE, (1, 0, 0, -skew, 1, 0), RESAMPLE_NEAREST)
                # Unflip
                front_iso = front_s.transpose(FLIP_LEFT_RIGHT)
                
                # --- Top Face ---
                # Rotate 45 deg, Scale Y 0.5.
                # This makes a diamond.
                # top.rotate expands? YES.
                top_rot = top.rotate(45, expand=True, resample=RESAMPLE_NEAREST)
                # Scale Y
                tH = top_rot.height // 2
                top_iso = top_rot.resize((top_rot.width, tH), RESAMPLE_NEAREST)
                
                # --- Assembly ---
                # Calculate Canvas size
                # Width = Left Width + Right Width
                canvas_w = fW + rW
                # Height = Top Height + Front Height (partially overlapping)
                # Top Diamond Height = tH.
                # Front Vertical Edge = h.
                # Side Vertical Edge = d_h.
                # Total height approx tH/2 + h + tH/2? No.
                
                # Let's find alignment point: "The Center Spine Top".
                # For Top Diamond: Center is (W/2, H/2). Bottom corner is (W/2, H).
                # For Left Face (Front): Top Right corner is (W, 0). (RelativeToImage).
                # But it is skewed.
                # In front_iso (Flipped, Sheared, Flipped):
                # The "Right Edge" (which was Left before flip) is the high edge.
                # Let's trace corners.
                # Front Image (w x h): TL(0,0), TR(w,0), BL(0,h), BR(w,h).
                # Flip: TL->TR.
                # Skew (Down-Right): TR stays (0,0)? No...
                # Skew mapping:
                # (0,0) -> (0,0).
                # (w,0) -> (w, 0.5w). (Dropped).
                # Unflip:
                # The "Left" side of result corresponds to the "Right" side of skewed.
                # Result TL corresponds to Skewed TR ((w, 0.5w)).
                # Result TR corresponds to Skewed TL ((0,0)).
                # So Top-Right corner of front_iso is at (w, 0)? High point.
                # Top-Left corner is at (0, 0.5w)? Low point.
                
                # So Front_Iso: TR is High (y=0 relative to image top?).
                # Ideally, TR should attach to Top Diamond Bottom-Center.
                
                # Side_Iso (Right Face):
                # Skew Down-Right:
                # TL (0,0) -> (0,0). High Point.
                # TR (d_w, 0) -> (d_w, 0.5*d_w). Low Point.
                # So TL is High. attaches to Top Diamond Bottom-Center.
                
                # So Alignment Point is:
                # Top: Bottom Center.
                # Front: Top Right.
                # Side: Top Left.
                
                cx = fW # Spine location in canvas X
                
                # Top Placement
                # Top Center X = cx.
                # Top Width = top_iso.width.
                # We place Top such that its "Bottom" is at the join Y.
                # Top Diamond Bottom is at y = tH.
                # So Top Top-Left is at (cx - top_iso.width//2, join_y - tH).
                
                # Where is Join Y? Let's say Join Y = tH. (So Top starts at 0).
                join_y = tH
                
                # Canvas Height
                # Max drop is from Left Face bottom-left? or Right Face bottom-right?
                # Left Face H = h + 0.5w.
                # Right Face H = d_h + 0.5 d_w.
                # Total H = join_y + max(h, d_h).
                
                canvas_h = join_y + max(h, d_h) + int(max(w, d_w)*0.5) 
                
                can = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
                
                # Paste Top
                can.paste(top_iso, (cx - top_iso.width//2, 0), top_iso)
                offset_top = 0 # Fudges can happen with pixel rounding
                
                # Paste Front (Left of Spine)
                # Position: Right edge at cx. Top edge at join_y.
                # front_iso width is fW.
                can.paste(front_iso, (cx - fW, join_y - offset_top), front_iso)
                
                # Paste Side (Right of Spine)
                # Position: Left edge at cx. Top edge at join_y.
                can.paste(side_iso, (cx, join_y - offset_top), side_iso)
                
                return can

            # --- Compose Character ---
            
            # Make Blocks
            b_head = make_iso_block(head_f, head_r, head_t)
            b_body = make_iso_block(body_f, body_r, body_t)
            # Right Arm (Viewer Left)
            b_ra = make_iso_block(ra_f, ra_r, ra_t)
            # Left Arm (Viewer Right)
            # Use la_out for side (it is the outer side of left arm).
            b_la = make_iso_block(la_f, la_out, la_t)
            # Legs
            b_rl = make_iso_block(rl_f, rl_r, get_part(0,0,4,4)) 
            b_ll = make_iso_block(ll_f, ll_out, get_part(0,0,4,4))
            
            # Canvas
            final_w, final_h = 400 * s // 2, 500 * s // 2
            final = Image.new("RGBA", (final_w, final_h), (0,0,0,0))
            
            # Center of the "Floor"
            mx = final_w // 2
            
            # We align by "Spines".
            # The Spine X of the body is at mx.
            # Head Spine X is mx.
            
            # Y Positioning.
            # Head Top is highest.
            # Let's start Head Top at y=10.
            head_y = 10 * s
            
            # Paste Head
            # b_head spine is at 8*s (Head width).
            # b_head width is 8+8=16 units.
            # We paste so spine is at mx. 
            # Img X for spine is head_f.width.
            # Paste X = mx - head_f.width.
            final.paste(b_head, (mx - head_f.width, head_y), b_head)
            
            # Body
            # Body should be under Head.
            # Neck is where Head Front meets Head Side at the bottom?
            # Head Front Height is 8.
            # But in Iso, height is pure Y? Yes, vertical lines are vertical.
            # So Neck Y = head_y + Top_Diamond_Height + 8*s.
            # Top_Diamond_Height for head (8x8) -> 45deg -> Width approx 11.3 -> Scale Y 0.5 -> Height approx 5.6?
            # Let's count pixels.
            # Top(8,8) -> Rotated Diag is 8*sqrt(2) approx 11.3.
            # Scaled Y 0.5 -> 5.65.
            # So b_head total height = 5.65 + 8 + skew_drop(4).
            # Connection point (Neck) is at "Front Face Top" + 8.
            # In make_iso_block, Front Face Top is at `join_y`.
            # join_y = tH (approx 6s).
            # So Neck Y = head_y + join_y + 8*s.
            
            tH_head = b_head.height - 12*s # approx?
            # Let's use computed join_y from block logic: tH.
            # tH approx 6*s for 8 unit block? 
            # 8*s unit block. 1 unit = s pixels? NO. 
            # get_part multiplies by s.
            # So 8 unit block is 8*s pixels wide.
            # Diag = 1.41 * 8s. Half = 0.7 * 8s = 5.6s.
            # join_y_head approx 6*s.
            
            # Refined Neck Y
            neck_y = head_y + int(5.6 * s) + int(8 * s) # top_h + face_h
            
            # Paste Body
            # Body width (front) is 8*s.
            final.paste(b_body, (mx - body_f.width, neck_y), b_body)
            
            # Legs
            # Leg Y = Neck Y + Body Height (12 units)
            leg_y = neck_y + int(12 * s)
            
            # Right Leg (Viewer Left)
            # Spine is shifted Left by Leg Width (4 units).
            # Because Body Center Spine splits the legs?
            # Standard Skin: RL is 0..4, LL is 4..8.
            # So Body Spine is between legs.
            # RL Spine is at mx - 2*s (Center of RL).
            # Wait, RL is box 4 wide.
            # Its spine (between Front/Side) is at 4 units from its left.
            # We want RL Right Edge to be at mx.
            # So RL Spine is at mx - 2 units? No.
            # RL Front is 0..4 relative to leg.
            # The RL Block has Spine at 4*s (Front Width).
            # We want RL Block Spine to be at mx?
            # If we put RL Spine at mx, then RL Front is left of mx, RL Side is right of mx.
            # But Leg is entirely Left of Center line?
            # Yes, RL is "Right Leg" (Viewer Left).
            # In skin file, RL is x=0..4. Body is x=4..12? No.
            # Body 20..28. RL 4..8.
            # Conceptually, RL is [Center-4, Center].
            # So RL "Right Side" (Inner) is at Center.
            # Our b_rl "Side" is the Outer side (Right of leg).
            # Wait, for RL (Viewer Left), the "Right Side" of the cube is the Outer Side?
            # Yes, standing normally.
            # So RL sits to the Left of MX.
            # Its "Right Edge" (Spine? No)
            # b_rl: [Front][Side]. Spine is between them.
            # Front is Left Face. Side is Right Face.
            # If we place b_rl spine at mx: We see Front (Left of mx) and Side (Right of mx).
            # That would mean RL is centered at mx.
            # But RL should be shifted left.
            # Shift by 2 units (half leg width)? 
            # No, Body is 8 wide. Center is 4.
            # RL is 4 wide. Center is 2.
            # So RL Center is -2 from Body Center.
            # So we shift b_rl by -2 units (-2*s).
            # AND Z-Order?
            # Right Leg is "Viewer Left".
            # Side visible is Outer (Right Side).
            # So we place it such that Spine is at mx - 2*s.
            final.paste(b_rl, (mx - rl_f.width - int(2*s), leg_y), b_rl)
            
            # Left Leg (Viewer Right)
            # Shift Right by 2 units (+2*s).
            # b_ll Spine at mx + 2*s.
            final.paste(b_ll, (mx - ll_f.width + int(2*s), leg_y), b_ll)

            # Arms
            # Arm Y = Neck Y.
            # Right Arm (Viewer Left).
            # Attaches to Body Top-Left-Corner?
            # Body Spine is mx.
            # Body Left Edge is mx - 4*s.
            # RA Right Edge is Body Left Edge?
            # RA width 4 (or 3).
            # RA Spine at mx - 4*s - (Half Arm)?
            # RA Spine is between Front and Side.
            # We want RA "Inner" side to touch Body "Left" Side using blocked space.
            # Ideally: RA Spine is at mx - 6*s. (4 body + 2 arm).
            final.paste(b_ra, (mx - ra_f.width - int(6*s), neck_y), b_ra)
            
            # Left Arm (Viewer Right)
            # Spine at mx + 6*s.
            final.paste(b_la, (mx - la_f.width + int(6*s), neck_y), b_la)

            # --- Finalize ---
            bbox = final.getbbox()
            if bbox:
                final = final.crop(bbox)
                
            ratio = final.width / final.height
            new_h = height
            new_w = int(new_h * ratio)
            return final.resize((new_w, new_h), RESAMPLE_NEAREST)

        except Exception as e:
            print(f"Skin render error: {e}")
            import traceback
            traceback.print_exc()
            return None

# --- Main App ---
class MinecraftLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("NLC | New launcher")
        try:
            self.root.iconbitmap(resource_path("logo.ico"))
        except Exception:
            pass
        self.root.geometry("1080x720")
        self.root.configure(bg=COLORS['main_bg'])
        self.minecraft_dir = get_minecraft_dir()
        
        # Config Priority: 
        # 1. Local "launcher_config.json" (Portable / Dev mode)
        # 2. AppData/.nlc (Standard Install)
        
        local_config = "launcher_config.json"
        
        if os.path.exists(local_config):
            self.config_file = os.path.abspath(local_config)
            self.config_dir = os.path.dirname(self.config_file)
            print(f"Using local config: {self.config_file}")
        else:
            app_data = os.getenv('APPDATA')
            if app_data:
                self.config_dir = os.path.join(app_data, ".nlc")
            else:
                self.config_dir = os.path.join(os.path.expanduser("~"), ".nlc")
                
            if not os.path.exists(self.config_dir):
                os.makedirs(self.config_dir, exist_ok=True)
                
            self.config_file = os.path.join(self.config_dir, "launcher_config.json")
            print(f"Using global config: {self.config_file}")
        
        self.last_version = ""
        self.profiles = [] # List of {"name": str, "type": "offline", "skin_path": str, "uuid": str} (ACCOUNTS)
        self.installations = [] # List of {"name": str, "version": str, "loader": str, "last_played": str, "created": str} (GAME PROFILES)
        self.current_profile_index = -1
        self.auto_download_mod = False
        self.mod_available_online = False
        self.ram_allocation = DEFAULT_RAM
        self.java_args = ""
        self.loader_var = tk.StringVar(value="Vanilla")
        self.version_var = tk.StringVar()
        self.rpc_enabled = True # Default True
        self.rpc_show_version = True # Default True
        self.rpc_show_server = True # Default True
        self.rpc = None
        self.rpc_connected = False
        self.auto_update_check = True # Default True
        self.icon_cache = {}

        self.start_time = None
        self.current_tab = None
        self.log_file_path = None

        self.setup_logging()
        self.setup_styles()
        self.create_layout()
        self.load_from_config()
        # Refresh UI with loaded data
        self.update_installation_dropdown()
        self.refresh_installations_list()
        self.load_versions()
        
        # Auto Update Check
        if self.auto_update_check:
            self.check_for_updates()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        # Combobox
        style.configure("Launcher.TCombobox",
                       fieldbackground=COLORS['input_bg'],
                       background=COLORS['input_bg'],
                       foreground=COLORS['text_primary'],
                       arrowcolor=COLORS['text_primary'],
                       bordercolor=COLORS['input_border'],
                       lightcolor=COLORS['input_bg'],
                       darkcolor=COLORS['input_bg'],
                       relief="flat")
        style.map('Launcher.TCombobox',
                 fieldbackground=[('readonly', COLORS['input_bg'])],
                 selectbackground=[('readonly', COLORS['input_bg'])],
                 selectforeground=[('readonly', COLORS['text_primary'])])
        
        # Progressbar
        style.configure("Launcher.Horizontal.TProgressbar",
                       troughcolor=COLORS['bottom_bar_bg'],
                       background=COLORS['success_green'],
                       bordercolor=COLORS['bottom_bar_bg'],
                       thickness=4)

    def create_layout(self):
        # 1. Sidebar (Left) - width 250px for proper menu
        self.sidebar = tk.Frame(self.root, bg=COLORS['sidebar_bg'], width=200)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        
        # --- Sidebar Profile Section (Top Left) ---
        self.profile_frame = tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'], cursor="hand2")
        self.profile_frame.pack(fill="x", ipady=10, padx=10, pady=10)
        self.profile_frame.bind("<Button-1>", lambda e: self.toggle_profile_menu())
        
        # Profile Icon
        self.sidebar_head_label = tk.Label(self.profile_frame, bg=COLORS['sidebar_bg'])
        self.sidebar_head_label.pack(side="left", padx=(5, 10))
        self.sidebar_head_label.bind("<Button-1>", lambda e: self.toggle_profile_menu())
        
        # Profile Text Container
        self.sidebar_text_frame = tk.Frame(self.profile_frame, bg=COLORS['sidebar_bg'])
        self.sidebar_text_frame.pack(side="left", fill="x")
        self.sidebar_text_frame.bind("<Button-1>", lambda e: self.toggle_profile_menu())
        
        self.sidebar_username = tk.Label(self.sidebar_text_frame, text="Steve", font=("Segoe UI", 11, "bold"),
                                        bg=COLORS['sidebar_bg'], fg=COLORS['text_primary'], anchor="w")
        self.sidebar_username.pack(fill="x")
        self.sidebar_username.bind("<Button-1>", lambda e: self.toggle_profile_menu())
        
        self.sidebar_acct_type = tk.Label(self.sidebar_text_frame, text="Offline", font=("Segoe UI", 8),
                                         bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'], anchor="w")
        self.sidebar_acct_type.pack(fill="x")
        self.sidebar_acct_type.bind("<Button-1>", lambda e: self.toggle_profile_menu())

        tk.Frame(self.sidebar, bg="#454545", height=1).pack(fill="x", padx=10, pady=(0, 20)) # Separator

        # --- Sidebar Menu Items ---
        # Minecraft: Java Edition (Highlighted)
        java_btn_frame = tk.Frame(self.sidebar, bg="#3A3B3C", cursor="hand2", padx=10, pady=10) # Lighter grey highlight
        java_btn_frame.pack(fill="x", padx=5)
        
        # Small icon (simple square for now or reused logo)
        try:
             # Just a small colored block or simple emoji
            tk.Label(java_btn_frame, text="Java", bg="#2D8F36", fg="white", font=("Segoe UI", 8, "bold"), width=4).pack(side="left", padx=(0,10))
        except: pass

        tk.Label(java_btn_frame, text="Minecraft", font=("Segoe UI", 10, "bold"),
                bg="#3A3B3C", fg="white").pack(side="left")

        # --- Sidebar Links ---
        # Spacer
        tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'], height=10).pack()

        # Modrinth Link
        self._create_sidebar_link("Modrinth", "https://modrinth.com/", indicator_text="Mods")

        # Bottom spacer
        tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'], height=10).pack(side="bottom")

        # Settings Link (Gear) - Packed to bottom first to be at the very bottom
        self._create_sidebar_link("Settings", lambda: self.open_global_settings(), is_action=True, pack_side="bottom", icon="⚙")

        # GitHub Link - Packed to bottom next to be above Settings
        self._create_sidebar_link("GitHub", "https://github.com/Amne-Dev/New-launcher", pack_side="bottom")

        # 2. Main Content Area
        self.content_area = tk.Frame(self.root, bg=COLORS['main_bg'])
        self.content_area.pack(side="right", fill="both", expand=True)
        
        # 3. Top Navigation Bar
        self.nav_bar = tk.Frame(self.content_area, bg=COLORS['tab_bar_bg'], height=60)
        self.nav_bar.pack(fill="x", side="top")
        self.nav_bar.pack_propagate(False)
        
        self.nav_buttons = {}
        # Tabs: Play, Installations, Locker
        self.create_nav_btn("Play", lambda: self.show_tab("Play"))
        self.create_nav_btn("Installations", lambda: self.show_tab("Installations"))
        self.create_nav_btn("Locker", lambda: self.show_tab("Locker"))

        # 4. Tab Container
        self.tab_container = tk.Frame(self.content_area, bg=COLORS['main_bg'])
        self.tab_container.pack(fill="both", expand=True)
        
        # Initialize Tabs
        self.tabs = {}
        self.create_play_tab()
        self.create_locker_tab()
        self.create_installations_tab()
        self.create_settings_tab()
        
        self.show_tab("Play")

    def open_global_settings(self):
        self.show_tab("Settings")

    def _create_sidebar_link(self, text, url_or_command, indicator_text=None, is_action=False, pack_side="top", icon=None):
        frame = tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'], cursor="hand2", padx=15, pady=8)
        frame.pack(fill="x", side=cast(Any, pack_side))
        
        # Indicator (like "Java" or "Mods")
        if indicator_text:
             bg_color = "#E74C3C" if indicator_text == "Mods" else "#2D8F36"
             tk.Label(frame, text=indicator_text, bg=bg_color, fg="white", 
                     font=("Segoe UI", 8, "bold"), width=4, cursor="hand2").pack(side="left", padx=(0,10))
        
        # Icon
        if icon:
             # Use a larger font for the symbol
             tk.Label(frame, text=icon, font=("Segoe UI", 12), bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'], 
                      cursor="hand2").pack(side="left", padx=(0, 10))

        lbl = tk.Label(frame, text=text, font=("Segoe UI", 9), bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'], cursor="hand2")
        lbl.pack(side="left")
        
        def handle_click(e):
            if is_action:
                url_or_command()
            else:
                webbrowser.open(url_or_command)
            
        frame.bind("<Button-1>", handle_click)
        lbl.bind("<Button-1>", handle_click)
        # bind children
        for child in frame.winfo_children():
            child.bind("<Button-1>", handle_click)
        
        # Hover effect
        def on_enter(e):
            frame.config(bg="#3A3B3C")
            for child in frame.winfo_children():
                if isinstance(child, tk.Label) and child.cget("text") != "Mods" and child.cget("text") != "Java": # Don't recolor badges
                    child.config(bg="#3A3B3C", fg=COLORS['text_primary'])
        
        def on_leave(e):
            frame.config(bg=COLORS['sidebar_bg'])
            for child in frame.winfo_children():
                if isinstance(child, tk.Label) and child.cget("text") != "Mods" and child.cget("text") != "Java":
                    child.config(bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'])
            
        frame.bind("<Enter>", on_enter)
        frame.bind("<Leave>", on_leave)

    def create_nav_btn(self, text, command):
        btn = tk.Button(self.nav_bar, text=text.upper(), font=("Segoe UI", 11, "bold"),
                       bg=COLORS['tab_bar_bg'], fg=COLORS['text_secondary'],
                       activebackground=COLORS['tab_bar_bg'], activeforeground=COLORS['text_primary'],
                       relief="flat", bd=0, cursor="hand2", command=command)
        btn.pack(side="left", padx=30, pady=15)
        self.nav_buttons[text] = btn

    def show_tab(self, tab_name):
        # Hide all tabs
        for t in self.tabs.values():
            t.pack_forget()
        
        # Update Nav Buttons
        for name, btn in self.nav_buttons.items():
            if name.upper() == tab_name.upper():
                btn.config(fg=COLORS['text_primary'])
                # Add underline effect (simplified)
            else:
                btn.config(fg=COLORS['text_secondary'])
        
        # Show selected tab
        if tab_name in self.tabs:
            self.tabs[tab_name].pack(fill="both", expand=True)
            self.current_tab = tab_name

    # --- PLAY TAB ---
    def create_play_tab(self):
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Play"] = frame
        
        # Hero Section (Background) - fills most of the space except bottom bar
        self.hero_canvas = tk.Canvas(frame, bg="#181818", highlightthickness=0)
        self.hero_canvas.pack(fill="both", expand=True, padx=0, pady=0)
        
        # Try load background
        self.hero_img_raw = None
        try:
            bg_path = resource_path("background.png")
            
            # Use wallpaper from config if available (loaded in init -> load_from_config)
            if hasattr(self, 'current_wallpaper') and self.current_wallpaper and os.path.exists(self.current_wallpaper):
                 bg_path = self.current_wallpaper

            if os.path.exists(bg_path):
                self.hero_img_raw = Image.open(bg_path)
        except Exception: 
            pass
            
        self.hero_canvas.bind("<Configure>", self._update_hero_layout)

        # Bottom Action Bar
        bottom_bar = tk.Frame(frame, bg=COLORS['bottom_bar_bg'], height=100) # Increased height
        bottom_bar.pack(fill="x", side="bottom")
        bottom_bar.pack_propagate(False)

        # We use grid for 3 distinct sections in the bottom bar to ensure centering
        bottom_bar.columnconfigure(0, weight=1) # Left
        bottom_bar.columnconfigure(1, weight=1) # Center
        bottom_bar.columnconfigure(2, weight=1) # Right
        
        # 1. Left (Installation Selector)
        left_frame = tk.Frame(bottom_bar, bg=COLORS['bottom_bar_bg'])
        left_frame.grid(row=0, column=0, sticky="w", padx=30)
        
        # Custom Dropdown Trigger
        self.inst_selector_frame = tk.Frame(left_frame, bg=COLORS['bottom_bar_bg'], cursor="hand2")
        self.inst_selector_frame.pack(fill="x", ipadx=10, ipady=5)
        
        # Text (Left) - Name and version
        self.inst_selector_text_frame = tk.Frame(self.inst_selector_frame, bg=COLORS['bottom_bar_bg']) 
        self.inst_selector_text_frame.pack(side="left", padx=(10, 0))
        
        self.inst_name_lbl = tk.Label(self.inst_selector_text_frame, text="", font=("Segoe UI", 11, "bold"), 
                                     bg=COLORS['bottom_bar_bg'], fg="white", cursor="hand2", anchor="w")
        self.inst_name_lbl.pack(anchor="w")
        
        self.inst_ver_lbl = tk.Label(self.inst_selector_text_frame, text="", font=("Segoe UI", 9), 
                                    bg=COLORS['bottom_bar_bg'], fg=COLORS['text_secondary'], cursor="hand2", anchor="w")
        self.inst_ver_lbl.pack(anchor="w")

        # Icon (Right)
        self.inst_selector_icon = tk.Label(self.inst_selector_frame, bg=COLORS['bottom_bar_bg'], cursor="hand2")
        self.inst_selector_icon.pack(side="left", before=self.inst_selector_text_frame)

        # Chevron (Far Right)
        self.inst_selector_arrow = tk.Label(self.inst_selector_frame, text="▼", font=("Segoe UI", 8), 
                                           bg=COLORS['bottom_bar_bg'], fg=COLORS['text_secondary'], cursor="hand2")
        self.inst_selector_arrow.pack(side="right", padx=(15, 5))

        # Hover logic
        def on_hover(e):
             bg = "#3A3B3C" # Sidebar selected color
             self.inst_selector_frame.config(bg=bg)
             self.inst_selector_text_frame.config(bg=bg)
             self.inst_name_lbl.config(bg=bg)
             self.inst_ver_lbl.config(bg=bg)
             self.inst_selector_icon.config(bg=bg)
             self.inst_selector_arrow.config(bg=bg)

        def on_leave(e):
             bg = COLORS['bottom_bar_bg']
             self.inst_selector_frame.config(bg=bg)
             self.inst_selector_text_frame.config(bg=bg)
             self.inst_name_lbl.config(bg=bg)
             self.inst_ver_lbl.config(bg=bg)
             self.inst_selector_icon.config(bg=bg)
             self.inst_selector_arrow.config(bg=bg)

        for w in [self.inst_selector_frame, self.inst_selector_text_frame, self.inst_name_lbl, self.inst_ver_lbl, self.inst_selector_icon, self.inst_selector_arrow]:
             w.bind("<Enter>", on_hover, add="+")
             w.bind("<Leave>", on_leave, add="+")
             w.bind("<Button-1>", self.open_selector_menu, add="+")
        
        # Populate with installations
        self.update_installation_dropdown()

        # 2. Center (Play Button)
        center_frame = tk.Frame(bottom_bar, bg=COLORS['bottom_bar_bg'])
        center_frame.grid(row=0, column=1, pady=25)

        # Composite Play Button (Frame)
        self.play_container = tk.Frame(center_frame, bg=COLORS['play_btn_green'])
        self.play_container.pack()

        self.launch_btn = tk.Button(self.play_container, text="PLAY", font=("Segoe UI", 14, "bold"),
                                   bg=COLORS['play_btn_green'], fg="white",
                                   activebackground=COLORS['play_btn_hover'], activeforeground="white",
                                   relief="flat", bd=0, cursor="hand2", width=14, pady=8,
                                   command=lambda: self.start_launch(force_update=False))
        self.launch_btn.pack(side="left")
        
        # Divider line
        tk.Frame(self.play_container, width=1, bg="#2D8F36").pack(side="left", fill="y")

        self.launch_opts_btn = tk.Button(self.play_container, text="▼", font=("Segoe UI", 10),
                                        bg=COLORS['play_btn_green'], fg="white",
                                        activebackground=COLORS['play_btn_hover'], activeforeground="white",
                                        relief="flat", bd=0, cursor="hand2", width=3,
                                        command=self.open_launch_options)
        self.launch_opts_btn.pack(side="left", fill="y")
        
        
        # 3. Right (Status / Account)
        right_frame = tk.Frame(bottom_bar, bg=COLORS['bottom_bar_bg'])
        right_frame.grid(row=0, column=2, sticky="e", padx=30)
        
        self.status_label = tk.Label(right_frame, text="Ready to launch", 
                                    font=("Segoe UI", 9), bg=COLORS['bottom_bar_bg'], fg=COLORS['text_secondary'], anchor="e")
        self.status_label.pack(anchor="e")
        
        # Small gamertag at bottom right
        self.bottom_gamertag = tk.Label(right_frame, text="", font=("Segoe UI", 8),
                                       bg=COLORS['bottom_bar_bg'], fg=COLORS['text_secondary'], anchor="e")
        self.bottom_gamertag.pack(anchor="e")


        # Progress Bar (Overlay at absolute bottom or integrated?)
        # Let's place it at the very bottom of the bar
        self.progress_bar = ttk.Progressbar(bottom_bar, orient='horizontal', mode='determinate',
                                           style="Launcher.Horizontal.TProgressbar")
        self.progress_bar.place(relx=0, rely=1.0, anchor="sw", relwidth=1, height=4) 

    def open_launch_options(self):
        # Popup near the arrow button
        menu = tk.Toplevel(self.root)
        menu.overrideredirect(True)
        menu.config(bg=COLORS['card_bg'])
        
        try:
             x = self.launch_opts_btn.winfo_rootx() + self.launch_opts_btn.winfo_width() - 150
             y = self.launch_opts_btn.winfo_rooty() + self.launch_opts_btn.winfo_height() + 5
             menu.geometry(f"150x40+{x}+{y}") 
        except:
             menu.geometry("150x40")
             
        def do_force():
            menu.destroy()
            self.start_launch(force_update=True)
            
        btn = tk.Label(menu, text="Force Update & Play", font=("Segoe UI", 10), 
                      bg=COLORS['card_bg'], fg=COLORS['text_primary'], anchor="w", padx=10, pady=8)
        btn.pack(fill="x")
        btn.bind("<Button-1>", lambda e: do_force())
        btn.bind("<Enter>", lambda e: btn.config(bg="#454545"))
        btn.bind("<Leave>", lambda e: btn.config(bg=COLORS['card_bg']))

        # Close on click outside
        menu.bind("<FocusOut>", lambda e: self.root.after(100, lambda: menu.destroy() if menu.winfo_exists() else None))
        menu.focus_set()

    def update_bottom_gamertag(self):
        # Update the small gamertag in the bottom right corner
        if hasattr(self, 'bottom_gamertag') and self.profiles:
             p = self.profiles[self.current_profile_index]
             self.bottom_gamertag.config(text=p.get("name", ""))

    def _update_hero_layout(self, event):
        w, h = event.width, event.height
        if w < 10 or h < 10: return
        
        self.hero_canvas.delete("all")
        
        # Draw Background
        if self.hero_img_raw:
            try:
                img_w, img_h = self.hero_img_raw.size
                ratio = max(w/img_w, h/img_h)
                new_w = int(img_w * ratio)
                new_h = int(img_h * ratio)
                
                # Use standard resampling or fallback
                resample_method = getattr(Image, 'LANCZOS', Image.Resampling.LANCZOS)
                resized = self.hero_img_raw.resize((new_w, new_h), resample_method)
                
                self.hero_bg_photo = ImageTk.PhotoImage(resized)
                self.hero_canvas.create_image(w//2, h//2, image=self.hero_bg_photo, anchor="center")
            except Exception: pass
            
        # Draw Text Overlay
        self.hero_canvas.create_text(w//2, h*0.4, text="MINECRAFT", font=("Segoe UI", 40, "bold"), fill="white", anchor="center")
        self.hero_canvas.create_text(w//2, h*0.4 + 50, text="JAVA EDITION", font=("Segoe UI", 14), fill=COLORS['text_secondary'], anchor="center")

    # --- INSTALLATIONS TAB (New) ---
    def create_installations_tab(self):
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Installations"] = frame
        
        # 1. Top Bar (Search, Sort, Filters, New)
        top_bar = tk.Frame(frame, bg=COLORS['main_bg'], pady=20, padx=40)
        top_bar.pack(fill="x")
        
        # Search
        search_frame = tk.Frame(top_bar, bg=COLORS['input_bg'], padx=10, pady=5)
        search_frame.pack(side="left")
        tk.Label(search_frame, text="🔍", bg=COLORS['input_bg'], fg=COLORS['text_secondary']).pack(side="left")
        search_entry = tk.Entry(search_frame, bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", font=("Segoe UI", 10))
        search_entry.pack(side="left", padx=5)
        
        # Sort (Placeholder)
        # tk.Label(top_bar, text="Sort by: Latest played", font=("Segoe UI", 9), bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(side="left", padx=20)
        
        # Filters (Checkboxes)
        filter_frame = tk.Frame(top_bar, bg=COLORS['main_bg'])
        filter_frame.pack(side="left", padx=40)
        
        self.show_releases = tk.BooleanVar(value=True)
        self.show_snapshots = tk.BooleanVar(value=False)
        self.show_modded = tk.BooleanVar(value=True)

        def on_filter_change():
            self.refresh_installations_list()

        def create_filter(text, var):
             cb = tk.Checkbutton(filter_frame, text=text, variable=var, 
                                bg=COLORS['main_bg'], fg=COLORS['text_primary'], 
                                selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                                command=on_filter_change)
             cb.pack(side="left", padx=10)
             return cb
             
        create_filter("Releases", self.show_releases)
        create_filter("Snapshots", self.show_snapshots)
        create_filter("Modded", self.show_modded)
        
        # New Installation Button
        tk.Button(top_bar, text="New installation", font=("Segoe UI", 10, "bold"),
                 bg=COLORS['success_green'], fg="white", relief="flat", padx=15, pady=6, cursor="hand2",
                 command=self.open_new_installation_modal).pack(side="right") 

        # 2. Profile List
        self.inst_list_frame = tk.Frame(frame, bg=COLORS['main_bg'])
        self.inst_list_frame.pack(fill="both", expand=True, padx=40)
        
        self.refresh_installations_list()

    def refresh_installations_list(self):
        for w in self.inst_list_frame.winfo_children(): w.destroy()
        
        for idx, inst in enumerate(self.installations):
            # Check Filters
            # Determine type
            v_id = inst.get("version", "").lower()
            loader = inst.get("loader", "Vanilla")
            
            is_snapshot = "snapshot" in v_id or "pre" in v_id or "c" in v_id
            is_modded = loader != "Vanilla"
            
            # If Modded: show if Show Modded is on. 
            # Note: Modded can also be a snapshot (rarely tracked), usually releases.
            
            if is_modded:
                if not self.show_modded.get(): continue
            else:
                if is_snapshot:
                    if not self.show_snapshots.get(): continue
                else:
                    # Release
                    if not self.show_releases.get(): continue

            self.create_installation_item(self.inst_list_frame, idx, inst)

    def get_icon_image(self, icon_identifier, size=(40, 40)):
        # icon_identifier can be a path "icons/grass.png" or just "grass" or an emoji
        if not icon_identifier: return None
        
        # Check if it's a known image file
        if str(icon_identifier).endswith(".png"):
            key = (icon_identifier, size)
            if key in self.icon_cache: 
                return self.icon_cache[key]
                
            try:
                # Try finding it
                path = resource_path(icon_identifier)
                if os.path.exists(path):
                    img = Image.open(path)
                    img = img.resize(size, RESAMPLE_NEAREST)
                    photo = ImageTk.PhotoImage(img)
                    self.icon_cache[key] = photo
                    return photo
            except Exception:
                pass
        return None

    def create_installation_item(self, parent, idx, inst):
        item = tk.Frame(parent, bg=COLORS['card_bg'], pady=15, padx=20)
        item.pack(fill="x", pady=2)
        
        # Determine Icon
        loader = inst.get("loader", "Vanilla")
        custom_icon = inst.get("icon")
        
        # Try loading as image
        icon_img = self.get_icon_image(custom_icon, (40, 40))
        
        if icon_img:
            icon_lbl = tk.Label(item, image=icon_img, bg=COLORS['card_bg'])
            icon_lbl.image = icon_img # type: ignore # Keep reference
            icon_lbl.pack(side="left", padx=(0, 20))
        else:
            # Fallback to Emoji / Default
            icon_char = "⬜"
            if custom_icon and not str(custom_icon).endswith(".png"):
                icon_char = custom_icon
            elif loader == "Fabric": icon_char = "🧵"
            elif loader == "Forge": icon_char = "🔨"
            elif loader == "BatMod": icon_char = "🦇"
            elif loader == "LabyMod": icon_char = "🐺"
            
            icon_lbl = tk.Label(item, text=icon_char, bg=COLORS['card_bg'], fg=COLORS['text_secondary'], font=("Segoe UI", 20))
            icon_lbl.pack(side="left", padx=(0, 20))
        
        # Details
        info_frame = tk.Frame(item, bg=COLORS['card_bg'])
        info_frame.pack(side="left", fill="x", expand=True)
        
        name = inst.get("name", "Unnamed Installation")
        ver = inst.get("version", "Latest")
        
        tk.Label(info_frame, text=name, font=("Segoe UI", 11, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(anchor="w")
        tk.Label(info_frame, text=f"{loader} {ver}", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        
        # Actions
        actions = tk.Frame(item, bg=COLORS['card_bg'])
        actions.pack(side="right")
        
        # Play
        tk.Button(actions, text="Play", bg=COLORS['success_green'], fg="white", font=("Segoe UI", 9, "bold"),
                 relief="flat", padx=15, cursor="hand2",
                 command=lambda: self.launch_installation(idx)).pack(side="left", padx=5)
                 
        # Folder
        tk.Button(actions, text="📁", bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", cursor="hand2",
                 command=lambda: self.open_installation_folder(idx)).pack(side="left", padx=5)
                 
        # Edit/Menu
        menu_btn = tk.Button(actions, text="...", bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", cursor="hand2")
        menu_btn.config(command=lambda b=menu_btn: self.open_installation_menu(idx, b))
        menu_btn.pack(side="left", padx=5)

    def open_installation_folder(self, idx):
        try:
            os.startfile(self.minecraft_dir)
        except Exception:
            pass

    def update_installation_dropdown(self):
        # Update dropdown - now custom button
        if not hasattr(self, 'inst_selector_frame'): return
        
        if self.installations:
            # Restore selection
            current = getattr(self, 'current_installation_index', 0)
            if current >= len(self.installations): 
                current = 0
            self.select_installation(current)
        else:
            self.inst_name_lbl.config(text="No Installations")
            self.inst_ver_lbl.config(text="")

    def select_installation(self, index):
        if not self.installations: return
        if not (0 <= index < len(self.installations)): return
        
        self.current_installation_index = index
        inst = self.installations[index]
        
        # Update Text
        name = inst.get("name", "Unnamed")
        ver = inst.get("version", "Latest")
        
        self.inst_name_lbl.config(text=name)
        self.inst_ver_lbl.config(text=ver)
        
        # Update Icon
        icon_path = inst.get("icon", "icons/crafting_table_front.png")
        img = self.get_icon_image(icon_path, (32, 32))
        
        if img:
            self.inst_selector_icon.config(image=img, text="", width=32, height=32)
            self.inst_selector_icon.image = img # type: ignore
        else:
             self.inst_selector_icon.config(image="", text="?", font=("Segoe UI", 12), fg="white", width=4, height=2)
             
        loader = inst.get("loader", "")
        self.set_status(f"Selected: {ver} ({loader})")

    def open_selector_menu(self, event=None):
        if not self.installations: return
        
        # Prevent duplication
        if hasattr(self, '_selector_menu') and self._selector_menu and self._selector_menu.winfo_exists():
            self._selector_menu.destroy()
            return

        menu = tk.Toplevel(self.root)
        self._selector_menu = menu
        menu.wm_overrideredirect(True)
        menu.config(bg=COLORS['card_bg'])
        
        # Border Frame
        menu_frame = tk.Frame(menu, bg=COLORS['card_bg'], highlightbackground="#454545", highlightthickness=1)
        menu_frame.pack(fill="both", expand=True)

        w = max(self.inst_selector_frame.winfo_width(), 300) # Enforce min width for longer names
        item_h = 55
        count = len(self.installations)
        h = min(count * item_h, 400) 
        
        x = self.inst_selector_frame.winfo_rootx()
        target_y = self.inst_selector_frame.winfo_rooty() - h - 5
        
        if target_y < 0: 
            target_y = self.inst_selector_frame.winfo_rooty() + self.inst_selector_frame.winfo_height() + 5
            
        menu.geometry(f"{w}x{h}+{x}+{target_y}")
        
        # Scrollable area
        canvas = tk.Canvas(menu_frame, bg=COLORS['card_bg'], highlightthickness=0)
        scrollbar = tk.Scrollbar(menu_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=COLORS['card_bg'])
        
        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw", width=w-20)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Close on click outside (Lose Focus)
        def on_focus_out(event):
            self.root.after(150, lambda: menu.destroy() if menu.winfo_exists() else None)
            
        menu.bind("<FocusOut>", on_focus_out)
        menu.focus_force()

        # Populate
        for i, inst in enumerate(self.installations):
            name = inst.get("name", "Unnamed")
            ver = inst.get("version", "Latest")
            icon_path = inst.get("icon", "icons/crafting_table_front.png")
            
            # Row Container
            row = tk.Frame(scroll_frame, bg=COLORS['card_bg'], cursor="hand2")
            row.pack(fill="x", ipady=5)
            
            # Icon
            img = self.get_icon_image(icon_path, (32, 32)) 
            ico_lbl = tk.Label(row, bg=COLORS['card_bg'], cursor="hand2")
            if img:
                ico_lbl.config(image=img)
                ico_lbl.image = img # type: ignore
            else:
                 ico_lbl.config(text="?", fg="white")
            ico_lbl.pack(side="left", padx=10)
            
            # Text
            txt_cx = tk.Frame(row, bg=COLORS['card_bg'], cursor="hand2")
            txt_cx.pack(side="left", fill="x", expand=True)
            
            tk.Label(txt_cx, text=name, font=("Segoe UI", 10, "bold"), 
                    bg=COLORS['card_bg'], fg="white", anchor="w", cursor="hand2").pack(fill="x")
            tk.Label(txt_cx, text=ver, font=("Segoe UI", 9), 
                    bg=COLORS['card_bg'], fg=COLORS['text_secondary'], anchor="w", cursor="hand2").pack(fill="x")
            
            # Hover & Click
            def on_enter(e, r=row):
                r["bg"] = "#454545"
                for c in r.winfo_children():
                    c["bg"] = "#454545"
                    for gc in c.winfo_children(): # Text frame children
                        gc["bg"] = "#454545"
                        
            def on_leave(e, r=row):
                r["bg"] = COLORS['card_bg']
                for c in r.winfo_children():
                    c["bg"] = COLORS['card_bg']
                    for gc in c.winfo_children():
                        gc["bg"] = COLORS['card_bg']

            row.bind("<Enter>", on_enter)
            row.bind("<Leave>", on_leave)
            
            def do_select(e, idx=i):
                self.select_installation(idx)
                menu.destroy()
                
            row.bind("<Button-1>", do_select)
            for child in row.winfo_children():
                child.bind("<Button-1>", do_select)
                for grand in child.winfo_children():
                    grand.bind("<Button-1>", do_select)


    def open_new_installation_modal(self, edit_mode=False, index=None):
        # Modal for Name, Version, etc.
        win = tk.Toplevel(self.root)
        title = "Edit Installation" if edit_mode else "New Installation"
        win.title(title)
        win.geometry("650x600")
        win.configure(bg="#1e1e1e")
        win.resizable(True, True) # Allow resizing to help fit content
        
        # Pre-load data if editing
        existing_data = {}
        if edit_mode and index is not None and 0 <= index < len(self.installations):
            existing_data = self.installations[index]

        # --- Header ---
        header = tk.Frame(win, bg="#1e1e1e")
        header.pack(fill="x", padx=25, pady=(25, 20))
        tk.Label(header, text=title, font=("Segoe UI", 16, "bold"), 
                bg="#1e1e1e", fg="white", anchor="w").pack(fill="x")

        # --- Content Area (Icon + Fields) ---
        content = tk.Frame(win, bg="#1e1e1e")
        content.pack(fill="both", expand=True, padx=25)

        # Icon Selector
        icon_frame = tk.Frame(content, bg="#1e1e1e")
        icon_frame.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 20))
        
        # Default to crafting table if no icon or strictly emoji (legacy)
        initial_icon = existing_data.get("icon", "icons/crafting_table_front.png")
        if not str(initial_icon).endswith(".png"):
            initial_icon = "icons/crafting_table_front.png"
            
        current_icon_var = tk.StringVar(value=initial_icon)
        
        # Main Icon Display (Image based)
        icon_btn = tk.Label(icon_frame, bg="#3A3B3C", cursor="hand2")
        icon_btn.pack()
        
        def update_main_icon(val):
            # Attempt to load
            img = self.get_icon_image(val, (64, 64))
            if img:
                # When image is present, width/height are in pixels
                icon_btn.config(image=img, text="", width=64, height=64)
                icon_btn.image = img # type: ignore
            else:
                # When text is present, width/height are in characters (approx)
                icon_btn.config(image="", text="?", font=("Segoe UI", 20), fg="white", width=4, height=2)

        update_main_icon(initial_icon)

        # Hint label
        tk.Label(icon_frame, text="Change", font=("Segoe UI", 8, "underline"), 
                bg="#1e1e1e", fg="#5A5B5C").pack(pady=(5,0))
                
        # Icon Selector Modal
        def open_icon_selector(e):
             sel_win = tk.Toplevel(win)
             sel_win.title("Select Icon")
             sel_win.geometry("460x500")
             sel_win.configure(bg="#2d2d2d")
             sel_win.transient(win)
             # Center
             x = win.winfo_x() + (win.winfo_width()//2) - 230
             y = win.winfo_y() + (win.winfo_height()//2) - 250
             sel_win.geometry(f"+{x}+{y}")

             tk.Label(sel_win, text="Select Block", font=("Segoe UI", 12, "bold"), bg="#2d2d2d", fg="white").pack(pady=(15,10))
             

             # Scrollable Frame for Icons
             container = tk.Frame(sel_win, bg="#2d2d2d")
             container.pack(expand=True, fill="both", padx=10, pady=10)
             
             canvas = tk.Canvas(container, bg="#2d2d2d", highlightthickness=0)
             scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
             
             icons_grid = tk.Frame(canvas, bg="#2d2d2d")
             
             icons_grid.bind(
                 "<Configure>",
                 lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
             )
             
             canvas.create_window((0, 0), window=icons_grid, anchor="nw")
             
             canvas.configure(yscrollcommand=scrollbar.set)
             
             canvas.pack(side="left", fill="both", expand=True)
             scrollbar.pack(side="right", fill="y")
             
             def _on_mousewheel(event):
                 canvas.yview_scroll(int(-1*(event.delta/120)), "units")
             
             # Bind scrolling to the window so it works when hovering anywhere in the modal
             sel_win.bind("<MouseWheel>", _on_mousewheel)
             
             # Popular Minecraft Blocks
             block_names = [
                 "grass_block_side.png", "dirt.png", "stone.png", "cobblestone.png", "oak_planks.png", 
                 "crafting_table_front.png", "furnace_front.png", "barrel_side.png", "tnt_side.png", "bookshelf.png",
                 "sand.png", "gravel.png", "bedrock.png", "obsidian.png", "spruce_log.png",
                 "diamond_ore.png", "gold_ore.png", "iron_ore.png", "coal_ore.png", "redstone_ore.png",
                 "diamond_block.png", "gold_block.png", "iron_block.png", "emerald_block.png", "lapis_block.png",
                 "snow.png", "ice.png", "clay.png", "pumpkin_side.png", "melon_side.png",
                 "netherrack.png", "soul_sand.png", "glowstone.png", "end_stone.png", "red_wool.png"
             ]
             
             # Inventory Slot Style
             slot_bg = "#8b8b8b"
             
             cols = 5
             for i, name in enumerate(block_names):
                 path = f"icons/{name}"
                 
                 # Slot Container
                 slot = tk.Frame(icons_grid, bg=slot_bg, width=64, height=64, 
                                highlightbackground="white", highlightthickness=0)
                 slot.grid(row=i//cols, column=i%cols, padx=6, pady=6)
                 slot.pack_propagate(False)
                 
                 # Image
                 img = self.get_icon_image(path, (48, 48))
                 
                 lbl = tk.Label(slot, bg=slot_bg, cursor="hand2")
                 if img:
                     lbl.config(image=img)
                     lbl.image = img # type: ignore
                 else:
                     lbl.config(text="?", fg="white")
                 
                 lbl.place(relx=0.5, rely=0.5, anchor="center")
                 
                 def set_ico(val=path):
                     current_icon_var.set(val)
                     update_main_icon(val)
                     sel_win.destroy()
                     
                 def on_hover(s=slot, l=lbl):
                     s.config(bg="#a0a0a0")
                     l.config(bg="#a0a0a0")
                     
                 def on_leave(s=slot, l=lbl):
                     s.config(bg=slot_bg)
                     l.config(bg=slot_bg)

                 lbl.bind("<Button-1>", lambda e, val=path: set_ico(val))
                 slot.bind("<Button-1>", lambda e, val=path: set_ico(val))
                 lbl.bind("<Enter>", lambda e: on_hover())
                 lbl.bind("<Leave>", lambda e: on_leave())
                 slot.bind("<Enter>", lambda e: on_hover())
                 slot.bind("<Leave>", lambda e: on_leave())
        
        icon_btn.bind("<Button-1>", open_icon_selector)


        # Fields Container
        fields_frame = tk.Frame(content, bg="#1e1e1e")
        fields_frame.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(1, weight=1) # Fields take remaining width

        # Label Helper
        def create_label(text):
            return tk.Label(fields_frame, text=text, font=("Segoe UI", 9, "bold"), 
                           bg="#1e1e1e", fg="#B0B0B0", anchor="w")

        # Input Style Helper
        input_bg_color = "#48494A" # Softer Gray
        input_fg_color = "white"

        # 1. NAME
        create_label("NAME").pack(fill="x", pady=(0,5))
        name_entry = tk.Entry(fields_frame, bg=input_bg_color, fg=input_fg_color, 
                             insertbackground="white", relief="flat", font=("Segoe UI", 10))
        name_entry.pack(fill="x", ipady=8, pady=(0, 15))

        if edit_mode: name_entry.insert(0, existing_data.get("name", ""))


        # 2. CLIENT / LOADER (Grouped)
        create_label("CLIENT / LOADER").pack(fill="x", pady=(0,5))
        
        loader_var = tk.StringVar()
        loader_combo = ttk.Combobox(fields_frame, textvariable=loader_var, 
                                   values=["Vanilla", "Fabric", "Forge", "Other versions (ie: BatMod, Laby Mod)"], 
                                   state="readonly", font=("Segoe UI", 10), width=40)
        loader_combo.pack(fill="x", ipady=5, pady=(0, 5))
        
        # Disclaimer
        self.disclaimer_lbl = tk.Label(fields_frame, text="⚠️ These versions need to be downloaded externally", 
                                      bg="#1e1e1e", fg="#F1C40F", font=("Segoe UI", 8), anchor="w")

        # 3. VERSION
        create_label("VERSION").pack(fill="x", pady=(10,5))
        
        self.modal_version_var = tk.StringVar()
        self.modal_ver_combo = ttk.Combobox(fields_frame, textvariable=self.modal_version_var, 
                                           state="disabled", font=("Segoe UI", 10), width=40)
        self.modal_ver_combo.pack(fill="x", ipady=5, pady=(0, 5))

        # Status / Helper below version
        self.modal_status_lbl = tk.Label(fields_frame, text="Select a loader to fetch versions", 
                                        bg="#1e1e1e", fg="#5A5B5C", font=("Segoe UI", 8), anchor="w")
        self.modal_status_lbl.pack(fill="x", pady=(0, 10))

        # Start logic if edit mode
        if edit_mode:
             loader_combo.set(existing_data.get("loader", "Vanilla"))
             self.modal_version_var.set(existing_data.get("version", ""))

        # --- Filters (Snapshots) ---
        filter_frame = tk.Frame(fields_frame, bg="#1e1e1e")
        filter_frame.pack(fill="x", pady=(0, 15))
        self.modal_show_snapshots = tk.BooleanVar(value=False)
        snap_chk = tk.Checkbutton(filter_frame, text="Show Snapshots", variable=self.modal_show_snapshots,
                      bg="#1e1e1e", fg="white", selectcolor="#1e1e1e", activebackground="#1e1e1e",
                      command=lambda: self.update_modal_versions_list())
        snap_chk.pack(side="left")


        # --- More Options (Collapsible) ---
        more_opts_frame = tk.Frame(fields_frame, bg="#1e1e1e")
        more_opts_frame.pack(fill="x", pady=(5, 0))
        
        opts_exposed = tk.BooleanVar(value=False)
        opts_container = tk.Frame(fields_frame, bg="#1e1e1e")
        
        def toggle_opts():
             if opts_exposed.get():
                  opts_container.pack_forget()
                  opts_exposed.set(False)
                  opts_btn.config(text="▸ MORE OPTIONS")
             else:
                  opts_container.pack(fill="x", pady=(10,0))
                  opts_exposed.set(True)
                  opts_btn.config(text="▾ MORE OPTIONS")

        opts_btn = tk.Label(more_opts_frame, text="▸ MORE OPTIONS", font=("Segoe UI", 9, "bold"),
                           bg="#1e1e1e", fg="white", cursor="hand2")
        opts_btn.pack(side="left")
        opts_btn.bind("<Button-1>", lambda e: toggle_opts())

        # Java Executable
        create_label("JAVA EXECUTABLE").pack(in_=opts_container, fill="x", pady=(5,5))
        java_entry = tk.Entry(opts_container, bg=input_bg_color, fg=input_fg_color, relief="flat", font=("Segoe UI", 10))
        java_entry.pack(fill="x", ipady=6)
        java_entry.insert(0, "<Use Bundled Java Runtime>")
        java_entry.config(state="disabled") # Placeholder for now

        # Resolution
        create_label("RESOLUTION").pack(in_=opts_container, fill="x", pady=(15,5))
        res_frame = tk.Frame(opts_container, bg="#1e1e1e")
        res_frame.pack(fill="x")
        
        res_w = tk.Entry(res_frame, bg=input_bg_color, fg=input_fg_color, width=10, relief="flat", font=("Segoe UI", 10))
        res_w.pack(side="left", ipady=6)
        res_w.insert(0, "Auto")
        
        tk.Label(res_frame, text=" x ", bg="#1e1e1e", fg="white").pack(side="left")
        
        res_h = tk.Entry(res_frame, bg=input_bg_color, fg=input_fg_color, width=10, relief="flat", font=("Segoe UI", 10))
        res_h.pack(side="left", ipady=6)
        res_h.insert(0, "Auto")


        # -- Logic --
        self.cached_loader_versions = [] 

        def check_installed(version_id, loader_type):
            try:
                installed_list = [v['id'] for v in minecraft_launcher_lib.utils.get_installed_versions(self.minecraft_dir)]
                if loader_type == "Vanilla":
                    return version_id in installed_list
                elif loader_type == "Fabric":
                    return any("fabric" in iv.lower() and version_id in iv for iv in installed_list)
                elif loader_type == "Forge":
                    return any("forge" in iv.lower() and version_id in iv for iv in installed_list)
                else: 
                     # For other clients, check exact match + client name usually
                     # Broad check for anything that looks like a version match in installed list
                     return any(version_id in iv for iv in installed_list)
            except:
                pass
            return False

        def fetch_versions_thread(loader_type):
            try:
                raw_versions = []
                if loader_type == "Vanilla":
                    vlist = minecraft_launcher_lib.utils.get_version_list()
                    for v in vlist:
                        raw_versions.append({'id': v['id'], 'type': v['type']})
                elif loader_type == "Fabric":
                    # Real Fetch using library
                    fab_list = minecraft_launcher_lib.fabric.get_all_minecraft_versions()
                    for v in fab_list:
                        # v is {'version': '1.21.1', 'stable': True}
                        v_type = 'release' if v['stable'] else 'snapshot'
                        raw_versions.append({'id': v['version'], 'type': v_type})
                elif loader_type == "Forge":
                    # Real Fetch using library
                    forge_strs = minecraft_launcher_lib.forge.list_forge_versions()
                    # format: MC-ForgeVersion e.g. 1.21-51.0.33
                    seen_mc = set()
                    temp_list = []
                    for fv in forge_strs:
                        # specific handling for old forge versions might be needed, 
                        # but generally it starts with MC version
                        parts = fv.split('-', 1)
                        if len(parts) >= 2:
                            mc_ver = parts[0]
                            if mc_ver not in seen_mc:
                                seen_mc.add(mc_ver)
                                # We assume it's a release for simplicity unless verified otherwise
                                temp_list.append({'id': mc_ver, 'type': 'release'})
                    raw_versions = temp_list
                
                # --- 3RD PARTY CLIENTS ---
                elif loader_type == "Other versions (ie: BatMod, Laby Mod)":
                     # Scan installed versions directory for custom clients
                     try:
                         installed = minecraft_launcher_lib.utils.get_installed_versions(self.minecraft_dir)
                         # Get known vanilla versions to filter
                         vanilla_ids = {v['id'] for v in minecraft_launcher_lib.utils.get_version_list()}
                         
                         for inst in installed:
                             vid = inst['id']
                             # Filter out standard loaders and vanilla versions
                             if "fabric" in vid.lower() or "forge" in vid.lower() or vid in vanilla_ids:
                                 continue
                             # Add to list
                             raw_versions.append({'id': vid, 'type': inst['type']})
                     except Exception as e:
                         print(f"Error scanning installed versions: {e}")

                self.cached_loader_versions = raw_versions
                if win.winfo_exists():
                    self.root.after(0, self.update_modal_versions_list)
            except Exception as e:
                print(f"Fetch error: {e}")
                if win.winfo_exists():
                    self.root.after(0, lambda: self.modal_status_lbl.config(text=f"Error: {e}"))

        def update_list():
            if not win.winfo_exists(): return
            loader = loader_var.get()
            show_snaps = self.modal_show_snapshots.get()
            display_values = []
            
            for v in self.cached_loader_versions:
                if v['type'] == 'snapshot' and not show_snaps: continue
                
                is_inst = check_installed(v['id'], loader)
                entry = v['id']
                if not is_inst:
                     if loader == "Other versions (ie: BatMod, Laby Mod)":
                          entry += " (External Install Required)" # Hint that we might not auto-install these
                     else:
                          entry += " (Not Installed)"
                else: entry += " (Installed)" 
                display_values.append(entry)
            
            self.modal_ver_combo['values'] = display_values
            if display_values:
                self.modal_ver_combo.current(0)
                self.modal_ver_combo.config(state="readonly")
                self.modal_status_lbl.config(text=f"Found {len(display_values)} versions")
            else:
                self.modal_ver_combo.set("")
                if loader: self.modal_status_lbl.config(text="No versions found")

        self.update_modal_versions_list = update_list

        def on_loader_change(e):
            loader = loader_var.get()
            if not loader: return
            
            # Update Disclaimer
            if loader == "Other versions (ie: BatMod, Laby Mod)":
                self.disclaimer_lbl.pack(anchor="w", pady=(0, 10))
            else:
                self.disclaimer_lbl.pack_forget()

            self.modal_ver_combo.set("Fetching...")
            self.modal_ver_combo.config(state="disabled")
            self.modal_status_lbl.config(text=f"Fetching {loader} versions...")
            threading.Thread(target=fetch_versions_thread, args=(loader,), daemon=True).start()

        loader_combo.bind("<<ComboboxSelected>>", on_loader_change)
        
        # Trigger fetch if editing
        if edit_mode and loader_var.get():
             self.root.after(500, lambda: on_loader_change(None))
        
        def create_action():
             name = name_entry.get().strip() or "New Installation"
             v_selection = self.modal_version_var.get()
             # Allow keeping existing version if not fetching/changing
             if not v_selection or "Fetching" in v_selection: 
                 if edit_mode: v_selection = existing_data.get("version", "")
                 else: return
             
             version_id = v_selection.split(" ")[0]
             loader = loader_var.get()
             icon_val = current_icon_var.get()
             
             new_profile = {
                 "name": name,
                 "version": version_id,
                 "loader": loader,
                 "icon": icon_val,
                 "last_played": existing_data.get("last_played", "Never"),
                 "created": existing_data.get("created", "2024-01-01")
             }
             
             if edit_mode and index is not None:
                 self.installations[index] = new_profile
             else:
                 self.installations.append(new_profile)
                 
             self.save_config()
             self.refresh_installations_list()
             self.update_installation_dropdown()
             win.destroy()

        # --- Footer Actions ---
        btn_row = tk.Frame(win, bg="#1e1e1e")
        btn_row.pack(side="bottom", fill="x", padx=25, pady=25)
        
        btn_text = "Save" if edit_mode else "Create"
        # Create/Save (Green)
        tk.Button(btn_row, text=btn_text, bg=COLORS['success_green'], fg="white", font=("Segoe UI", 10, "bold"),
                 relief="flat", padx=25, pady=8, cursor="hand2",
                 command=create_action).pack(side="right", padx=(10, 0))
                 
        # Cancel (Text only typically, but we keep button style for consistency)
        tk.Button(btn_row, text="Cancel", bg="#1e1e1e", fg="white", font=("Segoe UI", 10),
                 relief="flat", padx=15, pady=8, cursor="hand2",
                 activebackground="#1e1e1e", activeforeground="#B0B0B0",
                 command=win.destroy).pack(side="right")

    def open_installation_menu(self, idx, btn_widget):
        # Create a popup menu (Edit, Delete)
        menu = tk.Toplevel(self.root)
        menu.wm_overrideredirect(True)
        menu.config(bg=COLORS['card_bg'])
        
        # Position
        try:
             x = btn_widget.winfo_rootx()
             y = btn_widget.winfo_rooty() + btn_widget.winfo_height()
             menu.geometry(f"120x80+{x-80}+{y}") 
        except:
             menu.geometry("120x80")
             

        # Edit
        def do_edit():
            menu.destroy()
            self.edit_installation(idx)
            
        edit_btn = tk.Label(menu, text="Edit", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_primary'], anchor="w", padx=10, pady=5)
        edit_btn.pack(fill="x")
        edit_btn.bind("<Button-1>", lambda e: do_edit())
        edit_btn.bind("<Enter>", lambda e: edit_btn.config(bg="#454545"))
        edit_btn.bind("<Leave>", lambda e: edit_btn.config(bg=COLORS['card_bg']))

        # Delete
        def do_delete():
            menu.destroy()
            if messagebox.askyesno("Delete", "Are you sure you want to delete this installation?"):
                self.installations.pop(idx)
                self.save_config()
                self.refresh_installations_list()
                self.update_installation_dropdown()
            
        del_btn = tk.Label(menu, text="Delete", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['error_red'], anchor="w", padx=10, pady=5)
        del_btn.pack(fill="x")
        del_btn.bind("<Button-1>", lambda e: do_delete())
        del_btn.bind("<Enter>", lambda e: del_btn.config(bg="#454545"))
        del_btn.bind("<Leave>", lambda e: del_btn.config(bg=COLORS['card_bg']))

        # Close on click outside
        menu.bind("<FocusOut>", lambda e: self.root.after(100, lambda: menu.destroy() if menu.winfo_exists() else None))
        menu.focus_set()

    def edit_installation(self, idx):
        self.open_new_installation_modal(edit_mode=True, index=idx)

    # --- LOCKER TAB (Skins/Wallpapers) ---
    def create_locker_tab(self):
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Locker"] = frame
        
        # Sub-tabs Header
        header = tk.Frame(frame, bg=COLORS['main_bg'], pady=20)
        header.pack(fill="x")
        
        self.locker_view = tk.StringVar(value="Skins")
        
        btn_frame = tk.Frame(header, bg=COLORS['input_bg'])
        btn_frame.pack()
        
        def switch_view(v):
            self.locker_view.set(v)
            self.refresh_locker_view()
            
        self.locker_btns = {}
        for v in ["Skins", "Wallpapers"]:
             b = tk.Button(btn_frame, text=v, font=("Segoe UI", 10, "bold"),
                          command=lambda x=v: switch_view(x), relief="flat", padx=20, pady=5)
             b.pack(side="left")
             self.locker_btns[v] = b
             
        self.locker_content = tk.Frame(frame, bg=COLORS['main_bg'])
        self.locker_content.pack(fill="both", expand=True)
        
        self.refresh_locker_view()
        
    def refresh_locker_view(self):
        v = self.locker_view.get()
        # Update buttons
        for name, btn in self.locker_btns.items():
            if name == v:
                btn.config(bg=COLORS['success_green'], fg="white")
            else:
                btn.config(bg=COLORS['input_bg'], fg=COLORS['text_primary'])
        
        for w in self.locker_content.winfo_children(): w.destroy()
        
        if v == "Skins":
            self.render_skins_view(self.locker_content)
        else:
            self.render_wallpapers_view(self.locker_content)

    def render_skins_view(self, parent):
        # Main Container
        container = tk.Frame(parent, bg=COLORS['main_bg'])
        container.pack(expand=True, fill="both", padx=40, pady=40)
        
        # Configure Grid - 2 Columns
        # Column 0: Preview (Larger)
        # Column 1: Controls (Sidebar)
        container.columnconfigure(0, weight=3) # Preview takes 3 parts
        container.columnconfigure(1, weight=2, minsize=300) # Controls takes 2 parts
        container.rowconfigure(0, weight=1)
        
        # --- LEFT: PREVIEW AREA ---
        # Using a Frame to center the content
        preview_area = tk.Frame(container, bg=COLORS['main_bg'])
        preview_area.grid(row=0, column=0, sticky="nsew", padx=(0, 40))
        
        # We use pack with expand=True to center the card vertically/horizontally inside the area
        self.preview_card = tk.Frame(preview_area, bg=COLORS['card_bg'], padx=40, pady=40)
        self.preview_card.place(relx=0.5, rely=0.5, anchor="center") # Centered perfectly
        
        tk.Label(self.preview_card, text="CURRENT SKIN", font=("Segoe UI", 12, "bold"), 
                 bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(pady=(0, 20))

        # Canvas for the Skin
        self.preview_canvas = tk.Canvas(self.preview_card, bg=COLORS['card_bg'], width=300, height=360, highlightthickness=0)
        self.preview_canvas.pack()
        
        self.skin_indicator = tk.Label(self.preview_card, text="", 
                                      font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary'])
        self.skin_indicator.pack(pady=10)

        # --- RIGHT: CONTROLS AREA ---
        controls_area = tk.Frame(container, bg=COLORS['main_bg'])
        controls_area.grid(row=0, column=1, sticky="nsew")
        
        # Inner layout for controls
        controls_area.columnconfigure(0, weight=1)
        
        # 1. Config Card (Model Selection & Injection)
        config_frame = tk.Frame(controls_area, bg=COLORS['card_bg'], padx=20, pady=20)
        config_frame.pack(fill="x", pady=(0, 20))
        
        # Grid inside the card: Left (Model), Right (Injection)
        config_frame.columnconfigure(0, weight=1)
        config_frame.columnconfigure(1, weight=1)
        
        # -- Model (Left) --
        m_frame = tk.Frame(config_frame, bg=COLORS['card_bg'])
        m_frame.grid(row=0, column=0, sticky="w")
        
        tk.Label(m_frame, text="MODEL TYPE", font=("Segoe UI", 10, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 5))
        
        if self.profiles:
             p = self.profiles[self.current_profile_index]
             model_val = p.get("skin_model", "classic")
             self.skin_model_var = tk.StringVar(value=model_val)
        else:
             self.skin_model_var = tk.StringVar(value="classic")
             
        r_frame = tk.Frame(m_frame, bg=COLORS['card_bg'])
        r_frame.pack(fill="x", anchor="w")
        
        tk.Radiobutton(r_frame, text="Classic", variable=self.skin_model_var, value="classic",
                      bg=COLORS['card_bg'], fg=COLORS['text_primary'], selectcolor=COLORS['card_bg'], activebackground=COLORS['card_bg'],
                      command=self.update_skin_model).pack(side="left", padx=(0, 15))
                      
        tk.Radiobutton(r_frame, text="Slim", variable=self.skin_model_var, value="slim",
                      bg=COLORS['card_bg'], fg=COLORS['text_primary'], selectcolor=COLORS['card_bg'], activebackground=COLORS['card_bg'],
                      command=self.update_skin_model).pack(side="left")

        # -- Injection (Right) --
        # Add a separator? No, just spacing
        i_frame = tk.Frame(config_frame, bg=COLORS['card_bg'])
        i_frame.grid(row=0, column=1, sticky="w", padx=(20, 0))
        
        tk.Label(i_frame, text="OPTIONS", font=("Segoe UI", 10, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 5))
        
        self.auto_download_var = tk.BooleanVar(value=self.auto_download_mod)
        cb = tk.Checkbutton(i_frame, text="Skin Injection", variable=self.auto_download_var,
                      bg=COLORS['card_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['card_bg'], activebackground=COLORS['card_bg'],
                      font=("Segoe UI", 10),
                      command=lambda: self._set_auto_download(self.auto_download_var.get()))
        cb.pack(anchor="w")
        # Tooltip or subtitle
        tk.Label(i_frame, text="(Offline Mode)", font=("Segoe UI", 8), fg=COLORS['text_secondary'], bg=COLORS['card_bg']).pack(anchor="w", padx=20)

        # 2. Actions Card
        act_frame = tk.Frame(controls_area, bg=COLORS['card_bg'], padx=20, pady=20)
        act_frame.pack(fill="x", pady=(0, 20))
        
        tk.Label(act_frame, text="ACTIONS", font=("Segoe UI", 10, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 10))

        # Using a grid for buttons to make them uniform
        btn_grid = tk.Frame(act_frame, bg=COLORS['card_bg'])
        btn_grid.pack(fill="x")
        
        tk.Button(btn_grid, text="Upload Skin File", font=("Segoe UI", 10),
                 bg=COLORS['accent_blue'], fg="white", activebackground=COLORS['button_hover'], activeforeground="white",
                 relief="flat", bd=0, pady=8, cursor="hand2", width=20,
                 command=self.select_skin).pack(side="left", fill="x", expand=True, padx=(0, 10))

        tk.Button(btn_grid, text="Refresh", font=("Segoe UI", 10),
                 bg=COLORS['input_bg'], fg=COLORS['text_primary'], activebackground=COLORS['button_hover'],
                 relief="flat", bd=0, pady=8, cursor="hand2", width=10,
                 command=self.refresh_skin).pack(side="left")
                 
        # 4. Recent History (Fill Remaining)
        hist_frame = tk.Frame(controls_area, bg=COLORS['card_bg'], padx=20, pady=20)
        hist_frame.pack(fill="both", expand=True) # Fills the rest of the height
        
        tk.Label(hist_frame, text="RECENT SKINS", font=("Segoe UI", 10, "bold"), 
                            bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 10))

        self.history_canvas = tk.Canvas(hist_frame, bg=COLORS['card_bg'], highlightthickness=0)
        self.history_scroll = ttk.Scrollbar(hist_frame, orient="vertical", command=self.history_canvas.yview)
        self.history_frame = tk.Frame(self.history_canvas, bg=COLORS['card_bg'])

        self.history_canvas.create_window((0, 0), window=self.history_frame, anchor="nw")
        self.history_canvas.configure(yscrollcommand=self.history_scroll.set)
        
        self.history_frame.bind("<Configure>", lambda e: self.history_canvas.configure(scrollregion=self.history_canvas.bbox("all")))
        self.history_canvas.bind_all("<MouseWheel>", lambda e: self.history_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self.history_canvas.pack(side="left", fill="both", expand=True)
        self.history_scroll.pack(side="right", fill="y")
        
        # Initial Render logic...
        self.render_skin_history()
        
        if self.profiles: self.update_active_profile()

    def update_skin_model(self):
        val = self.skin_model_var.get()
        if self.profiles:
            self.profiles[self.current_profile_index]["skin_model"] = val
            self.save_config()
        # Force re-render of skin
        self.update_active_profile()

    def render_wallpapers_view(self, parent):
        container = tk.Frame(parent, bg=COLORS['main_bg'], padx=40, pady=20)
        container.pack(fill="both", expand=True)
        
        tk.Label(container, text="Select a background", font=("Segoe UI", 12, "bold"), bg=COLORS['main_bg'], fg="white").pack(anchor="w", pady=(0, 20))
        
        grid = tk.Frame(container, bg=COLORS['main_bg'])
        grid.pack(fill="both", expand=True)
        
        # Defaults
        defaults = ["background.png", "image1.png"]
        
        row, col = 0, 0
        for fname in defaults:
            path = resource_path(fname)
            if not os.path.exists(path): continue
            
            p_frame = tk.Frame(grid, bg=COLORS['card_bg'], padx=5, pady=5)
            p_frame.grid(row=row, column=col, padx=10, pady=10)
            
            # Thumb
            try:
                img = Image.open(path)
                img.thumbnail((200, 120))
                tk_img = ImageTk.PhotoImage(img)
                lbl = tk.Button(p_frame, image=tk_img, bg=COLORS['card_bg'], relief="flat",
                               command=lambda p=path: self.set_wallpaper(p))
                lbl.image = tk_img # type: ignore
                lbl.pack()
                tk.Label(p_frame, text=fname, bg=COLORS['card_bg'], fg="white").pack()
            except: pass
            
            col += 1
            
        # Add Custom
        btn = tk.Button(grid, text="+ Add Wallpaper", font=("Segoe UI", 12),
                       bg=COLORS['input_bg'], fg="white", relief="flat", width=20, height=5,
                       command=self.add_custom_wallpaper)
        btn.grid(row=row, column=col, padx=10, pady=10)

    def add_custom_wallpaper(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png;*.jpg;*.jpeg")])
        if path:
            self.set_wallpaper(path)

    def set_wallpaper(self, path):
        if not path or not os.path.exists(path): return
        
        # Save wallpaper to local config dir so it persists even if source is deleted
        try:
            wp_dir = os.path.join(self.config_dir, "wallpapers")
            if not os.path.exists(wp_dir):
                os.makedirs(wp_dir)
            
            # Check if we are already using a file in the config dir to avoid unnecessary copy
            abs_path = os.path.abspath(path)
            abs_wp_dir = os.path.abspath(wp_dir)

            if not abs_path.startswith(abs_wp_dir):
                # Calculate hash of source file to detect duplicates
                BUF_SIZE = 65536
                sha1 = hashlib.sha1()
                with open(path, 'rb') as f:
                    while True:
                        data = f.read(BUF_SIZE)
                        if not data: break
                        sha1.update(data)
                src_hash = sha1.hexdigest()
                
                # Check existance in target dir
                existing_file = None
                for wp in os.listdir(wp_dir):
                    wp_path = os.path.join(wp_dir, wp)
                    if not os.path.isfile(wp_path): continue
                    
                    # Compute hash for existing
                    try:
                        sha1_e = hashlib.sha1()
                        with open(wp_path, 'rb') as f:
                            while True:
                                data = f.read(BUF_SIZE)
                                if not data: break
                                sha1_e.update(data)
                        if sha1_e.hexdigest() == src_hash:
                            existing_file = wp_path
                            break
                    except: pass
                
                if existing_file:
                    path = existing_file
                    print(f"Using existing wallpaper: {path}")
                else:
                    filename = os.path.basename(path)
                    # Unique Name
                    name, ext = os.path.splitext(filename)
                    new_filename = f"{name}_{int(time.time())}{ext}"
                    new_path = os.path.join(wp_dir, new_filename)
                    shutil.copy2(path, new_path)
                    path = new_path
                    print(f"Wallpaper saved to: {path}")

        except Exception as e:
            print(f"Failed to save wallpaper locally: {e}")
            # Continue using original path if copy fails

        self.current_wallpaper = path
        # Reload hero
        try:
            self.hero_img_raw = Image.open(path)
            # Trigger resize
            w = self.hero_canvas.winfo_width()
            h = self.hero_canvas.winfo_height()
            self._update_hero_layout(type('obj', (object,), {'width':w, 'height':h}))
            self.save_config()
        except Exception as e:
            print(f"Wallpaper error: {e}")

    def render_skin_history(self):
        if not hasattr(self, 'history_frame') or not self.history_frame.winfo_exists(): return
        
        # Clear existing
        for w in self.history_frame.winfo_children(): w.destroy()
        
        if not self.profiles: return
        p = self.profiles[self.current_profile_index]
        history = cast(list, p.get("skin_history", []))
        
        if not history:
             tk.Label(self.history_frame, text="No history", bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(pady=10, padx=10)
             return

        for idx, path in enumerate(history):
             if not os.path.exists(path): continue
             
             item = tk.Frame(self.history_frame, bg=COLORS['card_bg'], pady=5, padx=5, cursor="hand2")
             item.pack(fill="x", pady=2, padx=5)
             
             # Tiny Head Preview
             head = self.get_head_from_skin(path, size=32)
             if head:
                 icon = tk.Label(item, image=head, bg=COLORS['card_bg'])
                 icon.image = head # type: ignore
                 icon.pack(side="left", padx=5)
             
             name = os.path.basename(path)
             if len(name) > 20: name = name[:17] + "..."
             
             tk.Label(item, text=name, bg=COLORS['card_bg'], fg=COLORS['text_primary'], font=("Segoe UI", 9)).pack(side="left")
             
             def _apply(p=path):
                 self.apply_history_skin(p)
                 
             item.bind("<Button-1>", lambda e, p=path: _apply(p))
             for child in item.winfo_children():
                 child.bind("<Button-1>", lambda e, p=path: _apply(p))

    def apply_history_skin(self, path):
        if not os.path.exists(path): return
        self.skin_path = path
        if self.profiles:
             self.profiles[self.current_profile_index]["skin_path"] = path
        self.update_active_profile()
        self.save_config()
        # Move to top of history
        self.add_skin_to_history(path)

    def add_skin_to_history(self, path):
        if not self.profiles or not path: return
        p = self.profiles[self.current_profile_index]
        history = cast(list, p.get("skin_history", []))
        
        # Avoid duplicates or invalid
        if path in history:
            history.remove(path)
        history.insert(0, path)
        if len(history) > 20: history = history[:20]
        
        p["skin_history"] = history # type: ignore
        self.save_config()
        self.render_skin_history()

    def toggle_profile_menu(self):
        if hasattr(self, 'profile_menu') and self.profile_menu.winfo_exists():
            self.profile_menu.destroy()
            return

        menu = tk.Toplevel(self.root)
        menu.overrideredirect(True)
        menu.config(bg=COLORS['card_bg'])
        self.profile_menu = menu

        try:
            x = self.sidebar.winfo_rootx() + self.sidebar.winfo_width()
            y = self.profile_frame.winfo_rooty()
            menu.geometry(f"250x300+{x}+{y}")
        except: 
            menu.geometry("250x300")

        tk.Label(menu, text="ACCOUNTS", font=("Segoe UI", 10, "bold"), 
                bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w", padx=15, pady=10)

        list_frame = tk.Frame(menu, bg=COLORS['card_bg'])
        list_frame.pack(fill="both", expand=True)

        if not self.profiles:
             tk.Label(list_frame, text="No profiles", bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(pady=10)
        else:
            for idx, p in enumerate(self.profiles):
                self.create_profile_item(list_frame, idx, p)

        footer = tk.Frame(menu, bg=COLORS['bottom_bar_bg'], height=45)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        tk.Button(footer, text="+ Add Account", font=("Segoe UI", 9), 
                 bg=COLORS['bottom_bar_bg'], fg=COLORS['text_primary'], relief="flat", bd=0, cursor="hand2",
                 command=self.open_add_account_modal).pack(side="left", padx=10, fill="y")

        menu.bind("<FocusOut>", lambda e: self._close_menu_delayed(menu))
        menu.focus_set()

    def _close_menu_delayed(self, menu):
        # Small delay to allow button clicks inside
        self.root.after(200, lambda: menu.destroy() if menu.winfo_exists() and self.root.focus_get() != menu else None)

    def delete_profile(self, idx):
        if not self.profiles or idx < 0 or idx >= len(self.profiles): return
        
        p_name = self.profiles[idx].get("name", "Account")
        if messagebox.askyesno("Remove Account", f"Are you sure you want to remove account '{p_name}'?"):
            del self.profiles[idx]
            
            # Reset index if needed
            if self.current_profile_index >= len(self.profiles):
                self.current_profile_index = max(0, len(self.profiles) - 1)
            
            if not self.profiles:
                self.create_default_profile()
            
            self.save_config()
            self.update_active_profile()
            
            # Close menu to refresh
            if hasattr(self, 'profile_menu'): self.profile_menu.destroy()
            # Re-open if we want, but better just close

    def create_profile_item(self, parent, idx, profile):
        is_active = (idx == self.current_profile_index)
        bg = "#454545" if is_active else COLORS['card_bg']
        
        frame = tk.Frame(parent, bg=bg, pady=8, padx=10, cursor="hand2")
        frame.pack(fill="x", pady=1)
        
        head = self.get_head_from_skin(profile.get("skin_path"), size=24)
        lbl_icon = tk.Label(frame, image=head, bg=bg) # type: ignore
        lbl_icon.image = head # type: ignore # keep ref
        lbl_icon.pack(side="left", padx=(0, 10))
        
        tk.Label(frame, text=profile.get("name", "Unknown"), font=("Segoe UI", 10, "bold"),
                bg=bg, fg=COLORS['text_primary']).pack(side="left")
        
        # Delete Button
        del_btn = tk.Button(frame, text="-", font=("Segoe UI", 12, "bold"),
                           bg=bg, fg="#ff6b6b", activebackground=bg, activeforeground="#ff4444",
                           relief="flat", bd=0, cursor="hand2",
                           command=lambda: self.delete_profile(idx))
        
        # Only show delete if strictly more than 1 profile? Or allow deleting the last one (which resets to default)?
        # User said "right of every account".
        # Standard launcher behavior typically allows removing any added account.
        del_btn.pack(side="right", padx=(5, 0))

        tk.Label(frame, text=profile.get("type", "offline").title(), font=("Segoe UI", 8),
                bg=bg, fg=COLORS['text_secondary']).pack(side="right")
        
        def on_click(e):
            self.current_profile_index = idx
            self.update_active_profile()
            if hasattr(self, 'profile_menu'): self.profile_menu.destroy()
            
        frame.bind("<Button-1>", on_click)
        for child in frame.winfo_children():
            if child != del_btn:
                child.bind("<Button-1>", on_click)

    def open_add_account_modal(self):
        if hasattr(self, 'profile_menu'): self.profile_menu.destroy()
        
        win = tk.Toplevel(self.root)
        win.title("Add Account")
        win.geometry("400x420")
        win.config(bg=COLORS['main_bg'])
        try:
            win.geometry(f"+{self.root.winfo_x() + 340}+{self.root.winfo_y() + 150}")
        except: pass
        win.transient(self.root)
        win.resizable(False, False)

        tk.Label(win, text="Add a new account", font=("Segoe UI", 16, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(30, 20))
        
        tk.Button(win, text="Microsoft Account", font=("Segoe UI", 11),
                 bg=COLORS['play_btn_green'], fg="white", width=25, pady=8, relief="flat", cursor="hand2",
                 command=lambda: messagebox.showinfo("Info", "Microsoft Auth placeholder")).pack(pady=5)

        tk.Button(win, text="Ely.by Account", font=("Segoe UI", 11),
                 bg="#3498DB", fg="white", width=25, pady=8, relief="flat", cursor="hand2",
                 command=lambda: self.show_elyby_login(win)).pack(pady=5)
                 
        tk.Button(win, text="Offline Account", font=("Segoe UI", 11),
                 bg=COLORS['input_bg'], fg=COLORS['text_primary'], width=25, pady=8, relief="flat", cursor="hand2",
                 command=lambda: self.show_offline_login(win)).pack(pady=5)

    def show_elyby_login(self, parent):
        for widget in parent.winfo_children(): widget.destroy()
        
        tk.Label(parent, text="Ely.by Login", font=("Segoe UI", 16, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(20, 10))

        frame = tk.Frame(parent, bg=COLORS['main_bg'])
        frame.pack(fill="x", padx=40)

        tk.Label(frame, text="Username / Email", font=("Segoe UI", 9), bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        user_entry = tk.Entry(frame, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat")
        user_entry.pack(fill="x", ipady=5, pady=(5, 15))

        tk.Label(frame, text="Password", font=("Segoe UI", 9), bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        pass_entry = tk.Entry(frame, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", show="*")
        pass_entry.pack(fill="x", ipady=5, pady=(5, 20))

        def do_login():
            u = user_entry.get().strip()
            p = pass_entry.get().strip()
            if not u or not p:
                messagebox.showerror("Error", "Please fill all fields")
                return
            
            res = ElyByAuth.authenticate(u, p)
            if "error" in res:
                messagebox.showerror("Login Failed", f"Could not login to Ely.by details: {res['error']}")
            else:
                # Success
                profile = cast(dict, res.get("selectedProfile", {}))
                uuid_ = profile.get("id", "")
                name_ = profile.get("name", u)
                token = res.get("accessToken", "")
                
                # Fetch Skin using shared logic
                skin_cache_path = self.fetch_elyby_skin(name_, uuid_, profile.get("properties", []))

                new_profile = {
                    "name": name_,
                    "type": "ely.by",
                    "skin_path": skin_cache_path, 
                    "uuid": uuid_,
                    "token": token
                }
                self.profiles.append(new_profile)
                self.current_profile_index = len(self.profiles) - 1
                self.update_active_profile()
                self.add_skin_to_history(skin_cache_path)
                self.save_config()
                parent.destroy()
                messagebox.showinfo("Success", f"Logged in as {name_}")

        tk.Button(parent, text="Login", font=("Segoe UI", 11, "bold"),
                 bg=COLORS['play_btn_green'], fg="white", width=25, pady=8, relief="flat", cursor="hand2",
                 command=do_login).pack(pady=10)

    def show_offline_login(self, parent):
        for widget in parent.winfo_children(): widget.destroy()
        
        tk.Label(parent, text="Offline Account", font=("Segoe UI", 16, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(30, 10))
                
        tk.Label(parent, text="Username", bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w", padx=60)
        entry = tk.Entry(parent, font=("Segoe UI", 11), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", insertbackground="white")
        entry.pack(fill="x", padx=60, pady=(5, 30), ipady=8)
        entry.focus()
        
        def save():
            name = entry.get().strip()
            if name:
                self.profiles.append({"name": name, "type": "offline", "skin_path": "", "uuid": ""})
                self.current_profile_index = len(self.profiles) - 1
                self.update_active_profile()
                self.save_config()
                parent.destroy()
        
        tk.Button(parent, text="Add Account", font=("Segoe UI", 11, "bold"),
                 bg=COLORS['play_btn_green'], fg="white", relief="flat", width=20, cursor="hand2",
                 command=save).pack(pady=10)

    # --- SETTINGS TAB ---
    def create_settings_tab(self):
        container = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Settings"] = container
        
        # Create a canvas with scrollbar
        canvas = tk.Canvas(container, bg=COLORS['main_bg'], highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        
        scrollable_frame = tk.Frame(canvas, bg=COLORS['main_bg'])
        
        # Configure scrolling
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=container.winfo_reqwidth())
        # Bind canvas resize to frame width to ensure fill
        def on_canvas_configure(event):
            canvas.itemconfig(canvas.find_withtag("all")[0], width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)

        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind mousewheel to canvas
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        # Bind all children to mousewheel
        def bind_to_mousewheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                bind_to_mousewheel(child)

        # Main container with padding (inside scrollable frame)
        main_container = tk.Frame(scrollable_frame, bg=COLORS['main_bg'])
        main_container.pack(fill="both", expand=True, padx=40, pady=30)
        
        # --- JAVA SETTINGS ---
        tk.Label(main_container, text="JAVA SETTINGS", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 15))
        
        # Minecraft Directory
        tk.Label(main_container, text="Minecraft Directory", font=("Segoe UI", 10),
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        
        dir_frame = tk.Frame(main_container, bg=COLORS['main_bg'])
        dir_frame.pack(fill="x", pady=(5, 15))
        
        self.dir_entry = tk.Entry(dir_frame, font=("Segoe UI", 10),
                                 bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                                 relief="flat", insertbackground="white")
        self.dir_entry.pack(side="left", fill="x", expand=True, ipady=5)
        
        tk.Button(dir_frame, text="Change", font=("Segoe UI", 9),
                 bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                 relief="flat", command=self.change_minecraft_dir).pack(side="left", padx=(10, 0))
                 
        tk.Button(dir_frame, text="Open", font=("Segoe UI", 9),
                 bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                 relief="flat", command=self.open_minecraft_dir).pack(side="left", padx=(5, 0))

        # Java Arguments
        tk.Label(main_container, text="Java Arguments (JVM Flags)", font=("Segoe UI", 10),
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        
        self.java_args_entry = tk.Entry(main_container, font=("Segoe UI", 10),
                                       bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                                       relief="flat", insertbackground="white")
        self.java_args_entry.pack(fill="x", pady=(5, 15), ipady=5)
        self.java_args_entry.bind("<FocusOut>", self.save_config)

        # Allocations
        tk.Label(main_container, text="Allocated Memory (MB)", font=("Segoe UI", 10),
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        
        self.ram_var = tk.IntVar(value=DEFAULT_RAM)
        self.ram_entry_var = tk.StringVar(value=str(DEFAULT_RAM))
        self.ram_entry_var.trace_add("write", self._on_ram_entry_change)
        
        ram_row = tk.Frame(main_container, bg=COLORS['main_bg'])
        ram_row.pack(fill="x", pady=(5, 10))
        
        tk.Scale(ram_row, from_=1024, to=16384, orient="horizontal", resolution=512,
                variable=self.ram_var, showvalue=0, bg=COLORS['main_bg'], fg=COLORS['text_primary'], # type: ignore
                troughcolor=COLORS['input_bg'], highlightthickness=0,
                command=self._on_ram_slider_change).pack(side="left", fill="x", expand=True)
                
        tk.Entry(ram_row, textvariable=self.ram_entry_var, width=8,
                bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat",
                insertbackground="white").pack(side="left", padx=(10, 0), ipady=4)

        # Discord RPC
        tk.Label(main_container, text="DISCORD INTEGRATION", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(anchor="w", pady=(20, 15))

        self.rpc_var = tk.BooleanVar(value=True)
        self.rpc_show_version_var = tk.BooleanVar(value=True)
        self.rpc_show_server_var = tk.BooleanVar(value=True)

        tk.Checkbutton(main_container, text="Enable Rich Presence", variable=self.rpc_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=self._on_rpc_toggle).pack(anchor="w", pady=(0, 5))
                      
        tk.Checkbutton(main_container, text="Show Game Version", variable=self.rpc_show_version_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=self.save_config).pack(anchor="w", padx=(20, 0), pady=(0, 5))

        tk.Checkbutton(main_container, text="Show Server IP", variable=self.rpc_show_server_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=self.save_config).pack(anchor="w", padx=(20, 0), pady=(0, 20))

        # --- ACCOUNT ---
        tk.Label(main_container, text="ACCOUNT", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(anchor="w", pady=(10, 15))
        
        tk.Label(main_container, text="Username", font=("Segoe UI", 10),
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        
        self.user_entry = tk.Entry(main_container, font=("Segoe UI", 11),
                                  bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                                  relief="flat", insertbackground="white")
        self.user_entry.pack(fill="x", pady=(5, 0), ipady=8)
        self.user_entry.bind("<FocusOut>", self.save_config)

        # --- LOGS ---
        tk.Label(main_container, text="LAUNCHER LOGS", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(anchor="w", pady=(30, 15))
        
        self.log_area = scrolledtext.ScrolledText(main_container, height=6, bg=COLORS['input_bg'], 
                                                 fg=COLORS['text_secondary'], font=("Consolas", 9), relief="flat")
        self.log_area.pack(fill="both", expand=True)

        # --- UPDATES ---
        tk.Label(main_container, text="UPDATES", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(anchor="w", pady=(30, 15))
        
        update_frame = tk.Frame(main_container, bg=COLORS['main_bg'])
        update_frame.pack(fill="x", anchor="w")

        tk.Label(update_frame, text=f"Current Version: {CURRENT_VERSION}", font=("Segoe UI", 10),
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(side="left", padx=(0, 20))
        
        tk.Button(update_frame, text="Check for Updates", font=("Segoe UI", 9),
                 bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                 relief="flat", command=self.check_for_updates).pack(side="left")

        self.update_status_lbl = tk.Label(main_container, text="", font=("Segoe UI", 9),
                                         bg=COLORS['main_bg'], fg=COLORS['text_secondary'])
        self.update_status_lbl.pack(anchor="w", pady=(5, 0))
        
        self.auto_update_var = tk.BooleanVar(value=self.auto_update_check)
        tk.Checkbutton(main_container, text="Automatically check for updates on startup", variable=self.auto_update_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=self.save_config).pack(anchor="w", pady=(5, 0))
        
        # Apply mousewheel binding after all widgets are added
        bind_to_mousewheel(scrollable_frame)
        canvas.bind("<MouseWheel>", _on_mousewheel)

    def change_minecraft_dir(self):
        path = filedialog.askdirectory(initialdir=self.minecraft_dir)
        if path:
            self.minecraft_dir = path
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, path)
            self.load_versions()

    def check_for_updates(self):
        self.update_status_lbl.config(text="Checking for updates...", fg=COLORS['text_secondary'])
        threading.Thread(target=self._update_check_thread, daemon=True).start()

    def _update_check_thread(self):
        try:
            url = "https://api.github.com/repos/Amne-Dev/New-launcher/releases/latest"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                latest_tag = data.get("tag_name", "").lstrip("v")
                
                # Check for updates (Simple Semantic Versioning)
                try:
                    current_parts = [int(x) for x in CURRENT_VERSION.split(".")]
                    latest_parts = [int(x) for x in latest_tag.split(".")]
                    
                    update_available = False
                    # Compare parts
                    for i in range(max(len(current_parts), len(latest_parts))):
                        cur = current_parts[i] if i < len(current_parts) else 0
                        lat = latest_parts[i] if i < len(latest_parts) else 0
                        if lat > cur:
                            update_available = True
                            break
                        elif lat < cur:
                            break # Latest is older than current
                            
                    if update_available:
                        self.root.after(0, lambda: self._on_update_found(latest_tag, data.get("html_url")))
                    else:
                         self.root.after(0, lambda: self.update_status_lbl.config(text="You are on the latest version.", fg=COLORS['success_green']))

                except ValueError:
                    # Fallback to string comparison if version format is weird
                    if latest_tag and latest_tag != CURRENT_VERSION:
                         self.root.after(0, lambda: self._on_update_found(latest_tag, data.get("html_url")))
                    else:
                         self.root.after(0, lambda: self.update_status_lbl.config(text="You are on the latest version.", fg=COLORS['success_green']))
            else:
                 self.root.after(0, lambda: self.update_status_lbl.config(text=f"Failed to check: {response.status_code}", fg=COLORS['error_red']))
        except Exception as e:
            self.root.after(0, lambda: self.update_status_lbl.config(text=f"Error checking updates", fg=COLORS['error_red']))
            print(f"Update check error: {e}")

    def _on_update_found(self, version, url):
        self.update_status_lbl.config(text=f"New version available: {version}", fg=COLORS['accent_blue'])
        if messagebox.askyesno("Update Available", f"A new version ({version}) is available.\nDo you want to download it now?"):
            if url:
                webbrowser.open(url)
            self.save_config()

    def open_minecraft_dir(self):
        try:
            os.startfile(self.minecraft_dir)
        except Exception as e:
            self.log(f"Error opening folder: {e}")

    # --- LOGIC ---
    def setup_logging(self):
        try:
            # Determine base directory (executable dir if frozen, else script dir)
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            log_dir = os.path.join(base_dir, "logs")
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)

            self.cleanup_old_logs(log_dir)
            
            fname = f"launcher_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
            self.log_file_path = os.path.join(log_dir, fname)
            
            with open(self.log_file_path, "w", encoding="utf-8") as f:
                f.write("Launcher initialized.\n")
        except Exception as e:
            print(f"Logging setup failed: {e}")
            self.log_file_path = None

    def cleanup_old_logs(self, log_dir):
        try:
            files = glob.glob(os.path.join(log_dir, "launcher_*.log"))
            files.sort(key=os.path.getmtime)
            while len(files) >= 5:
                try: os.remove(files.pop(0))
                except: pass
        except: pass

    def _on_ram_slider_change(self, value):
        try:
            val = int(float(value))
            self.ram_entry_var.set(str(val))
            self.ram_allocation = val
            self.save_config()
        except: pass

    def _on_ram_entry_change(self, *args):
        try:
            val = int(self.ram_entry_var.get())
            self.ram_allocation = val
            self.ram_var.set(val)
            self.save_config()
        except ValueError:
            pass

    def _on_rpc_toggle(self):
        self.rpc_enabled = self.rpc_var.get()
        if self.rpc_enabled:
            self.connect_rpc()
        else:
            self.close_rpc()
        self.save_config()

    def connect_rpc(self):
        if not RPC_AVAILABLE or not self.rpc_enabled or self.rpc_connected: return
        try:
            self.rpc = Presence("1458526248845443167") # pyright: ignore[reportPossiblyUnboundVariable] 
            self.rpc.connect()
            self.rpc_connected = True
            self.update_rpc("Idle", "In Launcher")
        except Exception as e:
            self.log(f"RPC Error: {e}")
            self.rpc_connected = False

    def close_rpc(self):
        if self.rpc:
            try: self.rpc.close()
            except: pass
        self.rpc_connected = False
        self.rpc = None

    def update_rpc(self, state, details=None, start=None):
        if not self.rpc_connected or not self.rpc: return
        try:
            kwargs = {
                "state": state,
                "details": details,
                "large_image": "logo", # Make sure you upload an art asset named 'logo' to your Discord App
                "large_text": "Minecraft Launcher"
            }
            if start: kwargs["start"] = start
            self.rpc.update(**kwargs)
        except Exception as e: 
            self.log(f"RPC Update Failed: {e}")
            self.rpc_connected = False

    def _set_auto_download(self, enabled):
        self.auto_download_mod = bool(enabled)
        self.save_config()

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        self.log_area.insert(tk.END, line + "\n")
        self.log_area.see(tk.END)
        
        log_path = getattr(self, 'log_file_path', None)
        if log_path:
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except: pass

    def set_status(self, text, color=None):
        self.status_label.config(text=text, fg=color if color else COLORS['text_secondary'])

    def get_head_from_skin(self, skin_path, size=40):
        try:
            if skin_path and os.path.exists(skin_path):
                img = Image.open(skin_path)
                # Head is 8x8 at 8,8
                head = img.crop((8, 8, 16, 16))
                return ImageTk.PhotoImage(head.resize((size, size), RESAMPLE_NEAREST))
        except: pass
        
        # Default Steve
        try:
            # Generate a simple blocky face
            img = Image.new('RGB', (8, 8), color='#7F684E') # Brown
            img.putpixel((1, 3), (255, 255, 255)) # Eyes
            img.putpixel((2, 3), (60, 60, 160))
            img.putpixel((5, 3), (255, 255, 255))
            img.putpixel((6, 3), (60, 60, 160))
            return ImageTk.PhotoImage(img.resize((size, size), RESAMPLE_NEAREST))
        except: return None

    def update_active_profile(self):
        if not self.profiles:
            self.skin_path = ""
            if hasattr(self, 'user_entry'):
                self.user_entry.delete(0, tk.END)
            self.update_profile_btn()
            return

        p = self.profiles[self.current_profile_index]
        self.skin_path = p.get("skin_path", "")
        
        if hasattr(self, 'user_entry'):
            self.user_entry.delete(0, tk.END)
            self.user_entry.insert(0, p.get("name", "Steve"))
        
        if self.skin_path:
            self.render_preview()
        
        # Update Model Radio var
        if hasattr(self, 'skin_model_var'):
            self.skin_model_var.set(p.get("skin_model", "classic"))

        self.update_skin_indicator()
        self.update_profile_btn()
        if hasattr(self, 'update_bottom_gamertag'): self.update_bottom_gamertag()
        self.save_config()

    def update_profile_btn(self):
        # Update text labels
        if not self.profiles: return
        p = self.profiles[self.current_profile_index]
        
        if hasattr(self, 'sidebar_username'):
            self.sidebar_username.config(text=p.get("name", "Steve"))
        
        if hasattr(self, 'sidebar_acct_type'):
            t = p.get("type", "offline")
            if t == "microsoft":
                label_text = "Microsoft Account"
            elif t == "ely.by":
                label_text = "Ely.by Account"
            else:
                label_text = "Offline Account"
            self.sidebar_acct_type.config(text=label_text)

        # Update Head Image
        if hasattr(self, 'sidebar_head_label'):
            img = self.get_head_from_skin(self.skin_path, size=35)
            if img:
                self.sidebar_head_img = img 
                self.sidebar_head_label.config(image=img)

    def load_from_config(self):
        print(f"Loading config from: {self.config_file}")
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                    # Profiles (Accounts)
                    self.profiles = data.get("profiles", [])
                    if not self.profiles:
                        old_user = data.get("username", DEFAULT_USERNAME)
                        old_skin = data.get("skin_path", "")
                        self.profiles = [{"name": old_user, "type": "offline", "skin_path": old_skin, "uuid": ""}]
                    
                    # Installations (Game Configs)
                    self.installations = data.get("installations", [])
                    if not self.installations:
                        # Create default
                        self.installations = [{
                            "name": "Latest Release",
                            "version": "latest-release", # Metadata placeholder
                            "loader": "Vanilla",
                            "icon": "icons/grass_block_side.png",
                            "last_played": "Never",
                            "created": "2024-01-01"
                        }]
                        print("Initialized default installations")
                    else:
                        print(f"Loaded {len(self.installations)} installations")
                    
                    idx = data.get("current_profile_index", 0)
                    self.current_profile_index = idx if 0 <= idx < len(self.profiles) else 0
                    
                    inst_idx = data.get("current_installation_index", 0)
                    self.current_installation_index = inst_idx if 0 <= inst_idx < len(self.installations) else 0

                    self.update_active_profile()

                    loader_choice = data.get("loader", LOADERS[0])
                    self.loader_var.set(loader_choice if loader_choice in LOADERS else LOADERS[0])
                    self.last_version = data.get("last_version", "")
                    self.auto_download_mod = data.get("auto_download_mod", False)
                    self.auto_download_var.set(self.auto_download_mod)
                    self.ram_allocation = data.get("ram_allocation", DEFAULT_RAM)
                    self.ram_var.set(self.ram_allocation)
                    self.ram_entry_var.set(str(self.ram_allocation))

                    # Load RPC
                    self.rpc_enabled = data.get("rpc_enabled", True)
                    self.rpc_var.set(self.rpc_enabled)
                    
                    self.rpc_show_version = data.get("rpc_show_version", True)
                    self.rpc_show_server = data.get("rpc_show_server", True)
                    self.auto_update_check = data.get("auto_update_check", True)
                    
                    if hasattr(self, 'rpc_show_version_var'):
                        self.rpc_show_version_var.set(self.rpc_show_version)
                    if hasattr(self, 'rpc_show_server_var'):
                        self.rpc_show_server_var.set(self.rpc_show_server)
                    if hasattr(self, 'auto_update_var'):
                        self.auto_update_var.set(self.auto_update_check)

                    if self.rpc_enabled:
                        self.root.after(1000, self.connect_rpc)

                    # Load Java Args
                    self.java_args = data.get("java_args", "")
                    if hasattr(self, 'java_args_entry'):
                        self.java_args_entry.delete(0, tk.END)
                        self.java_args_entry.insert(0, self.java_args)

                    # Load Custom Directory
                    custom_dir = data.get("minecraft_dir", "")
                    if custom_dir and os.path.isdir(custom_dir):
                        self.minecraft_dir = custom_dir
                    
                    if hasattr(self, 'dir_entry'):
                        self.dir_entry.delete(0, tk.END)
                        self.dir_entry.insert(0, self.minecraft_dir)
                    
                    # Load Wallpaper
                    wp = data.get("current_wallpaper")
                    if wp and os.path.exists(wp):
                         self.current_wallpaper = wp
                         try:
                             self.hero_img_raw = Image.open(wp)
                             if hasattr(self, 'hero_canvas'):
                                  w = self.hero_canvas.winfo_width()
                                  h = self.hero_canvas.winfo_height()
                                  # If window is already visible/sized
                                  if w > 1 and h > 1:
                                      self._update_hero_layout(type('obj', (object,), {'width':w, 'height':h}))
                         except Exception as e:
                             print(f"Failed to load saved wallpaper: {e}")
                    else:
                         self.current_wallpaper = None
                         
            except Exception as e: 
                print(f"Error loading config: {e}")
                self.create_default_profile()
        else: 
            print("Config file not found, creating default")
            self.create_default_profile()

    def save_config(self, *args):
        print(f"Saving config to: {self.config_file}")
        # Update current profile info before saving
        if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
            self.profiles[self.current_profile_index]["skin_path"] = self.skin_path
            # Sync username from entry if available
            if hasattr(self, 'user_entry'):
                 name = self.user_entry.get().strip()
                 if name:
                    self.profiles[self.current_profile_index]["name"] = name

        # Update java args from entry if it exists
        if hasattr(self, 'java_args_entry'):
             self.java_args = self.java_args_entry.get().strip()
             
        # Get RPC settings
        show_ver = True
        show_svr = True
        if hasattr(self, 'rpc_show_version_var'): show_ver = self.rpc_show_version_var.get()
        if hasattr(self, 'rpc_show_server_var'): show_svr = self.rpc_show_server_var.get()
        if hasattr(self, 'auto_update_var'): self.auto_update_check = self.auto_update_var.get()
        
        config = {
            "profiles": self.profiles,
            "installations": self.installations,
            "current_profile_index": self.current_profile_index,
            "current_installation_index": getattr(self, 'current_installation_index', 0),
            "loader": self.loader_var.get(), 
            "auto_download_mod": self.auto_download_mod, 
            "ram_allocation": self.ram_allocation,
            "java_args": self.java_args,
            "minecraft_dir": self.minecraft_dir,
            "rpc_enabled": self.rpc_enabled,
            "rpc_show_version": show_ver,
            "rpc_show_server": show_svr,
            "auto_update_check": self.auto_update_check,
            "current_wallpaper": getattr(self, 'current_wallpaper', None)
        }
        try:
            with open(self.config_file, "w", encoding="utf-8") as f: json.dump(config, f, indent=4)
            print("Config saved successfully")
        except Exception as e:
            print(f"Failed to save config: {e}")

    def create_default_profile(self):
        self.profiles = [{"name": DEFAULT_USERNAME, "type": "offline", "skin_path": "", "uuid": ""}]
        self.installations = [{
            "name": "Latest Release",
            "version": "latest-release",
            "loader": "Vanilla",
            "icon": "icons/grass_block_side.png",
            "last_played": "Never",
            "created": "2024-01-01"
        }]
        self.current_profile_index = 0
        self.current_installation_index = 0
        self.update_active_profile()

    def load_versions(self):
        pass

    def _apply_version_list(self, loader, display_list):
        pass



    def on_loader_change(self, event):
        pass

    def on_version_change(self, event):
        pass

    def launch_installation(self, idx):
        if 0 <= idx < len(self.installations):
            self.current_installation_index = idx
            self.show_tab("Play")
            self.update_installation_dropdown()
            self.start_launch()

    def update_skin_indicator(self):
        if not hasattr(self, 'skin_indicator') or not self.skin_indicator.winfo_exists(): return
        
        # Determine current account type
        current_profile = self.profiles[self.current_profile_index] if (self.profiles and 0 <= self.current_profile_index < len(self.profiles)) else {}
        acct_type = current_profile.get("type", "offline")

        if acct_type == "ely.by":
            self.skin_indicator.config(text="Skin via Ely.by", fg=COLORS['success_green'])
            return

        # Offline
        if self.auto_download_mod:
             if self.skin_path:
                 self.skin_indicator.config(text="Ready: Local Skin Injection", fg=COLORS['success_green'])
             else:
                 self.skin_indicator.config(text="Injection enabled (No Skin)", fg=COLORS['accent_blue'])
        else:
            self.skin_indicator.config(text="Skin Injection Disabled", fg=COLORS['text_secondary'])

    def check_mod_online(self, mc_version, loader):
        pass # Deprecated

    def render_preview(self):
        try:
            if not self.skin_path or not os.path.exists(self.skin_path): 
                 if hasattr(self, 'preview_canvas'): self.preview_canvas.delete("all")
                 return
            
            # Determine model
            model = "classic"
            if self.profiles:
                 model = self.profiles[self.current_profile_index].get("skin_model", "classic")

            # Use 3D Renderer
            if hasattr(self, 'preview_canvas'):
                 w = self.preview_canvas.winfo_width()
                 h = self.preview_canvas.winfo_height()
                 # Defaults if not mapped yet
                 if w < 50: w = 300
                 if h < 50: h = 360
                 
                 rendered = SkinRenderer3D.render(self.skin_path, model, height=int(h * 0.9))
                 if rendered:
                     self.preview_photo = ImageTk.PhotoImage(rendered)
                     self.preview_canvas.delete("all")
                     self.preview_canvas.create_image(w//2, h//2, image=self.preview_photo, anchor="center")
        except Exception as e:
            print(f"Preview Error: {e}")

    def refresh_skin(self):
        p = self.profiles[self.current_profile_index] if self.profiles else {}
        p_type = p.get("type", "offline")
        name = p.get("name", "")
        uuid_ = p.get("uuid", "")
        
        if p_type == "ely.by":
            self.skin_indicator.config(text="Refreshing...", fg=COLORS['text_primary'])
            self.root.update()
            
            def _refresh():
                path = self.fetch_elyby_skin(name, uuid_)
                
                def _update_ui():
                    if path:
                        self.profiles[self.current_profile_index]["skin_path"] = path
                        self.update_active_profile()
                        self.add_skin_to_history(path)
                        messagebox.showinfo("Skin Refreshed", "Skin updated from Ely.by successfully.")
                    else:
                        self.skin_indicator.config(text="Refresh Failed", fg="red")
                        messagebox.showwarning("Refresh Failed", "Could not fetch skin from Ely.by.")
                
                self.root.after(0, _update_ui)
            
            threading.Thread(target=_refresh, daemon=True).start()
        else:
             self.update_active_profile()

    def fetch_elyby_skin(self, username, uuid_, properties=None):
        skin_url = f"http://skinsystem.ely.by/skins/{username}.png"
        props = properties if properties else []

        try:
            # If properties are missing, fetch them from the Session Server
            if not props and uuid_:
                print(f"[DEBUG] Properties missing, fetching from Session Server for {uuid_}")
                try:
                    # Ely.by Session Server endpoint
                    session_url = f"https://authserver.ely.by/api/authlib-injector/sessionserver/session/minecraft/profile/{uuid_}?unsigned=false"
                    r_sess = requests.get(session_url, timeout=5)
                    if r_sess.status_code == 200:
                        session_profile = r_sess.json()
                        props = session_profile.get("properties", [])
                        print(f"[DEBUG] Session Server returned {len(props)} properties")
                except Exception as ex:
                    print(f"[ERROR] Session Server fetch failed: {ex}")

            # If still no properties/textures, try the /textures/ endpoint on skinsystem
            if not props:
                 print(f"[DEBUG] Session server produced no props, trying skinsystem/textures/{username}")
                 try:
                     r_tex = requests.get(f"http://skinsystem.ely.by/textures/{username}", timeout=5)
                     if r_tex.status_code == 200:
                         tex_data_direct = r_tex.json()
                         if "SKIN" in tex_data_direct and "url" in tex_data_direct["SKIN"]:
                             skin_url = tex_data_direct["SKIN"]["url"]
                             print(f"[DEBUG] Resolved skin URL from skinsystem/textures: {skin_url}")
                             props = [] 
                 except Exception as e_tex:
                     print(f"[DEBUG] Skinsystem texture fetch failed: {e_tex}")

            for prop in props:
                if prop.get("name") == "textures":
                    val = prop.get("value")
                    # value is base64 encoded json
                    decoded = base64.b64decode(val).decode('utf-8')
                    tex_data = json.loads(decoded)
                    if "textures" in tex_data and "SKIN" in tex_data["textures"]:
                        extracted_url = tex_data["textures"]["SKIN"].get("url")
                        if extracted_url:
                            skin_url = extracted_url
                            print(f"[DEBUG] Resolved skin URL: {skin_url}")
        except Exception as e:
            print(f"[ERROR] Failed to extract skin data: {e}")

        # Download
        target_path = os.path.join(self.config_dir, "skins", f"{username}.png")
        if not os.path.exists(os.path.dirname(target_path)):
             os.makedirs(os.path.dirname(target_path))
             
        try:
            print(f"[DEBUG] Fetching skin from {skin_url}")
            r_skin = requests.get(skin_url, timeout=5)
            if r_skin.status_code == 200:
                with open(target_path, "wb") as f:
                    f.write(r_skin.content)
                print(f"[DEBUG] Saved skin to {target_path}")
                return target_path
            else:
                 print(f"Ely.by skin not found (Status {r_skin.status_code})")
        except Exception as e:
            print(f"Skin fetch exception: {e}")
            if os.path.exists(target_path):
                return target_path 
        
        return ""

    def select_skin(self):
        # Check profile type
        p = self.profiles[self.current_profile_index] if self.profiles else {}
        p_type = p.get("type", "offline")
        
        if p_type == "ely.by":
            if messagebox.askyesno("Ely.by Skin", "Ely.by requires skins to be managed via their website.\n\nOpen Ely.by skin catalog for your user?"):
                name = p.get("name", "")
                webbrowser.open(f"https://ely.by/skins?uploader={name}")
            return

        if not self.auto_download_mod:
            if messagebox.askyesno("Skin Injection", "Enable Skin Injection to use this skin in-game?"):
                self.auto_download_mod = True
                self.auto_download_var.set(True)
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.png")])
        if path:
            self.skin_path = path
            if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
                self.profiles[self.current_profile_index]["skin_path"] = path
            self.update_active_profile()
            self.add_skin_to_history(path)
            self.save_config()

    def ensure_authlib_injector(self):
        """ Ensures authlib-injector is present. Code adapted to fetch latest release from GitHub. """
        jar_path = os.path.join(self.minecraft_dir, "authlib-injector.jar")
        if os.path.exists(jar_path) and os.path.getsize(jar_path) > 0:
             return jar_path
             
        repo = "yushijinhun/authlib-injector"
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            self.log("Checking for authlib-injector...")
            r = requests.get(api_url, timeout=10)
            if r.status_code == 200:
                release = r.json()
                for asset in release.get("assets", []):
                    if asset["name"].endswith(".jar"):
                        self.log(f"Downloading authlib-injector: {asset['name']}...")
                        r_file = requests.get(asset["browser_download_url"], stream=True)
                        with open(jar_path, "wb") as f:
                            for chunk in r_file.iter_content(8192): f.write(chunk)
                        return jar_path
        except Exception as e:
            self.log(f"Error downloading authlib-injector: {e}")
            
        return None

    def start_launch(self, force_update=False):
        if not self.installations: return
        
        idx = getattr(self, 'current_installation_index', 0)
        if not (0 <= idx < len(self.installations)): return
        
        inst = self.installations[idx]
        version_id = inst.get("version")
        loader = inst.get("loader", "Vanilla")
        
        if not version_id or version_id == "latest-release":
            # Heuristic for latest release if not specific
            version_id = minecraft_launcher_lib.utils.get_latest_version()["release"]

        # Get username from current profile or entry
        username = DEFAULT_USERNAME
        if hasattr(self, 'user_entry'):
            username = self.user_entry.get().strip() or DEFAULT_USERNAME
        
        if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
             # Sync back to profile
             self.profiles[self.current_profile_index]["name"] = username
             username = self.profiles[self.current_profile_index]["name"]

        self.save_config()
        
        # Show Progress Bar
        self.progress_bar.place(relx=0, rely=0.96, relwidth=1, height=4)
        
        self.update_rpc("Launching...", f"Version: {version_id} ({loader})")

        self.launch_btn.config(state="disabled", text="LAUNCHING...")
        self.launch_opts_btn.config(state="disabled")
        self.set_status("Launching Minecraft...")
        threading.Thread(target=self.launch_logic, args=(version_id, username, loader, force_update), daemon=True).start()

    def launch_logic(self, version, username, loader, force_update=False):
        callback = cast(Any, {
            "setStatus": lambda t: self.log(f"Status: {t}"),
            "setProgress": lambda v: self.root.after(0, lambda: self.progress_bar.config(value=v)),
            "setMax": lambda m: self.root.after(0, lambda: self.progress_bar.config(maximum=m))
        })
        local_skin_server = None
        try:
            launch_id = version
            
            # --- Check for existing installations to avoid re-downloading ---
            installed_versions = [v['id'] for v in minecraft_launcher_lib.utils.get_installed_versions(self.minecraft_dir)]
            
            if force_update:
                self.log("Force Update enabled: Verifying and re-installing versions...")
            
            if loader == "Fabric":
                found_fabric = None
                if not force_update:
                    for vid in installed_versions:
                        if "fabric" in vid and version in vid:
                             found_fabric = vid
                             break
                
                if found_fabric:
                    self.log(f"Using existing Fabric installation: {found_fabric}")
                    launch_id = found_fabric
                else:
                    self.log(f"Installing Fabric for {version}...")
                    result = minecraft_launcher_lib.fabric.install_fabric(version, self.minecraft_dir, callback=callback)
                    if result: launch_id = result
                    else:
                        loader_v = minecraft_launcher_lib.fabric.get_latest_loader_version()
                        launch_id = f"fabric-loader-{loader_v}-{version}"

            elif loader == "Forge":
                found_forge = None
                if not force_update:
                    for vid in installed_versions:
                        if "forge" in vid and version in vid:
                            found_forge = vid
                            break
                        
                if found_forge:
                    self.log(f"Using existing Forge installation: {found_forge}")
                    launch_id = found_forge
                else:
                    self.log(f"Installing Forge for {version}...")
                    forge_v = minecraft_launcher_lib.forge.find_forge_version(version)
                    if forge_v:
                        minecraft_launcher_lib.forge.install_forge_version(forge_v, self.minecraft_dir, callback=callback)
                        launch_id = forge_v
            
            else:
                if force_update or (version not in installed_versions and launch_id not in installed_versions):
                     self.log(f"Installing/Updating Vanilla version {version}...")
                     minecraft_launcher_lib.install.install_minecraft_version(version, self.minecraft_dir, callback=callback)

            # Determine Account & Injection Settings
            current_profile = self.profiles[self.current_profile_index] if (self.profiles and 0 <= self.current_profile_index < len(self.profiles)) else {"type": "offline", "skin_path": "", "uuid": ""}
            acct_type = current_profile.get("type", "offline")
            
            launch_uuid = ""
            launch_token = ""
            
            injector_path = None
            # Only use authlib-injector if requested (Ely.by or Offline+Injection)
            use_injection = False
            skin_server_url = ""

            if acct_type == "ely.by":
                # Ely.by Logic
                use_injection = True
                injector_path = self.ensure_authlib_injector()
                # Use the explicit API URL to avoid redirects/ambiguity
                skin_server_url = "https://authserver.ely.by/api/authlib-injector"
                launch_uuid = current_profile.get("uuid", "")
                launch_token = current_profile.get("token", "")
                self.log("Launching with Ely.by account...")

            elif acct_type == "offline":
                # Offline Logic
                launch_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{username}"))
                self.log(f"Offline UUID: {launch_uuid}")
                
                if self.auto_download_mod: # This toggle now means "Enable Skin Injection"
                     use_injection = True
                     injector_path = self.ensure_authlib_injector()
                     
                     # Start Local Skin Server
                     try:
                         local_skin_server = LocalSkinServer(port=0)
                         skin_path = current_profile.get("skin_path") or self.skin_path
                         skin_model = current_profile.get("skin_model", "classic")
                         skin_server_url = local_skin_server.start(skin_path, username, launch_uuid, skin_model)
                         self.log(f"Local Skin Server active at {skin_server_url}")
                     except Exception as e:
                         self.log(f"Failed to start local skin server: {e}")
                         use_injection = False

            # Build Options
            jvm_args = [f"-Xmx{self.ram_allocation}M"]
            if self.java_args:
                jvm_args.extend(self.java_args.split())
            
            if use_injection and injector_path and skin_server_url:
                self.log(f"Applying authlib-injector: {injector_path}={skin_server_url}")
                jvm_args.append(f"-javaagent:{injector_path}={skin_server_url}")
                # Ensure we pass the prefab UUID/Token so authlib trusts it if we can
                # For offline local server, token can be anything usually, but validation might fail if not careful.
                # Authlib Injector usually disables signature checks.

            options = {
                "username": username, 
                "uuid": launch_uuid, 
                "token": launch_token,
                "jvmArguments": jvm_args,
                "launcherName": "MinecraftLauncher",
                "gameDirectory": self.minecraft_dir
            }
            
            self.log(f"Generating command for: {launch_id}")
            command = minecraft_launcher_lib.command.get_minecraft_command(launch_id, self.minecraft_dir, options) # type: ignore
            
            self.root.after(0, self.root.withdraw)
            
            # RPC Logic
            rpc_details = "Playing Minecraft"
            if getattr(self, 'rpc_show_version', True):
                 rpc_details = f"Playing {version} ({loader})"
            
            self.root.after(0, lambda: self.update_rpc("In Game", rpc_details, start=time.time()))
            
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            process = subprocess.Popen(
                command, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                creationflags=creationflags
            )
            
            if process.stdout:
                for line in process.stdout:
                    line_stripped = line.strip()
                    self.root.after(0, lambda l=line_stripped: self.log(f"[GAME] {l}"))
                    
                    if "Connecting to" in line_stripped and "," in line_stripped:
                         if getattr(self, 'rpc_show_server', True):
                            try:
                                parts = line_stripped.split("Connecting to")[-1].strip()
                                server_addr = parts.split(",")[0].strip()
                                if server_addr:
                                    self.root.after(0, lambda s=server_addr: self.update_rpc("In Game", f"Playing on {s}", start=time.time()))
                            except: pass

            process.wait()
            self.root.after(0, self.root.deiconify)
            self.root.after(0, lambda: self.update_rpc("Idle", "In Launcher"))
        except Exception as e:
            self.log(f"Error: {e}")
            self.root.after(0, lambda: messagebox.showerror("Launch Error", str(e)))
            self.root.after(0, lambda: self.update_rpc("Idle", "In Launcher"))
        finally:
            if local_skin_server:
                self.log("Stopping local skin server...")
                try: local_skin_server.stop()
                except: pass
                
            def reset_ui():
                self.launch_btn.config(state="normal", text="PLAY")
                self.launch_opts_btn.config(state="normal")
                self.update_skin_indicator()
                self.progress_bar.place_forget()
                
            self.root.after(0, reset_ui)

if __name__ == "__main__":
    root = tk.Tk()
    app = MinecraftLauncher(root)
    root.mainloop()