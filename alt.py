import socket
import tkinter as tk
from tkinter import font 
import logging
import platform

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
import io
import webbrowser
import zipfile
try:
    from skinpy import Skin, Perspective, BodyPart
except ImportError:
    pass
from PIL import Image, ImageTk
from datetime import datetime
from typing import Any, cast
import time
import traceback

import hashlib
import http.server
import socketserver
import base64
import uuid
import urllib.parse

from config import (COLORS, CURRENT_VERSION, MSA_CLIENT_ID, MSA_REDIRECT_URI, 
                    DEFAULT_RAM, LOADERS, MOD_COMPATIBLE_LOADERS, 
                    DEFAULT_USERNAME, INSTALL_MARK) 
from utils import (resource_path, get_minecraft_dir, is_version_installed, 
                   RESAMPLE_NEAREST, FLIP_LEFT_RIGHT, AFFINE)
from handlers import MicrosoftLoginHandler, LocalSkinServer
from auth import ElyByAuth

try:
    from pypresence import Presence # type: ignore
    RPC_AVAILABLE = True
except ImportError:
    RPC_AVAILABLE = False

try:
    from pystray import MenuItem as TrayItem, Icon as TrayIcon
    TRAY_AVAILABLE = True
except ImportError:
    TrayItem = None
    TrayIcon = None
    TRAY_AVAILABLE = False

# --- Helpers ---
# Moved to utils.py

# --- Color Scheme (Official Launcher Look) ---
# Moved to config.py

# --- Helpers ---
# Moved to utils.py

# LOADERS, etc moved to config.py

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

# --- Custom Popups ---
class CustomMessagebox(tk.Toplevel):
    def __init__(self, title, message, type="info", buttons=None, parent=None):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=COLORS['card_bg'])
        try: self.attributes('-topmost', True) 
        except: pass
        
        # Remove standard window decorations if we wanted strictly custom, 
        # but standard title bar is safer for cross-platform/dragging.
        # self.overrideredirect(True) 
        
        self.result = None
        target_parent = parent
        
        # Styles
        bg_col = COLORS['card_bg']
        fg_col = COLORS['text_primary']
        accent_col = COLORS.get('play_btn_green', '#2D8F36')
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Main Frame
        frame = tk.Frame(self, bg=bg_col, padx=25, pady=25)
        frame.pack(fill="both", expand=True)
        
        # Icon (Optional, simplistic text icon for now)
        icon_char = "ℹ"
        icon_col = accent_col
        if type == "error": 
            icon_char = "✖"
            icon_col = COLORS.get('red', '#E74C3C')
        elif type == "warning": 
            icon_char = "⚠"
            icon_col = COLORS.get('orange', '#E67E22')
        elif type == "yesno":
            icon_char = "?"
            icon_col = COLORS.get('blue', '#3498DB')
            
        # Title/Icon Row
        # tk.Label(frame, text=icon_char, bg=bg_col, fg=icon_col, font=("Segoe UI", 20)).pack()
        
        # Message
        msg_lbl = tk.Label(frame, text=message, bg=bg_col, fg=fg_col, 
                          font=("Segoe UI", 10), wraplength=380, justify="center")
        msg_lbl.pack(pady=(5, 20))
        
        # Buttons Setup
        btn_frame = tk.Frame(frame, bg=bg_col)
        btn_frame.pack(fill="x", pady=(10, 0))
        btn_inner = tk.Frame(btn_frame, bg=bg_col)
        btn_inner.pack(anchor="center")
        
        if buttons is None:
            if type == "yesno":
                buttons = [("Yes", True, "primary"), ("No", False, "secondary")]
            elif type == "error":
                buttons = [("Close", False, "secondary")]
            else:
                buttons = [("OK", True, "primary")]
                
        for text, val, style in buttons:
            b_bg = accent_col if style == "primary" else "#555555"
            b_fg = "white"
            
            btn = tk.Button(btn_inner, text=text, bg=b_bg, fg=b_fg, 
                           font=("Segoe UI", 9, "bold"), relief="flat",
                           activebackground=b_bg, activeforeground=b_fg,
                           bd=0, padx=20, pady=6,
                           command=lambda v=val: self.on_click(v))
            btn.pack(side="left", padx=10)
            
        # Centering Logic
        self.update_idletasks()
        w = 440
        h = max(160, self.winfo_reqheight())
        
        # Safe Centering
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w // 2) - (w // 2)
        y = (screen_h // 2) - (h // 2)
        
        if target_parent and target_parent.winfo_exists():
            try:
                px = target_parent.winfo_rootx()
                py = target_parent.winfo_rooty()
                pw = target_parent.winfo_width()
                ph = target_parent.winfo_height()
                # Center on parent
                if pw > 100 and ph > 100:
                    x = px + (pw // 2) - (w // 2)
                    y = py + (ph // 2) - (h // 2)
            except: pass
            
        self.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        self.transient(target_parent)
        self.grab_set()
        self.wait_window()
        
    def on_click(self, val):
        self.result = val
        self.destroy()
        
    def on_close(self):
        self.result = None
        self.destroy()

def custom_showinfo(title, message, parent=None):
    CustomMessagebox(title, message, type="info", parent=parent)

def custom_showwarning(title, message, parent=None):
    CustomMessagebox(title, message, type="warning", parent=parent)

def custom_showerror(title, message, parent=None):
    CustomMessagebox(title, message, type="error", parent=parent)

def custom_askyesno(title, message, parent=None):
    mbox = CustomMessagebox(title, message, type="yesno", parent=parent)
    return mbox.result

# --- Main App ---
class DownloadManager:
    def __init__(self, app):
        self.app = app
        self.mod_queue = []     # List of (func, task_id)
        self.pack_queue = []    # List of (func, task_id)
        self.active_mods = 0
        self.active_packs = 0
        self.MAX_MODS = 3
        self.MAX_PACKS = 1
        
    def queue_mod(self, func, task_id):
        self.mod_queue.append((func, task_id))
        self.app.root.after(0, lambda: self.app.update_download_task(task_id, detail="Queued..."))
        self.process_queues()

    def queue_modpack(self, func, task_id):
        self.pack_queue.append((func, task_id))
        self.app.root.after(0, lambda: self.app.update_download_task(task_id, detail="Queued..."))
        self.process_queues()

    def process_queues(self):
        max_p = getattr(self.app, 'max_concurrent_packs', 1)
        max_m = getattr(self.app, 'max_concurrent_mods', 3)
        
        # Process Packs
        while self.active_packs < max_p and self.pack_queue:
            self.active_packs += 1
            func, task_id = self.pack_queue.pop(0)
            self.start_task(func, task_id, is_pack=True)
            
        # Process Mods
        while self.active_mods < max_m and self.mod_queue:
            self.active_mods += 1
            func, task_id = self.mod_queue.pop(0)
            self.start_task(func, task_id, is_pack=False)

    def start_task(self, func, task_id, is_pack):
        self.app.root.after(0, lambda: self.app.update_download_task(task_id, status="Downloading", detail="Starting..."))
        
        def wrapper():
            try:
                func() 
            finally:
                self.app.root.after(0, lambda: self.task_finished(is_pack))

        threading.Thread(target=wrapper, daemon=True).start()

    def task_finished(self, is_pack):
        if is_pack: self.active_packs -= 1
        else: self.active_mods -= 1
        self.process_queues()

class MinecraftLauncher:
    def __init__(self, root):
        self.root = root
        self.download_manager = DownloadManager(self)
        self.root.title("NLC | New launcher")
        
        # Determine config path early for logging
        app_data = os.getenv('APPDATA')
        if os.path.exists("launcher_config.json"):
             self.config_dir = os.path.abspath(os.path.dirname("launcher_config.json"))
        elif app_data:
             self.config_dir = os.path.join(app_data, ".nlc")
        else:
             self.config_dir = os.path.join(os.path.expanduser("~"), ".nlc")

        # Initialize Logging
        self.setup_logging()

        # Global Exception Hook
        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            
            logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
            traceback.print_exception(exc_type, exc_value, exc_traceback)
            
            # Show error dialog if GUI is up
            if self.root:
                 # Truncate for message box
                 tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                 start_idx = max(0, len(tb_lines) - 5)
                 err_text = "".join(tb_lines[start_idx:])
                 self.root.after(0, lambda: messagebox.showerror("Critical Error", f"An unexpected error occurred:\n{exc_value}\n\nSee logs for full details."))

        sys.excepthook = handle_exception

        try:
            self.root.iconbitmap(resource_path("logo.ico"))
        except Exception:
            pass
            
        # Center Window
        w, h = 1080, 720
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        x = (ws/2) - (w/2)
        y = (hs/2) - (h/2)
        self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))
        
        self.root.configure(bg=COLORS['main_bg'])
        self.minecraft_dir = get_minecraft_dir()
        
        # Download Queue State
        self.download_tasks = {} # id -> {ui_elements, data}
        self.addons_config: dict[str, Any] = {} # Addons configuration
        self.download_queue_visible = False
        
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
        
        # --- Pre-load Accent Color ---
        self.accent_color_name = "Green"
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    _d = json.load(f)
                    self.accent_color_name = _d.get("accent_color", "Green")
                    
                    _colors = {
                        "Green": "#2D8F36",
                        "Blue": "#3498DB",
                        "Orange": "#E67E22",
                        "Purple": "#9B59B6",
                        "Red": "#E74C3C"
                    }
                    if self.accent_color_name in _colors:
                        c = _colors[self.accent_color_name]
                        COLORS['play_btn_green'] = c
                        COLORS['active_tab_border'] = c
                        COLORS['success_green'] = c
                        # We keep accent_blue as blue unless requested otherwise, 
                        # but play_btn_green is the main brand color used everywhere.
        except Exception as e:
            print(f"Error pre-loading config: {e}")

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
        self.hero_img_raw = None
        self.first_run = True # Default for new installs

        # Addons Config
        self.addons_config = {
            "p3_reload_menu": False
        }
        
        # Agent / Background Process
        self.agent_process = None
        self.agent_callbacks = {}
        self.agent_lock = threading.Lock()

        self.start_time = None
        self.current_tab = None
        self.log_file_path = None

        self.setup_logging()
        self.setup_tray()
        
        self.modpacks = []
        self.load_modpacks()

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
            
        # Start Background Agent
        self.start_agent_process()
            
        # Onboarding Trigger
        if self.first_run:
            self.root.after(500, self.show_onboarding_wizard)

    def load_modpacks(self):
        self.modpacks = []
        try:
            mp_file = os.path.join(self.config_dir, "modpacks.json")
            if os.path.exists(mp_file):
                with open(mp_file, "r") as f:
                    self.modpacks = json.load(f)
        except Exception as e:
            self.log(f"Error loading modpacks: {e}")

    def save_modpacks(self):
        try:
            mp_file = os.path.join(self.config_dir, "modpacks.json")
            with open(mp_file, "w") as f:
                json.dump(self.modpacks, f, indent=4)
        except Exception as e:
            self.log(f"Error saving modpacks: {e}")

    def get_modpack_dir(self, pack_id):
        # Base dir for modpacks
        base = os.path.join(getattr(self, 'config_dir', os.getcwd()), "modpacks", pack_id)
        if not os.path.exists(base):
            os.makedirs(base, exist_ok=True)
        return base

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
                       troughcolor="#212121",
                       background=COLORS['success_green'],
                       bordercolor="#212121",
                       lightcolor="#212121",
                       darkcolor="#212121",
                       borderwidth=0,
                       thickness=15)
        
        # Scrollbar (Custom Dark)
        # Note: 'clam' theme Scrollbars are tricky. 
        # We need to use 'Vertical.TScrollbar' and define the layout or element options clearly.
        # Alternatively, using standard Tk Scrollbar with colors if ttk fails, but let's try to fix style map.
        
        style.layout("Launcher.Vertical.TScrollbar", 
                    [('Vertical.Scrollbar.trough',
                      {'children': [('Vertical.Scrollbar.thumb', 
                                    {'expand': '1', 'sticky': 'nswe'})],
                       'sticky': 'ns'})]) # type: ignore
                       
        style.configure("Launcher.Vertical.TScrollbar",
                       background="#3A3B3C",
                       troughcolor=COLORS['main_bg'],
                       bordercolor=COLORS['main_bg'],
                       arrowcolor=COLORS['text_secondary'],
                       lightcolor="#3A3B3C",
                       darkcolor="#3A3B3C",
                       relief="flat",
                       borderwidth=0)
        
        style.map("Launcher.Vertical.TScrollbar",
                 background=[('pressed', '#505050'), ('active', '#4a4a4a')],
                 arrowcolor=[('pressed', COLORS['text_primary']), ('active', COLORS['text_primary'])])

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
        self.sidebar_items = []

        # Minecraft: Java Edition (Highlighted)
        java_btn_frame = tk.Frame(self.sidebar, bg="#3A3B3C", cursor="hand2", padx=10, pady=10) # Lighter grey highlight
        java_btn_frame.pack(fill="x", padx=5)
        self.sidebar_items.append(java_btn_frame)
        self.minecraft_btn_frame = java_btn_frame # Store ref
        java_btn_frame.is_active = True # type: ignore # Default active
        
        def on_minecraft_click(e):
            self.set_active_sidebar(java_btn_frame)
            self.show_tab("Play")

        java_btn_frame.bind("<Button-1>", on_minecraft_click)

        # Small icon (simple square for now or reused logo)
        try:
             # Just a small colored block or simple emoji
            l1 = tk.Label(java_btn_frame, text="Java", bg="#2D8F36", fg="white", font=("Segoe UI", 8, "bold"), width=4)
            l1.pack(side="left", padx=(0,10))
            l1.bind("<Button-1>", on_minecraft_click)
        except: pass

        l2 = tk.Label(java_btn_frame, text="Minecraft", font=("Segoe UI", 10, "bold"),
                bg="#3A3B3C", fg="white")
        l2.pack(side="left")
        l2.bind("<Button-1>", on_minecraft_click)
        
        # Add hover effect
        self._attach_sidebar_hover(java_btn_frame)

        # --- Sidebar Links ---
        # Spacer
        tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'], height=10).pack()

        # Modrinth Link
        def on_modrinth_click():
             if getattr(self, 'enable_modrinth', False):
                 self.show_tab("Mods")
             else:
                 self.show_modrinth_enable_dialog()

        self._create_sidebar_link("Modrinth", on_modrinth_click, indicator_text="Mods", is_action=True)
        
        # Addons Link
        self._create_sidebar_link("Addons", lambda: self.show_tab("Addons"), indicator_text="Agent", indicator_color="#E67E22", is_action=True)

        # Bottom spacer
        tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'], height=10).pack(side="bottom")

        # Settings Link (Gear) - Packed to bottom first to be at the very bottom
        self._create_sidebar_link("Settings", lambda: self.open_global_settings(), is_action=True, pack_side="bottom", icon="⚙")

        # GitHub Link - Packed to bottom next to be above Settings
        self._create_sidebar_link("GitHub", "https://github.com/Amne-Dev/New-launcher", pack_side="bottom")

        # Download Queue UI (Initially hidden or empty)
        self.create_download_queue_ui()

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
        self.create_nav_btn("Modpacks", lambda: self.show_tab("Modpacks"))
        self.create_nav_btn("Locker", lambda: self.show_tab("Locker"))

        # 4. Tab Container
        self.tab_container = tk.Frame(self.content_area, bg=COLORS['main_bg'])
        self.tab_container.pack(fill="both", expand=True)
        
        # Initialize Tabs
        self.tabs = {}
        self.create_play_tab()
        self.create_locker_tab()
        self.create_installations_tab()
        # Modrinth Tabs Lazy Loading
        # self.create_mods_tab()
        self.create_modpacks_tab()
        self.create_settings_tab()
        self.create_addons_tab()
        
        self.show_tab("Play")

    def create_download_queue_ui(self):
        # Container - packed at bottom of sidebar (stacking upwards above previous bottom items)
        self.queue_container = tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'])
        # Hidden initially
        # self.queue_container.pack(side="bottom", fill="x", padx=10, pady=10)
        
        # Header
        self.queue_header = tk.Label(self.queue_container, text="Downloads", font=("Segoe UI", 9, "bold"), 
                                     fg=COLORS['text_secondary'], bg=COLORS['sidebar_bg'], anchor="w")
        self.queue_header.pack(fill="x", pady=(0, 5))
        
        # List Frame
        self.queue_list_frame = tk.Frame(self.queue_container, bg=COLORS['sidebar_bg'])
        self.queue_list_frame.pack(fill="x")

    def add_download_task(self, name, type_str="file"):
        # Show container if hidden
        if not self.queue_container.winfo_viewable():
             self.queue_container.pack(side="bottom", fill="x", padx=10, pady=10)

        task_id = str(uuid.uuid4())
        
        # Card style
        frame = tk.Frame(self.queue_list_frame, bg="#2b2b2b", pady=5, padx=8)
        frame.pack(fill="x", pady=2)
        
        # Title Row
        top = tk.Frame(frame, bg="#2b2b2b")
        top.pack(fill="x")
        
        # Truncate name
        disp_name = (name[:18] + '..') if len(name) > 18 else name
        tk.Label(top, text=disp_name, font=("Segoe UI", 8, "bold"), fg="white", bg="#2b2b2b", anchor="w").pack(side="left")
        
        # Detail Frame (Container)
        detail_frame = tk.Frame(frame, bg="#2b2b2b")
        detail_lbl = tk.Label(detail_frame, text="Starting...", font=("Segoe UI", 7), fg="#cccccc", bg="#2b2b2b", anchor="w")
        detail_lbl.pack(fill="x")
        
        # Dropdown/Expand capability
        if type_str == "modpack":
            def toggle():
                if detail_frame.winfo_viewable():
                    detail_frame.pack_forget()
                    btn.config(text="▼")
                else:
                    detail_frame.pack(fill="x", pady=(2,0))
                    btn.config(text="▲")
            
            btn = tk.Button(top, text="▼", font=("Segoe UI", 6), bg="#2b2b2b", fg="white", 
                            bd=0, activebackground="#2b2b2b", activeforeground="white",
                            command=toggle, width=2, cursor="hand2")
            btn.pack(side="right")
        else:
             # Just show status inline or always hidden? 
             # For single files, maybe no detail frame, or always visible?
             # Let's keep it simpler: hidden by default.
             pass

        # Progress
        pb = ttk.Progressbar(frame, orient="horizontal", mode="determinate", length=100)
        pb.pack(fill="x", pady=3)
        
        self.download_tasks[task_id] = {
            "frame": frame,
            "pb": pb,
            "detail_lbl": detail_lbl,
            "detail_frame": detail_frame,
            "type": type_str,
            "cancel_event": threading.Event()
        }
        
        # Context Menu for Cancellation
        menu = tk.Menu(frame, tearoff=0, bg="#2b2b2b", fg="white")
        menu.add_command(label="Cancel", command=lambda: self.cancel_download(task_id))
        
        def show_menu(e):
            menu.post(e.x_root, e.y_root)
            
        # Bind to everything in the card
        frame.bind("<Button-3>", show_menu)
        top.bind("<Button-3>", show_menu)
        detail_frame.bind("<Button-3>", show_menu)
        detail_lbl.bind("<Button-3>", show_menu)
        
        return task_id

    def cancel_download(self, task_id):
        if task_id in self.download_tasks:
            self.download_tasks[task_id]['cancel_event'].set()
            self.update_download_task(task_id, detail="Cancelling...")

    def update_download_task(self, task_id, progress=None, status=None, detail=None):
        if task_id not in self.download_tasks: return
        data = self.download_tasks[task_id]
        
        if progress is not None:
            data['pb']['value'] = progress
            
        if detail is not None:
             data['detail_lbl'].config(text=detail)

    def complete_download_task(self, task_id):
        if task_id not in self.download_tasks: return
        
        data = self.download_tasks[task_id]
        data['pb']['value'] = 100
        
        # Fade out or remove
        def remove():
            if task_id in self.download_tasks:
                data = self.download_tasks[task_id]
                data['frame'].destroy()
                del self.download_tasks[task_id]
            
            if not self.download_tasks:
                 self.queue_container.pack_forget()
        
        # Wait 2 sec
        self.root.after(2000, remove)

    def apply_accent_color(self, name):
        # Update Data
        self.accent_color_name = name
        
        _colors = {
            "Green": "#2D8F36", "Blue": "#3498DB", "Orange": "#E67E22", "Purple": "#9B59B6", "Red": "#E74C3C"
        }
        if name in _colors:
            c = _colors[name]
            COLORS['play_btn_green'] = c
            COLORS['active_tab_border'] = c
            COLORS['success_green'] = c
            COLORS['accent_blue'] = c
            
            # Update Styles
            style = ttk.Style()
            style.configure("Launcher.Horizontal.TProgressbar", background=c)
            
            # Update UI Elements
            # 1. Play Button
            if hasattr(self, 'play_container'): self.play_container.config(bg=c)
            if hasattr(self, 'launch_btn'): self.launch_btn.config(bg=c, activebackground=c)
            if hasattr(self, 'launch_opts_btn'): self.launch_opts_btn.config(bg=c, activebackground=c)
            
            # 2. Installations Tab
            if hasattr(self, 'new_inst_btn'): self.new_inst_btn.config(bg=c)
            if hasattr(self, 'inst_list_frame'): self.refresh_installations_list()

            # 3. Locker Tab
            if hasattr(self, 'locker_btns'): self.refresh_locker_view()

            # 4. Settings Tab (Rebuild to apply new colors to pickers/checkboxes)
            if "Settings" in self.tabs:
                self.tabs["Settings"].destroy()
                self.create_settings_tab()
                # If currently on settings, ensure it's packed
                if self.current_tab == "Settings":
                    self.tabs["Settings"].pack(fill="both", expand=True)

            self.save_config()

    def perform_auto_update(self, asset_url, version):
        # 1. Download
        self.update_status_lbl.config(text=f"Downloading update {version}...", fg=COLORS['accent_blue'])
        
        # Show Progress Bar
        self.root.after(0, self.show_update_progress)
        
        threading.Thread(target=self._download_update_thread, args=(asset_url,), daemon=True).start()

    def show_progress_overlay(self, task_name="Loading..."):
        # Update Container (Hides bottom bar/content behind it)
        if not hasattr(self, 'update_frame'):
            self.update_frame = tk.Frame(self.root, bg=COLORS['bottom_bar_bg'])
            
            # Label
            self.update_progress_label = tk.Label(self.update_frame, text=task_name, 
                                                 font=("Segoe UI", 10, "bold"), 
                                                 bg=COLORS['bottom_bar_bg'], fg="white")
            self.update_progress_label.pack(side="top", pady=(15, 10))

            # Counter Label (Top Right of Bar area)
            self.update_counter_label = tk.Label(self.update_frame, text="", 
                                                font=("Segoe UI", 9), 
                                                bg=COLORS['bottom_bar_bg'], fg=COLORS['text_secondary'])
            self.update_counter_label.place(relx=0.98, rely=0.75, anchor="e")
            
            # Progress Bar
            self.update_progress_bar = ttk.Progressbar(self.update_frame, orient='horizontal', mode='determinate', 
                                                      style="Launcher.Horizontal.TProgressbar")
            self.update_progress_bar.pack(side="bottom", fill="x", ipady=10) # Thicker bar inside frame
            
        else:
            self.update_progress_label.config(text=task_name)
            self.update_progress_bar['value'] = 0
            if hasattr(self, 'update_counter_label'): self.update_counter_label.config(text="")

        # Show Frame
        # Height 100 to match bottom_bar height
        # x=200 to start after Sidebar, width=-200 + relwidth=1 to fill remaining space
        self.update_frame.place(x=200, rely=1.0, anchor="sw", relwidth=1, width=-200, height=100) 
        self.update_frame.lift()

    def hide_progress_overlay(self):
        if hasattr(self, 'update_frame'):
            self.update_frame.place_forget()

    def update_download_progress(self, current, total):
        if hasattr(self, 'update_progress_bar'):
            if total > 0:
                pct = (current / total) * 100
                self.update_progress_bar['value'] = pct
                
                # Update text (Status)
                if hasattr(self, 'update_progress_label'):
                    self.update_progress_label.config(text=f"Downloading Update... {int(pct)}%")
                
                # Clear/Hide Counter (User requested to remove it for updates)
                if hasattr(self, 'update_counter_label'):
                    self.update_counter_label.config(text="")
    
    # Alias for backward compat / shared usage if needed
    show_update_progress = lambda self: self.show_progress_overlay("Preparing Update...")
    hide_update_progress = hide_progress_overlay

    def _download_update_thread(self, url):
        try:
            # Save to a persistent directory (avoid Temp/MEI issues)
            updates_dir = os.path.join(self.config_dir, "updates")
            if not os.path.exists(updates_dir):
                os.makedirs(updates_dir)
            
            # Determine filename
            filename = "NewLauncher_Update.exe"
            path = os.path.join(updates_dir, filename)
            
            # Download
            r = requests.get(url, stream=True)
            total_size = int(r.headers.get('content-length', 0))
            block_size = 1024 * 64 # Larger chunks
            wrote = 0
            
            with open(path, 'wb') as f:
                for data in r.iter_content(block_size):
                    wrote += len(data)
                    f.write(data)
                    self.root.after(0, lambda c=wrote, t=total_size: self.update_download_progress(c, t))
            
            # On Finish
            self.root.after(0, self.hide_update_progress)
            self.root.after(0, lambda: self._on_download_complete(path))
            
        except Exception as e:
            print(f"Update download failed: {e}")
            self.root.after(0, self.hide_update_progress)
            self.root.after(0, lambda: self.update_status_lbl.config(text="Update failed.", fg=COLORS['error_red']))

    def _on_download_complete(self, path):
         # Define custom buttons for the dialog
        btns = [
             ("Yes, Install", True, "primary"), 
             ("I'll do it myself", "manual", "secondary"), 
             ("No", False, "secondary")
        ]
        
        # Use underlying message box class directly for custom buttons since askyesno only supports yes/no
        mbox = CustomMessagebox("Update Available", "Update downloaded successfully.\nInstall now? (The launcher will restart)", 
                                type="yesno", buttons=btns, parent=self.root)
        result = mbox.result

        if result is True:
            try:
                # Launch new executable
                if path.endswith(".exe"):
                    # Detached process to avoid locking parent directory
                    if os.name == 'nt':
                        # Use shell execution to handle UAC better and potentially resolve context issues
                        os.startfile(path)
                    else:
                        subprocess.Popen([path], close_fds=True)
                        
                    self.root.quit()
                else:
                    custom_showinfo("Manual Install", f"Update saved to:\n{path}\nPlease run it manually.")
            except Exception as e:
                custom_showerror("Error", f"Could not launch update: {e}")
        elif result == "manual":
             webbrowser.open("https://github.com/Amne-Dev/New-launcher/releases/latest")

    def show_onboarding_wizard(self):
        """Shows the First Run Wizard"""
        try:
            # 1. Background Dimming (Overlay)
            overlay = tk.Toplevel(self.root)
            overlay.configure(bg="#000000")
            overlay.withdraw()
            overlay.overrideredirect(True)
            overlay.attributes("-alpha", 0.65) # Dark transparency

            # Match root geometry exactly
            self.root.update_idletasks()
            rx, ry = 50, 50
            rw, rh = 1080, 720
            try:
                # Force geometry update
                rx, ry = self.root.winfo_x(), self.root.winfo_y()
                rw, rh = self.root.winfo_width(), self.root.winfo_height()
                overlay.geometry(f"{rw}x{rh}+{rx}+{ry}")
            except:
                overlay.geometry(f"1080x720+50+50")

            overlay.deiconify()

            # 2. Wizard Modal
            wizard = tk.Toplevel(overlay) # Parenting to overlay keeps z-order (mostly)
            wizard.withdraw() 
            wizard.title("Welcome Setup")
            wizard.configure(bg=COLORS['card_bg'])
            wizard.overrideredirect(True) # Borderless
            
            # Dimensions
            w = 700
            h = 500
            
            # Center relative to the overlay/root
            try:
                x = rx + (rw // 2) - (w // 2)
                y = ry + (rh // 2) - (h // 2)
            except:
                x, y = 100, 100
                
            wizard.geometry(f"{w}x{h}+{x}+{y}")
            
            wizard.deiconify()
            wizard.lift()
            wizard.attributes("-topmost", True)
            wizard.focus_force()
            wizard.grab_set()

            # Branding Header
            branding = tk.Frame(wizard, bg="#212121", height=40)
            branding.pack(fill="x", side="top")
            branding.pack_propagate(False)

            tk.Label(branding, text="NEW LAUNCHER SETUP", font=("Segoe UI", 9, "bold"), 
                     bg="#212121", fg="#808080").pack(side="left", padx=20)

            # --- Container ---
            content_frame = tk.Frame(wizard, bg=COLORS['card_bg'])
            content_frame.pack(fill="both", expand=True)
            
            self.wizard_account_data = {}

            # --- Helpers ---
            def clear_page():
                for widget in content_frame.winfo_children(): widget.destroy()

            # --- Step 0: Account Type ---
            def show_step_0_account_type():
                clear_page()
                tk.Label(content_frame, text="Welcome to New Launcher", font=("Segoe UI", 20, "bold"), 
                         fg="white", bg=COLORS['card_bg']).pack(pady=(50, 10))
                tk.Label(content_frame, text="How do you want to play today?", font=("Segoe UI", 12), 
                         fg=COLORS['text_secondary'], bg=COLORS['card_bg']).pack(pady=(0, 40))

                btn_frame = tk.Frame(content_frame, bg=COLORS['card_bg'], padx=10, pady=10)
                btn_frame.pack()

                def make_choice_btn(text, color, icon_char, cmd):
                    f = tk.Frame(btn_frame, bg=COLORS['card_bg'], padx=10, pady=10)
                    f.pack(side="left", padx=10)
                    btn = tk.Button(f, text=f"{icon_char}\n\n{text}", font=("Segoe UI", 11, "bold"),
                                   bg=color, fg="white", width=18, height=8, relief="flat", cursor="hand2",
                                   command=cmd)
                    btn.pack()

                make_choice_btn("Microsoft", "#00A4EF", "⊞", show_step_1_microsoft)
                make_choice_btn("Ely.by", "#3498DB", "☁", show_step_1_elyby)
                make_choice_btn("Offline", "#454545", "👤", show_step_1_offline)

            # --- Step 1: Login Details ---
            def show_step_1_microsoft():
                clear_page()
                tk.Label(content_frame, text="Microsoft Login", font=("Segoe UI", 18, "bold"), fg="white", bg=COLORS['card_bg']).pack(pady=(20, 10))
                
                status_lbl = tk.Label(content_frame, text="Initializing...", font=("Segoe UI", 10), 
                                     bg=COLORS['card_bg'], fg=COLORS['text_secondary'], wraplength=450)
                status_lbl.pack(pady=10)
                
                code_lbl = tk.Label(content_frame, text="", font=("Segoe UI", 24, "bold"), 
                                   bg=COLORS['card_bg'], fg=COLORS['success_green'])
                code_lbl.pack(pady=10)
                
                url_lbl = tk.Label(content_frame, text="", font=("Segoe UI", 11, "underline"), 
                                  bg=COLORS['card_bg'], fg="#3498DB", cursor="hand2")
                url_lbl.pack(pady=5)
                
                copy_btn = tk.Button(content_frame, text="Copy Code", font=("Segoe UI", 10),
                         bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", state="disabled")
                copy_btn.pack(pady=10)
                
                tk.Button(content_frame, text="Cancel", font=("Segoe UI", 10),
                         bg=COLORS['card_bg'], fg=COLORS['text_secondary'], relief="flat", cursor="hand2",
                         command=show_step_0_account_type).pack(pady=20)
                         
                def open_url(e):
                    url = url_lbl.cget("text")
                    if url: webbrowser.open(url)
                url_lbl.bind("<Button-1>", open_url)

                # Threaded Login Logic
                def run_flow():
                    try:
                        client_id = MSA_CLIENT_ID
                        scope = "XboxLive.signin offline_access"
                        if not wizard.winfo_exists(): return
                        status_lbl.config(text="Contacting Microsoft...")
                        
                        r = requests.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode",
                                          data={"client_id": client_id, "scope": scope})
                        if r.status_code != 200:
                            if wizard.winfo_exists(): status_lbl.config(text=f"Error: {r.text}", fg=COLORS['error_red'])
                            return
                        
                        data = r.json()
                        user_code = data.get("user_code")
                        verification_uri = data.get("verification_uri")
                        device_code = data.get("device_code")
                        interval = data.get("interval", 5)
                        
                        if wizard.winfo_exists():
                            code_lbl.config(text=user_code)
                            url_lbl.config(text=verification_uri)
                            status_lbl.config(text=f"1. Click link above\n2. Enter code\n3. Login to Microsoft")
                            copy_btn.config(state="normal", command=lambda: self.root.clipboard_clear() or self.root.clipboard_append(user_code) or self.root.update())
                            
                        # Poll
                        while wizard.winfo_exists():
                            time.sleep(interval)
                            r_poll = requests.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
                                                  data={"grant_type": "device_code", "client_id": client_id, "device_code": device_code})
                            
                            if r_poll.status_code == 200:
                                # Success
                                token_data = r_poll.json()
                                # Authenticate MC
                                status_lbl.config(text="Authenticating with Xbox Live...")
                                access_token = token_data["access_token"]
                                refresh_token = token_data["refresh_token"]
                                
                                xbl = minecraft_launcher_lib.microsoft_account.authenticate_with_xbl(access_token)
                                status_lbl.config(text="Authenticating with XSTS...")
                                xsts = minecraft_launcher_lib.microsoft_account.authenticate_with_xsts(xbl["Token"])
                                
                                status_lbl.config(text="Authenticating with Minecraft...")
                                mc_auth = minecraft_launcher_lib.microsoft_account.authenticate_with_minecraft(xbl["DisplayClaims"]["xui"][0]["uhs"], xsts["Token"])
                                
                                status_lbl.config(text="Fetching Profile...")
                                profile = minecraft_launcher_lib.microsoft_account.get_profile(mc_auth["access_token"])
                                
                                # Save
                                self.wizard_account_data = {
                                    "name": profile["name"],
                                    "uuid": profile["id"],
                                    "type": "microsoft",
                                    "skin_path": "",
                                    "access_token": mc_auth["access_token"],
                                    "refresh_token": refresh_token
                                }
                                save_account_and_continue()
                                break
                            
                            err = r_poll.json()
                            err_code = err.get("error")
                            if err_code == "authorization_pending": continue
                            elif err_code == "slow_down": interval += 2
                            elif err_code == "expired_token":
                                if wizard.winfo_exists(): status_lbl.config(text="Code expired.", fg=COLORS['error_red'])
                                break
                            else:
                                if wizard.winfo_exists(): status_lbl.config(text=f"Error: {err.get('error_description')}", fg=COLORS['error_red'])
                                break
                    except Exception as e:
                        print(f"Wizard Login Error: {e}")
                        if wizard.winfo_exists(): status_lbl.config(text=f"Error: {e}", fg=COLORS['error_red'])

                threading.Thread(target=run_flow, daemon=True).start()

            def show_step_1_offline():
                clear_page()
                tk.Label(content_frame, text="Offline Setup", font=("Segoe UI", 18, "bold"), fg="white", bg=COLORS['card_bg']).pack(pady=(40, 20))
                
                form = tk.Frame(content_frame, bg=COLORS['card_bg'])
                form.pack(fill="x", padx=150)
                
                tk.Label(form, text="Username", font=("Segoe UI", 10), fg=COLORS['text_secondary'], bg=COLORS['card_bg']).pack(anchor="w")
                name_var = tk.StringVar(value="Player")
                e = tk.Entry(form, textvariable=name_var, font=("Segoe UI", 12), bg=COLORS['input_bg'], fg="white", relief="flat", bd=5)
                e.pack(fill="x", ipady=5, pady=(5, 20))
                e.focus_set()

                def next_step():
                    name = name_var.get().strip() or "Player"
                    self.wizard_account_data = {"name": name, "type": "offline", "skin_path": "", "uuid": ""}
                    save_account_and_continue()

                tk.Button(form, text="Continue", font=("Segoe UI", 11, "bold"), bg=COLORS['success_green'], fg="white", 
                          relief="flat", cursor="hand2", command=next_step).pack(fill="x", pady=10)
                tk.Button(form, text="Back", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary'], 
                          relief="flat", cursor="hand2", command=show_step_0_account_type).pack()

            def show_step_1_elyby():
                clear_page()
                tk.Label(content_frame, text="Ely.by Login", font=("Segoe UI", 18, "bold"), fg="white", bg=COLORS['card_bg']).pack(pady=(40, 20))
                form = tk.Frame(content_frame, bg=COLORS['card_bg'])
                form.pack(fill="x", padx=150)
                
                tk.Label(form, text="Username / Email", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
                ue = tk.Entry(form, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat")
                ue.pack(fill="x", ipady=5, pady=(5, 10))
                
                tk.Label(form, text="Password", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
                pe = tk.Entry(form, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", show="*")
                pe.pack(fill="x", ipady=5, pady=(5, 20))

                def do_auth():
                    user_input = ue.get()
                    res = ElyByAuth.authenticate(user_input.strip(), pe.get().strip())
                    if "error" in res:
                        custom_showerror("Error", res['error'], parent=wizard)
                    else:
                        prof = cast(dict, res.get("selectedProfile", {}))
                        name = prof.get("name", user_input)
                        self.wizard_account_data = {
                            "name": name, "type": "ely.by", "uuid": prof.get("id", ""), 
                             # We'd fetch skin here properly in bg, but for onboarding simplicity just set basic info
                            "skin_path": "" 
                        }
                        # Trigger background skin fetch if possible, or just continue
                        save_account_and_continue()

                tk.Button(form, text="Login", font=("Segoe UI", 11, "bold"), bg="#3498DB", fg="white", 
                          relief="flat", cursor="hand2", command=do_auth).pack(fill="x", pady=10)
                tk.Button(form, text="Back", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary'], 
                          relief="flat", cursor="hand2", command=show_step_0_account_type).pack()

            def show_step_success(next_callback, message="Account Added Successfully!"):
                clear_page()
                tk.Label(content_frame, text="Success", font=("Segoe UI", 20, "bold"), 
                         fg=COLORS['success_green'], bg=COLORS['card_bg']).pack(pady=(50, 10))
                         
                tk.Label(content_frame, text=message, font=("Segoe UI", 12), 
                         fg="white", bg=COLORS['card_bg']).pack(pady=(0, 40))
                
                tk.Button(content_frame, text="Next Step", font=("Segoe UI", 12, "bold"), 
                          bg=COLORS['play_btn_green'], fg="white", relief="flat", cursor="hand2", 
                          width=20, pady=5, command=next_callback).pack()

            def save_account_and_continue():
                # Correctly add to list instead of always overwriting index 0
                is_default_steve = False
                if len(self.profiles) == 1:
                     p = self.profiles[0]
                     # Check if it is the placeholder Steve
                     if p.get("name") == "Steve" and p.get("type") == "offline" and not p.get("uuid"):
                         is_default_steve = True
                
                if not self.profiles or is_default_steve:
                    self.profiles = [self.wizard_account_data]
                    self.current_profile_index = 0
                else:
                    self.profiles.append(self.wizard_account_data)
                    self.current_profile_index = len(self.profiles) - 1
                    
                self.save_config(sync_ui=False)
                self.update_active_profile()
                
                # Show success page instead of jumping
                show_step_success(show_step_preference_setup, "Account set up successfully!")

            def show_step_preference_setup():
                clear_page()
                tk.Label(content_frame, text="Setup Preferences", font=("Segoe UI", 18, "bold"), fg="white", bg=COLORS['card_bg']).pack(pady=(40, 20))
                
                form = tk.Frame(content_frame, bg=COLORS['card_bg'])
                form.pack(fill="x", padx=120)
                
                # RAM
                tk.Label(form, text="Memory Allocation (MB)", font=("Segoe UI", 10, "bold"), fg=COLORS['text_secondary'], bg=COLORS['card_bg']).pack(anchor="w")
                
                ram_v = tk.IntVar(value=self.ram_allocation)
                tk.Scale(form, from_=1024, to=16384, orient="horizontal", resolution=512,
                        variable=ram_v, showvalue=True, bg=COLORS['card_bg'], fg="white", 
                        troughcolor=COLORS['input_bg'], highlightthickness=0).pack(fill="x", pady=(5, 30))

                # Toggles
                c_launch = tk.BooleanVar(value=True)
                c_tray = tk.BooleanVar(value=False)
                
                def mk_chk(txt, var):
                    tk.Checkbutton(form, text=txt, variable=var, font=("Segoe UI", 10),
                                  bg=COLORS['card_bg'], fg="white", selectcolor=COLORS['card_bg'], activebackground=COLORS['card_bg']).pack(anchor="w", pady=5)
                
                mk_chk("Close launcher when game starts", c_launch)
                mk_chk("Minimize to system tray on close", c_tray)

                def next_pref():
                    self.ram_allocation = ram_v.get()
                    self.close_launcher = c_launch.get()
                    self.minimize_to_tray = c_tray.get()
                    self.save_config(sync_ui=False)
                    show_step_2_appearance()

                tk.Button(content_frame, text="Continue", font=("Segoe UI", 11, "bold"), 
                          bg=COLORS['play_btn_green'], fg="white", relief="flat", cursor="hand2", 
                          command=next_pref).pack(pady=40, ipadx=20)

            def show_step_2_appearance():
                clear_page()
                tk.Label(content_frame, text="Customize Appearance", font=("Segoe UI", 18, "bold"), fg="white", bg=COLORS['card_bg']).pack(pady=(40, 20))
                
                tk.Label(content_frame, text="Choose an Accent Color", font=("Segoe UI", 10), fg=COLORS['text_secondary'], bg=COLORS['card_bg']).pack()
                
                accent_frame = tk.Frame(content_frame, bg=COLORS['card_bg'])
                accent_frame.pack(pady=20)

                def pick(c_name):
                    self.accent_color_name = c_name
                    # Apply globally so main window updates instantly
                    self.apply_accent_color(c_name)
                    self.save_config()

                    # Realtime apply (partial) for wizard context
                    _colors = {
                        "Green": "#2D8F36", "Blue": "#3498DB", "Orange": "#E67E22", "Purple": "#9B59B6", "Red": "#E74C3C"
                    }
                    if c_name in _colors:
                        new_c = _colors[c_name]
                        # Already done in apply_accent_color but wizard elements might have local references
                    else:
                        new_c = COLORS['success_green']
                    
                    # Refresh indicators
                    for w in accent_frame.winfo_children():
                        w['bg'] = COLORS['card_bg']
                        if getattr(w, '_color_name', '') == c_name:
                             w['bg'] = "white"
                    
                    # Update Finish button color dynamically
                    if finish_btn:
                        finish_btn.config(bg=new_c)

                _colors = [("Green", "#2D8F36"), ("Blue", "#3498DB"), ("Orange", "#E67E22"), ("Purple", "#9B59B6"), ("Red", "#E74C3C")]
                
                finish_btn = None 

                for name, col in _colors:
                    f = tk.Frame(accent_frame, bg=COLORS['card_bg'], padx=3, pady=3)
                    f._color_name = name # type: ignore
                    f.pack(side="left", padx=10)
                    
                    btn = tk.Button(f, bg=col, width=4, height=2, relief="flat", cursor="hand2", command=lambda n=name: pick(n))
                    btn.pack()
                    
                    if name == getattr(self, "accent_color_name", "Green"):
                         f.config(bg="white")

                finish_btn = tk.Button(content_frame, text="Finish Setup", font=("Segoe UI", 11, "bold"), bg=COLORS['success_green'], fg="white", 
                          relief="flat", cursor="hand2", command=show_step_3_finalize)
                finish_btn.pack(fill="x", padx=150, pady=(40, 10))

            # --- Step 3: Finalize ---
            def show_step_3_finalize():
                # Close the wizard

                wizard.destroy()
                overlay.destroy()
                
                # Highlight "Installations" Tab
                self.show_tab("Installations")
                self.root.update()
                
                # Show Coach Mark
                target = None
                if hasattr(self, 'new_inst_btn'):
                    target = self.new_inst_btn
                elif "Installations" in self.tabs:
                    # Fallback to the tab frame
                     target = self.tabs["Installations"]
                
                if target:
                    self.show_coach_mark(target, "Click here to add your first\nMinecraft Installation!", 
                                         next_action=self.start_locker_tour)
                else:
                    self.start_locker_tour()
                    
                self.first_run = False
                self.save_config()

            # Init
            show_step_0_account_type()

        except Exception as e:
            print(f"Error showing wizard: {e}")
            custom_showerror("Error", f"Wizard crashed: {e}")
            if 'wizard' in locals(): wizard.destroy() # type: ignore

    def start_locker_tour(self):
        """Step 3: Locker (Skins/Wallpapers)"""
        # Switch to Locker Tab
        self.show_tab("Locker")
        self.root.update()
        
        # Explain Locker
        target = None
        if hasattr(self, 'locker_btns') and "Skins" in self.locker_btns:
             target = self.locker_btns["Skins"]
        elif "Locker" in self.tabs:
             target = self.tabs["Locker"]

        if target:
             self.show_coach_mark(target, "Customize your look here!\nSwitch between Skins and Wallpapers.",
                                  next_action=self.start_settings_tour)
        else:
             self.start_settings_tour()



    def start_settings_tour(self):
        """Step 4: Settings"""
        self.show_tab("Settings")
        self.root.update()
        
        # Show a generic center message or find a widget
        target = None
        if "Settings" in self.tabs:
             # Try children first
             try:
                 children = self.tabs["Settings"].winfo_children()
                 if children: target = children[0]
             except: pass
             # Fallback to main tab
             if not target: target = self.tabs["Settings"]
        
        if target:
            self.show_coach_mark(target, "Finally, configure advanced options\nand account management here.",
                                 next_action=lambda: custom_showinfo("All Set!", "You are ready to play!\nHave fun with the New Launcher."))
        else:
             custom_showinfo("All Set!", "You are ready to play!\nHave fun with the New Launcher.")

    def show_coach_mark(self, widget, text, next_action=None):
        try:
            # Get coords
            x = widget.winfo_rootx()
            y = widget.winfo_rooty()
            w = widget.winfo_width()
            h = widget.winfo_height()
            
            # Create tooltip window
            tip = tk.Toplevel(self.root)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            
            # Calc position (below-left aligned)
            tip_x = x - 150 + w 
            tip_y = y + h + 10
            tip.geometry(f"+{tip_x}+{tip_y}")
            
            # Style
            bg = "#0078D7" # Blue accent
            fg = "white"
            
            frame = tk.Frame(tip, bg=bg, padx=2, pady=2)
            frame.pack()
            
            # Content
            lbl = tk.Label(frame, text=text, font=("Segoe UI", 10, "bold"), bg=bg, fg=fg, padx=10, pady=8, justify="left")
            lbl.pack()
            
            # Wrapper for controls to sit at bottom
            controls = tk.Frame(frame, bg=bg)
            controls.pack(fill="x", padx=10, pady=(4, 8))

            # Skip Link (Hyperlink style)
            if next_action:
                def on_skip(e):
                    if tip.winfo_exists(): tip.destroy()
                    
                skip_lbl = tk.Label(controls, text="Skip tutorial", font=("Segoe UI", 8, "underline"), 
                                  bg=bg, fg="#D1E8FF", cursor="hand2")
                skip_lbl.pack(side="left")
                skip_lbl.bind("<Button-1>", on_skip)

            # Continue Button
            btn_text = "Continue" if next_action else "Finish"
            
            def on_click(e=None):
                if not tip.winfo_exists(): return
                tip.destroy()
                if next_action:
                    self.root.after(200, next_action)
            
            btn = tk.Label(controls, text=btn_text, font=("Segoe UI", 9, "bold"), 
                          bg="#005A9E", fg="white", padx=10, pady=4, cursor="hand2")
            btn.pack(side="right")
            btn.bind("<Button-1>", on_click)
            
            # NOTE: We do NOT bind to the widget or set a timeout.
            # The tooltip persists until 'Continue' or 'Skip' is clicked.
            
        except Exception as e:
            print(f"Coach mark error: {e}")
            if next_action: next_action()

    def open_global_settings(self):
        self.show_tab("Settings")
        
    def show_modrinth_enable_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Enable Mod Support")
        dialog.geometry("400x250")
        dialog.config(bg=COLORS['main_bg'])
        # Center
        x = self.root.winfo_x() + (self.root.winfo_width()//2) - 200
        y = self.root.winfo_y() + (self.root.winfo_height()//2) - 125
        dialog.geometry(f"+{x}+{y}")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        
        container = tk.Frame(dialog, bg=COLORS['main_bg'], padx=20, pady=20)
        container.pack(fill="both", expand=True)
        
        tk.Label(container, text="Enable Mod Support?", font=("Segoe UI", 14, "bold"), 
                 bg=COLORS['main_bg'], fg="white").pack(pady=(0, 15))
                 
        tk.Label(container, text="Would you like to enable mod support in the launcher?", 
                 font=("Segoe UI", 10), bg=COLORS['main_bg'], fg="#dddddd", wraplength=350).pack(pady=(0, 10))
        
        # Resource Warning + Tooltip
        warn_frame = tk.Frame(container, bg=COLORS['main_bg'])
        warn_frame.pack(pady=(0, 10))
        
        tk.Label(warn_frame, text="(Uses additional resources)", font=("Segoe UI", 9, "italic"),
                bg=COLORS['main_bg'], fg="#F1C40F").pack(side="left")
                
        # Info Icon
        info_lbl = tk.Label(warn_frame, text="ⓘ", font=("Segoe UI", 10), 
                           bg=COLORS['main_bg'], fg="#3498DB", cursor="hand2")
        info_lbl.pack(side="left", padx=5)
        
        # Simple Tooltip
        tooltip_win = None
        def show_tip(e):
             nonlocal tooltip_win
             tooltip_win = tk.Toplevel(dialog)
             tooltip_win.wm_overrideredirect(True)
             tooltip_win.geometry(f"+{e.x_root+10}+{e.y_root+10}")
             lbl = tk.Label(tooltip_win, text="While the impact is minimal it can still be\nnoticeable on low end PCs.",
                           bg="#222", fg="white", font=("Segoe UI", 8), relief="solid", borderwidth=1, padx=5, pady=2)
             lbl.pack()
             
        def hide_tip(e):
             nonlocal tooltip_win
             if tooltip_win: tooltip_win.destroy()
             tooltip_win = None
             
        info_lbl.bind("<Enter>", show_tip)
        info_lbl.bind("<Leave>", hide_tip)
        
        tk.Label(container, text="Note: You can disable it later in Settings > Downloads", 
                 font=("Segoe UI", 8), bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(pady=(10, 20))
                 
        btn_frame = tk.Frame(container, bg=COLORS['main_bg'])
        btn_frame.pack(fill="x")
        
        def enable():
            self.enable_modrinth = True
            self.save_config()
            if hasattr(self, 'enable_modrinth_var'): self.enable_modrinth_var.set(True)
            dialog.destroy()
            
            if messagebox.askyesno("Restart Required", "The launcher needs to restart to apply changes.\nRestart now?"):
                 # Restart App
                cmd = [sys.executable]
                cwd = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
                if not getattr(sys, 'frozen', False):
                    script = sys.argv[0]
                    if not os.path.isabs(script):
                        script = os.path.abspath(script)
                        cwd = os.path.dirname(script)
                    cmd = [sys.executable, script] + sys.argv[1:]
                
                if os.name == 'nt':
                     subprocess.Popen(cmd, cwd=cwd, close_fds=True, creationflags=0x00000008)
                else:
                     subprocess.Popen(cmd, cwd=cwd, close_fds=True)
                self.root.quit()
        
        tk.Button(btn_frame, text="Yes, Enable", bg=COLORS['success_green'], fg="white", 
                 font=("Segoe UI", 10, "bold"), relief="flat", padx=15, pady=5, 
                 command=enable).pack(side="right", padx=5)
                 
        tk.Button(btn_frame, text="No", bg=COLORS['input_bg'], fg="white", 
                 font=("Segoe UI", 10), relief="flat", padx=15, pady=5, 
                 command=dialog.destroy).pack(side="right", padx=5)

    def set_active_sidebar(self, active_frame):
        for frame in getattr(self, 'sidebar_items', []):
            if frame == active_frame:
                frame.config(bg="#3A3B3C")
                frame.is_active = True
                for child in frame.winfo_children():
                    if isinstance(child, tk.Label):
                        txt = child.cget("text")
                        if txt not in ["Mods", "Java", "Agent"]:
                            child.config(bg="#3A3B3C", fg=COLORS['text_primary'])
            else:
                frame.config(bg=COLORS['sidebar_bg'])
                frame.is_active = False
                for child in frame.winfo_children():
                    if isinstance(child, tk.Label):
                        txt = child.cget("text")
                        if txt not in ["Mods", "Java", "Agent"]:
                            child.config(bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'])

    def _attach_sidebar_hover(self, frame):
        def on_enter(e):
            frame.config(bg="#3A3B3C")
            for child in frame.winfo_children():
                if isinstance(child, tk.Label):
                    txt = child.cget("text")
                    if txt not in ["Mods", "Java", "Agent"]:
                        child.config(bg="#3A3B3C", fg=COLORS['text_primary'])
        
        def on_leave(e):
            if getattr(frame, "is_active", False):
                 return
            
            frame.config(bg=COLORS['sidebar_bg'])
            for child in frame.winfo_children():
                if isinstance(child, tk.Label):
                    txt = child.cget("text")
                    if txt not in ["Mods", "Java", "Agent"]:
                        child.config(bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'])
            
        frame.bind("<Enter>", on_enter)
        frame.bind("<Leave>", on_leave)

    def _create_sidebar_link(self, text, url_or_command, indicator_text=None, indicator_color=None, is_action=False, pack_side="top", icon=None):
        frame = tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'], cursor="hand2", padx=15, pady=8)
        frame.pack(fill="x", side=cast(Any, pack_side))
        
        # Register for active state tracking
        if not hasattr(self, 'sidebar_items'): self.sidebar_items = []
        self.sidebar_items.append(frame)
        
        # Indicator (like "Java" or "Mods")
        if indicator_text:
             if indicator_color:
                 bg_color = indicator_color
             else:
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
                self.set_active_sidebar(frame)
                url_or_command()
            else:
                webbrowser.open(url_or_command)
            
        frame.bind("<Button-1>", handle_click)
        lbl.bind("<Button-1>", handle_click)
        # bind children
        for child in frame.winfo_children():
            child.bind("<Button-1>", handle_click)
        
        # Hover effect
        self._attach_sidebar_hover(frame)

    def create_nav_btn(self, text, command):
        def wrapped_command():
            # Automatically set Minecraft as active sidebar when top nav is clicked
            if hasattr(self, 'minecraft_btn_frame'):
                self.set_active_sidebar(self.minecraft_btn_frame)
            command()

        btn = tk.Button(self.nav_bar, text=text.upper(), font=("Segoe UI", 11, "bold"),
                       bg=COLORS['tab_bar_bg'], fg=COLORS['text_secondary'],
                       activebackground=COLORS['tab_bar_bg'], activeforeground=COLORS['text_primary'],
                       relief="flat", bd=0, cursor="hand2", command=wrapped_command)
        btn.pack(side="left", padx=30, pady=15)
        self.nav_buttons[text] = btn

    def show_tab(self, tab_name):
        # Lazy Init Mods Tab
        if tab_name == "Mods" and "Mods" not in self.tabs:
             if getattr(self, 'enable_modrinth', True):
                 self.create_mods_tab()
             else:
                 return

        # Hide all tabs
        for t in self.tabs.values():
            t.pack_forget()
        
        # Update Nav Buttons
        for name, btn in self.nav_buttons.items():
            if name.upper() == tab_name.upper():
                btn.config(fg=COLORS['text_primary'])
            else:
                btn.config(fg=COLORS['text_secondary'])
        
        # Show selected tab
        if tab_name in self.tabs:
            self.tabs[tab_name].pack(fill="both", expand=True)
            self.current_tab = tab_name
            
            # Lazy Load triggers
            if tab_name == "Mods":
                if hasattr(self, 'mods_tab_initialized') and not self.mods_tab_initialized:
                    self.mods_tab_initialized = True
                    self.search_mods_thread(reset=True)

    # --- PLAY TAB ---
    def create_play_tab(self):
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Play"] = frame
        
        # P3 Menu is now a game injection, not a launcher UI replacement
        # if self.addons_config.get("p3_menu", False): ... (Removed)

        # Hero Section (Background) - fills most of the space except bottom bar
        self.hero_canvas = tk.Canvas(frame, bg="#181818", highlightthickness=0)
        self.hero_canvas.pack(fill="both", expand=True) # Ensure it's packed!
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
        self.new_inst_btn = tk.Button(top_bar, text="New installation", font=("Segoe UI", 10, "bold"),
                 bg=COLORS['success_green'], fg="white", relief="flat", padx=15, pady=6, cursor="hand2",
                 command=self.open_new_installation_modal)
        self.new_inst_btn.pack(side="right") 

        # 2. Profile List (Scrollable)
        list_container = tk.Frame(frame, bg=COLORS['main_bg'])
        list_container.pack(fill="both", expand=True, padx=40)
        
        canvas = tk.Canvas(list_container, bg=COLORS['main_bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview, style="Launcher.Vertical.TScrollbar")
        
        self.inst_list_frame = tk.Frame(canvas, bg=COLORS['main_bg'])
        
        self.inst_list_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )
        
        canvas_window = canvas.create_window((0, 0), window=self.inst_list_frame, anchor="nw")
        
        # Auto-width
        def configure_width(event):
            canvas.itemconfig(canvas_window, width=event.width)
        
        canvas.bind("<Configure>", configure_width)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mousewheel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            
        def _bind_mousewheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel(child)
        
        # Bind when entering the container area
        list_container.bind("<Enter>", lambda e: _bind_mousewheel(self.inst_list_frame))
        
        # Update Scrollbar visibility
        def update_scroll_state(e=None):
            self.inst_list_frame.update_idletasks() # Ensure dimensions
            canvas.configure(scrollregion=canvas.bbox("all"))
            bbox = canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1]) > canvas.winfo_height():
                scrollbar.pack(side="right", fill="y")
            else:
                scrollbar.pack_forget()

        # Also bind strictly to children on refresh
        list_container.bind("<Configure>", update_scroll_state)
        self.inst_list_frame.bind("<Configure>", update_scroll_state)
        
        self.refresh_installations_list(lambda: [_bind_mousewheel(self.inst_list_frame), update_scroll_state()])

    def refresh_installations_list(self, callback=None):
        if not hasattr(self, 'inst_list_frame'): return # Safety check
        for w in self.inst_list_frame.winfo_children(): w.destroy()
        
        self.inst_list_frame.update_idletasks()
        
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

        if callback:
            self.root.after(100, callback)

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
                 command=lambda i=idx: self.launch_installation(i)).pack(side="left", padx=5)
                 
        # Folder
        tk.Button(actions, text="📁", bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", cursor="hand2",
                 command=lambda i=idx: self.open_installation_folder(i)).pack(side="left", padx=5)
                 
        # Edit/Menu
        menu_btn = tk.Button(actions, text="...", bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", cursor="hand2")
        menu_btn.config(command=lambda b=menu_btn, i=idx: self.open_installation_menu(i, b))
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
        scrollbar = ttk.Scrollbar(menu_frame, orient="vertical", command=canvas.yview, style="Launcher.Vertical.TScrollbar")
        scroll_frame = tk.Frame(canvas, bg=COLORS['card_bg'])
        
        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw", width=w-20)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        # Scrollbar visibility managed later
        
        # Mousewheel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def _bind_mousewheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel(child)
        
        # Close on click outside (Lose Focus)
        def on_focus_out(event):
            # Check if focus moved to scrollbar or inner element
            if menu.focus_get() and str(menu.focus_get()).startswith(str(menu)):
                return
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

        scroll_frame.update_idletasks()
        
        # Check scrollbar need
        bbox = canvas.bbox("all")
        if bbox and (bbox[3] - bbox[1]) > h:
            scrollbar.pack(side="right", fill="y")
        else:
            scrollbar.pack_forget()
        
        _bind_mousewheel(scroll_frame)

    def create_background_resource_pack(self):
        """Generates a resource pack that replaces the menu panorama with the current launcher wallpaper"""
        if not self.current_wallpaper or not os.path.exists(self.current_wallpaper):
            return "LauncherTheme" # Return just valid name if creation fails
            
        try:
            self.log("Generating Launcher Theme Resource Pack...")
            
            # Paths
            rp_dir = os.path.join(self.minecraft_dir, "resourcepacks")
            if not os.path.exists(rp_dir): os.makedirs(rp_dir)
            
            pack_name = "LauncherTheme"
            zip_path = os.path.join(rp_dir, f"{pack_name}.zip")
            
            # Prepare Image
            # Panoramas are usually 6 images (north, south, east, west, up, down)
            # We will use the same image for all to create a 'box' effect, or crop.
            # Vanilla uses assets/minecraft/textures/gui/title/background/panorama_X.png (0-5)
            # Note: Newer versions rely heavily on panorama_overlay.png too.
            
            # Prepare Image
            # Ensure RGB and Resize to standard power-of-two square (1024x1024)
            # This fixes potential reload failures due to massive resolutions or alpha channels
            img_src = Image.open(self.current_wallpaper).convert("RGB")
            img_src = img_src.resize((1024, 1024), Image.Resampling.LANCZOS)
            
            with zipfile.ZipFile(zip_path, 'w') as zf:
                # 1. pack.mcmeta 
                # Removing 'supported_formats' to avoid metadata errors with high values (99).
                # Format 34 targets 1.21.x.
                meta = {
                   "pack": {
                      "pack_format": 34,
                      "description": "Launcher Background Sync"
                   }
                }
                zf.writestr('pack.mcmeta', json.dumps(meta, indent=2))
                
                # 2. Icon - Use Launcher Logo (logo.png)
                try:
                    logo_path = resource_path("logo.png")
                    if os.path.exists(logo_path):
                        # Verify logo is small enough, or resize it too
                        with Image.open(logo_path) as l_img:
                             l_ico = l_img.resize((64, 64))
                             with io.BytesIO() as bio:
                                 l_ico.save(bio, format="PNG")
                                 zf.writestr('pack.png', bio.getvalue())
                    else:
                        # Fallback to scaled wallpaper
                        icon = img_src.resize((64, 64))
                        with io.BytesIO() as bio:
                            icon.save(bio, format="PNG")
                            zf.writestr('pack.png', bio.getvalue())
                except: pass
                
                # 3. Panorama Files
                # Strategy: Make the rotating cube invisible (Black) and put the wallpaper on the Overlay.
                # This achieves a "Static Image" effect as the overlay does not rotate.
                
                # A. Write Black Faces (16x16 is enough)
                black_img = Image.new("RGB", (16, 16), (0, 0, 0))
                with io.BytesIO() as b_bio:
                    black_img.save(b_bio, format="PNG")
                    black_bytes = b_bio.getvalue()
                    
                    base_path = "assets/minecraft/textures/gui/title/background/"
                    for i in range(6):
                        zf.writestr(f"{base_path}panorama_{i}.png", black_bytes)
                
                # B. Write Wallpaper as Overlay
                # Ensure it's opaque and good quality
                with io.BytesIO() as ov_bio:
                    img_src.save(ov_bio, format="PNG")
                    zf.writestr(f"{base_path}panorama_overlay.png", ov_bio.getvalue())

            self.log(f"Generated {pack_name}.zip successfully.")
            return f"file/{pack_name}.zip"
            
        except Exception as e:
            self.log(f"Failed to generate resource pack: {e}")
            return None

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
             
             try:
                 if edit_mode and index is not None:
                     self.installations[index] = new_profile
                 else:
                     self.installations.append(new_profile)
                 
                 self.save_config()
                 self.refresh_installations_list()
                 self.update_installation_dropdown()
             except Exception as e:
                 print(f"Error saving profile: {e}")
                 custom_showerror("Error", f"Failed to save profile: {e}")
             finally:
                 if win.winfo_exists(): win.destroy()

        # --- Footer Actions ---
        btn_row = tk.Frame(win, bg="#1e1e1e")
        btn_row.pack(side="bottom", fill="x", padx=25, pady=25)
        
        btn_text = "Save" if edit_mode else "Create"
        # Create/Save (Green)
        save_btn = tk.Button(btn_row, text=btn_text, bg=COLORS['success_green'], fg="white", font=("Segoe UI", 10, "bold"),
                 relief="flat", padx=25, pady=8, cursor="hand2",
                 command=create_action)
        save_btn.pack(side="right", padx=(10, 0))
                 
        # Cancel (Text only typically, but we keep button style for consistency)
        tk.Button(btn_row, text="Cancel", bg="#1e1e1e", fg="white", font=("Segoe UI", 10),
                 relief="flat", padx=15, pady=8, cursor="hand2",
                 activebackground="#1e1e1e", activeforeground="#B0B0B0",
                 command=win.destroy).pack(side="right")
        
        # --- Onboarding Tour Logic ---
        # Check if we are in the "First Installation" phase (coach mark previously shown)
        # We can detect this if installations count was 0 or just check if it's the very first time opening this
        if not edit_mode and len(self.installations) == 0:
            # We are likely in the tour
            def show_tour_step():
                if loader_combo.winfo_exists():
                     self.show_coach_mark(loader_combo, "First, select your Mod Loader\n(Vanilla, Fabric, etc.)")
                     
                # Chain next step for Version after a small delay
                def show_version_step():
                    if hasattr(self, 'modal_ver_combo') and self.modal_ver_combo.winfo_exists():
                        self.show_coach_mark(self.modal_ver_combo, "Then verify the Version here.")
                        
                # Just show them in sequence or show version step when Loader interaction happens?
                # Simple timer for now
                self.root.after(4000, show_version_step)
                
            self.root.after(500, show_tour_step)
            
            # Override Save Action to continue tour
            original_create = create_action
            def tour_create_action():
                original_create()
                # Trigger Next Step: Skins/Wallpaper
                self.root.after(800, self.start_locker_tour)
            
            save_btn.config(command=tour_create_action)

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
            if custom_askyesno("Delete", "Are you sure you want to delete this installation?"):
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
            p = self.profiles[self.current_profile_index]
            old_val = p.get("skin_model", "classic")
            if old_val == val: return # No change
            
            p["skin_model"] = val
            self.save_config()
            
            # If Microsoft, sync change to server
            if p.get("type", "offline") == "microsoft":
                path = p.get("skin_path")
                
                if path and os.path.exists(path):
                    token = p.get("access_token")
                    
                    def _sync_model():
                        # We re-upload the same skin with new model
                        if self.upload_ms_skin(path, val, token):
                            # self.log(f"Synced model change ({val}) to Microsoft")
                            pass
                        else:
                            # Revert on failure? Or just warn?
                            # Warning is better.
                            custom_showwarning("Sync Error", "Failed to update skin model on Minecraft servers.")
                            
                    threading.Thread(target=_sync_model, daemon=True).start()
                else:
                    self.log(f"DEBUG: Skipping model sync. Path: {path}")
                    custom_showinfo("Skin Update", "Skin model changed locally.\n\nTo update on Minecraft servers, please re-upload your skin file.")

        # Force re-render of skin
        self.update_active_profile()

    def render_wallpapers_view(self, parent):
        # Header
        header = tk.Frame(parent, bg=COLORS['main_bg'], padx=40, pady=20)
        header.pack(fill="x")
        tk.Label(header, text="Select a background", font=("Segoe UI", 12, "bold"), bg=COLORS['main_bg'], fg="white").pack(anchor="w")

        # Scrollable Area
        container = tk.Frame(parent, bg=COLORS['main_bg'])
        container.pack(fill="both", expand=True, padx=20)
        
        canvas = tk.Canvas(container, bg=COLORS['main_bg'], highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        
        self.wp_grid_frame = tk.Frame(canvas, bg=COLORS['main_bg'])
        
        canvas_window = canvas.create_window((0, 0), window=self.wp_grid_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Defaults
        defaults = ["background.png", "image1.png", "Island.png", "River.png"]
        
        # Helper: Get Hash
        def get_img_hash(p):
            try:
                h = hashlib.sha1()
                with open(p, 'rb') as f:
                    while True:
                        b = f.read(65536)
                        if not b: break
                        h.update(b)
                return h.hexdigest()
            except: return None

        current_wp_hash = None
        if hasattr(self, 'current_wallpaper') and self.current_wallpaper and os.path.exists(self.current_wallpaper):
            current_wp_hash = get_img_hash(self.current_wallpaper)

        # Gather all images: (name, path, hash)
        all_images = []
        default_hashes = set()
        
        # 1. Resources
        for fname in defaults:
            path = resource_path(fname)
            final_path = None
            if os.path.exists(path):
                final_path = path
            else:
                # Fallback
                path2 = resource_path(os.path.join("wallpapers", fname))
                if os.path.exists(path2):
                    final_path = path2
            
            if final_path:
                h = get_img_hash(final_path)
                if h: default_hashes.add(h)
                all_images.append((fname, final_path, h))
                
        # 2. Custom Wallpapers
        try:
            wp_dir = os.path.join(self.config_dir, "wallpapers")
            if os.path.exists(wp_dir):
                for f in os.listdir(wp_dir):
                    if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                        full_path = os.path.join(wp_dir, f)
                        h = get_img_hash(full_path)
                        # Filter duplicates of defaults
                        if h and h in default_hashes:
                            continue
                        all_images.append((f, full_path, h))
        except Exception as e:
            print(f"Error listing wallpapers: {e}")

        # Create Widgets list (Store to grid on reflow)
        self.wp_widgets = []

        # Render Images
        for name, path, img_hash in all_images:
            p_frame = tk.Frame(self.wp_grid_frame, bg=COLORS['card_bg'], padx=5, pady=5)
            
            # Thumb
            try:
                img = Image.open(path)
                img.thumbnail((200, 120))
                tk_img = ImageTk.PhotoImage(img)
                btn = tk.Button(p_frame, image=tk_img, bg=COLORS['card_bg'], relief="flat",
                               command=lambda p=path: self.set_wallpaper(p))
                btn.image = tk_img # type: ignore
                btn.pack()
                
                # Check if selected
                is_selected = False
                if hasattr(self, 'current_wallpaper') and self.current_wallpaper:
                    # Check path match
                    if os.path.normpath(self.current_wallpaper) == os.path.normpath(path):
                        is_selected = True
                    # Check hash match (if default changed location or copied)
                    elif current_wp_hash and img_hash and img_hash == current_wp_hash:
                        is_selected = True
                        
                if is_selected:
                     tk.Label(p_frame, text="SELECTED", bg=COLORS['success_green'], fg="white", font=("Segoe UI", 8, "bold")).pack(fill="x")
                
                tk.Label(p_frame, text=name[:20], bg=COLORS['card_bg'], fg="white").pack()
                
                self.wp_widgets.append(p_frame)
            except: 
                p_frame.destroy()
                pass
            
        # Add Custom Button
        btn = tk.Button(self.wp_grid_frame, text="+ Add Wallpaper", font=("Segoe UI", 12),
                       bg=COLORS['input_bg'], fg="white", relief="flat", width=20, height=5,
                       command=self.add_custom_wallpaper)
        self.wp_widgets.append(btn)

        # Responsive Reflow Logic
        def reflow(event):
            # width is canvas width
            w = max(1, event.width)
            # Item width approx 230-240 (200 image + padding)
            item_width = 240
            cols = max(1, w // item_width)
            
            for i, widget in enumerate(self.wp_widgets):
                r = i // cols
                c = i % cols
                widget.grid(row=r, column=c, padx=10, pady=10)
                
            # Update Scroll Info
            self.wp_grid_frame.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
            reflow(event)

        canvas.bind("<Configure>", on_configure)

        # Mousewheel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def bind_recursive(w):
            w.bind("<MouseWheel>", _on_mousewheel)
            for c in w.winfo_children():
                bind_recursive(c)

        bind_recursive(self.wp_grid_frame)
        canvas.bind("<MouseWheel>", _on_mousewheel)

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
            
            # Refresh UI if in Locker -> Wallpapers to show "SELECTED" indicator
            if self.current_tab == "Locker" and hasattr(self, 'locker_view') and self.locker_view.get() == "Wallpapers":
                self.refresh_locker_view()
                
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

        for idx, item in enumerate(history):
             # Handle Legacy (String) vs New (Dict)
             if isinstance(item, str):
                 path = item
                 model = "classic"
             else:
                 path = item.get("path")
                 model = item.get("model", "classic")
                 
             if not path or not os.path.exists(path): continue
             
             row = tk.Frame(self.history_frame, bg=COLORS['card_bg'], pady=5, padx=5, cursor="hand2")
             row.pack(fill="x", pady=2, padx=5)
             
             # Tiny Head Preview
             head = self.get_head_from_skin(path, size=32)
             if head:
                 icon = tk.Label(row, image=head, bg=COLORS['card_bg'])
                 icon.image = head # type: ignore
                 icon.pack(side="left", padx=5)
             
             name = os.path.basename(path)
             if len(name) > 15: name = name[:12] + "..."
             
             info_frame = tk.Frame(row, bg=COLORS['card_bg'])
             info_frame.pack(side="left", fill="x", expand=True)
             
             tk.Label(info_frame, text=name, bg=COLORS['card_bg'], fg=COLORS['text_primary'], font=("Segoe UI", 9), anchor="w").pack(fill="x")
             tk.Label(info_frame, text=model.title(), bg=COLORS['card_bg'], fg=COLORS['text_secondary'], font=("Segoe UI", 7), anchor="w").pack(fill="x")
             
             def _apply(p=path, m=model):
                 self.apply_history_skin(p, m)
                 
             row.bind("<Button-1>", lambda e, p=path, m=model: _apply(p, m))
             for child in row.winfo_children():
                 child.bind("<Button-1>", lambda e, p=path, m=model: _apply(p, m))
                 for grand in child.winfo_children():
                      grand.bind("<Button-1>", lambda e, p=path, m=model: _apply(p, m))

    def apply_history_skin(self, path, model="classic"):
        if not os.path.exists(path): return
        
        p = self.profiles[self.current_profile_index]
        p_type = p.get("type", "offline")
        
        # Auto Sync for Microsoft
        if p_type == "microsoft":
             token = p.get("access_token")
             if self.upload_ms_skin(path, model, token):
                 # Silent success or log
                 pass
             else:
                 custom_showerror("Error", "Failed to upload skin to Minecraft servers.")
        
        self.skin_path = path   
        p["skin_path"] = path
        p["skin_model"] = model
        self.update_active_profile()
        self.save_config()
        # Move to top of history
        self.add_skin_to_history(path, model)

    def add_skin_to_history(self, path, model="classic"):
        if not self.profiles or not path: return
        p = self.profiles[self.current_profile_index]
        history = cast(list, p.get("skin_history", []))
        
        # New Entry
        entry = {"path": path, "model": model}
        
        # Remove Existing (check path equality)
        to_remove = None
        for item in history:
            existing_path = item if isinstance(item, str) else item.get("path")
            if existing_path == path:
                to_remove = item
                break
        
        if to_remove:
            history.remove(to_remove)
            
        history.insert(0, entry)
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

        # Create Footer FIRST (so we can pack it to bottom)
        footer = tk.Frame(menu, bg=COLORS['bottom_bar_bg'], height=45)
        # Use pack(side="bottom") for footer first to ensure it stays visible!
        footer.pack(fill="x", side="bottom") 
        footer.pack_propagate(False)

        # Scrollable Area
        container = tk.Frame(menu, bg=COLORS['card_bg'])
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, bg=COLORS['card_bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview, style="Launcher.Vertical.TScrollbar")
        list_frame = tk.Frame(canvas, bg=COLORS['card_bg'])

        list_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas.create_window((0, 0), window=list_frame, anchor="nw", width=230) # 250 - 20 padding/scrollbar
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        # Scrollbar packing handled in refresh/configure
        
        # Mousewheel
        def _on_mousewheel(event):
            # Prevent scrolling up past top
            if event.delta > 0 and canvas.yview()[0] <= 0: return
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        # Bind to canvas and list_frame and children
        def _bind_mousewheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel(child)
        
        # Initial bind
        _bind_mousewheel(canvas)
        
        # Update Scrollbar visibility
        def update_scroll_state(e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            bbox = canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1]) > canvas.winfo_height():
                scrollbar.pack(side="right", fill="y")
            else:
                scrollbar.pack_forget()
            _bind_mousewheel(list_frame)

        list_frame.bind("<Configure>", update_scroll_state)
        
        list_frame.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        if not self.profiles:
             tk.Label(list_frame, text="No profiles", bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(pady=10)
        else:
            for idx, p in enumerate(self.profiles):
                self.create_profile_item(list_frame, idx, p)

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
        if custom_askyesno("Remove Account", f"Are you sure you want to remove account '{p_name}'?"):
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
                 command=lambda: self.show_microsoft_login(win)).pack(pady=5)

        tk.Button(win, text="Ely.by Account", font=("Segoe UI", 11),
                 bg="#3498DB", fg="white", width=25, pady=8, relief="flat", cursor="hand2",
                 command=lambda: self.show_elyby_login(win)).pack(pady=5)
                 
        tk.Button(win, text="Offline Account", font=("Segoe UI", 11),
                 bg=COLORS['input_bg'], fg=COLORS['text_primary'], width=25, pady=8, relief="flat", cursor="hand2",
                 command=lambda: self.show_offline_login(win)).pack(pady=5)

    def show_microsoft_login(self, parent):
        for widget in parent.winfo_children():
            widget.destroy()
            
        parent.title("Microsoft Login - Device Flow")
        parent.geometry("500x450")
        
        tk.Label(parent, text="Microsoft Login", font=("Segoe UI", 16, "bold"), 
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(20, 10))
        
        # Status Label
        status_lbl = tk.Label(parent, text="Initializing...", font=("Segoe UI", 10), 
                             bg=COLORS['main_bg'], fg=COLORS['text_secondary'], wraplength=450)
        status_lbl.pack(pady=10)
        
        # Code Display
        code_lbl = tk.Label(parent, text="", font=("Segoe UI", 24, "bold"), 
                           bg=COLORS['main_bg'], fg=COLORS['success_green'])
        code_lbl.pack(pady=10)
        
        # URL Display
        url_lbl = tk.Label(parent, text="", font=("Segoe UI", 11, "underline"), 
                          bg=COLORS['main_bg'], fg="#3498DB", cursor="hand2")
        url_lbl.pack(pady=5)
        
        # Copy Button
        copy_btn = tk.Button(parent, text="Copy Code", font=("Segoe UI", 10),
                 bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", state="disabled")
        copy_btn.pack(pady=10)
        
        tk.Button(parent, text="Cancel", font=("Segoe UI", 10),
                 bg="#1e1e1e", fg="white", relief="flat",
                 command=parent.destroy).pack(pady=20)

        # Helper to open URL
        def open_url(e):
            url = url_lbl.cget("text")
            if url: webbrowser.open(url)
        url_lbl.bind("<Button-1>", open_url)

        # Start Thread
        threading.Thread(target=self._start_microsoft_device_flow, args=(parent, status_lbl, code_lbl, url_lbl, copy_btn), daemon=True).start()
    
    def _start_microsoft_device_flow(self, win, status, code_display, url_display, copy_btn):
        # 1. Request Device Code
        self.log("Starting Microsoft Account device flow login...")
        try:
             client_id = MSA_CLIENT_ID
             scope = "XboxLive.signin offline_access"
             
             if not win.winfo_exists(): return
             status.config(text="Contacting Microsoft...")
             
             # Request Device Code
             r = requests.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode",
                               data={"client_id": client_id, "scope": scope})
             
             if r.status_code != 200:
                 if win.winfo_exists(): status.config(text=f"Error initiating login: {r.text}", fg=COLORS['error_red'])
                 return
                 
             data = r.json()
             user_code = data.get("user_code")
             verification_uri = data.get("verification_uri")
             device_code = data.get("device_code")
             interval = data.get("interval", 5)
             
             # Update UI
             if win.winfo_exists():
                 code_display.config(text=user_code)
                 url_display.config(text=verification_uri)
                 status.config(text=f"1. Click the link above\n2. Enter the code\n3. Login to your Microsoft Account")
                 
                 copy_btn.config(state="normal", command=lambda: self.root.clipboard_clear() or self.root.clipboard_append(user_code) or self.root.update())
             
             # 2. Poll
             while win.winfo_exists():
                 time.sleep(interval)
                 
                 r_poll = requests.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
                                       data={"grant_type": "device_code", "client_id": client_id, "device_code": device_code})
                 
                 if r_poll.status_code == 200:
                     # Success
                     token_data = r_poll.json()
                     self._finalize_microsoft_login(token_data, win, status)
                     break
                 
                 err = r_poll.json()
                 err_code = err.get("error")
                 
                 if err_code == "authorization_pending":
                     continue # Keep waiting
                 elif err_code == "slow_down":
                     interval += 2
                 elif err_code == "expired_token":
                     if win.winfo_exists(): status.config(text="Code expired. Please try again.", fg=COLORS['error_red'])
                     break
                 else:
                     if win.winfo_exists(): status.config(text=f"Error: {err.get('error_description')}", fg=COLORS['error_red'])
                     break
                     
        except Exception as e:
            self.log(f"Device Flow Error: {e}")
            logging.error("Device Flow Error", exc_info=True)
            if win.winfo_exists(): status.config(text=f"Exception: {e}", fg=COLORS['error_red'])

    def _finalize_microsoft_login(self, token_data, win, status):
        self.log("Finalizing Microsoft Login...")
        try:
            if not win.winfo_exists(): return
            status.config(text="Authenticating with Xbox Live...")
            access_token = token_data["access_token"]
            refresh_token = token_data["refresh_token"]
            
            # Xbox Live
            xbl = minecraft_launcher_lib.microsoft_account.authenticate_with_xbl(access_token)
            
            # XSTS
            if not win.winfo_exists(): return
            status.config(text="Authenticating with XSTS...")
            xsts = minecraft_launcher_lib.microsoft_account.authenticate_with_xsts(xbl["Token"])
            
            # Minecraft
            if not win.winfo_exists(): return
            status.config(text="Authenticating with Minecraft...")
            mc_auth = minecraft_launcher_lib.microsoft_account.authenticate_with_minecraft(xbl["DisplayClaims"]["xui"][0]["uhs"], xsts["Token"])
            
            # Profile
            if not win.winfo_exists(): return
            status.config(text="Fetching Profile...")
            profile = minecraft_launcher_lib.microsoft_account.get_profile(mc_auth["access_token"])
            
            # Success - Save
            new_profile = {
                "name": profile["name"],
                "uuid": profile["id"],
                "type": "microsoft",
                "skin_path": "", # Will fetch later
                "access_token": mc_auth["access_token"],
                "refresh_token": refresh_token,
                "created": datetime.now().strftime("%Y-%m-%d")
            }
            
            self.profiles.append(new_profile)
            self.current_profile_index = len(self.profiles) - 1
            self.save_config()
            
            # Done
            if win.winfo_exists():
                status.config(text="Login Successful!", fg=COLORS['success_green'])
                win.after(1000, win.destroy)
                
                def on_finish():
                    self.update_active_profile()
                    self.refresh_skin()
                    
                self.root.after(100, on_finish)
                
        except Exception as e:
            self.log(f"Microsoft Auth Error: {e}")
            logging.error("Microsoft Auth Trace", exc_info=True)
            if win.winfo_exists(): status.config(text=f"Finalization Error: {e}", fg=COLORS['error_red'])

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
                custom_showerror("Error", "Please fill all fields")
                return
            
            res = ElyByAuth.authenticate(u, p)
            if "error" in res:
                custom_showerror("Login Failed", f"Could not login to Ely.by details: {res['error']}")
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
                custom_showinfo("Success", f"Logged in as {name_}")

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
    # --- MODS TAB ---
    def create_modpacks_tab(self):
        container = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Modpacks"] = container
        
        # Top Bar
        top_bar = tk.Frame(container, bg=COLORS['main_bg'], pady=15, padx=20)
        top_bar.pack(fill="x")
        
        tk.Label(top_bar, text="My Modpacks", font=("Segoe UI", 16, "bold"), 
                 bg=COLORS['main_bg'], fg="white").pack(side="left")
                 
        tk.Button(top_bar, text="+ Create New Modpack", font=("Segoe UI", 10, "bold"),
                 bg=COLORS['play_btn_green'], fg="white", relief="flat", padx=15, pady=5, cursor="hand2",
                 command=self.show_create_modpack_dialog).pack(side="right")

        # Config Warning
        if not self.modpacks:
            tk.Label(container, text="Create a modpack to get started!", 
                    font=("Segoe UI", 12), fg=COLORS['text_secondary'], bg=COLORS['main_bg']).pack(pady=40)
        
        # Scrollable Area
        self.mp_canvas = tk.Canvas(container, bg=COLORS['main_bg'], highlightthickness=0)
        self.mp_scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.mp_canvas.yview, style="Launcher.Vertical.TScrollbar")
        self.mp_scrollable_frame = tk.Frame(self.mp_canvas, bg=COLORS['main_bg'])
        
        self.mp_scrollable_frame.bind(
            "<Configure>",
            lambda e: self.mp_canvas.configure(scrollregion=self.mp_canvas.bbox("all"))
        )
        
        self.mp_canvas_window = self.mp_canvas.create_window((0, 0), window=self.mp_scrollable_frame, anchor="nw")
        
        def on_canvas_configure(event):
            self.mp_canvas.itemconfig(self.mp_canvas_window, width=event.width)
            
        self.mp_canvas.bind("<Configure>", on_canvas_configure)
        self.mp_canvas.configure(yscrollcommand=self.mp_scrollbar.set)
        
        self.mp_canvas.pack(side="left", fill="both", expand=True)
        # Scrollbar visibility managed in refresh
        
        # Mousewheel
        def _on_mousewheel(event):
            self.mp_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def _bind_mousewheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel(child)

        container.bind("<Enter>", lambda e: _bind_mousewheel(self.mp_scrollable_frame))
        
        self.refresh_modpacks_list()

    def refresh_modpacks_list(self):
        for w in self.mp_scrollable_frame.winfo_children(): w.destroy()
        
        # Show/Hide Scrollbar based on content
        # Note: We need to let it pack first to know height, but for now we can just check count
        # A simpler way is to always check bbox after update
        
        if not self.modpacks:
            self.mp_scrollbar.pack_forget()
            return

        for i, pack in enumerate(self.modpacks):
            self._create_modpack_item(pack, i)
            
        self.mp_scrollable_frame.update_idletasks()
        try:
            bbox = self.mp_canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1]) > self.mp_canvas.winfo_height():
                self.mp_scrollbar.pack(side="right", fill="y")
            else:
                self.mp_scrollbar.pack_forget()
        except: pass

    def _create_modpack_item(self, pack, index):
        card = tk.Frame(self.mp_scrollable_frame, bg=COLORS['card_bg'], pady=15, padx=15)
        card.pack(fill="x", padx=20, pady=5)
        
        # Icon / Initial
        initial = pack['name'][0].upper() if pack['name'] else "?"
        icon = tk.Label(card, text=initial, font=("Segoe UI", 18, "bold"), 
                       bg="#333333", fg="white", width=4, height=2)
        icon.pack(side="left", padx=(0, 15))
        
        # Details
        info = tk.Frame(card, bg=COLORS['card_bg'])
        info.pack(side="left", fill="both", expand=True)
        
        tk.Label(info, text=pack['name'], font=("Segoe UI", 14, "bold"), fg="white", bg=COLORS['card_bg'], anchor="w").pack(fill="x")
        
        meta = f"Loader: {pack.get('loader', 'Unknown').capitalize()}  •  Version: {pack.get('mc_version', 'Unknown')}"
        tk.Label(info, text=meta, font=("Segoe UI", 10), fg=COLORS['text_secondary'], bg=COLORS['card_bg'], anchor="w").pack(fill="x", pady=2)

        # Linked Status
        linked_inst_id = pack.get("linked_installation_id")
        link_status = "Not linked"
        link_color = COLORS['text_secondary']
        
        if linked_inst_id:
            # Check if inst exists
             curr_insts = self.get_installations()
             # Finding name is hard without helper, let's just say "Linked"
             link_status = "Linked to Installation"
             link_color = COLORS['play_btn_green']

        tk.Label(info, text=link_status, font=("Segoe UI", 9, "italic"), fg=link_color, bg=COLORS['card_bg'], anchor="w").pack(fill="x")

        # Buttons
        btns = tk.Frame(card, bg=COLORS['card_bg'])
        btns.pack(side="right")
        
        btn_opts = {"font": ("Segoe UI", 10), "relief": "flat", "height": 1}

        # Link
        tk.Button(btns, text="Link", bg=COLORS['input_bg'], fg="white", padx=10, **btn_opts,
                 command=lambda: self.show_link_modpack_dialog(pack)).pack(side="left", padx=2)

        # Show Mods
        tk.Button(btns, text="Show Mods", bg=COLORS['accent_blue'], fg="white", padx=10, **btn_opts,
                 command=lambda: self.show_modpack_contents_dialog(pack)).pack(side="left", padx=2)

        # Browse (+)
        def browse_action():
            if getattr(self, 'enable_modrinth', True):
                self.select_modpack_and_browse(pack)
            else:
                self.install_local_mods(pack)

        tk.Button(btns, text="+", bg=COLORS['success_green'], fg="white", width=3, **btn_opts,
                 command=browse_action).pack(side="left", padx=2)
        
        # Menu (⋮) - Now on Right
        menu_btn = tk.Button(btns, text="⋮", bg=COLORS['input_bg'], fg="white", width=3, **btn_opts)
        menu_btn.pack(side="left", padx=2)
        
        menu = tk.Menu(menu_btn, tearoff=0, bg=COLORS['card_bg'], fg="white")
        menu.add_command(label="Open Folder", command=lambda: os.startfile(self.get_modpack_dir(pack['id'])))
        menu.add_separator()
        menu.add_command(label="Delete Modpack", command=lambda: self.delete_modpack(pack))
        
        menu_btn.config(command=lambda: menu.post(menu_btn.winfo_rootx(), menu_btn.winfo_rooty() + menu_btn.winfo_height()))

    def install_local_mods(self, pack):
        paths = filedialog.askopenfilenames(filetypes=[("Jar Files", "*.jar")])
        if not paths: return
        
        mods_dir = os.path.join(self.get_modpack_dir(pack['id']), "mods")
        if not os.path.exists(mods_dir): os.makedirs(mods_dir)
        
        count = 0
        for p in paths:
             try:
                 shutil.copy(p, mods_dir)
                 count += 1
             except: pass
             
        if count > 0:
             messagebox.showinfo("Success", f"Installed {count} mods locally.")

    def delete_modpack(self, pack):
        if not messagebox.askyesno("Delete Modpack", f"Are you sure you want to delete '{pack['name']}'?"):
            return
        
        try:
            d = self.get_modpack_dir(pack['id'])
            if os.path.exists(d):
                shutil.rmtree(d)
        except Exception as e:
            print(f"Error deleting dir: {e}")
        
        self.modpacks = [p for p in self.modpacks if p['id'] != pack['id']]
        self.save_modpacks()
        self.refresh_modpacks_list()
        self.update_active_modpack_dropdown()

    def show_modpack_contents_dialog(self, pack):
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Mods in {pack['name']}")
        dialog.geometry("500x500")
        dialog.config(bg=COLORS['main_bg'])
        
        mods_dir = os.path.join(self.get_modpack_dir(pack['id']), "mods")
        if not os.path.exists(mods_dir): os.makedirs(mods_dir)
        
        files = [f for f in os.listdir(mods_dir) if f.endswith(".jar")]
        
        tk.Label(dialog, text=f"Installed Mods ({len(files)})", font=("Segoe UI", 12, "bold"),
                 bg=COLORS['main_bg'], fg="white").pack(pady=10)
        
        scroll = tk.Scrollbar(dialog)
        scroll.pack(side="right", fill="y")
        
        lb = tk.Listbox(dialog, bg=COLORS['input_bg'], fg="white", font=("Segoe UI", 9),
                       yscrollcommand=scroll.set, activestyle="dotbox")
        lb.pack(fill="both", expand=True, padx=10, pady=5)
        scroll.config(command=lb.yview)
        
        for f in files:
            lb.insert("end", f)
            
        def delete_sel():
            sel = lb.curselection()
            if not sel: return
            fname = lb.get(sel[0])
            try:
                os.remove(os.path.join(mods_dir, fname))
                lb.delete(sel[0])
                # Remove from pack meta if tracked
                rem_meta = next((m for m in pack['mods'] if m.get('filename') == fname), None)
                if rem_meta:
                    pack['mods'].remove(rem_meta)
                    self.save_modpacks()
            except Exception as e:
                messagebox.showerror("Error", str(e))
                
        tk.Button(dialog, text="Delete Selected", bg=COLORS['error_red'], fg="white",
                 command=delete_sel).pack(pady=10)

    def show_create_modpack_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("New Modpack")
        dialog.geometry("400x300")
        dialog.config(bg=COLORS['main_bg'])
        
        # Name
        tk.Label(dialog, text="Modpack Name", bg=COLORS['main_bg'], fg="white").pack(pady=(20,5))
        name_var = tk.StringVar()
        tk.Entry(dialog, textvariable=name_var).pack()
        
        # Loader
        tk.Label(dialog, text="Mod Loader", bg=COLORS['main_bg'], fg="white").pack(pady=(15,5))
        loader_var = tk.StringVar(value="fabric")
        ttk.Combobox(dialog, textvariable=loader_var, values=["fabric", "forge"], state="readonly").pack()
        
        # Version
        tk.Label(dialog, text="Minecraft Version", bg=COLORS['main_bg'], fg="white").pack(pady=(15,5))
        ver_var = tk.StringVar(value="Fetching...")
        ver_cb = ttk.Combobox(dialog, textvariable=ver_var, values=[], state="disabled")
        ver_cb.pack()
        
        def fetch_vers():
            try:
                # Fetch only releases for stable modpack creation
                vlist = minecraft_launcher_lib.utils.get_version_list()
                releases = [v['id'] for v in vlist if v['type'] == 'release']
                
                def update():
                    if not dialog.winfo_exists(): return
                    ver_cb['values'] = releases
                    if releases:
                        ver_cb.current(0)
                        ver_cb.config(state="readonly")
                    else:
                        ver_var.set("Error fetching")
                        
                self.root.after(0, update)
            except Exception as e:
                print(f"Version fetch error: {e}")
                if dialog.winfo_exists():
                    self.root.after(0, lambda: ver_var.set("Network Error"))

        threading.Thread(target=fetch_vers, daemon=True).start()
        
        def create():
             name = name_var.get().strip()
             if not name: return
             
             new_pack = {
                 "id": str(uuid.uuid4()),
                 "name": name,
                 "loader": loader_var.get(),
                 "mc_version": ver_var.get(),
                 "mods": [], # List of file paths or meta
                 "linked_installation_id": None
             }
             self.modpacks.append(new_pack)
             self.save_modpacks()
             self.refresh_modpacks_list()
             self.update_active_modpack_dropdown() # Update dropdown in Mods tab
             self.get_modpack_dir(new_pack['id']) # Create dir
             dialog.destroy()
             
        tk.Button(dialog, text="Create", command=create, bg=COLORS['play_btn_green'], fg="white").pack(pady=20)

    def show_link_modpack_dialog(self, pack):
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Link '{pack['name']}'")
        dialog.geometry("400x400")
        dialog.config(bg=COLORS['main_bg'])
        
        tk.Label(dialog, text="Select Installation to Link", font=("Segoe UI", 12),
                 bg=COLORS['main_bg'], fg="white").pack(pady=15)
                 
        tk.Label(dialog, text=f"Requires: {pack['mc_version']} ({pack['loader']})", 
                 bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(pady=(0, 15))
                 
        # List Compatible Installs
        insts = self.get_installations().items()
        
        scroll = tk.Scrollbar(dialog)
        scroll.pack(side="right", fill="y")
        lb = tk.Listbox(dialog, bg=COLORS['input_bg'], fg="white", yscrollcommand=scroll.set, width=40)
        lb.pack(pady=10, fill="both", expand=True)
        scroll.config(command=lb.yview)
        
        map_insts = {} # index -> inst_id
        
        idx = 0
        for inst_id, inst in insts:
            # Check version match
            # "version" holds e.g. "1.20.1"
            # "loader" holds e.g. "Fabric"
            
            v_id = inst.get('version', '').lower()
            l_id = inst.get('loader', '').lower()
            
            # Loose compatibility check
            # Pack version should be in installation version string
            # Pack loader should match installation loader (excluding Vanilla)
            
            is_compat = False
            
            if pack['loader'].lower() == "fabric":
                 if "fabric" in l_id and pack['mc_version'] in v_id: is_compat = True
            elif pack['loader'].lower() == "forge":
                 if "forge" in l_id and pack['mc_version'] in v_id: is_compat = True
            
            # Also allow fuzzy match if user knows what they are doing
            # or if installation is just "1.20.1" (Vanila) and we want to allow it (Wait, no, we need loader installed)
            # Actually, the launcher installs the loader on launch if missing FOR THAT VERSION.
            # But here we are linking to an EXISTING installation profile.
            
            # Simplified check:
            if pack['mc_version'] in v_id:
                 is_compat = True
                 
            if is_compat:
                lb.insert("end", f"{inst.get('name', 'Unnamed')} ({v_id} - {l_id})")
                map_insts[idx] = inst_id
                idx += 1
                
        def link():
            sel = lb.curselection()
            if not sel: return
            inst_id = map_insts[sel[0]]
            
            # Link it
            pack['linked_installation_id'] = inst_id
            self.save_modpacks()
            self.refresh_modpacks_list()
            dialog.destroy()
        
        def create_match():
             threading.Thread(target=self._create_matching_installation_thread, args=(pack, dialog), daemon=True).start()

        tk.Button(dialog, text="Create Matching Installation", command=create_match, bg=COLORS['accent_blue'], fg="white").pack(pady=(15, 5))
        tk.Button(dialog, text="Link Selected", command=link, bg=COLORS['play_btn_green'], fg="white").pack(pady=(5, 15))

    def _create_matching_installation_thread(self, pack, dialog):
        try:
            # 1. Prepare Profile Data
            mc_ver = pack['mc_version']
            loader = pack['loader'] # "Fabric" or "Forge"
            
            # Ensure title case for loader to match launch logic expectations
            loader = loader.capitalize() if loader else "Vanilla"
            
            new_id = str(uuid.uuid4()).replace("-", "")
            new_name = f"{pack['name']} ({loader})"
            
            # 2. Create Profile in self.installations (Launcher's own list)
            new_profile = {
                 "id": new_id,
                 "name": new_name,
                 "version": mc_ver,
                 "loader": loader,
                 "icon": "icons/crafting_table_front.png", 
                 "last_played": "Never",
                 "created": datetime.now().isoformat()
            }
            
            # Try to use pack icon if available
            if 'icon' in pack and pack['icon']:
                 # Ensure it's a valid path we can use
                 new_profile['icon'] = pack['icon']

            self.installations.append(new_profile)
            
            # 3. Link and Refresh
            pack['linked_installation_id'] = new_id
            self.save_config() # Saves installations
            self.save_modpacks() # Saves modpack link
            
            self.root.after(0, lambda: [
                self.refresh_installations_list(),
                self.update_installation_dropdown(),
                self.refresh_modpacks_list(),
                dialog.destroy(),
                messagebox.showinfo("Success", f"Created installation '{new_name}' and linked it.")
            ])
            
        except Exception as e:
            print(e)
            err_msg = str(e)
            self.root.after(0, lambda m=err_msg: messagebox.showerror("Error", m))

    def update_active_modpack_dropdown(self):
        if hasattr(self, 'mods_active_pack_combobox'):
            pack_names = ["None"] + [p['name'] for p in self.modpacks]
            self.mods_active_pack_combobox['values'] = pack_names

    def select_modpack_and_browse(self, pack):
        # Set active modpack and switch tab
        self.show_tab("Mods")
        # Update dropdown var
        if hasattr(self, 'active_modpack_var'):
            self.active_modpack_var.set(pack['name'])
            
            # Manually trigger filter update since .set() doesn't fire event
            if hasattr(self, 'mod_loader_filter'):
                self.mod_loader_filter.set(pack['loader'])
            
            # Trigger search with new constraints
            self.search_mods_thread(reset=True)

    def create_mods_tab(self):
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Mods"] = frame
        
        # Top Bar (Search & Filters)
        top_bar = tk.Frame(frame, bg=COLORS['main_bg'], pady=10, padx=20)
        top_bar.pack(fill="x")

        # Modpack Selection
        mp_frame = tk.Frame(top_bar, bg=COLORS['main_bg'])
        mp_frame.pack(side="top", fill="x", pady=(0, 10))
        
        tk.Label(mp_frame, text="Active Modpack:", bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(side="left")
        
        pack_names = ["None"] + [p['name'] for p in self.modpacks]
        self.active_modpack_var = tk.StringVar(value="None")
        
        self.mods_active_pack_combobox = ttk.Combobox(mp_frame, textvariable=self.active_modpack_var, 
                            values=pack_names, 
                            style="Launcher.TCombobox", width=25, state="readonly")
        self.mods_active_pack_combobox.pack(side="left", padx=10)
        
        # When modpack changes, force filter update
        def on_pack_change(e):
             p_name = self.active_modpack_var.get()
             if p_name != "None":
                 # Find pack
                 pack = next((p for p in self.modpacks if p['name'] == p_name), None)
                 if pack:
                     self.mod_loader_filter.set(pack['loader'])
                     # We might want to lock it or show it's locked
             self.search_mods_thread(reset=True)

        self.mods_active_pack_combobox.bind("<<ComboboxSelected>>", on_pack_change)

        # View Mode (Mods vs Modpacks)
        self.browse_mode_var = tk.StringVar(value="mod")
        
        mode_frame = tk.Frame(top_bar, bg=COLORS['main_bg'])
        mode_frame.pack(side="top", fill="x", pady=(0, 10))
        
        def switch_mode(m):
            self.browse_mode_var.set(m)
            self.search_mods_thread(reset=True)
            # visual update
            if m == "mod":
                btn_mod.config(bg=COLORS['accent_blue'])
                btn_pack.config(bg=COLORS['input_bg'])
            else:
                btn_mod.config(bg=COLORS['input_bg'])
                btn_pack.config(bg=COLORS['accent_blue'])

        btn_mod = tk.Button(mode_frame, text="Mods", command=lambda: switch_mode("mod"), 
                           bg=COLORS['accent_blue'], fg="white", relief="flat", width=12)
        btn_mod.pack(side="left", padx=(0, 5))
        
        btn_pack = tk.Button(mode_frame, text="Modpacks", command=lambda: switch_mode("modpack"), 
                            bg=COLORS['input_bg'], fg="white", relief="flat", width=12)
        btn_pack.pack(side="left", padx=5)
        
        # Search Entry
        search_line = tk.Frame(top_bar, bg=COLORS['main_bg'])
        search_line.pack(fill="x")
        
        self.mod_search_var = tk.StringVar()
        self.mod_search_var.trace_add("write", lambda *args: self.schedule_mod_search())
        
        search_frame = tk.Frame(search_line, bg=COLORS['input_bg'], padx=10, pady=5)
        search_frame.pack(side="left", fill="x", expand=True)
        
        tk.Label(search_frame, text="🔍", bg=COLORS['input_bg'], fg=COLORS['text_secondary']).pack(side="left")
        
        entry = tk.Entry(search_frame, textvariable=self.mod_search_var, font=("Segoe UI", 11),
                        bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", insertbackground="white")
        entry.pack(side="left", fill="x", expand=True)

        # Filters
        self.mod_loader_filter = tk.StringVar(value="fabric") # Default
        loader_cb = ttk.Combobox(search_line, textvariable=self.mod_loader_filter, 
                                values=["fabric", "forge"], 
                                style="Launcher.TCombobox", width=10, state="readonly")
        loader_cb.pack(side="left", padx=10)
        loader_cb.bind("<<ComboboxSelected>>", lambda e: self.search_mods_thread(reset=True))
        
        self.mods_loader_combobox = loader_cb # Store ref for updates

        # Game Version Filter
        self.mod_version_filter = tk.StringVar(value="All")
        version_cb = ttk.Combobox(search_line, textvariable=self.mod_version_filter, 
                                values=["All"], 
                                style="Launcher.TCombobox", width=10, state="readonly")
        version_cb.pack(side="left", padx=5)
        version_cb.bind("<<ComboboxSelected>>", lambda e: self.search_mods_thread(reset=True))
        
        self.mods_version_combobox = version_cb

        # Load Versions Async
        def load_versions():
            try:
                vlist = minecraft_launcher_lib.utils.get_version_list()
                releases = ["All"] + [v['id'] for v in vlist if v['type'] == 'release']
                self.root.after(0, lambda: version_cb.config(values=releases))
            except: pass
        threading.Thread(target=load_versions, daemon=True).start()

        # Update controls when pack changes
        def update_filter_state(e=None):
             p_name = self.active_modpack_var.get()
             if p_name != "None":
                 # Find pack
                 pack = next((p for p in self.modpacks if p['name'] == p_name), None)
                 if pack:
                     # Set and Disable
                     self.mod_loader_filter.set(pack['loader'])
                     self.mod_version_filter.set(pack['mc_version'])
                     
                     loader_cb.config(state="disabled")
                     version_cb.config(state="disabled")
             else:
                 # Enable
                 loader_cb.config(state="readonly")
                 version_cb.config(state="readonly")
                 
             self.search_mods_thread(reset=True)

        # Rebind
        self.mods_active_pack_combobox.bind("<<ComboboxSelected>>", update_filter_state)

        # Content Area (Scrollable)
        self.mods_canvas = tk.Canvas(frame, bg=COLORS['main_bg'], highlightthickness=0)
        self.mods_scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.mods_canvas.yview, style="Launcher.Vertical.TScrollbar")
        self.mods_scrollable_frame = tk.Frame(self.mods_canvas, bg=COLORS['main_bg'])
        
        self.mods_scrollable_frame.bind(
            "<Configure>",
            lambda e: self.mods_canvas.configure(scrollregion=self.mods_canvas.bbox("all"))
        )
        
        self.mods_canvas_window = self.mods_canvas.create_window((0, 0), window=self.mods_scrollable_frame, anchor="nw")
        
        def on_canvas_configure(event):
            self.mods_canvas.itemconfig(self.mods_canvas_window, width=event.width)
        
        self.mods_canvas.bind("<Configure>", on_canvas_configure)
        self.mods_canvas.configure(yscrollcommand=self._on_scrollbar_update) # This method likely used for infinite scroll logic? need to check
        
        self.mods_canvas.pack(side="left", fill="both", expand=True)
        self.mods_scrollbar.pack(side="right", fill="y")
        
        # Mousewheel for Mods Tab
        self.last_scroll_check = 0
        
        def _on_mousewheel(event):
            # Prevent scrolling up past top
            if event.delta > 0 and self.mods_canvas.yview()[0] <= 0: return

            self.mods_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            
            # Simple throttle for scroll checking (Infinite Scroll / Pagination)
            now = time.time()

            if now - self.last_scroll_check > 0.2:
                self.last_scroll_check = now
                self._check_scroll_position()
        
        def _bind_mousewheel(widget):
            # Only bind if not already bound to avoid duplicates stack
            # But tk binds replace usually.
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel(child)
        
        # Bind when entering the specific frame, unbind when leaving? 
        # Actually proper way is key bindings only when focused, but for mousewheel 
        # usually we just bind to the widget under mouse.
        
        frame.bind("<Enter>", lambda e: _bind_mousewheel(self.mods_scrollable_frame))
        self.mods_scrollable_frame.bind("<Configure>", lambda e: _bind_mousewheel(self.mods_scrollable_frame))
        self.mods_canvas.bind("<Enter>", lambda e: _bind_mousewheel(self.mods_canvas))

        self.mod_search_timer = None
        self.cached_mod_images = {}
        
        # Pagination State
        self.mod_offset = 0
        self.mod_loading = False
        self.mod_end_reached = False
        self.mods_tab_initialized = False # Flag for lazy load
        
        # We DO NOT auto-load here to prevent startup freeze.
        # It is triggered by show_tab("Mods")
        tk.Label(self.mods_scrollable_frame, text="Loading Mods...", 
                font=("Segoe UI", 12), fg=COLORS['text_secondary'], bg=COLORS['main_bg']).pack(pady=40)

    def _on_scrollbar_update(self, first, last):
        self.mods_scrollbar.set(first, last)
        self._check_scroll_position()

    def _check_scroll_position(self):
        if self.mod_loading or self.mod_end_reached: return
        try:
            if self.mods_canvas.yview()[1] > 0.85:
                self.load_more_mods()
        except: pass

    def schedule_mod_search(self, *args):
        if self.mod_search_timer:
            self.root.after_cancel(self.mod_search_timer)
        self.mod_search_timer = self.root.after(800, lambda: self.search_mods_thread(reset=True))

    def load_more_mods(self):
        if self.mod_loading or self.mod_end_reached: return
        self.search_mods_thread(reset=False)

    def search_mods_thread(self, reset=False):
        if self.mod_loading and reset == False: return
        self.mod_loading = True
        
        query = self.mod_search_var.get().strip()
        loader = self.mod_loader_filter.get().lower()
        if loader == "all": loader = "" # Though we default to fabric now
        
        # Check active modpack for version constraint
        version_facet = ""
        p_name = self.active_modpack_var.get()
        if p_name != "None":
             pack = next((p for p in self.modpacks if p['name'] == p_name), None)
             if pack:
                 loader = pack['loader'] # Force loader
                 version_facet = pack['mc_version']
        else:
             # Use filters
             if hasattr(self, 'mod_version_filter'):
                 vf = self.mod_version_filter.get()
                 if vf != "All": version_facet = vf

        if reset:
            self.mod_offset = 0
            self.mod_end_reached = False
            # Scroll to top
            self.mods_canvas.yview_moveto(0)
            
            for w in self.mods_scrollable_frame.winfo_children(): w.destroy()
            tk.Label(self.mods_scrollable_frame, text="Searching...", 
                     font=("Segoe UI", 12), fg=COLORS['accent_blue'], bg=COLORS['main_bg']).pack(pady=20)
        
        threading.Thread(target=self._perform_mod_search, args=(query, loader, version_facet, reset), daemon=True).start()

    def _perform_mod_search(self, query, loader, version_facet, reset):
        payload = {
            "query": query,
            "limit": 20,
            "offset": self.mod_offset,
            "facets": []
        }
        
        # Project Type
        p_type = "mod"
        if hasattr(self, 'browse_mode_var'):
             p_type = self.browse_mode_var.get()
        payload["facets"].append(f'project_type:{p_type}')

        if loader:
            payload["facets"].append(f'categories:{loader}')
        if version_facet:
            payload["facets"].append(f'versions:{version_facet}')
            
        # Use Agent
        self.send_agent_request("search_mods", payload, lambda res: self._on_mod_search_result(res, reset))

    def _on_mod_search_result(self, result, reset):
        if not result or result.get("status") != "success":
            self.mod_loading = False
            msg = result.get("msg", "Unknown error") if result else "No response"
            self._display_mod_error(msg)
            return
            
        data = result.get("data", {})
        hits = data.get("hits", [])
        
        if hits:
            self.mod_offset += len(hits)
        else:
            self.mod_end_reached = True

        self._display_mod_results(hits, reset)

    def _display_mod_error(self, msg):
        tk.Label(self.mods_scrollable_frame, text=f"Error: {msg}", 
                 fg=COLORS['error_red'], bg=COLORS['main_bg']).pack(pady=20)

    def _display_mod_results(self, hits, reset):
        if reset:
            for w in self.mods_scrollable_frame.winfo_children(): w.destroy()
            if not hits:
                tk.Label(self.mods_scrollable_frame, text="No results found", 
                         fg=COLORS['text_secondary'], bg=COLORS['main_bg']).pack(pady=20)
                self.mod_loading = False
                return

        for hit in hits:
            self._create_mod_card(hit)
            
        # Update Scrollbar Region Explicitly
        self.mods_scrollable_frame.update_idletasks()
        self.mods_canvas.configure(scrollregion=self.mods_canvas.bbox("all"))

        self.mod_loading = False

    def _create_mod_card(self, mod):
        card = tk.Frame(self.mods_scrollable_frame, bg=COLORS['card_bg'], pady=10, padx=10)
        card.pack(fill="x", padx=20, pady=5)
        
        # Icon
        icon_lbl = tk.Label(card, text="?", bg="#212121", fg="white", width=8, height=4)
        icon_lbl.pack(side="left", padx=(0, 15))
        
        icon_url = mod.get("icon_url")
        if icon_url:
            self._load_mod_icon_async(icon_url, icon_lbl)

        # Info
        info_frame = tk.Frame(card, bg=COLORS['card_bg'])
        info_frame.pack(side="left", fill="both", expand=True)
        
        tk.Label(info_frame, text=mod.get("title", "Unknown"), font=("Segoe UI", 12, "bold"), 
                 fg="white", bg=COLORS['card_bg'], anchor="w").pack(fill="x")
        
        # Desc
        desc = mod.get("description", "")
        if len(desc) > 80: desc = desc[:77] + "..."
        tk.Label(info_frame, text=desc, font=("Segoe UI", 9), 
                 fg=COLORS['text_secondary'], bg=COLORS['card_bg'], anchor="w").pack(fill="x")
        
        # Meta
        tk.Label(info_frame, text=f"By {mod.get('author', 'Unknown')}", font=("Segoe UI", 8), 
                 fg="#808080", bg=COLORS['card_bg'], anchor="w").pack(fill="x", pady=(2, 0))

        # Buttons
        btn_frame = tk.Frame(card, bg=COLORS['card_bg'])
        btn_frame.pack(side="right")
        
        # INSTALL BUTTON (If pack selected or Modpack Browse)
        if mod.get('project_type') == 'modpack':
             btn = tk.Button(btn_frame, text="Download", font=("Segoe UI", 9, "bold"), 
                        bg=COLORS['play_btn_green'], fg="white", relief="flat", cursor="hand2")
             btn.pack(side="right", padx=5)
             # Logic to install Modpack from Modrinth
             # We need a new method for this
             btn.config(command=lambda m=mod, b=btn: self._install_mr_modpack(m, b))

        else:
            active_pack_name = self.active_modpack_var.get()
            if active_pack_name != "None":
                # Check if installed
                pack = next((p for p in self.modpacks if p['name'] == active_pack_name), None)
                is_installed = False
                if pack:
                    # Check meta
                    mod_slug = mod.get('slug')
                    # Also check filename if slug check fails or is not present? 
                    # Meta structure: {slug: "sodium", filename: "sodium-..."}
                    if any(m.get('slug') == mod_slug for m in pack['mods']):
                        is_installed = True
                
                if is_installed:
                    tk.Label(btn_frame, text="✔ Installed", font=("Segoe UI", 9, "bold"), 
                            fg=COLORS['success_green'], bg=COLORS['card_bg']).pack(side="right", padx=10)
                else:
                    btn = tk.Button(btn_frame, text="Install", font=("Segoe UI", 9, "bold"), 
                            bg=COLORS['play_btn_green'], fg="white", relief="flat", cursor="hand2")
                    btn.pack(side="right", padx=5)
                    btn.config(command=lambda b=btn, m=mod, p=active_pack_name: self._install_mod_to_pack(m, p, b))

        tk.Button(btn_frame, text="Web", font=("Segoe UI", 9), bg=COLORS['input_bg'], fg="white",
                 relief="flat", cursor="hand2", 
                 command=lambda u=f"https://modrinth.com/{mod.get('project_type', 'mod')}/{mod['slug']}": webbrowser.open(u)).pack(side="right", padx=5)

    def _install_mod_to_pack(self, mod_data, pack_name, btn_widget):
        pack = next((p for p in self.modpacks if p['name'] == pack_name), None)
        if not pack: return
        
        # Update button state
        btn_widget.config(state="disabled", text="Queued...", bg=COLORS['text_secondary'])
        
        # Add to Queue
        task_id = self.add_download_task(mod_data.get('title', 'Mod'), "mod")
        
        def run_install():
            self.root.after(0, lambda: btn_widget.config(text="Installing..."))
            success = False
            try:
                mod_id = mod_data['slug'] # or project_id or slug from search hit
                
                self.root.after(0, lambda: self.update_download_task(task_id, 0, detail="Fetching versions..."))
                
                # version request
                v_url = f"https://api.modrinth.com/v2/project/{mod_id}/version?loaders=[%22{pack['loader']}%22]&game_versions=[%22{pack['mc_version']}%22]"
                r = requests.get(v_url, timeout=10)
                if r.status_code != 200:
                    raise Exception(f"Failed to fetch versions: {r.status_code}")
                
                versions = r.json()
                if not versions:
                    raise Exception("No compatible version found for this modpack.")
                
                # Pick first (newest)
                best_ver = versions[0]
                files = best_ver.get('files', [])
                if not files:
                    raise Exception("No files in version.")
                    
                primary_file = next((f for f in files if f.get('primary', False)), files[0])
                download_url = primary_file['url']
                filename = primary_file['filename']
                size = primary_file.get('size', 0)
                
                # Download
                target_dir = os.path.join(self.get_modpack_dir(pack['id']), "mods")
                if not os.path.exists(target_dir): os.makedirs(target_dir)
                
                target_path = os.path.join(target_dir, filename)
                
                self.root.after(0, lambda: self.update_download_task(task_id, 0, detail=f"Downloading {filename}..."))
                
                with requests.get(download_url, stream=True) as d_r:
                    d_r.raise_for_status()
                    total_downloaded = 0
                    with open(target_path, 'wb') as f:
                        for chunk in d_r.iter_content(chunk_size=8192):
                            # Check Cancel
                            if task_id in self.download_tasks and self.download_tasks[task_id]['cancel_event'].is_set():
                                raise Exception("Cancelled by user")
                                
                            f.write(chunk)
                            total_downloaded += len(chunk)
                            
                            # Speed Limit
                            if getattr(self, 'limit_download_speed_enabled', False):
                                limit_kb = getattr(self, 'max_download_speed', 2048)
                                if limit_kb > 0:
                                    try: time.sleep(len(chunk) / (limit_kb * 1024))
                                    except: pass

                            if size > 0:
                                prog = (total_downloaded / size) * 100
                                # Throttle UI updates? 100 updates per mod is fine.
                                self.root.after(0, lambda p=prog: self.update_download_task(task_id, p))
                            
                success = True
                
                # Update Pack Meta
                # Store full info to detect duplicates
                meta = {
                    "slug": mod_id,
                    "filename": filename,
                    "version_id": best_ver['id']
                }
                
                # Remove old entry if same slug exists (updating?)
                # For now just append, user can manage files manually if needed
                pack['mods'].append(meta) 
                
                self.save_modpacks()
                
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda m=err_msg: messagebox.showerror("Error", m))
            
            # Post-Op UI Update
            def finish():
                self.complete_download_task(task_id)
                if success:
                    btn_widget.destroy() # Remove install button (or replace with checkmark)
                    pass 
                else:
                    btn_widget.config(state="normal", text="Install", bg=COLORS['play_btn_green'])
            
            self.root.after(0, finish)
        
        self.download_manager.queue_mod(run_install, task_id)

    def _install_mr_modpack(self, mod_data, btn_widget):
        btn_widget.config(state="disabled", text="Queued...")
        task_id = self.add_download_task(mod_data['title'], "modpack")
        
        def run():
             self.root.after(0, lambda: btn_widget.config(text="Installing..."))
             self._install_mr_modpack_thread(mod_data, btn_widget, task_id)
             
        self.download_manager.queue_modpack(run, task_id)

    def _install_mr_modpack_thread(self, mod_data, btn_widget, task_id):
        try:
             mod_id = mod_data['slug']
             
             self.root.after(0, lambda: self.update_download_task(task_id, 0, detail="Fetching info..."))
             
             v_url = f"https://api.modrinth.com/v2/project/{mod_id}/version"
             r = requests.get(v_url, headers={"User-Agent": "AmneDev/NewLauncher"}, timeout=10)
             versions = r.json()
             if not versions:
                 raise Exception("No versions found")
                 
             best = versions[0]
             
             files = best.get('files', [])
             mrpack_file = next((f for f in files if f['filename'].endswith('.mrpack')), None)
             
             if not mrpack_file:
                 # Some packs might not distribute mrpack on all versions?
                 raise Exception("No .mrpack file found in latest version")
                 
             # Create Pack Entry
             pack_name = mod_data['title']
             mc_ver = best['game_versions'][0]
             loader = best['loaders'][0]
             
             new_id = str(uuid.uuid4())
             new_pack = {
                 "id": new_id,
                 "name": pack_name,
                 "loader": loader,
                 "mc_version": mc_ver,
                 "mods": [],
                 "linked_installation_id": None
             }
             
             # Download .mrpack to temp
             self.root.after(0, lambda: self.update_download_task(task_id, 5, detail="Downloading mrpack..."))
             import tempfile
             with tempfile.TemporaryDirectory() as temp_dir:
                 mr_path = os.path.join(temp_dir, "pack.mrpack")
                 with requests.get(mrpack_file['url'], stream=True) as d_r:
                     d_r.raise_for_status()
                     with open(mr_path, 'wb') as f:
                         for chunk in d_r.iter_content(chunk_size=8192):
                             if task_id in self.download_tasks and self.download_tasks[task_id]['cancel_event'].is_set():
                                 raise Exception("Cancelled")
                             f.write(chunk)
                         
                 # Extract
                 if task_id in self.download_tasks and self.download_tasks[task_id]['cancel_event'].is_set(): raise Exception("Cancelled")

                 self.root.after(0, lambda: self.update_download_task(task_id, 10, detail="Extracting..."))
                 with zipfile.ZipFile(mr_path, 'r') as zf:
                     zf.extractall(temp_dir)
                     
                 # Read index.json
                 index_path = os.path.join(temp_dir, "modrinth.index.json")
                 if not os.path.exists(index_path):
                     raise Exception("Invalid mrpack: No index.json")
                     
                 with open(index_path, 'r') as f:
                     idx = json.load(f)
                     
                 # Download mods
                 target_dir = os.path.join(self.get_modpack_dir(new_id), "mods")
                 if not os.path.exists(target_dir): os.makedirs(target_dir)
                 
                 files_list = idx.get('files', [])
                 total_files = len(files_list)
                 completed_files = 0
                 
                 for file_def in files_list:
                     if task_id in self.download_tasks and self.download_tasks[task_id]['cancel_event'].is_set():
                         raise Exception("Cancelled")

                     d_url = file_def['downloads'][0]
                     f_path = file_def['path'] 
                     f_name = os.path.basename(f_path)
                     
                     # Allow subdirectories 
                     # Modrinth packs put mods in 'mods/...' usually.
                     # We flatten? No, keep it in mods dir.
                     # If path starts with 'mods/', it goes to target_dir.
                     # If path is 'config/', we ignore for now as requested (simple implementation)
                     if f_path.startswith("mods/"):
                         dest = os.path.join(self.get_modpack_dir(new_id), f_path) # e.g. pack/mods/fabric-api.jar
                         # Ensure dir exists
                         os.makedirs(os.path.dirname(dest), exist_ok=True)
                         
                         self.root.after(0, lambda n=f_name: self.update_download_task(task_id, detail=f"Downloading {n}"))
                         
                         with requests.get(d_url, stream=True) as mf:
                             mf.raise_for_status()
                             with open(dest, 'wb') as out:
                                 for chunk in mf.iter_content(chunk_size=8192):
                                     if task_id in self.download_tasks and self.download_tasks[task_id]['cancel_event'].is_set():
                                         raise Exception("Cancelled")
                                     out.write(chunk)
                                 
                     completed_files += 1
                     if total_files > 0:
                         prog = 10 + (completed_files / total_files * 85)
                         self.root.after(0, lambda p=prog: self.update_download_task(task_id, p))
                                 
                     # To support config overrides, we would need to copy from extracted 'overrides' folder too.
                 
                 # Add to modpacks list
                 self.root.after(0, lambda: self.complete_download_task(task_id))
                 
                 self.modpacks.append(new_pack)
                 self.save_modpacks()
                 
             self.root.after(0, lambda: [
                 self.refresh_modpacks_list(),
                 self.update_active_modpack_dropdown(),
                 messagebox.showinfo("Success", f"Installed modpack '{pack_name}'"),
                 btn_widget.destroy()
             ])
             
        except Exception as e:
            print(f"Modpack install error: {e}")
            err_msg = f"Failed to install pack: {e}"
            self.root.after(0, lambda m=err_msg: [
                self.update_download_task(task_id, detail="Error"),
                messagebox.showerror("Error", m),
                btn_widget.config(state="normal", text="Download")
            ])

    def _load_mod_icon_async(self, url, label):
        if url in self.cached_mod_images:
            label.config(image=self.cached_mod_images[url], text="", width=64, height=64)
            return

        def fetch():
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    data = r.content
                    img = Image.open(io.BytesIO(data))
                    img = img.resize((64, 64), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    
                    def update_ui():
                        if label.winfo_exists():
                            self.cached_mod_images[url] = photo 
                            label.config(image=photo, text="", width=64, height=64)
                            # label.image = photo # tk bug prevention # already doing it via dict? No need to set attr if we have dict ref
                    
                    self.root.after(0, update_ui)
            except: pass
        
        threading.Thread(target=fetch, daemon=True).start()

    def create_settings_tab(self):
        container = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Settings"] = container
        
        # --- Layout: Sidebar (Left) + Content (Right) ---
        
        # Left Nav
        nav_frame = tk.Frame(container, bg=COLORS['sidebar_bg'], width=200) 
        nav_frame.pack(side="left", fill="y")
        nav_frame.pack_propagate(False)
        
        # Nav Header
        tk.Label(nav_frame, text="SETTINGS", font=("Segoe UI", 12, "bold"), 
                 bg=COLORS['sidebar_bg'], fg=COLORS['text_primary']).pack(pady=(20, 20))

        # Right Content
        content_frame = tk.Frame(container, bg=COLORS['main_bg'])
        content_frame.pack(side="right", fill="both", expand=True)

        # Content Canvas
        canvas = tk.Canvas(content_frame, bg=COLORS['main_bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=canvas.yview, style="Launcher.Vertical.TScrollbar")
        
        scrollable_frame = tk.Frame(canvas, bg=COLORS['main_bg'])
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=content_frame.winfo_reqwidth())

        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)

        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        # Scrollbar auto-hide logic could be added here, but Settings usually needs scrolling
        scrollbar.pack(side="right", fill="y")
        
        # Mousewheel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def _bind_mousewheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel(child)
        
        scrollable_frame.bind("<Configure>", lambda e: _bind_mousewheel(scrollable_frame))
        content_frame.bind("<Enter>", lambda e: _bind_mousewheel(scrollable_frame))

        # Scroll helper
        def scroll_to_widget(widget):
             # Force update to get accurate coords
             scrollable_frame.update_idletasks()
             y = widget.winfo_y()
             h = scrollable_frame.winfo_height()
             if h > 0:
                 canvas.yview_moveto(y / h)

        # Nav Buttons logic
        def create_nav_btn(text, target_widget):
            btn = tk.Button(nav_frame, text=text, font=("Segoe UI", 10),
                           bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'],
                           relief="flat", anchor="w", padx=20, pady=8,
                           command=lambda: scroll_to_widget(target_widget))
            btn.pack(fill="x")
            
            # Hover
            def on_enter(e): btn.config(bg=COLORS['card_bg'], fg="white")
            def on_leave(e): btn.config(bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'])
            btn.bind("<Enter>", on_enter)
            btn.bind("<Leave>", on_leave)

        # Main container
        main_container = tk.Frame(scrollable_frame, bg=COLORS['main_bg'])
        main_container.pack(fill="both", expand=True, padx=40, pady=30)
        
        # --- GENERAL ---
        lbl_general = tk.Label(main_container, text="GENERAL", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        lbl_general.pack(anchor="w", pady=(0, 15))

        self.close_launcher_var = tk.BooleanVar(value=getattr(self, 'close_launcher', True))
        tk.Checkbutton(main_container, text="Close launcher when game starts", variable=self.close_launcher_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=self.save_config).pack(anchor="w", pady=(0, 5))

        self.minimize_to_tray_var = tk.BooleanVar(value=getattr(self, 'minimize_to_tray', False))
        tk.Checkbutton(main_container, text="Minimize to tray on close", variable=self.minimize_to_tray_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=self.save_config).pack(anchor="w", pady=(0, 5))

        self.show_console_var = tk.BooleanVar(value=getattr(self, 'show_console', False))
        tk.Checkbutton(main_container, text="Keep output console open (Debug)", variable=self.show_console_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=self.save_config).pack(anchor="w", pady=(0, 15))

        # --- JAVA SETTINGS ---
        lbl_java = tk.Label(main_container, text="JAVA SETTINGS", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        lbl_java.pack(anchor="w", pady=(10, 15))
        
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
                 relief="flat", command=self.open_minecraft_dir).pack(side="left", padx=(5, 0)) # type: ignore

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

        # --- DOWNLOADS ---
        lbl_downloads = tk.Label(main_container, text="DOWNLOADS & FEATURES", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        lbl_downloads.pack(anchor="w", pady=(20, 15))

        # Modrinth Toggle
        self.enable_modrinth_var = tk.BooleanVar(value=getattr(self, 'enable_modrinth', True))
        def on_modrinth_toggle():
             val = self.enable_modrinth_var.get()
             self.enable_modrinth = val
             self.save_config()
             custom_showinfo("Restart Required", "Please restart the launcher to apply changes to Modrinth integration.")
        
        tk.Checkbutton(main_container, text="Enable Modrinth Integration (Mods Tab)", variable=self.enable_modrinth_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=on_modrinth_toggle).pack(anchor="w", pady=(0, 15))

        # Concurrent Limits
        tk.Label(main_container, text="Concurrent Limits", font=("Segoe UI", 10, "bold"), 
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 5))
        
        lim_frame = tk.Frame(main_container, bg=COLORS['main_bg'])
        lim_frame.pack(fill="x", pady=5)
        
        def update_limits(*args):
             try:
                 self.max_concurrent_packs = int(self.limit_packs_var.get())
                 self.max_concurrent_mods = int(self.limit_mods_var.get())
                 self.save_config(sync_ui=False)
             except: pass

        # Packs
        tk.Label(lim_frame, text="Modpacks:", bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(side="left")
        self.limit_packs_var = tk.StringVar(value=str(getattr(self, 'max_concurrent_packs', 1)))
        self.limit_packs_var.trace_add("write", update_limits)
        tk.Entry(lim_frame, textvariable=self.limit_packs_var, width=5, bg=COLORS['input_bg'], fg="white", relief="flat").pack(side="left", padx=(5, 15))

        # Mods
        tk.Label(lim_frame, text="Mods:", bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(side="left")
        self.limit_mods_var = tk.StringVar(value=str(getattr(self, 'max_concurrent_mods', 3)))
        self.limit_mods_var.trace_add("write", update_limits)
        tk.Entry(lim_frame, textvariable=self.limit_mods_var, width=5, bg=COLORS['input_bg'], fg="white", relief="flat").pack(side="left", padx=5)

        # Download Speed
        speed_frame = tk.Frame(main_container, bg=COLORS['main_bg'])
        speed_frame.pack(fill="x", pady=15)
        
        self.limit_speed_enc_var = tk.BooleanVar(value=getattr(self, 'limit_download_speed_enabled', False))
        tk.Checkbutton(speed_frame, text="Limit Download Speed", variable=self.limit_speed_enc_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'], selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=lambda: [setattr(self, 'limit_download_speed_enabled', self.limit_speed_enc_var.get()), self.save_config(sync_ui=False)]).pack(side="left")
        
        self.limit_speed_val_var = tk.StringVar(value=str(getattr(self, 'max_download_speed', 2048)))
        
        def update_speed(*args):
             try:
                 self.max_download_speed = int(self.limit_speed_val_var.get())
                 self.save_config(sync_ui=False)
             except: pass
        self.limit_speed_val_var.trace_add("write", update_speed)

        tk.Entry(speed_frame, textvariable=self.limit_speed_val_var, width=8, bg=COLORS['input_bg'], fg="white", relief="flat").pack(side="left", padx=(10, 5))
        tk.Label(speed_frame, text="KB/s", bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(side="left")

        # Discord RPC
        lbl_discord = tk.Label(main_container, text="DISCORD INTEGRATION", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        lbl_discord.pack(anchor="w", pady=(20, 15))

        self.rpc_var = tk.BooleanVar(value=True)
        self.rpc_detail_mode_var = tk.StringVar(value="Show Version")

        tk.Checkbutton(main_container, text="Enable Rich Presence", variable=self.rpc_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=self._on_rpc_toggle).pack(anchor="w", pady=(0, 5))
        
        # Detail Dropdown
        tk.Label(main_container, text="Second Line Detail", font=("Segoe UI", 10), 
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w", padx=20, pady=(5,0))
                
        rpc_combo = ttk.Combobox(main_container, textvariable=self.rpc_detail_mode_var, 
                                state="readonly", values=["Show Version", "Show Server IP", "Hidden"],
                                style="Launcher.TCombobox", width=30)
        rpc_combo.pack(anchor="w", padx=20, pady=(5, 20))
        rpc_combo.bind("<<ComboboxSelected>>", lambda e: self.save_config())

        # --- ACCOUNT ---
        lbl_acct = tk.Label(main_container, text="ACCOUNT", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        lbl_acct.pack(anchor="w", pady=(10, 15))
        
        tk.Label(main_container, text="Username", font=("Segoe UI", 10),
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        
        self.user_entry = tk.Entry(main_container, font=("Segoe UI", 11),
                                  bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                                  relief="flat", insertbackground="white")
        self.user_entry.pack(fill="x", pady=(5, 0), ipady=8)
        self.user_entry.bind("<FocusOut>", self.save_config)

        # --- APPEARANCE ---
        lbl_appear = tk.Label(main_container, text="LAUNCHER APPEARANCE", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        lbl_appear.pack(anchor="w", pady=(30, 15))
        
        # Accent Color
        tk.Label(main_container, text="Accent Color", font=("Segoe UI", 10),
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        
        accent_frame = tk.Frame(main_container, bg=COLORS['main_bg'])
        accent_frame.pack(fill="x", pady=(5, 10))
        
        def set_accent(name):
            self.apply_accent_color(name)

        _current = getattr(self, "accent_color_name", "Green")
        _attrs = [("Green", "#2D8F36"), ("Blue", "#3498DB"), ("Orange", "#E67E22"), ("Purple", "#9B59B6"), ("Red", "#E74C3C")]
        
        for name, col in _attrs:
            f = tk.Frame(accent_frame, bg=COLORS['main_bg'], padx=2, pady=2)
            f.pack(side="left", padx=5)
            
            # Indicator border if selected
            if name == _current:
                f.config(bg="white")

            btn = tk.Button(f, bg=col, width=6, height=2, relief="flat", cursor="hand2",
                           command=lambda n=name: set_accent(n))
            btn.pack()

        # Review Onboarding
        tk.Label(main_container, text="Onboarding", font=("Segoe UI", 10),
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(10, 5))
                
        tk.Button(main_container, text="Review setup wizard", font=("Segoe UI", 9),
                 bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", padx=15, pady=6, cursor="hand2",
                 command=lambda: self.show_onboarding_wizard()).pack(anchor="w")

        # --- LOGS ---
        lbl_logs = tk.Label(main_container, text="LAUNCHER LOGS", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        lbl_logs.pack(anchor="w", pady=(30, 15))
        
        self.log_area = scrolledtext.ScrolledText(main_container, height=6, bg=COLORS['input_bg'], 
                                                 fg=COLORS['text_secondary'], font=("Consolas", 9), relief="flat")
        self.log_area.pack(fill="both", expand=True)

        # --- UPDATES ---
        lbl_updates = tk.Label(main_container, text="UPDATES", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        lbl_updates.pack(anchor="w", pady=(30, 15))
        
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
        
        # --- DANGER ZONE ---
        lbl_danger = tk.Label(main_container, text="DANGER ZONE", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg="#E74C3C")
        lbl_danger.pack(anchor="w", pady=(30, 15))
        
        tk.Button(main_container, text="Reset to Defaults", font=("Segoe UI", 9, "bold"),
                 bg="#E74C3C", fg="white", activebackground="#C0392B", activeforeground="white",
                 relief="flat", padx=15, pady=8, cursor="hand2",
                 command=self.reset_to_defaults).pack(anchor="w")

        # Initial binding
        _bind_mousewheel(scrollable_frame)
        canvas.bind("<MouseWheel>", _on_mousewheel)
        
        # Populate Nav
        create_nav_btn("General", lbl_general)
        create_nav_btn("Java", lbl_java)
        create_nav_btn("Downloads", lbl_downloads)
        create_nav_btn("Discord", lbl_discord)
        create_nav_btn("Account", lbl_acct)
        create_nav_btn("Appearance", lbl_appear)
        create_nav_btn("Logs", lbl_logs)
        create_nav_btn("Updates", lbl_updates)
        create_nav_btn("Reset", lbl_danger)

    def reset_to_defaults(self):
        if custom_askyesno("Confirm Reset", "Are you sure you want to reset all settings?\nThis will delete your profiles and configurations.\nThe launcher will restart."):
            try:
                # Reset Config
                if os.path.exists(self.config_file):
                    try: os.remove(self.config_file)
                    except: pass
                
                # Reset Custom Wallpapers
                wp_dir = os.path.join(self.config_dir, "wallpapers")
                if os.path.exists(wp_dir):
                    try: shutil.rmtree(wp_dir, ignore_errors=True)
                    except: pass

                # Restart Logic
                cmd = [sys.executable]
                cwd = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()

                # Handle script vs frozen exe
                if not getattr(sys, 'frozen', False):
                    # We are running as a script (e.g. python alt.py)
                    script = sys.argv[0]
                    if not os.path.isabs(script):
                        script = os.path.abspath(script)
                        cwd = os.path.dirname(script)
                    cmd = [sys.executable, script] + sys.argv[1:]
                
                # Launch new instance detached with explicit CWD
                if os.name == 'nt':
                     subprocess.Popen(cmd, cwd=cwd, close_fds=True, creationflags=0x00000008) # DETACHED_PROCESS
                else:
                     subprocess.Popen(cmd, cwd=cwd, close_fds=True)

                # Exit current instance gracefully after a short delay
                self.root.after(500, self.root.quit)
                
            except Exception as e:
                custom_showerror("Error", f"Failed to reset: {e}")

    def create_addons_tab(self):
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Addons"] = frame
        
        # Header
        header = tk.Frame(frame, bg=COLORS['main_bg'], pady=20, padx=30)
        header.pack(fill="x")
        
        tk.Label(header, text="Addons & Agent", font=("Segoe UI", 24, "bold"), bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(side="left")

        # Scrollable Content
        canvas = tk.Canvas(frame, bg=COLORS['main_bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview, style="Launcher.Vertical.TScrollbar")
        scroll_frame = tk.Frame(canvas, bg=COLORS['main_bg'])
        
        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
            
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mousewheel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def _bind_mousewheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel(child)

        # Bind enter/leave for scrolling
        frame.bind("<Enter>", lambda e: _bind_mousewheel(scroll_frame))
        
        # --- content ---
        content = tk.Frame(scroll_frame, bg=COLORS['main_bg'], padx=30, pady=10)
        content.pack(fill="x")

        # GitHub Skin Sync
        sync_frame = tk.Frame(content, bg=COLORS['card_bg'], padx=20, pady=20)
        sync_frame.pack(fill="x", pady=(0, 20))
        
        tk.Label(sync_frame, text="GitHub Skin Sync", font=("Segoe UI", 16, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 5))
        tk.Label(sync_frame, text="Link a GitHub repository to sync skins with your friends.", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 20))

        # Enable Toggle
        self.gh_sync_enabled = tk.BooleanVar(value=self.addons_config.get("gh_sync_enabled", False))
        tk.Checkbutton(sync_frame, text="Enable Skin Sync", variable=self.gh_sync_enabled,
                      bg=COLORS['card_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['card_bg'], activebackground=COLORS['card_bg'],
                      command=self._save_addons_config).pack(anchor="w", pady=(0, 15))

        # Inputs Grid
        grid_frame = tk.Frame(sync_frame, bg=COLORS['card_bg'])
        grid_frame.pack(fill="x")
        grid_frame.columnconfigure(1, weight=1)

        # Repo
        tk.Label(grid_frame, text="Repository (user/repo):", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).grid(row=0, column=0, sticky="w", pady=5)
        self.gh_repo_entry = tk.Entry(grid_frame, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg="white", relief="flat")
        self.gh_repo_entry.insert(0, str(self.addons_config.get("gh_repo", "")))
        self.gh_repo_entry.grid(row=0, column=1, sticky="ew", padx=10, ipady=5)

        # Token
        tk.Label(grid_frame, text="Access Token (PAT):", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).grid(row=1, column=0, sticky="w", pady=5)
        self.gh_token_entry = tk.Entry(grid_frame, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg="white", relief="flat", show="*")
        self.gh_token_entry.insert(0, str(self.addons_config.get("gh_token", "")))
        self.gh_token_entry.grid(row=1, column=1, sticky="ew", padx=10, ipady=5)
        
        # Save Button
        tk.Button(sync_frame, text="Save & Sync", command=self._save_gh_sync_settings, 
                 bg=COLORS['accent_blue'], fg="white", font=("Segoe UI", 10), 
                 padx=20, pady=8, relief="flat", cursor="hand2").pack(anchor="w", pady=(20, 0))

        # Instructions
        info_frame = tk.Frame(content, bg=COLORS['main_bg'], pady=10)
        info_frame.pack(fill="x")
        
        info_text = """
How to use:
1. Create a public or private GitHub repository.
2. Generate a Personal Access Token (PAT) with 'repo' scope.
3. Enter the repository name (e.g., 'MyName/Skins') and the token above.
4. Enable the feature. The launcher will upload your current skin to the repo and download friends' skins automatically.
        """
        tk.Label(info_frame, text=info_text, font=("Segoe UI", 9), justify="left", bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")

    def _save_addons_config(self):
        self.addons_config["gh_sync_enabled"] = self.gh_sync_enabled.get()
        self.save_config()

    def _save_gh_sync_settings(self):
        repo = self.gh_repo_entry.get().strip()
        token = self.gh_token_entry.get().strip()
        
        self.addons_config.update({
            "gh_sync_enabled": self.gh_sync_enabled.get(),
            "gh_repo": repo,
            "gh_token": token
        })
        self.save_config()
        
        if self.gh_sync_enabled.get():
             self.perform_gh_skin_sync()
        else:
             custom_showinfo("Saved", "Settings saved.")

    def perform_gh_skin_sync(self):
        # Trigger Agent to Sync
        if not self.profiles: return
        
        current_p = self.profiles[self.current_profile_index]
        username = current_p.get("name", "Unknown")
        skin_path = current_p.get("skin_path")
        
        payload = {
            "repo": self.addons_config.get("gh_repo"),
            "token": self.addons_config.get("gh_token"),
            "username": username,
            "skin_path": skin_path,
            "upload": True,
            "download": True
        }
        
        self.show_progress_overlay("Syncing Skins...")
        
        def on_complete(res):
            self.hide_progress_overlay()
            if res.get("status") == "success":
                custom_showinfo("Success", f"Skin sync complete!\n{res.get('msg', '')}")
            else:
                custom_showerror("Sync Error", res.get("msg", "Unknown error"))
                
        self.send_agent_request("gh_skin_sync", payload, lambda r: self.root.after(0, lambda: on_complete(r)))

    def start_agent_process(self):

        if hasattr(self, 'agent_process') and self.agent_process and self.agent_process.poll() is None:
            return # Already running
            
        try:
            cwd = os.path.dirname(os.path.abspath(__file__))
            
            # Determine command based on environment (Frozen vs Source)
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
                agent_exe = os.path.join(base_dir, "agent.exe")
                cmd = [agent_exe, self.config_dir]
                cwd = base_dir
            else:
                script = os.path.join(cwd, "agent.py")
                cmd = [sys.executable, script, self.config_dir]
            
            # Start detached process with pipes
            startupinfo = None
            creationflags = 0
            
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = subprocess.CREATE_NO_WINDOW
                
            self.agent_process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, 
                text=True,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            
            # Start Listener
            threading.Thread(target=self._agent_listener_thread, daemon=True).start()
            
            self.log(f"Agent started with PID {self.agent_process.pid}")
            
        except Exception as e:
            custom_showerror("Agent Error", f"Failed to start agent: {e}")

    def _agent_listener_thread(self):
        if not self.agent_process: return
        
        try:
            while self.agent_process and self.agent_process.poll() is None:
                # Use readline to get line-buffered output
                if not self.agent_process.stdout: break
                line = self.agent_process.stdout.readline()
                if not line: break
                
                try:
                    data = json.loads(line)
                    req_id = data.get("id")
                    
                    if req_id in self.agent_callbacks:
                        callback = self.agent_callbacks.pop(req_id)
                        # Run callback on main thread
                        self.root.after(0, lambda c=callback, d=data.get("result"): c(d))
                        
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            print(f"Agent listener error: {e}")
            
        # Cleanup if process died
        self.root.after(0, self._on_agent_exit)

    def _on_agent_exit(self):
        self.agent_process = None

    def send_agent_request(self, action, payload, callback=None):
        if not self.agent_process or self.agent_process.poll() is not None:
            # Try to auto-start
            self.start_agent_process()
            # If still failed, abort
            if not self.agent_process or self.agent_process.poll() is not None:
                if callback:
                    callback({"status": "error", "msg": "Agent not running"})
                return

        req_id = str(uuid.uuid4())
        request = {"id": req_id, "action": action, "payload": payload}
        
        if callback:
            self.agent_callbacks[req_id] = callback
            
        try:
            with self.agent_lock:
                if self.agent_process.stdin:
                    self.agent_process.stdin.write(json.dumps(request) + "\n")
                    self.agent_process.stdin.flush()
        except Exception as e:
            if req_id in self.agent_callbacks:
                 del self.agent_callbacks[req_id]
            if callback:
                 callback({"status": "error", "msg": str(e)})

    def stop_agent_process(self):
        if hasattr(self, 'agent_process') and self.agent_process:
            self.agent_process.terminate()
            self.agent_process = None
            
            self.log("Agent stopped.")

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
                update_available = False
                try:
                    current_parts = [int(x) for x in CURRENT_VERSION.split(".")]
                    latest_parts = [int(x) for x in latest_tag.split(".")]
                    
                    for i in range(max(len(current_parts), len(latest_parts))):
                        cur = current_parts[i] if i < len(current_parts) else 0
                        lat = latest_parts[i] if i < len(latest_parts) else 0
                        if lat > cur:
                            update_available = True
                            break
                        elif lat < cur:
                            break 
                except ValueError:
                    if latest_tag and latest_tag != CURRENT_VERSION:
                        update_available = True
                            
                if update_available:
                    asset_url = None
                    for asset in data.get("assets", []):
                        if asset.get("name", "").endswith(".exe"):
                            asset_url = asset.get("browser_download_url")
                            break
                    self.root.after(0, lambda: self._on_update_found(latest_tag, data.get("html_url"), asset_url))
                else:
                     self.root.after(0, lambda: self.update_status_lbl.config(text="You are on the latest version.", fg=COLORS['success_green']))
            else:
                 self.root.after(0, lambda: self.update_status_lbl.config(text=f"Failed to check: {response.status_code}", fg=COLORS['error_red']))
        except Exception as e:
            self.root.after(0, lambda: self.update_status_lbl.config(text=f"Error checking updates", fg=COLORS['error_red']))
            print(f"Update check error: {e}")

    def _on_update_found(self, version, html_url, asset_url):
        self.update_status_lbl.config(text=f"New version available: {version}", fg=COLORS['accent_blue'])
        
        # Choice: Yes -> Auto Update, Manual -> Visit Page, No -> Dismiss
        btns = [
            ("Yes, Update", True, "primary"), 
            ("I'll do it myself", "manual", "secondary"), 
            ("No", False, "secondary")
        ]
        
        mbox = CustomMessagebox(
            "Update Available", 
            f"A new version ({version}) is available.\n\n"
            "Would you like to auto-update now?", 
            type="yesno", 
            buttons=btns, 
            parent=self.root
        )
        choice = mbox.result
        
        if choice is True:
            if asset_url:
                self.perform_auto_update(asset_url, version)
            else:
                custom_showerror("Error", "No executable found for auto-update.\nOpening release page instead.")
                if html_url:
                    webbrowser.open(html_url)
        elif choice == "manual":
             if html_url:
                webbrowser.open(html_url)

    def open_minecraft_dir(self):
        try:
            os.startfile(self.minecraft_dir)
        except Exception as e:
            self.log(f"Error opening folder: {e}")

    def setup_tray(self):
        if not TRAY_AVAILABLE or TrayItem is None: return
        
        def quit_app(icon, item):
            icon.stop()
            self.root.destroy()
            sys.exit()

        def show_app(icon, item):
            self.restore_window()
        try:
            image = Image.open(resource_path("logo.ico"))
        except:
            # Fallback
            image = Image.new('RGB', (64, 64), color = (73, 109, 137))
            
        menu = (TrayItem('Open', show_app, default=True), TrayItem('Quit', quit_app))
        if TRAY_AVAILABLE and TrayIcon:
            self.tray_icon = TrayIcon("New Launcher", image, "New Launcher", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        
        # Override minimize
        self.root.bind("<Unmap>", self._on_window_minimize)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_window_minimize(self, event):
        # Filter out random Unmap events (e.g. from widgets)
        if event and event.widget != self.root:
            return

        if self.root.state() == 'iconic':
            # Only withdraw if "Minimize to tray" is enabled
            should_tray = False
            if hasattr(self, 'minimize_to_tray_var'):
                should_tray = self.minimize_to_tray_var.get()
            else:
                should_tray = getattr(self, 'minimize_to_tray', False)

            if should_tray:
                self.root.withdraw()

    def restore_window(self):
        self.root.deiconify()
        self.root.state('normal')
        
    def _on_close(self):
         should_tray = False
         if hasattr(self, 'minimize_to_tray_var'):
             should_tray = self.minimize_to_tray_var.get()
         else:
             should_tray = getattr(self, 'minimize_to_tray', False)

         if should_tray and hasattr(self, 'tray_icon') and self.tray_icon:
             self.root.withdraw()
         else:
             if hasattr(self, 'tray_icon') and self.tray_icon:
                 self.tray_icon.stop()
             self.root.destroy()
             os._exit(0)

    # --- LOGIC ---
    def setup_logging(self):
        try:
            # Determine log directory based on config location
            # If config_dir is set (which points to either local dir or .nlc), use that.
            if hasattr(self, 'config_dir'):
                log_dir = os.path.join(self.config_dir, "logs")
            else:
                # Fallback if config_dir is not yet set
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
            
            # Remove existing handlers
            for handler in logging.root.handlers[:]:
                logging.root.removeHandler(handler)
                
            logging.basicConfig(
                level=logging.NOTSET, # Capture everything, handlers will filter
                format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
                handlers=[
                    logging.FileHandler(self.log_file_path, encoding='utf-8'),
                    logging.StreamHandler(sys.stdout)
                ]
            )
            
            logging.info(f"Launcher initialized. Log file: {self.log_file_path}")
            logging.info(f"System: {platform.system()} {platform.release()} {platform.version()}")
            
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
            # User Info for formatted Rich Presence
            user_text = "Steve"
            small_key = "steve" # Fallback asset key
            
            if self.profiles and hasattr(self, 'current_profile_index') and 0 <= self.current_profile_index < len(self.profiles):
                p = self.profiles[self.current_profile_index]
                user_text = p.get("name", "Steve")
                # Use MC-Heads for dynamic avatar if UUID exists (Microsoft/Ely.by)
                if p.get("uuid"):
                    small_key = f"https://mc-heads.net/avatar/{p.get('uuid')}"
            
            kwargs = {
                "state": state,
                "details": details,
                "large_image": "logo", 
                "large_text": "New Launcher",
                "small_image": small_key,
                "small_text": user_text
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
        # Update UI
        try:
            if hasattr(self, 'log_area') and self.log_area.winfo_exists():
                timestamp = datetime.now().strftime("%H:%M:%S")
                # Strip [GAME] prefix for UI if needed, but keeping it is good for context
                line = f"[{timestamp}] {message}"
                self.log_area.insert(tk.END, line + "\n")
                self.log_area.see(tk.END)
        except:
            pass
        
        # Write to log file via logging module
        logging.info(message)

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
        
        # Enforce settings based on account type
        p_type = p.get("type", "offline")
        if p_type == "microsoft":
            self.auto_download_mod = False
            if hasattr(self, 'auto_download_var'):
                 self.auto_download_var.set(False)
        
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

                    # First Run Check (Must be done before any save_config triggers)
                    self.first_run = not data.get("first_run_completed", False)
                    self.addons_config = data.get("addons", {})
                    
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
                            "id": str(uuid.uuid4()),
                            "name": "Latest Release",
                            "version": "latest-release", # Metadata placeholder
                            "loader": "Vanilla",
                            "icon": "icons/grass_block_side.png",
                            "last_played": "Never",
                            "created": "2024-01-01"
                        }]
                        print("Initialized default installations")
                    else:
                        # Ensure IDs
                        for inst in self.installations:
                            if "id" not in inst:
                                inst["id"] = str(uuid.uuid4())
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

                    # Downloads & Features
                    self.max_concurrent_packs = data.get("max_concurrent_packs", 1)
                    self.max_concurrent_mods = data.get("max_concurrent_mods", 3)
                    self.limit_download_speed_enabled = data.get("limit_download_speed_enabled", False)
                    self.max_download_speed = data.get("max_download_speed", 2048) # KB/s
                    self.enable_modrinth = data.get("enable_modrinth", False)
                    
                    if hasattr(self, 'enable_modrinth_var'): self.enable_modrinth_var.set(self.enable_modrinth)
                    
                    # Addons
                    if "addons" in data:
                        self.addons_config.update(data["addons"])

                    # Load RPC
                    self.rpc_enabled = data.get("rpc_enabled", True)
                    self.rpc_var.set(self.rpc_enabled)
                    
                    # New Detail Mode with Backward Compat
                    saved_mode = data.get("rpc_detail_mode", None)
                    if saved_mode:
                        self.rpc_detail_mode_var.set(saved_mode)
                    else:
                        # Infer from old bools
                        show_ver = data.get("rpc_show_version", True)
                        show_serv = data.get("rpc_show_server", True)
                        if show_ver: val = "Show Version"
                        elif show_serv: val = "Show Server IP"
                        else: val = "Hidden"
                        self.rpc_detail_mode_var.set(val)
                    
                    self.rpc_show_version = (self.rpc_detail_mode_var.get() == "Show Version")
                    self.rpc_show_server = (self.rpc_detail_mode_var.get() == "Show Server IP")
                    self.auto_update_check = data.get("auto_update_check", True)
                    self.close_launcher = data.get("close_launcher", True)
                    self.minimize_to_tray = data.get("minimize_to_tray", False)
                    self.show_console = data.get("show_console", False)
                    
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
                self.first_run = True # Error implies we should probable re-onboard or fallback
        else: 
            print("Config file not found, creating default")
            self.first_run = True # Explicitly true for no config

        # --- Default Wallpaper Fallback ---
        if not self.hero_img_raw:
             try:
                 # Check for 'Island.png' or 'background.png' in wallpapers dir
                 possible_defaults = ["Island.png", "background.png"]
                 for name in possible_defaults:
                     path = resource_path(os.path.join("wallpapers", name))
                     if os.path.exists(path):
                         self.current_wallpaper = path
                         self.hero_img_raw = Image.open(path)
                         print(f"Loaded default wallpaper: {name}")
                         break
             except Exception as e:
                 print(f"Failed to load default wallpaper: {e}")
            
        # Trigger background check for MS skin model to ensure radio button matches server
        if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
            try:
                p = self.profiles[self.current_profile_index]
                if p.get("type") == "microsoft":
                     threading.Thread(target=self._startup_ms_skin_check, daemon=True).start()
            except: pass

    def save_config(self, *args, sync_ui=True):
        print(f"Saving config to: {self.config_file}")
        # Update current profile info before saving
        if sync_ui and self.profiles and 0 <= self.current_profile_index < len(self.profiles):
            self.profiles[self.current_profile_index]["skin_path"] = self.skin_path
            # Sync username from entry if available
            if hasattr(self, 'user_entry'):
                 name = self.user_entry.get().strip()
                 if name:
                    self.profiles[self.current_profile_index]["name"] = name
        
        # Update java args from entry if it exists
        if sync_ui and hasattr(self, 'java_args_entry'):
             self.java_args = self.java_args_entry.get().strip()
             
        # Get RPC settings

        rpc_mode = "Show Version"
        if hasattr(self, 'rpc_detail_mode_var'): rpc_mode = self.rpc_detail_mode_var.get()
        if hasattr(self, 'auto_update_var'): self.auto_update_check = self.auto_update_var.get()
        
        # Map mode to old bools for compat or runtime usage
        self.rpc_show_version = (rpc_mode == "Show Version")
        self.rpc_show_server = (rpc_mode == "Show Server IP")
        
        config = {
            "first_run_completed": not self.first_run,
            "accent_color": getattr(self, "accent_color_name", "Green"),
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
            "rpc_detail_mode": rpc_mode,
            "rpc_show_version": self.rpc_show_version,
            "rpc_show_server": self.rpc_show_server,
            "auto_update_check": self.auto_update_check,
            # Features / Downloads
            "max_concurrent_packs": getattr(self, 'max_concurrent_packs', 1),
            "max_concurrent_mods": getattr(self, 'max_concurrent_mods', 3),
            "limit_download_speed_enabled": getattr(self, 'limit_download_speed_enabled', False),
            "max_download_speed": getattr(self, 'max_download_speed', 2048),
            "enable_modrinth": getattr(self, 'enable_modrinth', True),
            # UI State
            "close_launcher": getattr(self, 'close_launcher_var', tk.BooleanVar(value=True)).get(),
            "minimize_to_tray": getattr(self, 'minimize_to_tray_var', tk.BooleanVar(value=False)).get(),
            "show_console": getattr(self, 'show_console_var', tk.BooleanVar(value=False)).get(),
            "current_wallpaper": getattr(self, 'current_wallpaper', None),
            "addons": getattr(self, "addons_config", {})
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

    def custom_skin_model_popup(self, parent=None):
        # Returns "classic" or "slim" or None if cancelled
        result = {"model": None}
        
        # Check current profile for default preference
        current_model = "classic"
        if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
            current_model = self.profiles[self.current_profile_index].get("skin_model", "classic")
            
        dialog = tk.Toplevel(parent if parent else self.root)
        dialog.title("Skin Model")
        dialog.geometry("350x250")
        dialog.config(bg=COLORS['main_bg'])
        try: # Center it
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 175
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 125
            dialog.geometry(f"+{x}+{y}")
        except: pass
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()
        
        tk.Label(dialog, text="Select Skin Model", font=("Segoe UI", 12, "bold"), 
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=15)
        
        tk.Label(dialog, text="Does your skin have 3px (Slim) or 4px (Classic) arms?", 
                 font=("Segoe UI", 9), bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(pady=(0, 20))
        
        btn_frame = tk.Frame(dialog, bg=COLORS['main_bg'])
        btn_frame.pack(fill="x", padx=30)
        
        def set_classic():
            result['model'] = "classic" # type: ignore
            dialog.destroy()
            
        def set_slim():
            result['model'] = "slim" # type: ignore
            dialog.destroy()
            
        # Helper for active style
        active_bd = 2
        active_relief = "solid"
        
        # Classic (Steve)
        b1_bg = COLORS['success_green'] if current_model == "classic" else COLORS['card_bg']
        b1 = tk.Button(btn_frame, text="Classic (Steve)\n4px Arms", font=("Segoe UI", 10),
                      bg=b1_bg, fg=COLORS['text_primary'], relief="flat", padx=10, pady=10,
                      command=set_classic, width=15)
        if current_model == "classic": b1.config(fg="white") # Highlight text too
        b1.pack(side="left", padx=5)
        
        # Slim (Alex)
        b2_bg = COLORS['success_green'] if current_model == "slim" else COLORS['card_bg']
        b2 = tk.Button(btn_frame, text="Slim (Alex)\n3px Arms", font=("Segoe UI", 10),
                      bg=b2_bg, fg=COLORS['text_primary'], relief="flat", padx=10, pady=10,
                      command=set_slim, width=15)
        if current_model == "slim": b2.config(fg="white")
        b2.pack(side="right", padx=5)
        
        self.root.wait_window(dialog)
        return result['model']

    def upload_ms_skin(self, path, variant, token):
        self.log(f"DEBUG: Uploading skin to Minecraft... Path: {path}, Variant: {variant}")
        try:
             url = "https://api.minecraftservices.com/minecraft/profile/skins"
             # Mask token in logs for security, only show first few chars
             masked_token = token[:8] + "..." if len(token) > 8 else "***"
             self.log(f"DEBUG: Request URL: {url}")
             self.log(f"DEBUG: Auth Token: {masked_token}")
             
             headers = {"Authorization": f"Bearer {token}"}
             files = {
                 "variant": (None, variant),
                 "file": ("skin.png", open(path, "rb"), "image/png")
             }
             
             r = requests.post(url, headers=headers, files=files)
             
             self.log(f"DEBUG: Response Status: {r.status_code}")
             self.log(f"DEBUG: Response Headers: {r.headers}")
             self.log(f"DEBUG: Response Body: {r.text}")
             
             if r.status_code == 200:
                 self.log(f"Skin uploaded successfully ({variant})")
                 return True
             else:
                 self.log(f"Skin upload failed: {r.status_code} {r.text}")
                 return False
        except Exception as e:
            self.log(f"Upload exception: {e}")
            import traceback
            self.log(traceback.format_exc())
            return False

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
                        self.add_skin_to_history(path, "classic")
                        custom_showinfo("Skin Refreshed", "Skin updated from Ely.by successfully.")
                    else:
                        self.skin_indicator.config(text="Refresh Failed", fg="red")
                        custom_showwarning("Refresh Failed", "Could not fetch skin from Ely.by.")
                
                self.root.after(0, _update_ui)
            
            threading.Thread(target=_refresh, daemon=True).start()
        
        elif p_type == "microsoft":
            self.skin_indicator.config(text="Refreshing...", fg=COLORS['text_primary'])
            self.root.update()
            
            def _refresh_ms():
                token = p.get("access_token")
                path = self.fetch_microsoft_skin(name, uuid_, token)
                
                def _update_ui():
                    if path:
                        self.profiles[self.current_profile_index]["skin_path"] = path
                        # Model is updated in profile by fetch_microsoft_skin side-effect
                        model = self.profiles[self.current_profile_index].get("skin_model", "classic")
                        self.update_active_profile()
                        self.add_skin_to_history(path, model)
                        # Don't show success box if auto-called (check if called by user?) or just show small toast?
                        # For now, let's keep it but maybe it's annoying if auto-called.
                        # Actually, better to just log it if successful, only warn on fail.
                        pass # self.log("Skin updated")
                    else:
                        self.skin_indicator.config(text="Refresh Failed", fg="red")
                        # messagebox.showwarning("Refresh Failed", "Could not fetch skin. Session might be expired.")
                
                self.root.after(0, _update_ui)
                
            threading.Thread(target=_refresh_ms, daemon=True).start()
            
        else:
             self.update_active_profile()

    def _startup_ms_skin_check(self):
        try:
            if not self.profiles: return
            p = self.profiles[self.current_profile_index]
            token = p.get("access_token")
            if not token: return

            headers = {"Authorization": f"Bearer {token}"}
            # Silent check
            r = requests.get("https://api.minecraftservices.com/minecraft/profile", headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                skins = data.get("skins", [])
                active_skin = next((s for s in skins if s["state"] == "ACTIVE"), None)
                if active_skin:
                    variant = active_skin.get("variant", "CLASSIC").lower()
                    # Check against local
                    local_model = p.get("skin_model", "classic")
                    
                    if variant != local_model:
                         self.log(f"Syncing skin model to match server ({variant})")
                         p["skin_model"] = variant
                         if hasattr(self, 'skin_model_var'):
                             self.root.after(0, lambda: self.skin_model_var.set(variant))
                         self.save_config(sync_ui=False)
        except: pass

    def fetch_microsoft_skin(self, username, uuid_, token):
        try:
            headers = {"Authorization": f"Bearer {token}"}
            # Fetch Profile
            r = requests.get("https://api.minecraftservices.com/minecraft/profile", headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                skins = data.get("skins", [])
                active_skin = next((s for s in skins if s["state"] == "ACTIVE"), None)
                
                if active_skin:
                    skin_url = active_skin["url"]
                    variant = active_skin.get("variant", "CLASSIC").lower()
                    
                    # Store model
                    if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
                         self.profiles[self.current_profile_index]["skin_model"] = "classic" if variant == "classic" else "slim"
                    
                    # Download
                    target_path = os.path.join(self.config_dir, "skins", f"{username}_ms.png")
                    if not os.path.exists(os.path.dirname(target_path)):
                        os.makedirs(os.path.dirname(target_path))
                        
                    print(f"Downloading MS skin from {skin_url}")
                    r_img = requests.get(skin_url, timeout=10)
                    if r_img.status_code == 200:
                        with open(target_path, "wb") as f:
                            f.write(r_img.content)
                        return target_path
            else:
                 print(f"MS Profile fetch failed: {r.status_code}")
                 
        except Exception as e:
            print(f"Error fetching MS skin: {e}")
            
        return ""

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
            if custom_askyesno("Ely.by Skin", "Ely.by requires skins to be managed via their website.\n\nOpen Ely.by skin catalog for your user?"):
                name = p.get("name", "")
                webbrowser.open(f"https://ely.by/skins?uploader={name}")
            return
            
        elif p_type == "microsoft":
             # Upload Logic directly
             path = filedialog.askopenfilename(filetypes=[("Image files", "*.png")])
             if not path: return
             
             # Verify size
             try:
                 im = Image.open(path)
                 w, h = im.size
                 if w != 64 or (h != 64 and h != 32):
                     if not custom_askyesno("Warning", f"Skin dimensions {w}x{h} might not work perfectly. Standard is 64x64. Continue?"):
                         return
                 
                 token = p.get("access_token")
                 
                 # Ask model
                 variant = self.custom_skin_model_popup()
                 if not variant: return # Cancelled
                     
                 # Upload
                 if self.upload_ms_skin(path, variant, token):
                     custom_showinfo("Success", "Skin uploaded successfully!")
                     self.profiles[self.current_profile_index]["skin_path"] = path
                     self.profiles[self.current_profile_index]["skin_model"] = variant
                     self.update_active_profile()
                     self.add_skin_to_history(path, variant)
                     self.save_config()
                 else:
                     custom_showerror("Error", f"Failed to upload skin.")
                     
             except Exception as e:
                 custom_showerror("Error", f"Upload failed: {e}")
             return

        # Offline / Standard
        if not self.auto_download_mod:
            if custom_askyesno("Skin Injection", "Enable Skin Injection to use this skin in-game?"):
                self.auto_download_mod = True
                self.auto_download_var.set(True)
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.png")])
        if path:
            self.skin_path = path
            
            # Ask model for offline usage too (for correct injections/rendering)
            variant = self.custom_skin_model_popup() or "classic"
            
            if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
                self.profiles[self.current_profile_index]["skin_path"] = path
                self.profiles[self.current_profile_index]["skin_model"] = variant
                
            self.update_active_profile()
            self.add_skin_to_history(path, variant)
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

    def get_installations(self):
        # Return dict {id: inst}
        d = {}
        for inst in self.installations:
            if "id" in inst:
                d[inst["id"]] = inst
        return d

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
        
        # Generate Background Resource Pack if wallpaper exists
        if self.current_wallpaper:
            self.create_background_resource_pack()

        # Show Progress Overlay
        self.show_progress_overlay("Launching Minecraft...")
        
        self.update_rpc("Launching...", f"Version: {version_id} ({loader})")

        self.launch_btn.config(state="disabled", text="LAUNCHING...")
        self.launch_opts_btn.config(state="disabled")
        # self.set_status("Launching Minecraft...") # Redundant with overlay
        inst_id = inst.get("id")
        threading.Thread(target=self.launch_logic, args=(version_id, username, loader, force_update, inst_id), daemon=True).start()

    def launch_logic(self, version, username, loader, force_update=False, inst_id=None):
        mods_backup_path = None
        # Callback wrapper to update overlay
        def update_status(t):
            self.log(f"Status: {t}")
            self.root.after(0, lambda: self.update_progress_label.config(text=t) if hasattr(self, 'update_progress_label') else None)

        def update_progress(v):
            if hasattr(self, 'update_progress_bar'):
                self.update_progress_bar.config(value=v)
                # Update counter label (Current / Max)
                try:
                    m = self.update_progress_bar['maximum']
                    if hasattr(self, 'update_counter_label') and m > 0:
                        self.update_counter_label.config(text=f"{int(v)} / {int(m)}")
                except: pass

        def set_max(m):
             if hasattr(self, 'update_progress_bar'):
                self.update_progress_bar.config(maximum=m)
                # Force update counter immediately if max changes
                try:
                    v = self.update_progress_bar['value']
                    if hasattr(self, 'update_counter_label') and m > 0:
                         self.update_counter_label.config(text=f"{int(v)} / {int(m)}")
                except: pass

        callback = cast(Any, {
            "setStatus": update_status,
            "setProgress": lambda v: self.root.after(0, lambda: update_progress(v)),
            "setMax": lambda m: self.root.after(0, lambda: set_max(m))
        })
        local_skin_server = None
        try:
            launch_id = version
            
            # --- Check for existing installations to avoid re-downloading ---
            installed_versions = [v['id'] for v in minecraft_launcher_lib.utils.get_installed_versions(self.minecraft_dir)]

            # Resolve Java for Installers (Fabric/Forge need Java to run their installer)
            java_install_path = "java"
            try:
                # 1. Try Library Utility (No args)
                rt = minecraft_launcher_lib.utils.get_java_executable()
                
                if rt and os.path.exists(rt):
                    java_install_path = rt
                elif shutil.which("java"):
                    java_install_path = shutil.which("java")
                else:
                    # 2. Check Local Runtime Folder Manually
                    runtime_dir = os.path.join(self.minecraft_dir, "runtime")
                    local_java = None
                    if os.path.exists(runtime_dir):
                        for root, dirs, files in os.walk(runtime_dir):
                            if "java.exe" in files:
                                local_java = os.path.join(root, "java.exe")
                                break
                            elif "java" in files and sys.platform != "win32":
                                local_java = os.path.join(root, "java")
                                break
                    
                    if local_java:
                        java_install_path = local_java
                    else:
                        # 3. No Java found - Install Vanilla first to fetch Runtime
                        self.log("Java not found. Installing Vanilla version to fetch Runtime...")
                        try:
                            minecraft_launcher_lib.install.install_minecraft_version(version, self.minecraft_dir, callback=callback)
                            # Scan again
                            if os.path.exists(runtime_dir):
                                for root, dirs, files in os.walk(runtime_dir):
                                    if "java.exe" in files:
                                        java_install_path = os.path.join(root, "java.exe")
                                        break
                                    elif "java" in files and sys.platform != "win32":
                                        java_install_path = os.path.join(root, "java")
                                        break
                        except Exception as e:
                            self.log(f"Failed to install vanilla runtime: {e}")
                            if "launchermeta.mojang.com" in str(e) or "getaddrinfo failed" in str(e):
                                self.log("Network Error: Could not connect to Mojang. Check your internet.")

                        if java_install_path == "java" and not shutil.which("java"):
                             self.log("Warning: Could not resolve setup Java. Fabric/Forge installation might fail.")
            except Exception as e:
                self.log(f"Java resolution error: {e}")
            
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
                    result = minecraft_launcher_lib.fabric.install_fabric(version, self.minecraft_dir, callback=callback, java=java_install_path)
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
                        minecraft_launcher_lib.forge.install_forge_version(forge_v, self.minecraft_dir, callback=callback, java=java_install_path)
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

            elif acct_type == "microsoft":
                self.log("Validating Microsoft Session...")
                refresh_token = current_profile.get("refresh_token")
                if refresh_token:
                    try:
                         # Refresh
                         new_data = minecraft_launcher_lib.microsoft_account.complete_refresh(MSA_CLIENT_ID, None, MSA_REDIRECT_URI, refresh_token)
                         if "error" not in new_data:
                             # Update profile
                             current_profile["access_token"] = new_data["access_token"]
                             current_profile["refresh_token"] = new_data["refresh_token"]
                             current_profile["name"] = new_data["name"]
                             current_profile["uuid"] = new_data["id"]
                             self.save_config()
                             
                             username = new_data["name"]
                             launch_uuid = new_data["id"]
                             launch_token = new_data["access_token"]
                             self.log(f"Session refreshed for {username}")
                         else:
                             raise Exception(f"Session Expired: {new_data.get('error')}")
                    except Exception as e:
                         self.log(f"Token refresh error: {e}")
                         raise Exception("Failed to refresh Microsoft session. Please re-login.")
                else:
                    raise Exception("No refresh token found. Please re-login.")

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

            # --- MODPACK SWAP ---
            try:
                if inst_id:
                     pack = next((p for p in self.modpacks if p.get('linked_installation_id') == inst_id), None)
                     if pack:
                         self.log(f"Loading Modpack: {pack['name']}")
                         mods_dir = os.path.join(self.minecraft_dir, "mods")
                         pack_mods_dir = os.path.join(self.get_modpack_dir(pack['id']), "mods")
                         
                         # Only swap if pack has mods folder
                         if os.path.exists(pack_mods_dir):
                             timestamp = int(time.time())
                             mods_backup_path = os.path.join(self.minecraft_dir, f"mods_backup_{timestamp}")
                             
                             if os.path.exists(mods_dir):
                                 # Rename current to backup
                                 os.rename(mods_dir, mods_backup_path)
                             
                             # Copy pack mods to live folder
                             # Using copytree can be slow. Symlink if possible?
                             # Windows requires Admin for symlinks usually. Copy is safer.
                             shutil.copytree(pack_mods_dir, mods_dir)
                             self.log("Swapped mods folder for modpack.")
            except Exception as e:
                self.log(f"Modpack swap error: {e}")

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
                cwd=self.minecraft_dir,
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
            
            err_msg = str(e)
            if "launchermeta.mojang.com" in err_msg or "getaddrinfo failed" in err_msg:
                 err_msg = "Network Error: Could not connect to Mojang servers.\nPlease check your internet connection."
            
            self.root.after(0, lambda: custom_showerror("Launch Error", err_msg))
            self.root.after(0, lambda: self.update_rpc("Idle", "In Launcher"))
        finally:
            if mods_backup_path and os.path.exists(mods_backup_path):
                try:
                    current_mods = os.path.join(self.minecraft_dir, "mods")
                    if os.path.exists(current_mods):
                        shutil.rmtree(current_mods) 
                    os.rename(mods_backup_path, current_mods)
                    self.log("Restored original mods folder.")
                except Exception as e:
                    self.log(f"Error restoring mods: {e}")

            if local_skin_server:
                self.log("Stopping local skin server...")
                try: local_skin_server.stop()
                except: pass
                
            def reset_ui():
                self.launch_btn.config(state="normal", text="PLAY")
                self.launch_opts_btn.config(state="normal")
                self.update_skin_indicator()
                self.hide_progress_overlay()
                
            self.root.after(0, reset_ui)

if __name__ == "__main__":
    root = tk.Tk()
    app = MinecraftLauncher(root)
    root.mainloop()