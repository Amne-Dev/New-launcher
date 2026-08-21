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
import tempfile
try:
    import certifi
except ImportError:
    certifi = None
try:
    from skinpy import Skin, Perspective, BodyPart
except ImportError:
    pass
from PIL import Image, ImageTk, ImageDraw
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
import ctypes
from ctypes import wintypes

from config import (COLORS, CURRENT_VERSION, MSA_CLIENT_ID, MSA_REDIRECT_URI, 
                    DEFAULT_RAM, LOADERS, MOD_COMPATIBLE_LOADERS, 
                    DEFAULT_USERNAME, INSTALL_MARK) 
from utils import (resource_path, get_minecraft_dir, is_version_installed, 
                   RESAMPLE_NEAREST, FLIP_LEFT_RIGHT, AFFINE)
from handlers import MicrosoftLoginHandler, LocalSkinServer
from auth import ElyByAuth
from agent import (
    addon_add_saved_server,
    addon_delete_screenshot,
    addon_list_screenshot_files,
    addon_normalize_config,
    addon_record_play_session,
    addon_remove_saved_server,
    addon_reset_playtime_tracker,
    addon_set_streamer_mode,
)

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


_ORIGINAL_PIL_PHOTOIMAGE = ImageTk.PhotoImage
_IMAGETK_FALLBACK_WARNED = False


def _safe_pil_photoimage(image, *args, **kwargs):
    global _IMAGETK_FALLBACK_WARNED
    try:
        return _ORIGINAL_PIL_PHOTOIMAGE(image, *args, **kwargs)
    except Exception as exc:
        if not _IMAGETK_FALLBACK_WARNED:
            logging.warning("ImageTk.PhotoImage failed (%s); using tkinter.PhotoImage PNG fallback.", exc)
            _IMAGETK_FALLBACK_WARNED = True
        with io.BytesIO() as png_buffer:
            image.save(png_buffer, format="PNG")
            encoded = base64.b64encode(png_buffer.getvalue()).decode("ascii")
        return tk.PhotoImage(data=encoded, format="png")


ImageTk.PhotoImage = _safe_pil_photoimage


def _resolve_requests_ca_bundle():
    env_vars = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE")
    for var_name in env_vars:
        path = os.environ.get(var_name)
        if not path:
            continue
        if os.path.exists(path):
            return path
        try:
            os.environ.pop(var_name, None)
        except Exception:
            pass

    if certifi is not None:
        try:
            path = certifi.where()
            if path and os.path.exists(path):
                return path
        except Exception:
            pass

    for bundled in ("certifi/cacert.pem", "cacert.pem"):
        try:
            path = resource_path(bundled)
            if path and os.path.exists(path):
                return path
        except Exception:
            pass

    return None


_REQUESTS_CA_BUNDLE = _resolve_requests_ca_bundle()
_ORIG_REQUESTS_SESSION_REQUEST = requests.sessions.Session.request


def _patched_requests_session_request(session, method, url, **kwargs):
    if kwargs.get("verify", None) is None and _REQUESTS_CA_BUNDLE:
        kwargs["verify"] = _REQUESTS_CA_BUNDLE

    # A missing timeout leaves the UI's worker threads hanging indefinitely on a
    # broken connection.  Individual calls can still request a longer timeout.
    kwargs.setdefault("timeout", (10, 60))

    try:
        return _ORIG_REQUESTS_SESSION_REQUEST(session, method, url, **kwargs)
    except OSError as exc:
        if "Could not find a suitable TLS CA certificate bundle" not in str(exc):
            raise
        for var_name in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
            try:
                os.environ.pop(var_name, None)
            except Exception:
                pass
        # Never silently fall back to an unverified TLS connection.  Requests
        # will use its bundled/default trust store after the invalid override
        # has been cleared.
        retry_kwargs = dict(kwargs)
        retry_kwargs.pop("verify", None)
        logging.warning("Invalid TLS CA bundle path; retrying with the default trust store: %s", url)
        return _ORIG_REQUESTS_SESSION_REQUEST(session, method, url, **retry_kwargs)


requests.sessions.Session.request = _patched_requests_session_request # type: ignore

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


def _safe_extract_zip(archive, destination):
    """Extract a ZIP without allowing its entries to escape *destination*."""
    destination_path = os.path.realpath(destination)
    with zipfile.ZipFile(archive, "r") as zip_file:
        for member in zip_file.infolist():
            # Unix symlinks encoded in ZIP metadata can redirect a later file
            # outside the target folder even when the filename looks harmless.
            is_symlink = ((member.external_attr >> 16) & 0o170000) == 0o120000
            member_path = os.path.realpath(os.path.join(destination_path, member.filename))
            if is_symlink or os.path.commonpath((destination_path, member_path)) != destination_path:
                raise ValueError(f"Unsafe archive entry rejected: {member.filename}")
        zip_file.extractall(destination_path)


def _atomic_download(url, destination, *, cancel_event=None, chunk_size=64 * 1024, progress=None, headers=None, rate_limit_kib=0, expected_sha1=None):
    """Download to a sibling temporary file, then atomically publish it."""
    destination = os.path.abspath(destination)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temporary = f"{destination}.{uuid.uuid4().hex}.part"
    try:
        with requests.get(url, stream=True, headers=headers, timeout=(10, 60)) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            started_at = time.monotonic()
            with open(temporary, "wb") as output:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("Cancelled")
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded += len(chunk)
                    if rate_limit_kib:
                        target_elapsed = downloaded / (max(1, rate_limit_kib) * 1024)
                        remaining = target_elapsed - (time.monotonic() - started_at)
                        if remaining > 0:
                            time.sleep(remaining)
                    if progress is not None:
                        progress(downloaded, total)
        if expected_sha1:
            digest = hashlib.sha1()
            with open(temporary, "rb") as downloaded_file:
                for block in iter(lambda: downloaded_file.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest().lower() != str(expected_sha1).lower():
                raise ValueError("Downloaded file failed checksum verification.")
        os.replace(temporary, destination)
        return destination
    finally:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            logging.warning("Could not remove incomplete download: %s", temporary)


def _get_lib_name_without_version(lib):
    return ":".join(str(lib.get("name", "")).split(":")[:-1])


def _safe_inherit_json(original_data, path):
    inherit_version = original_data["inheritsFrom"]

    with open(os.path.join(path, "versions", inherit_version, inherit_version + ".json"), encoding="utf-8") as f:
        new_data = json.load(f)

    original_libs = {}
    for current_lib in original_data.get("libraries", []):
        lib_name = _get_lib_name_without_version(current_lib)
        original_libs[lib_name] = True

    lib_list = original_data.get("libraries", [])
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
                    existing_list = target_dict.get(child_key, [])
                    if not isinstance(existing_list, list):
                        existing_list = []
                    target_dict[child_key] = existing_list + child_value
                else:
                    target_dict[child_key] = child_value
        else:
            new_data[key] = value

    return new_data


def _safe_get_minecraft_arguments(data, version_data, path, options, classpath):
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
            logging.warning(
                "Skipping malformed launch argument without 'value' for version %s: %s",
                version_id,
                entry,
            )
            continue

        argument_value = entry.get("value")
        if isinstance(argument_value, str):
            arglist.append(
                minecraft_launcher_lib.command.replace_arguments(
                    argument_value, version_data, path, options, classpath
                )
            )
            continue

        if isinstance(argument_value, list):
            for value in argument_value:
                arglist.append(
                    minecraft_launcher_lib.command.replace_arguments(
                        value, version_data, path, options, classpath
                    )
                )
            continue

        logging.warning(
            "Skipping malformed launch argument value for version %s: %r",
            version_id,
            argument_value,
        )

    return arglist


def _patch_minecraft_launcher_launch_helpers():
    try:
        minecraft_launcher_lib.command.inherit_json = _safe_inherit_json
        minecraft_launcher_lib.command.get_arguments = _safe_get_minecraft_arguments
    except Exception:
        logging.exception("Failed to patch minecraft-launcher-lib command helpers")


_patch_minecraft_launcher_launch_helpers()


def _get_streamer_hidden_name():
    return "Hidden Account"


def _get_widget_hwnd(widget):
    if os.name != "nt":
        return 0
    try:
        return int(widget.winfo_id())
    except Exception:
        return 0


def _iter_widget_hwnds(widget):
    if os.name != "nt":
        return []
    try:
        user32 = ctypes.windll.user32
        base_hwnd = int(widget.winfo_id())
    except Exception:
        return []

    try:
        root_hwnd = int(user32.GetAncestor(base_hwnd, 2))  # GA_ROOT
    except Exception:
        root_hwnd = 0
    if root_hwnd > 0:
        return [root_hwnd]
    if base_hwnd > 0:
        return [base_hwnd]
    return []


def _ensure_window_icon(window, owner=None):
    try:
        icon_ico = resource_path("logo.ico")
        if os.path.exists(icon_ico):
            window.iconbitmap(icon_ico)
    except Exception:
        pass

    try:
        shared_photo = None
        if owner is not None:
            shared_photo = getattr(owner, "_nlc_icon_photo", None)
        if shared_photo is None:
            shared_photo = getattr(window, "_nlc_icon_photo", None)
        if shared_photo is None:
            icon_png = resource_path("logo.png")
            if os.path.exists(icon_png):
                shared_photo = tk.PhotoImage(file=icon_png)
        if shared_photo is not None:
            window._nlc_icon_photo = shared_photo
            window.iconphoto(True, shared_photo)
    except Exception:
        pass


def _detach_window_owner(window):
    if os.name != "nt":
        return
    try:
        set_window_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)
        GWL_HWNDPARENT = -8
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020

        for hwnd in _iter_widget_hwnds(window):
            try:
                set_window_long(hwnd, GWL_HWNDPARENT, 0)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
            except Exception:
                continue
    except Exception:
        pass


def _force_taskbar_button(window):
    if os.name != "nt":
        return
    try:
        _detach_window_owner(window)

        get_window_long = getattr(ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW)
        set_window_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)

        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020
        SWP_SHOWWINDOW = 0x0040

        for hwnd in _iter_widget_hwnds(window):
            try:
                ex_style = int(get_window_long(hwnd, GWL_EXSTYLE))
                new_style = (ex_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                if new_style != ex_style:
                    set_window_long(hwnd, GWL_EXSTYLE, new_style)
                # Always commit frame change so Explorer updates taskbar grouping immediately.
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
                )
            except Exception:
                continue
    except Exception:
        pass


def _prime_taskbar_window(window):
    if os.name != "nt":
        return

    def enforce():
        try:
            if not window.winfo_exists():
                return
            _force_taskbar_button(window)
        except Exception:
            pass

    try:
        window.wm_attributes("-toolwindow", False)
    except Exception:
        pass

    def schedule_prime(_event=None):
        try:
            if not window.winfo_exists():
                return
        except Exception:
            return
        window.after_idle(enforce)
        window.after(80, enforce)
        window.after(180, enforce)
        window.after(320, lambda: _refresh_taskbar_registration(window))
        window.after(650, lambda: _refresh_taskbar_registration(window))

    if not getattr(window, "_nlc_taskbar_hooks", False):
        try:
            window.bind("<Map>", schedule_prime, add="+")
        except Exception:
            pass
        try:
            window.bind("<FocusIn>", lambda _event=None: window.after(40, enforce), add="+")
        except Exception:
            pass
        try:
            window._nlc_taskbar_hooks = True  # type: ignore[attr-defined]
        except Exception:
            pass

    schedule_prime()


def _refresh_taskbar_registration(window):
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020
        RDW_INVALIDATE = 0x0001
        RDW_UPDATENOW = 0x0100
        RDW_FRAME = 0x0400
        did_refresh = False
        for hwnd in _iter_widget_hwnds(window):
            try:
                user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
                user32.RedrawWindow(hwnd, None, None, RDW_INVALIDATE | RDW_UPDATENOW | RDW_FRAME)
                did_refresh = True
            except Exception:
                continue
        return did_refresh
    except Exception:
        return False

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
        if os.name == 'nt':
            try:
                self.withdraw()
            except Exception:
                pass
        self.title(title)
        self.configure(bg=COLORS['card_bg'])
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_win_x = 0
        self._drag_win_y = 0
        try:
            # Keep a short fade-in for Windows without forcing topmost.
            if os.name == 'nt':
                self.attributes('-alpha', 0.0)
                self.after(10, lambda: self.attributes('-alpha', 1.0))
        except Exception:
            pass
        use_custom_chrome = (os.name == 'nt')
        if use_custom_chrome:
            try:
                self.overrideredirect(True)
            except Exception:
                use_custom_chrome = False
        
        self.result = None
        self._default_button = None
        target_parent = parent
        self._target_parent = target_parent
        self._parent_focus_bind_id = None
        self._dialog_manager = None
        try:
            manager = getattr(target_parent, "_nlc_app", None) if target_parent is not None else None
            if manager is None:
                default_root = getattr(tk, "_default_root", None)
                manager = getattr(default_root, "_nlc_app", None) if default_root is not None else None
            if manager is not None:
                self._dialog_manager = manager
                manager._register_dialog_window(self)
        except Exception:
            self._dialog_manager = None
        _ensure_window_icon(self, owner=target_parent)
        
        # Styles
        bg_col = COLORS['card_bg']
        fg_col = COLORS['text_primary']
        accent_col = COLORS.get('play_btn_green', '#2D8F36')
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Escape>", lambda _event: self.on_close())
        content_root = self
        if use_custom_chrome:
            chrome = tk.Frame(self, bg=COLORS.get('sidebar_bg', '#141414'), highlightthickness=0, bd=0)
            chrome.pack(fill="both", expand=True)

            titlebar = tk.Frame(chrome, bg=COLORS.get('tab_bar_bg', '#252526'), height=34)
            titlebar.pack(fill="x", side="top")
            titlebar.pack_propagate(False)

            left = tk.Frame(titlebar, bg=titlebar.cget("bg"))
            left.pack(side="left", fill="y")
            badge = tk.Label(left, text="NLC", bg=accent_col, fg="white",
                             font=("Segoe UI", 8, "bold"), padx=8, pady=3)
            badge.pack(side="left", padx=(8, 8), pady=6)
            tk.Label(left, text=title, bg=titlebar.cget("bg"), fg=fg_col,
                     font=("Segoe UI", 9, "bold")).pack(side="left")

            for drag_widget in (titlebar, left, badge):
                drag_widget.bind("<ButtonPress-1>", self._drag_start)
                drag_widget.bind("<B1-Motion>", self._drag_move)

            close_btn = tk.Button(titlebar, text="✕", font=("Segoe UI Symbol", 10), fg="white",
                                  bg=titlebar.cget("bg"), bd=0, relief="flat", width=4,
                                  cursor="hand2", command=self.on_close)
            close_btn.pack(side="right", fill="y")
            close_btn.bind("<Enter>", lambda _e: close_btn.config(bg="#C42B1C"))
            close_btn.bind("<Leave>", lambda _e: close_btn.config(bg=titlebar.cget("bg")))

            content_root = tk.Frame(chrome, bg=bg_col)
            content_root.pack(fill="both", expand=True)

        # Main Frame
        frame = tk.Frame(content_root, bg=bg_col, padx=25, pady=25)
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
            is_danger = style == "danger"
            b_bg = COLORS.get('error_red', '#E74C3C') if is_danger else (accent_col if style == "primary" else "#555555")
            b_fg = "white"
            b_hover_bg = "#C42B1C" if is_danger else (COLORS.get('play_btn_green', '#2D8F36') if style == "primary" else "#666666")
            
            btn = tk.Button(btn_inner, text=text, bg=b_bg, fg=b_fg, 
                           font=("Segoe UI", 9, "bold"), relief="flat",
                           activebackground=b_hover_bg, activeforeground=b_fg,
                           bd=0, padx=20, pady=6,
                           cursor="hand2",
                           command=lambda v=val: self.on_click(v))
            btn.pack(side="left", padx=10)
            
            # Enhanced hover effect
            def on_enter(e, b=btn, hover_bg=b_hover_bg):
                b.config(bg=hover_bg)
            def on_leave(e, b=btn, orig_bg=b_bg):
                b.config(bg=orig_bg)
            
            btn.bind("<Enter>", on_enter)
            btn.bind("<Leave>", on_leave)
            if self._default_button is None and style in ("primary", "danger"):
                self._default_button = btn
            
        # Centering Logic
        self.update_idletasks()
        w = 440
        h = max(160, self.winfo_reqheight())
        
        _schedule_window_centering(self, target_parent, width=w, height=h)
        if os.name == 'nt':
            def _finalize_windows_dialog_show():
                try:
                    if not self.winfo_exists():
                        return
                    self.deiconify()
                    _schedule_window_centering(self, target_parent, width=w, height=h)
                    self.lift()
                    self.focus_force()
                except Exception:
                    pass

            _finalize_windows_dialog_show()
            _prime_taskbar_window(self)
            for delay in (40, 140, 320, 700):
                try:
                    self.after(delay, _finalize_windows_dialog_show)
                except Exception:
                    pass
        if target_parent and target_parent.winfo_exists():
            self.transient(target_parent)
        if target_parent and target_parent.winfo_exists():
            try:
                self._parent_focus_bind_id = target_parent.bind("<FocusIn>", self._on_parent_focus, add="+")
            except Exception:
                self._parent_focus_bind_id = None
        self.bind("<Map>", self._on_map_restore_focus, add="+")
        try:
            self.grab_set()
        except tk.TclError:
            logging.warning("Unable to acquire modal input for dialog '%s'.", title)
        if self._default_button is not None:
            self.bind("<Return>", lambda _event: self._default_button.invoke())
            self.after(0, self._default_button.focus_set)
        self.after(0, self._restore_modal_focus)
        self.wait_window()

    def _drag_start(self, event):
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_win_x = self.winfo_x()
        self._drag_win_y = self.winfo_y()

    def _drag_move(self, event):
        dx = event.x_root - self._drag_start_x
        dy = event.y_root - self._drag_start_y
        self.geometry(f"+{self._drag_win_x + dx}+{self._drag_win_y + dy}")

    def _restore_modal_focus(self):
        try:
            if not self.winfo_exists():
                return
            if self.grab_current() == self:
                self.lift()
                self.focus_force()
        except Exception:
            pass

    def _on_parent_focus(self, _event=None):
        self.after(0, self._restore_modal_focus)

    def _on_map_restore_focus(self, _event=None):
        self.after(0, self._restore_modal_focus)
        
    def on_click(self, val):
        self.result = val
        target_parent = getattr(self, "_target_parent", None)
        bind_id = getattr(self, "_parent_focus_bind_id", None)
        if target_parent and bind_id:
            try:
                target_parent.unbind("<FocusIn>", bind_id)
            except Exception:
                pass
        manager = getattr(self, "_dialog_manager", None)
        if manager is not None:
            try:
                manager._unregister_dialog_window(self)
            except Exception:
                pass
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        
    def on_close(self):
        target_parent = getattr(self, "_target_parent", None)
        bind_id = getattr(self, "_parent_focus_bind_id", None)
        if target_parent and bind_id:
            try:
                target_parent.unbind("<FocusIn>", bind_id)
            except Exception:
                pass
        manager = getattr(self, "_dialog_manager", None)
        if manager is not None:
            try:
                manager._unregister_dialog_window(self)
            except Exception:
                pass
        self.result = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

def _parse_messagebox_args(args, kwargs):
    title = kwargs.get("title")
    message = kwargs.get("message")
    parent = kwargs.get("parent")

    if len(args) >= 1 and title is None:
        title = args[0]
    if len(args) >= 2 and message is None:
        message = args[1]

    if title is None:
        title = "Message"
    if message is None:
        message = ""

    return str(title), str(message), parent


def _center_window_on_parent(win, parent=None, width=None, height=None):
    try:
        if parent is not None and hasattr(parent, "winfo_exists") and parent.winfo_exists():
            try:
                parent.update_idletasks()
            except Exception:
                pass

        try:
            win.update_idletasks()
        except Exception:
            pass

        final_w = width if width is not None else win.winfo_width()
        final_h = height if height is not None else win.winfo_height()

        if not final_w or final_w <= 1:
            final_w = win.winfo_reqwidth()
        if not final_h or final_h <= 1:
            final_h = win.winfo_reqheight()

        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        x = (screen_w - final_w) // 2
        y = (screen_h - final_h) // 2

        if parent is not None and hasattr(parent, "winfo_exists") and parent.winfo_exists():
            try:
                parent_x = parent.winfo_rootx()
                parent_y = parent.winfo_rooty()
                parent_w = parent.winfo_width()
                parent_h = parent.winfo_height()
                if parent_w > 1 and parent_h > 1:
                    x = parent_x + (parent_w - final_w) // 2
                    y = parent_y + (parent_h - final_h) // 2
            except Exception:
                pass

        x = max(0, min(x, max(0, screen_w - final_w)))
        y = max(0, min(y, max(0, screen_h - final_h)))
        win.geometry(f"{int(final_w)}x{int(final_h)}+{int(x)}+{int(y)}")
    except Exception:
        pass


def _resolve_dialog_parent(preferred_parent=None, fallback_widget=None):
    candidates = []
    if preferred_parent is not None:
        candidates.append(preferred_parent)
    if fallback_widget is not None:
        try:
            manager = getattr(fallback_widget, "_nlc_app", None)
            if manager is not None and getattr(manager, "root", None) is not None:
                candidates.append(manager.root)
        except Exception:
            pass
        try:
            top = fallback_widget.winfo_toplevel()
            if top is not None:
                candidates.append(top)
        except Exception:
            pass
    default_root = getattr(tk, "_default_root", None)
    if default_root is not None:
        candidates.append(default_root)

    seen = set()
    for candidate in candidates:
        if candidate is None:
            continue
        ident = id(candidate)
        if ident in seen:
            continue
        seen.add(ident)
        try:
            if candidate.winfo_exists():
                return candidate
        except Exception:
            continue
    return None


def _schedule_window_centering(win, parent=None, width=None, height=None):
    owner = _resolve_dialog_parent(parent, win)
    try:
        win._nlc_center_owner = owner  # type: ignore[attr-defined]
        win._nlc_center_width = width  # type: ignore[attr-defined]
        win._nlc_center_height = height  # type: ignore[attr-defined]
    except Exception:
        pass

    def apply_center(target=win, target_owner=owner, target_width=width, target_height=height):
        try:
            if not target.winfo_exists():
                return
            if os.name == "nt":
                try:
                    if str(target.state()) == "withdrawn":
                        return
                except Exception:
                    pass
            _center_window_on_parent(target, target_owner, width=target_width, height=target_height)
        except Exception:
            pass

    apply_center()

    delays = (0, 30, 120, 240, 420, 760) if os.name == "nt" else (0, 30, 120)
    for delay in delays:
        try:
            win.after(delay, apply_center)
        except Exception:
            pass

    if not getattr(win, "_nlc_center_hooks", False):
        try:
            win.bind(
                "<Map>",
                lambda _event, w=win: _schedule_window_centering(
                    w,
                    getattr(w, "_nlc_center_owner", None),
                    getattr(w, "_nlc_center_width", None),
                    getattr(w, "_nlc_center_height", None),
                ),
                add="+",
            )
        except Exception:
            pass
        try:
            win._nlc_center_hooks = True  # type: ignore[attr-defined]
        except Exception:
            pass


def _build_missing_skin_head(size):
    try:
        pattern = [
            "..###...",
            ".#...#..",
            "....#...",
            "...#....",
            "...#....",
            "........",
            "...#....",
            "........",
        ]
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for y, row in enumerate(pattern):
            for x, cell in enumerate(row):
                if cell == "#":
                    draw.point((x, y), fill=(255, 255, 255, 255))
        return ImageTk.PhotoImage(img.resize((size, size), RESAMPLE_NEAREST))
    except Exception:
        return None


def custom_showinfo(*args, **kwargs):
    title, message, parent = _parse_messagebox_args(args, kwargs)
    _show_popup(title, message, type="info", parent=parent)
    return "ok"


def custom_showwarning(*args, **kwargs):
    title, message, parent = _parse_messagebox_args(args, kwargs)
    _show_popup(title, message, type="warning", parent=parent)
    return "ok"


def custom_showerror(*args, **kwargs):
    title, message, parent = _parse_messagebox_args(args, kwargs)
    _show_popup(title, message, type="error", parent=parent)
    return "ok"


def custom_askyesno(*args, **kwargs):
    title, message, parent = _parse_messagebox_args(args, kwargs)
    return bool(_show_popup(title, message, type="yesno", parent=parent))


class PopupManager:
    """One owner for application dialogs, including duplicate suppression."""
    def __init__(self, root):
        self.root = root
        self._active = set()

    def show(self, title, message, *, type="info", buttons=None, parent=None):
        signature = (type, str(title), str(message))
        if signature in self._active:
            logging.info("Suppressed duplicate popup: %s", title)
            return None
        self._active.add(signature)
        try:
            dialog = CustomMessagebox(title, message, type=type, buttons=buttons, parent=parent or self.root)
            return dialog.result
        finally:
            self._active.discard(signature)


def _show_popup(title, message, *, type="info", buttons=None, parent=None):
    resolved_parent = _resolve_dialog_parent(parent)
    manager = getattr(resolved_parent, "_nlc_popup_manager", None) if resolved_parent else None
    if manager is not None:
        return manager.show(title, message, type=type, buttons=buttons, parent=resolved_parent)
    dialog = CustomMessagebox(title, message, type=type, buttons=buttons, parent=resolved_parent)
    return dialog.result


class ToastManager:
    """Lightweight, deduplicated feedback for completed background work."""
    def __init__(self, root):
        self.root = root
        self._toasts = []
        self._signatures = set()

    def show(self, message, *, kind="success", duration=3600):
        signature = (kind, str(message))
        if signature in self._signatures:
            return
        self._signatures.add(signature)
        colors = {
            "success": COLORS.get("success_green", "#2ECC71"),
            "warning": "#E67E22",
            "error": COLORS.get("error_red", "#E74C3C"),
            "info": COLORS.get("accent_blue", "#3498DB"),
        }
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.configure(bg=COLORS["card_bg"])
        toast.attributes("-topmost", True)
        body = tk.Frame(toast, bg=COLORS["card_bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="●", fg=colors.get(kind, colors["info"]), bg=COLORS["card_bg"], font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))
        tk.Label(body, text=str(message), fg=COLORS["text_primary"], bg=COLORS["card_bg"], font=("Segoe UI", 9), wraplength=330, justify="left").pack(side="left")

        def dismiss():
            if toast in self._toasts:
                self._toasts.remove(toast)
            self._signatures.discard(signature)
            try:
                toast.destroy()
            except tk.TclError:
                pass
            self._reposition()

        toast.bind("<Button-1>", lambda _event: dismiss())
        body.bind("<Button-1>", lambda _event: dismiss())
        self._toasts.append(toast)
        self._reposition()
        toast.after(duration, dismiss)

    def _reposition(self):
        self._toasts[:] = [toast for toast in self._toasts if toast.winfo_exists()]
        try:
            self.root.update_idletasks()
            x = self.root.winfo_rootx() + self.root.winfo_width() - 20
            y = self.root.winfo_rooty() + 54
            for toast in self._toasts:
                toast.update_idletasks()
                width, height = toast.winfo_reqwidth(), toast.winfo_reqheight()
                toast.geometry(f"+{x - width}+{y}")
                y += height + 8
        except tk.TclError:
            pass


# Route all tkinter messagebox calls through custom dialogs so every prompt
# gets the same custom chrome + taskbar icon behavior.
messagebox.showinfo = custom_showinfo # type: ignore[assignment]
messagebox.showwarning = custom_showwarning # type: ignore[assignment]
messagebox.showerror = custom_showerror # type: ignore[assignment]
messagebox.askyesno = custom_askyesno # type: ignore[assignment]

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
        try:
            self.root._nlc_app = self  # type: ignore[attr-defined]
        except Exception:
            pass
        self.popup_manager = PopupManager(self.root)
        self.toast_manager = ToastManager(self.root)
        self.root._nlc_popup_manager = self.popup_manager  # type: ignore[attr-defined]
        _ensure_window_icon(self.root, owner=self.root)
        if os.name != 'nt':
            try:
                self.root.option_add("*Button.highlightThickness", 0)
                self.root.option_add("*Entry.highlightThickness", 0)
                self.root.option_add("*Listbox.highlightThickness", 0)
                self.root.option_add("*Text.highlightThickness", 0)
                self.root.option_add("*Canvas.highlightThickness", 0)
                self.root.option_add("*Checkbutton.highlightThickness", 0)
                self.root.option_add("*Radiobutton.highlightThickness", 0)
                self.root.option_add("*Scale.highlightThickness", 0)
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
        self.custom_titlebar_enabled = True # Will be overridden by config, but default to true on windows
        self.neo_style_enabled = True # Will be overridden by config
        if os.name != 'nt':
            self.custom_titlebar_enabled = False
        self._custom_chrome_applied = False
        self._window_is_maximized = False
        self.root.update_idletasks()
        self._windowed_geometry = (
            self.root.winfo_x(),
            self.root.winfo_y(),
            max(1, self.root.winfo_width()),
            max(1, self.root.winfo_height())
        )
        self._last_nonmax_geometry = self._windowed_geometry
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_win_x = 0
        self._drag_win_y = 0
        self._drag_last_x = 0
        self._drag_last_y = 0
        self._drag_active = False
        self._drag_target_x = 0
        self._drag_target_y = 0
        self._drag_apply_after_id = None
        self._drag_preview_enabled = (os.name == 'nt')
        self._drag_preview_win = None
        self._drag_preview_w = 0
        self._drag_preview_h = 0
        self._drag_preview_logo = None
        self._window_animating = False
        self._window_anim_after_id = None
        self._transition_overlay_win = None
        self._pre_minimize_geometry = None
        self._pre_minimize_anchor_geometry = None
        self._pre_minimize_was_maximized = False
        self._taskbar_refresh_done = False
        self._original_win_style = None
        self._use_native_drag = False
        self._onboarding_wizard = None
        self._onboarding_overlay = None
        self._onboarding_focus_bindings = []
        self._dialog_windows = []
        self._dialog_focus_bindings = []
        self._dialog_raise_scheduled = False
        self._dialog_raise_after_id = None
        self._dialog_last_raise_ts = 0.0
        self._dialog_raise_min_interval = 0.12
        self.window_shell = None
        self.window_content = self.root
        self._update_in_progress = False
        self._update_shutdown_started = False
        self._config_save_after_id = None
        self._config_save_delay_ms = 250
        self._config_sync_ui_pending = False
        self._launch_in_progress = False
        
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
        
        # --- Pre-load Accent Color & Custom Titlebar ---
        self.accent_color_name = "Green"
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    _d = json.load(f)
                    self.accent_color_name = _d.get("accent_color", "Green")
                    
                    # Pre-load custom titlebar setting BEFORE window creation
                    if "custom_titlebar_enabled" in _d:
                        self.custom_titlebar_enabled = _d["custom_titlebar_enabled"] and os.name == 'nt'
                    
                    self.neo_style_enabled = _d.get("neo_style_enabled", True)
                    if self.neo_style_enabled:
                        # Apply OLED Black Neo Style
                        COLORS['sidebar_bg'] = '#000000'
                        COLORS['main_bg'] = '#050505'
                        COLORS['tab_bar_bg'] = '#050505'
                        COLORS['bottom_bar_bg'] = '#000000'
                        COLORS['card_bg'] = '#111111'
                        COLORS['input_bg'] = '#1A1A1A'
                        COLORS['input_border'] = '#333333'
                        COLORS['separator'] = '#1F1F1F'
                    
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
        self.skin_path = ""  # Initialize before load_from_config
        self.auto_download_mod = False
        self.enable_modrinth = True
        self.installed_mods_view_mode = "grid"
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
            "p3_reload_menu": False,
            "gh_sync_enabled": False,
            "gh_repo": "",
            "gh_token": "",
            "playtime_tracker": {},
            "saved_servers": []
        }
        self.screenshot_thumbnail_cache = {}
        self.quick_join_installation_labels = {}
        self.third_party_addons = []
        self.third_party_addon_input_vars = {}
        
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

        # Smooth scrolling state
        self._scroll_velocities = {}  # canvas_id -> velocity
        self._scroll_anim_ids = {}    # canvas_id -> after_id

        self.setup_styles()
        self.setup_window_chrome()
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
            
        # Onboarding / What's New Trigger
        if self.first_run:
            self.last_version = CURRENT_VERSION
            self.root.after(500, self.show_onboarding_wizard)
        elif getattr(self, "last_version", "") and self.last_version != CURRENT_VERSION:
            self.root.after(1000, lambda: self.show_whats_new(CURRENT_VERSION))
            self.last_version = CURRENT_VERSION
            self.save_config()

    def load_modpacks(self):
        self.modpacks = []
        try:
            mp_file = os.path.join(self.config_dir, "modpacks.json")
            if os.path.exists(mp_file):
                with open(mp_file, "r") as f:
                    loaded = json.load(f)
                    if not isinstance(loaded, list):
                        raise ValueError("Modpacks configuration must be a list.")
                    self.modpacks = [pack for pack in loaded if isinstance(pack, dict)]
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
        # IDs are persisted user data; do not let a malformed config traverse
        # out of the launcher's modpack storage before a delete/copy operation.
        safe_id = os.path.basename(str(pack_id or "").strip())
        if not safe_id or safe_id in {".", ".."}:
            raise ValueError("Invalid modpack identifier.")
        root = os.path.abspath(os.path.join(getattr(self, 'config_dir', os.getcwd()), "modpacks"))
        base = os.path.abspath(os.path.join(root, safe_id))
        if os.path.commonpath((root, base)) != root:
            raise ValueError("Modpack path is outside launcher storage.")
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

    def _set_custom_window_chrome(self, enabled):
        if not self.custom_titlebar_enabled:
            return
        try:
            if os.name != 'nt':
                if enabled and not self._custom_chrome_applied:
                    self.root.overrideredirect(True)
                    self._custom_chrome_applied = True
                elif not enabled and self._custom_chrome_applied:
                    self.root.overrideredirect(False)
                    self._custom_chrome_applied = False
                return

            hwnd = self._get_native_hwnd()
            if not hwnd:
                return
            get_window_long = getattr(ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW)
            set_window_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)

            GWL_STYLE = -16
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            WS_POPUP = 0x80000000
            WS_CAPTION = 0x00C00000
            WS_THICKFRAME = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000

            current_style = int(get_window_long(hwnd, GWL_STYLE))
            if self._original_win_style is None:
                self._original_win_style = current_style

            if enabled:
                new_style = (current_style & ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)) | WS_POPUP
                if new_style != current_style:
                    set_window_long(hwnd, GWL_STYLE, new_style)
                    ctypes.windll.user32.SetWindowPos(
                        hwnd, 0, 0, 0, 0, 0,
                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                    )
                self._custom_chrome_applied = True
                self.root.after(10, self._ensure_taskbar_visibility)
            elif not enabled and self._custom_chrome_applied:
                restore_style = int(self._original_win_style) if self._original_win_style is not None else current_style
                set_window_long(hwnd, GWL_STYLE, restore_style)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
                self._custom_chrome_applied = False
        except Exception:
            pass

    def _get_native_hwnd(self):
        if os.name != 'nt':
            return 0
        try:
            base_hwnd = int(self.root.winfo_id())
            GA_ROOT = 2
            user32 = ctypes.windll.user32
            root_hwnd = user32.GetAncestor(base_hwnd, GA_ROOT)
            return int(root_hwnd) if root_hwnd else base_hwnd
        except Exception:
            return 0

    def _ensure_taskbar_visibility(self):
        if not self.custom_titlebar_enabled or os.name != 'nt':
            return
        try:
            hwnd = self._get_native_hwnd()
            if not hwnd:
                return
            get_window_long = getattr(ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW)
            set_window_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)

            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020

            ex_style = int(get_window_long(hwnd, GWL_EXSTYLE))
            new_style = (ex_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            if new_style != ex_style:
                set_window_long(hwnd, GWL_EXSTYLE, new_style)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
            if not self._taskbar_refresh_done:
                self._taskbar_refresh_done = True
                self.root.after(30, self._refresh_taskbar_window)
        except Exception:
            pass

    def _refresh_taskbar_window(self):
        if not self.custom_titlebar_enabled or os.name != 'nt':
            return
        try:
            if str(self.root.state()) == 'withdrawn':
                return
            geom = self.root.geometry()
            self.root.withdraw()
            self.root.after(20, lambda g=geom: self._restore_from_taskbar_refresh(g))
        except Exception:
            pass

    def _restore_from_taskbar_refresh(self, geom):
        try:
            self.root.deiconify()
            self.root.geometry(geom)
            self.root.lift()
            self._set_custom_window_chrome(True)
        except Exception:
            pass

    def _on_root_map_restore_chrome(self, event):
        if not self.custom_titlebar_enabled:
            return
        if event and event.widget != self.root:
            return
        self.root.after(30, lambda: self._set_custom_window_chrome(True))
        self.root.after(60, self._ensure_taskbar_visibility)

    def _start_native_drag(self, window=None):
        if not self._use_native_drag or os.name != 'nt':
            return False
        try:
            target = window if window is not None else self.root
            hwnd = self._get_native_hwnd_for_widget(target)
            if not hwnd:
                return False
            user32 = ctypes.windll.user32
            user32.ReleaseCapture()
            user32.SendMessageW(hwnd, 0x00A1, 0x0002, 0)  # WM_NCLBUTTONDOWN + HTCAPTION
            return True
        except Exception:
            return False

    def _begin_window_drag(self, event):
        if not self.custom_titlebar_enabled:
            return
        if self._window_is_maximized or str(self.root.state()) == "zoomed":
            ratio = (event.x_root - self.root.winfo_x()) / max(1, self.root.winfo_width())
            ratio = min(max(ratio, 0.1), 0.9)
            
            # Instantly unmaximize without animation so dragging isn't interrupted
            self.root.state("normal")
            target = getattr(self, '_windowed_geometry', None) or getattr(self, '_last_nonmax_geometry', None)
            if not target:
                target = self._build_default_windowed_geometry()
            
            w = target[2]
            h = target[3]
            
            self._window_is_maximized = False
            if hasattr(self, 'window_max_btn'):
                self.window_max_btn.config(text="□")
            try:
                self._update_titlebar_controls_offset()
                self._set_custom_window_chrome(True)
                self._ensure_taskbar_visibility()
            except Exception:
                pass
            
            x = int(event.x_root - (w * ratio))
            y = max(0, event.y_root - 12)
            self.root.geometry(f"{max(1, int(w))}x{max(1, int(h))}+{int(x)}+{int(y)}")
            self.root.update_idletasks()

        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_win_x = self.root.winfo_x()
        self._drag_win_y = self.root.winfo_y()
        self._drag_last_x = event.x_root
        self._drag_last_y = event.y_root
        self._drag_target_x = self._drag_win_x
        self._drag_target_y = self._drag_win_y
        self._drag_active = True
        self._open_drag_preview()

    def _open_drag_preview(self):
        if not self._drag_preview_enabled or self._drag_preview_win is not None:
            return
        try:
            self.root.update_idletasks()
            self._drag_preview_w = max(500, self.root.winfo_width())
            self._drag_preview_h = max(320, self.root.winfo_height())

            preview = tk.Toplevel(self.root)
            preview.overrideredirect(True)
            preview.configure(bg="#0f0f0f")
            try:
                preview.attributes("-topmost", True)
            except Exception:
                pass
            preview.geometry(
                f"{self._drag_preview_w}x{self._drag_preview_h}+{self._drag_target_x}+{self._drag_target_y}"
            )

            shell = tk.Frame(preview, bg="#0f0f0f", highlightthickness=1, highlightbackground="#2f2f2f")
            shell.pack(fill="both", expand=True)
            center = tk.Frame(shell, bg="#0f0f0f")
            center.place(relx=0.5, rely=0.5, anchor="center")

            logo_path = resource_path("logo.png")
            if os.path.exists(logo_path):
                try:
                    img = Image.open(logo_path).convert("RGBA")
                    img = img.resize((92, 92), Image.Resampling.LANCZOS)
                    self._drag_preview_logo = ImageTk.PhotoImage(img)
                    tk.Label(center, image=self._drag_preview_logo, bg="#0f0f0f").pack(pady=(0, 14))
                except Exception:
                    pass

            tk.Label(
                center,
                text="NLC",
                font=("Segoe UI", 22, "bold"),
                fg="white",
                bg="#0f0f0f"
            ).pack()
            tk.Label(
                center,
                text="Drag anywhere you want",
                font=("Segoe UI", 11),
                fg="#A0A0A0",
                bg="#0f0f0f"
            ).pack(pady=(8, 0))

            self._drag_preview_win = preview
            self.root.withdraw()
        except Exception:
            self._drag_preview_win = None

    def _apply_window_drag_target(self):
        self._drag_apply_after_id = None
        if not self._drag_active:
            return
        if self._drag_preview_win and self._drag_preview_win.winfo_exists():
            self._drag_preview_win.geometry(
                f"{self._drag_preview_w}x{self._drag_preview_h}+{self._drag_target_x}+{self._drag_target_y}"
            )
        else:
            self.root.geometry(f"+{self._drag_target_x}+{self._drag_target_y}")

    def _schedule_window_drag_apply(self):
        if self._drag_apply_after_id is not None:
            return
        self._drag_apply_after_id = self.root.after(8, self._apply_window_drag_target)

    def _do_window_drag(self, event):
        if not self.custom_titlebar_enabled or not self._drag_active:
            return
        target_x = self._drag_win_x + (event.x_root - self._drag_start_x)
        target_y = self._drag_win_y + (event.y_root - self._drag_start_y)
        if target_x == self._drag_target_x and target_y == self._drag_target_y:
            return
        self._drag_target_x = target_x
        self._drag_target_y = target_y
        self._schedule_window_drag_apply()

    def _end_window_drag(self, _event=None):
        if self._drag_apply_after_id is not None:
            try:
                self.root.after_cancel(self._drag_apply_after_id)
            except Exception:
                pass
            self._drag_apply_after_id = None
        if self._drag_active:
            if self._drag_preview_win and self._drag_preview_win.winfo_exists():
                try:
                    self.root.deiconify()
                    self.root.geometry(
                        f"{self._drag_preview_w}x{self._drag_preview_h}+{self._drag_target_x}+{self._drag_target_y}"
                    )
                    self._set_custom_window_chrome(True)
                    self.root.lift()
                    self.root.focus_force()
                except Exception:
                    pass
                try:
                    self._drag_preview_win.destroy()
                except Exception:
                    pass
                self._drag_preview_win = None
                self._drag_preview_logo = None
            else:
                self.root.geometry(f"+{self._drag_target_x}+{self._drag_target_y}")
        elif self._drag_preview_win and self._drag_preview_win.winfo_exists():
            try:
                self._drag_preview_win.destroy()
            except Exception:
                pass
            self._drag_preview_win = None
            self._drag_preview_logo = None
            try:
                self.root.deiconify()
                self._set_custom_window_chrome(True)
            except Exception:
                pass
        self._drag_active = False

    def _bind_drag_widget(self, widget):
        widget.bind("<ButtonPress-1>", self._begin_window_drag)
        widget.bind("<B1-Motion>", self._do_window_drag)
        widget.bind("<ButtonRelease-1>", self._end_window_drag)
        widget.bind("<Double-Button-1>", lambda _e: self._toggle_window_maximize())

    def _get_work_area(self):
        if os.name == 'nt':
            try:
                class _RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long),
                    ]

                class _MONITORINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", wintypes.DWORD),
                        ("rcMonitor", _RECT),
                        ("rcWork", _RECT),
                        ("dwFlags", wintypes.DWORD),
                    ]

                hwnd = self._get_native_hwnd()
                user32 = ctypes.windll.user32
                MONITOR_DEFAULTTONEAREST = 2
                monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                if monitor:
                    mi = _MONITORINFO()
                    mi.cbSize = ctypes.sizeof(_MONITORINFO)
                    ok = user32.GetMonitorInfoW(monitor, ctypes.byref(mi))
                    if ok:
                        return (
                            int(mi.rcWork.left),
                            int(mi.rcWork.top),
                            int(mi.rcWork.right - mi.rcWork.left),
                            int(mi.rcWork.bottom - mi.rcWork.top),
                        )
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _get_current_geometry_tuple(self):
        return (
            int(self.root.winfo_x()),
            int(self.root.winfo_y()),
            max(1, int(self.root.winfo_width())),
            max(1, int(self.root.winfo_height())),
        )

    def _is_geometry_maximized_like(self, geom, tolerance=14):
        try:
            wx, wy, ww, wh = self._get_work_area()
            x, y, w, h = geom
            right = int(x) + int(w)
            bottom = int(y) + int(h)
            work_right = int(wx) + int(ww)
            work_bottom = int(wy) + int(wh)
            return (
                int(x) <= int(wx) + tolerance
                and int(y) <= int(wy) + tolerance
                and right >= work_right - tolerance
                and bottom >= work_bottom - tolerance
            )
        except Exception:
            return False

    def _build_default_windowed_geometry(self):
        wx, wy, ww, wh = self._get_work_area()
        dw = max(900, min(1100, int(ww * 0.78)))
        dh = max(620, min(760, int(wh * 0.78)))
        dx = wx + max(0, (ww - dw) // 2)
        dy = wy + max(0, (wh - dh) // 2)
        return (dx, dy, dw, dh)

    def _set_geometry_tuple(self, geom):
        x, y, w, h = geom
        self.root.geometry(f"{max(1, int(w))}x{max(1, int(h))}+{int(x)}+{int(y)}")

    def _cancel_window_animation(self):
        if self._window_anim_after_id is not None:
            try:
                self.root.after_cancel(self._window_anim_after_id)
            except Exception:
                pass
            self._window_anim_after_id = None
        self._window_animating = False
        self._destroy_transition_overlay()

    def _animate_window_geometry(self, start_geom, end_geom, duration=150, steps=12, on_done=None, apply_geometry=None, cancel_existing=True):
        if cancel_existing:
            self._cancel_window_animation()
        self._window_animating = True
        step_delay = max(8, int(duration / max(1, steps)))
        apply_cb = apply_geometry if apply_geometry is not None else self._set_geometry_tuple

        sx, sy, sw, sh = start_geom
        ex, ey, ew, eh = end_geom

        def tick(i):
            t = i / max(1, steps)
            # Smoothstep easing
            eased = t * t * (3 - 2 * t)
            nx = round(sx + (ex - sx) * eased)
            ny = round(sy + (ey - sy) * eased)
            nw = round(sw + (ew - sw) * eased)
            nh = round(sh + (eh - sh) * eased)
            apply_cb((nx, ny, nw, nh))

            if i >= steps:
                self._window_animating = False
                self._window_anim_after_id = None
                if on_done:
                    on_done()
                return
            self._window_anim_after_id = self.root.after(step_delay, lambda: tick(i + 1))

        tick(0)

    def _destroy_transition_overlay(self):
        overlay = self._transition_overlay_win
        self._transition_overlay_win = None
        if overlay is not None:
            try:
                if overlay.winfo_exists():
                    overlay.destroy()
            except Exception:
                pass

    def _set_transition_overlay_geometry(self, geom):
        overlay = self._transition_overlay_win
        if overlay is None:
            self._set_geometry_tuple(geom)
            return
        try:
            if overlay.winfo_exists():
                x, y, w, h = geom
                overlay.geometry(f"{max(1, int(w))}x{max(1, int(h))}+{int(x)}+{int(y)}")
                return
        except Exception:
            pass
        self._set_geometry_tuple(geom)

    def _create_transition_overlay(self, geom, subtitle=""):
        if os.name != 'nt' or not self.custom_titlebar_enabled:
            return False
        try:
            self._destroy_transition_overlay()
            x, y, w, h = geom
            overlay = tk.Toplevel(self.root)
            overlay.overrideredirect(True)
            overlay.configure(bg="#0d0d0d")
            try:
                overlay.attributes("-topmost", True)
            except Exception:
                pass
            overlay.geometry(f"{max(1, int(w))}x{max(1, int(h))}+{int(x)}+{int(y)}")

            shell = tk.Frame(overlay, bg="#0d0d0d", highlightthickness=1, highlightbackground="#2f2f2f")
            shell.pack(fill="both", expand=True)

            center = tk.Frame(shell, bg="#0d0d0d")
            center.place(relx=0.5, rely=0.5, anchor="center")
            tk.Label(
                center,
                text="NLC",
                font=("Segoe UI", 22, "bold"),
                fg="white",
                bg="#0d0d0d"
            ).pack()
            if subtitle:
                tk.Label(
                    center,
                    text=subtitle,
                    font=("Segoe UI", 11),
                    fg="#A0A0A0",
                    bg="#0d0d0d"
                ).pack(pady=(8, 0))
            self._transition_overlay_win = overlay
            return True
        except Exception:
            self._destroy_transition_overlay()
            return False

    def _run_transition_with_overlay(self, start_geom, end_geom, duration=150, steps=12, subtitle="", finalize=None, on_done=None):
        self._cancel_window_animation()
        overlay_ready = self._create_transition_overlay(start_geom, subtitle=subtitle)
        apply_cb = self._set_transition_overlay_geometry if overlay_ready else self._set_geometry_tuple

        def finish():
            try:
                if finalize:
                    finalize()
            finally:
                self._destroy_transition_overlay()
                if on_done:
                    on_done()

        if start_geom == end_geom:
            finish()
            return

        self._animate_window_geometry(
            start_geom,
            end_geom,
            duration=duration,
            steps=steps,
            on_done=finish,
            apply_geometry=apply_cb,
            cancel_existing=False
        )

    def _toggle_window_maximize(self):
        if self._drag_active:
            return
        if self._window_animating:
            return
        current_state = str(self.root.state())
        current_geom = self._get_current_geometry_tuple()
        is_geom_max = self._is_geometry_maximized_like(current_geom, tolerance=24)
        currently_maximized = self._window_is_maximized or current_state == "zoomed" or is_geom_max
        if currently_maximized:
            if current_state == "zoomed":
                self.root.state("normal")
                self.root.update_idletasks()
            start = self._get_current_geometry_tuple()
            target = self._windowed_geometry if self._windowed_geometry else self._last_nonmax_geometry
            if not target:
                target = self._build_default_windowed_geometry()
            if self._is_geometry_maximized_like(target, tolerance=20):
                target = self._build_default_windowed_geometry()

            def on_restore_done():
                self._window_is_maximized = False
                self._windowed_geometry = target
                self._last_nonmax_geometry = target
                if hasattr(self, 'window_max_btn'):
                    self.window_max_btn.config(text="□")
                self._update_titlebar_controls_offset()
                self._set_custom_window_chrome(True)
                self._ensure_taskbar_visibility()

            def finalize_restore():
                self.root.state("normal")
                self._set_geometry_tuple(target)

            self._run_transition_with_overlay(
                start,
                target,
                duration=150,
                steps=12,
                subtitle="Restoring window",
                finalize=finalize_restore,
                on_done=on_restore_done
            )
        else:
            if current_state == "zoomed":
                self.root.state("normal")
                self.root.update_idletasks()
            start = self._get_current_geometry_tuple()
            if current_state == "normal" and not self._is_geometry_maximized_like(start, tolerance=20):
                self._windowed_geometry = start
                self._last_nonmax_geometry = start
            x, y, w, h = self._get_work_area()
            target = (x, y, max(1, w), max(1, h))

            def on_max_done():
                self._window_is_maximized = True
                if hasattr(self, 'window_max_btn'):
                    self.window_max_btn.config(text="❐")
                self._update_titlebar_controls_offset()
                self._set_custom_window_chrome(True)
                self._ensure_taskbar_visibility()

            def finalize_max():
                self.root.state("normal")
                self._set_geometry_tuple(target)

            self._run_transition_with_overlay(
                start,
                target,
                duration=150,
                steps=12,
                subtitle="Maximizing window",
                finalize=finalize_max,
                on_done=on_max_done
            )

    def _minimize_window(self):
        if self._drag_active:
            return
        if str(self.root.state()) == "iconic":
            return
        self._cancel_window_animation()
        start = self._get_current_geometry_tuple()
        self._pre_minimize_geometry = start
        self._pre_minimize_was_maximized = bool(self._window_is_maximized or str(self.root.state()) == "zoomed")
        wx, wy, ww, wh = self._get_work_area()
        tw = max(280, int(start[2] * 0.45))
        th = max(180, int(start[3] * 0.45))
        tx = wx + (ww - tw) // 2
        ty = wy + wh - th - 10
        self._pre_minimize_anchor_geometry = (tx, ty, tw, th)

        def finalize_min():
            self.root.state("iconic")

        self._run_transition_with_overlay(
            start,
            self._pre_minimize_anchor_geometry,
            duration=130,
            steps=10,
            subtitle="Minimizing window",
            finalize=finalize_min
        )

    def _sync_window_state(self, event=None):
        if not self.custom_titlebar_enabled:
            return
        if event and event.widget != self.root:
            return
        if self._drag_active or self._window_animating:
            return
        try:
            state = str(self.root.state())
            wx, wy, ww, wh = self._get_work_area()
            rx, ry, rw, rh = self._get_current_geometry_tuple()
            is_geom_max = self._is_geometry_maximized_like((rx, ry, rw, rh), tolerance=14)
            is_max = (state == "zoomed") or (state == "normal" and is_geom_max)
            if is_max != self._window_is_maximized:
                self._window_is_maximized = is_max
                if hasattr(self, 'window_max_btn'):
                    self.window_max_btn.config(text="❐" if is_max else "□")
                self._update_titlebar_controls_offset()
            if not self._window_is_maximized and state == "normal" and not is_geom_max:
                self._windowed_geometry = (rx, ry, rw, rh)
                self._last_nonmax_geometry = self._windowed_geometry
        except Exception:
            pass

    def _update_titlebar_controls_offset(self):
        if not hasattr(self, 'window_controls_frame'):
            return
        try:
            if self._window_is_maximized:
                self.window_controls_frame.pack_configure(padx=(0, 10))
            else:
                self.window_controls_frame.pack_configure(padx=(0, 10))
        except Exception:
            pass

    def setup_window_chrome(self):
        self.window_content = self.root
        if not self.custom_titlebar_enabled:
            return

        shell = tk.Frame(
            self.root,
            bg=COLORS.get('sidebar_bg', '#141414'),
            highlightthickness=0,
            bd=0
        )
        shell.pack(fill="both", expand=True)
        self.window_shell = shell

        titlebar = tk.Frame(shell, bg=COLORS.get('tab_bar_bg', '#252526'), height=36)
        titlebar.pack(fill="x", side="top")
        titlebar.pack_propagate(False)
        self.window_titlebar = titlebar

        left = tk.Frame(titlebar, bg=titlebar.cget("bg"))
        left.pack(side="left", fill="y")
        badge = tk.Label(left, text="NLC", bg=COLORS.get('play_btn_green', '#2D8F36'),
                         fg="white", font=("Segoe UI", 8, "bold"), padx=8, pady=4)
        badge.pack(side="left", padx=(8, 8), pady=6)
        title_lbl = tk.Label(left, text="New Launcher", font=("Segoe UI", 10, "bold"),
                             bg=titlebar.cget("bg"), fg=COLORS.get('text_primary', 'white'))
        title_lbl.pack(side="left")

        self._bind_drag_widget(titlebar)
        self._bind_drag_widget(left)
        self._bind_drag_widget(badge)
        self._bind_drag_widget(title_lbl)

        controls = tk.Frame(titlebar, bg=titlebar.cget("bg"))
        controls.pack(side="right", fill="y")
        self.window_controls_frame = controls

        def style_btn(btn, hover_bg, leave_bg=None):
            normal_bg = leave_bg if leave_bg is not None else titlebar.cget("bg")
            btn.config(bg=normal_bg, activebackground=hover_bg, activeforeground="white")
            btn.bind("<Enter>", lambda _e, b=btn, c=hover_bg: b.config(bg=c))
            btn.bind("<Leave>", lambda _e, b=btn, c=normal_bg: b.config(bg=c))

        btn_font = ("Segoe UI Symbol", 10)

        min_btn = tk.Button(controls, text="—", font=btn_font, fg=COLORS.get('text_primary', 'white'),
                            bd=0, relief="flat", width=4, cursor="hand2", command=self._minimize_window)
        min_btn.pack(side="left", fill="y")
        style_btn(min_btn, "#3A3A3A")

        self.window_max_btn = tk.Button(
            controls,
            text="□",
            font=btn_font,
            fg=COLORS.get('text_primary', 'white'),
            bd=0,
            relief="flat",
            width=4,
            cursor="hand2",
            command=self._toggle_window_maximize
        )
        self.window_max_btn.pack(side="left", fill="y")
        style_btn(self.window_max_btn, "#3A3A3A")

        close_btn = tk.Button(controls, text="✕", font=btn_font, fg="white",
                              bd=0, relief="flat", width=4, cursor="hand2", command=self._on_close)
        close_btn.pack(side="left", fill="y")
        style_btn(close_btn, "#C42B1C")

        self.window_content = tk.Frame(shell, bg=COLORS['main_bg'])
        self.window_content.pack(fill="both", expand=True)

        self.root.bind("<Map>", self._on_root_map_restore_chrome, add="+")
        self.root.bind("<Configure>", self._sync_window_state, add="+")
        self._set_custom_window_chrome(True)
        self.root.after(120, self._ensure_taskbar_visibility)

    def _get_native_hwnd_for_widget(self, widget):
        if os.name != 'nt':
            return 0
        try:
            base_hwnd = int(widget.winfo_id())
            GA_ROOT = 2
            user32 = ctypes.windll.user32
            root_hwnd = user32.GetAncestor(base_hwnd, GA_ROOT)
            return int(root_hwnd) if root_hwnd else base_hwnd
        except Exception:
            return 0

    def _prepare_dialog_window(self, win, owner=None):
        owner_win = owner if owner is not None else self.root
        _ensure_window_icon(win, owner=owner_win)
        self._register_dialog_window(win)
        if os.name == 'nt':
            try:
                win.transient(None)
            except Exception:
                pass
            try:
                win.grab_release()
            except Exception:
                pass
            _prime_taskbar_window(win)
            try:
                win.after(140, lambda w=win: _prime_taskbar_window(w) if w.winfo_exists() else None)
            except Exception:
                pass
            try:
                win.after(20, lambda w=win: (w.lift(), w.focus_force()) if w.winfo_exists() else None)
            except Exception:
                pass

    def _apply_custom_toplevel_chrome(self, win, title_text, close_command=None):
        owner = _resolve_dialog_parent(getattr(win, "master", None), self.root)
        if os.name == 'nt':
            try:
                win.withdraw()
            except Exception:
                pass

        def finalize_windows_dialog():
            if os.name != 'nt':
                return
            try:
                if not win.winfo_exists():
                    return
                win.deiconify()
                _schedule_window_centering(win, owner)
                win.lift()
                win.focus_force()
            except Exception:
                pass

        def schedule_windows_finalize():
            if os.name != 'nt':
                return
            finalize_windows_dialog()
            for delay in (40, 140, 320, 700):
                try:
                    win.after(delay, finalize_windows_dialog)
                except Exception:
                    pass

        if not (self.custom_titlebar_enabled and os.name == 'nt'):
            self._prepare_dialog_window(win)
            _schedule_window_centering(win, owner)
            schedule_windows_finalize()
            return win
        existing_content = getattr(win, "_custom_content_root", None)
        if existing_content and existing_content.winfo_exists():
            title_label = getattr(win, "_custom_title_label", None)
            if title_label and title_label.winfo_exists():
                try:
                    title_label.config(text=title_text)
                except Exception:
                    pass
            self._prepare_dialog_window(win)
            _schedule_window_centering(win, owner)
            schedule_windows_finalize()
            return existing_content

        try:
            win.overrideredirect(True)
        except Exception:
            self._prepare_dialog_window(win)
            _schedule_window_centering(win, owner)
            schedule_windows_finalize()
            return win

        shell = tk.Frame(win, bg=COLORS.get('sidebar_bg', '#141414'), highlightthickness=0, bd=0)
        shell.pack(fill="both", expand=True)

        titlebar = tk.Frame(shell, bg=COLORS.get('tab_bar_bg', '#252526'), height=34)
        titlebar.pack(fill="x", side="top")
        titlebar.pack_propagate(False)

        left = tk.Frame(titlebar, bg=titlebar.cget("bg"))
        left.pack(side="left", fill="y")
        badge = tk.Label(left, text="NLC", bg=COLORS.get('play_btn_green', '#2D8F36'),
                         fg="white", font=("Segoe UI", 8, "bold"), padx=8, pady=3)
        badge.pack(side="left", padx=(8, 8), pady=6)
        title_lbl = tk.Label(left, text=title_text, bg=titlebar.cget("bg"),
                             fg=COLORS.get('text_primary', 'white'), font=("Segoe UI", 9, "bold"))
        title_lbl.pack(side="left")

        drag_state = {"native": False, "sx": 0, "sy": 0, "wx": 0, "wy": 0, "lx": 0, "ly": 0}

        def drag_start(event):
            drag_state["native"] = False
            drag_state["sx"] = event.x_root
            drag_state["sy"] = event.y_root
            drag_state["wx"] = win.winfo_x()
            drag_state["wy"] = win.winfo_y()
            drag_state["lx"] = event.x_root
            drag_state["ly"] = event.y_root

        def drag_move(event):
            if drag_state["native"]:
                return
            dx = event.x_root - drag_state["lx"]
            dy = event.y_root - drag_state["ly"]
            if dx == 0 and dy == 0:
                return
            win.geometry(f"+{win.winfo_x() + dx}+{win.winfo_y() + dy}")
            drag_state["lx"] = event.x_root
            drag_state["ly"] = event.y_root

        for drag_widget in (titlebar, left, badge, title_lbl):
            drag_widget.bind("<ButtonPress-1>", drag_start)
            drag_widget.bind("<B1-Motion>", drag_move)

        close_btn = tk.Button(
            titlebar,
            text="✕",
            font=("Segoe UI Symbol", 10),
            fg="white",
            bg=titlebar.cget("bg"),
            bd=0,
            relief="flat",
            width=4,
            cursor="hand2",
            command=close_command if close_command else win.destroy
        )
        close_btn.pack(side="right", fill="y")
        close_btn.bind("<Enter>", lambda _e: close_btn.config(bg="#C42B1C"))
        close_btn.bind("<Leave>", lambda _e: close_btn.config(bg=titlebar.cget("bg")))

        body = tk.Frame(shell, bg=win.cget("bg"))
        body.pack(fill="both", expand=True)
        try:
            win._custom_content_root = body  # type: ignore[attr-defined]
            win._custom_title_label = title_lbl  # type: ignore[attr-defined]
        except Exception:
            pass
        self._prepare_dialog_window(win)
        _schedule_window_centering(win, owner)
        schedule_windows_finalize()
        return body

    def _get_toplevel_content_root(self, parent):
        content_root = getattr(parent, "_custom_content_root", None)
        if content_root and content_root.winfo_exists():
            return content_root
        return parent

    def _clear_toplevel_content(self, parent):
        content_root = self._get_toplevel_content_root(parent)
        for widget in content_root.winfo_children():
            widget.destroy()
        return content_root

    def _clear_dialog_focus_bindings(self):
        pending_after = getattr(self, "_dialog_raise_after_id", None)
        if pending_after is not None:
            try:
                self.root.after_cancel(pending_after)
            except Exception:
                pass
            self._dialog_raise_after_id = None
        self._dialog_raise_scheduled = False
        for seq, bind_id in getattr(self, "_dialog_focus_bindings", []):
            try:
                self.root.unbind(seq, bind_id)
            except Exception:
                pass
        self._dialog_focus_bindings = []

    def _cleanup_dialog_windows(self):
        cleaned = []
        for win in getattr(self, "_dialog_windows", []):
            try:
                if win is not None and win.winfo_exists():
                    cleaned.append(win)
            except Exception:
                continue
        self._dialog_windows = cleaned

    def _register_dialog_window(self, win):
        if win is None:
            return
        self._cleanup_dialog_windows()
        if win not in self._dialog_windows:
            self._dialog_windows.append(win)
            try:
                win.bind("<Destroy>", lambda _e, w=win: self._unregister_dialog_window(w), add="+")
            except Exception:
                pass
            try:
                win.bind("<FocusIn>", self._schedule_dialog_raise, add="+")
            except Exception:
                pass
        try:
            if not hasattr(win, "_nlc_force_above_launcher"):
                win._nlc_force_above_launcher = True  # type: ignore[attr-defined]
        except Exception:
            pass
        self._bind_dialog_focus_tracking()
        self._schedule_dialog_raise()

    def _unregister_dialog_window(self, win):
        if getattr(self, "_dialog_windows", None):
            self._dialog_windows = [w for w in self._dialog_windows if w is not win]
        if not self._dialog_windows:
            self._clear_dialog_focus_bindings()

    def _is_dialog_above_root(self, win):
        try:
            return bool(int(win.tk.call("wm", "stackorder", str(win), "isabove", str(self.root))))
        except Exception:
            return False

    def _raise_single_dialog_above_launcher(self, win):
        if os.name != "nt":
            try:
                win.transient(self.root)
            except Exception:
                pass
            if self._is_dialog_above_root(win):
                return
            try:
                win.lift(self.root)
            except Exception:
                win.lift()
            return

        try:
            win.lift(self.root)
        except Exception:
            try:
                win.lift()
            except Exception:
                return

        # Windows sometimes ignores plain lift() for custom/override windows.
        # Briefly toggling topmost forces z-order update, then immediately reverts.
        try:
            if not bool(getattr(win, "_nlc_force_above_launcher", False)):
                return
            now = time.time()
            last = float(getattr(win, "_nlc_last_topmost_bump", 0.0))
            if now - last < 0.35:
                return
            win._nlc_last_topmost_bump = now  # type: ignore[attr-defined]
            win.attributes("-topmost", True)
            win.after(
                35,
                lambda w=win: (w.winfo_exists() and w.attributes("-topmost", False))
            )
        except Exception:
            pass

    def _raise_dialogs_above_launcher(self):
        self._dialog_raise_scheduled = False
        self._dialog_raise_after_id = None
        self._dialog_last_raise_ts = time.time()
        try:
            if str(self.root.state()) in ("iconic", "withdrawn"):
                return
        except Exception:
            return

        self._cleanup_dialog_windows()
        if not self._dialog_windows:
            self._clear_dialog_focus_bindings()
            return

        for win in self._dialog_windows:
            try:
                if str(win.state()) in ("iconic", "withdrawn"):
                    continue
                self._raise_single_dialog_above_launcher(win)
            except Exception:
                continue

    def _schedule_dialog_raise(self, _event=None):
        if self._dialog_raise_scheduled:
            return
        now = time.time()
        elapsed = now - float(getattr(self, "_dialog_last_raise_ts", 0.0))
        min_interval = float(getattr(self, "_dialog_raise_min_interval", 0.12))
        wait_s = max(0.0, min_interval - elapsed)
        delay_ms = int(wait_s * 1000)
        self._dialog_raise_scheduled = True
        try:
            if delay_ms <= 0:
                self.root.after_idle(self._raise_dialogs_above_launcher)
            else:
                self._dialog_raise_after_id = self.root.after(delay_ms, self._raise_dialogs_above_launcher)
        except Exception:
            self._dialog_raise_scheduled = False
            self._dialog_raise_after_id = None

    def _bind_dialog_focus_tracking(self):
        self._clear_dialog_focus_bindings()
        bindings = []
        for seq in ("<FocusIn>", "<Map>", "<Activate>"):
            try:
                bind_id = self.root.bind(seq, self._schedule_dialog_raise, add="+")
                if bind_id:
                    bindings.append((seq, bind_id))
            except Exception:
                pass
        self._dialog_focus_bindings = bindings

    def _clear_onboarding_focus_bindings(self):
        for seq, bind_id in getattr(self, "_onboarding_focus_bindings", []):
            try:
                self.root.unbind(seq, bind_id)
            except Exception:
                pass
        self._onboarding_focus_bindings = []

    def _cancel_onboarding_raise_burst(self):
        pass

    def _raise_onboarding_above_launcher(self):
        wizard = getattr(self, "_onboarding_wizard", None)
        if not wizard:
            self._clear_onboarding_focus_bindings()
            self._cancel_onboarding_raise_burst()
            return
        try:
            if not wizard.winfo_exists():
                self._onboarding_wizard = None
                self._clear_onboarding_focus_bindings()
                self._cancel_onboarding_raise_burst()
                return
            if str(self.root.state()) in ("iconic", "withdrawn"):
                return
            if str(wizard.state()) == "withdrawn":
                wizard.deiconify()

            if os.name != "nt":
                wizard.transient(self.root)
                wizard.lift(self.root)
                try:
                    wizard.attributes("-topmost", True)
                except Exception:
                    pass
            else:
                wizard.lift()
                try:
                    wizard.focus_force()
                except Exception:
                    pass
        except Exception:
            pass

    def _schedule_onboarding_raise(self, _event=None):
        try:
            self.root.after_idle(self._raise_onboarding_above_launcher)
        except Exception:
            pass

    def _bind_onboarding_focus_tracking(self):
        self._clear_onboarding_focus_bindings()
        bindings = []
        for seq in ("<FocusIn>", "<Map>"):
            try:
                bind_id = self.root.bind(seq, self._schedule_onboarding_raise, add="+")
                if bind_id:
                    bindings.append((seq, bind_id))
            except Exception:
                pass
        self._onboarding_focus_bindings = bindings

    def _focus_main_window(self):
        try:
            state = str(self.root.state())
            if state in ("iconic", "withdrawn"):
                self.root.deiconify()
            self.root.lift()
            if os.name == 'nt':
                try:
                    self.root.attributes("-topmost", True)
                    self.root.after(
                        40,
                        lambda: self.root.winfo_exists() and self.root.attributes("-topmost", False)
                    )
                except Exception:
                    pass
            try:
                self.root.focus_force()
            except Exception:
                pass
        except Exception:
            pass

    def create_layout(self):
        root_parent = self.window_content if self.window_content is not None else self.root
        # 1. Sidebar (Left) - width 250px for proper menu
        neo_mode = getattr(self, 'neo_style_enabled', True)
        sb_width = 240 if neo_mode else 200
        self.sidebar = tk.Frame(root_parent, bg=COLORS['sidebar_bg'], width=sb_width)
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

        tk.Frame(self.sidebar, bg=COLORS.get('separator', '#454545'), height=1).pack(fill="x", padx=10, pady=(0, 20)) # Separator

        # --- Sidebar Menu Items ---
        self.sidebar_items = []
        self.nav_buttons = {}

        if neo_mode:
            # Unified Navigation for Neo Mode
            self.sidebar_nav_frame = tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'])
            self.sidebar_nav_frame.pack(fill="both", expand=True)

            def _neo_nav(parent, text, tab_name, icon_name=None, action=None):
                frame = tk.Frame(parent, bg=COLORS['sidebar_bg'], cursor="hand2", padx=15, pady=8)
                frame.pack(fill="x")
                self.sidebar_items.append(frame)

                if icon_name:
                    icon_path = f"icons/{icon_name}" if not icon_name.startswith("icons/") else icon_name
                    img = getattr(self, "get_icon_image", lambda x, y: None)(icon_path, (20, 20))
                    if img:
                        lbl_img = tk.Label(frame, image=img, bg=COLORS['sidebar_bg'], cursor="hand2")
                        lbl_img.image = img # type: ignore
                        lbl_img.pack(side="left", padx=(0, 10))
                    else:
                        tk.Label(frame, text="*", font=("Segoe UI", 12), bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'], cursor="hand2").pack(side="left", padx=(0, 10))
                
                lbl = tk.Label(frame, text=text, font=("Segoe UI", 10, "bold"), bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'], cursor="hand2")
                lbl.pack(side="left")

                def on_click(e):
                    if action:
                        action()
                        self.set_active_sidebar(frame)
                        return
                    self.set_active_sidebar(frame)
                    self.show_tab(tab_name)

                frame.bind("<Button-1>", on_click)
                lbl.bind("<Button-1>", on_click)
                for c in frame.winfo_children():
                    c.bind("<Button-1>", on_click)

                self._attach_sidebar_hover(frame)

                if tab_name == "Play":
                    self.minecraft_btn_frame = frame # type: ignore
                    frame.is_active = True # type: ignore
                    lbl.config(fg="white")

            def build_main_sidebar():
                for widget in self.sidebar_nav_frame.winfo_children():
                    widget.destroy()
                self.sidebar_items = [item for item in getattr(self, 'sidebar_items', []) if item.winfo_exists() and item.master != self.sidebar_nav_frame]
                
                tk.Label(self.sidebar_nav_frame, text="GAMES", font=("Segoe UI", 8, "bold"), fg="#505050", bg=COLORS['sidebar_bg']).pack(anchor="w", padx=15, pady=(0,5))
                _neo_nav(self.sidebar_nav_frame, "Minecraft Java", "Play", "grass_block_side.png")
                _neo_nav(self.sidebar_nav_frame, "Installations", "Installations", "crafting_table_front.png")
                _neo_nav(self.sidebar_nav_frame, "Modpacks", "Modpacks", "shulker_box.png")

                tk.Label(self.sidebar_nav_frame, text="DISCOVER", font=("Segoe UI", 8, "bold"), fg="#505050", bg=COLORS['sidebar_bg']).pack(anchor="w", padx=15, pady=(15,5))
                _neo_nav(self.sidebar_nav_frame, "Modrinth", "Modrinth", "crafting_table_top.png", action=build_modrinth_sidebar)
                _neo_nav(self.sidebar_nav_frame, "Addons", "Addons", "beacon.png")
                _neo_nav(self.sidebar_nav_frame, "Locker", "Locker", "enchanting_table_side.png")

            def build_modrinth_sidebar():
                for widget in self.sidebar_nav_frame.winfo_children():
                    widget.destroy()
                self.sidebar_items = [item for item in getattr(self, 'sidebar_items', []) if item.winfo_exists() and item.master != self.sidebar_nav_frame]
                
                _neo_nav(self.sidebar_nav_frame, "← Back", "Back", None, action=build_main_sidebar)
                
                tk.Label(self.sidebar_nav_frame, text="MODRINTH NETWORK", font=("Segoe UI", 8, "bold"), fg="#505050", bg=COLORS['sidebar_bg']).pack(anchor="w", padx=15, pady=(10,5))
                
                def nav_modrinth(mode):
                    def _action():
                        self.show_tab("Mods")
                        if hasattr(self, 'switch_modrinth_mode'):
                            self.switch_modrinth_mode(mode)
                    return _action

                _neo_nav(self.sidebar_nav_frame, "Mods", "Mods", "comparator_on.png", action=nav_modrinth("mod"))
                _neo_nav(self.sidebar_nav_frame, "Resource Packs", "Resource Packs", "painting.png", action=nav_modrinth("resourcepack"))
                _neo_nav(self.sidebar_nav_frame, "Modpacks", "Modpacks", "shulker_box.png", action=nav_modrinth("modpack"))
                _neo_nav(self.sidebar_nav_frame, "Shaders", "Shaders", "glowstone.png", action=nav_modrinth("shader"))

            build_main_sidebar()

        else:
            # Classic Navigation
            # Minecraft: Java Edition (Highlighted)
            java_btn_frame = tk.Frame(self.sidebar, bg=COLORS.get('hover_bg', '#3A3B3C'), cursor="hand2", padx=10, pady=10) # Lighter grey highlight
        # Settings Link (Gear) - Packed to bottom first to be at the very bottom
        self._create_sidebar_link("Settings", lambda: self.open_global_settings(), is_action=True, pack_side="bottom", icon="⚙")

        # GitHub Link - Packed to bottom next to be above Settings
        self._create_sidebar_link("GitHub", "https://github.com/Amne-Dev/New-launcher", pack_side="bottom")

        # Download Queue UI (Initially hidden or empty)
        self.create_download_queue_ui()

        # 2. Main Content Area
        self.content_area = tk.Frame(root_parent, bg=COLORS['main_bg'])
        self.content_area.pack(side="right", fill="both", expand=True)
        
        # 3. Top Navigation Bar (Only for Classic)
        if not neo_mode:
            self.nav_bar = tk.Frame(self.content_area, bg=COLORS['tab_bar_bg'], height=60)
            self.nav_bar.pack(fill="x", side="top")
            self.nav_bar.pack_propagate(False)
            
            self.create_nav_btn("Play", lambda: self.show_tab("Play"))
            self.create_nav_btn("Installations", lambda: self.show_tab("Installations"))
            self.create_nav_btn("Modpacks", lambda: self.show_tab("Modpacks"))
            self.create_nav_btn("Locker", lambda: self.show_tab("Locker"))
        else:
            self.nav_bar = None # Clear it

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
        
        # Trigger play selection
        if neo_mode and hasattr(self, 'minecraft_btn_frame'):
             self.set_active_sidebar(self.minecraft_btn_frame) # type: ignore
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

    def _show_skeleton_list(self, parent, *, rows=3, card_height=96, padx=20, pady=8):
        """Render lightweight structural placeholders while async content loads."""
        for child in parent.winfo_children():
            child.destroy()

        surface = COLORS.get('card_bg', '#3A3B3C')
        placeholder = COLORS.get('input_bg', '#48494A')
        muted_placeholder = COLORS.get('separator', '#454545')
        for index in range(rows):
            card = tk.Frame(parent, bg=surface, height=card_height, padx=14, pady=12)
            card.pack(fill="x", padx=padx, pady=(pady if index else 0, pady))
            card.pack_propagate(False)

            avatar = tk.Frame(card, bg=placeholder, width=52, height=52)
            avatar.pack(side="left", padx=(0, 14))
            avatar.pack_propagate(False)

            lines = tk.Frame(card, bg=surface)
            lines.pack(side="left", fill="both", expand=True, pady=2)
            tk.Frame(lines, bg=placeholder, height=13, width=210).pack(anchor="w", pady=(2, 10))
            tk.Frame(lines, bg=muted_placeholder, height=9, width=320).pack(anchor="w", pady=(0, 7))
            tk.Frame(lines, bg=muted_placeholder, height=9, width=160).pack(anchor="w")

            action = tk.Frame(card, bg=placeholder, width=70, height=30)
            action.pack(side="right", padx=(12, 0))
            action.pack_propagate(False)

    def add_download_task(self, name, type_str="file"):
        # Show container if hidden with fade-in effect
        if not self.queue_container.winfo_viewable():
             self.queue_container.pack(side="bottom", fill="x", padx=10, pady=10)

        task_id = str(uuid.uuid4())
        
        # Card style with subtle border
        card_bg = "#2b2b2b"
        border_color = "#3d3d3d"
        
        border_frame = tk.Frame(self.queue_list_frame, bg=border_color, padx=1, pady=1)
        border_frame.pack(fill="x", pady=3)
        
        frame = tk.Frame(border_frame, bg=card_bg, pady=6, padx=10)
        frame.pack(fill="x")
        
        # Title Row
        top = tk.Frame(frame, bg=card_bg)
        top.pack(fill="x")
        
        # Truncate name
        disp_name = (name[:18] + '..') if len(name) > 18 else name
        tk.Label(top, text=disp_name, font=("Segoe UI", 8, "bold"), fg="white", bg=card_bg, anchor="w").pack(side="left")
        
        # Detail Frame (Container)
        detail_frame = tk.Frame(frame, bg=card_bg)
        detail_lbl = tk.Label(detail_frame, text="Starting...", font=("Segoe UI", 7), fg="#cccccc", bg=card_bg, anchor="w")
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
            
            btn = tk.Button(top, text="▼", font=("Segoe UI", 6), bg=card_bg, fg="white", 
                            bd=0, activebackground="#3d3d3d", activeforeground="white",
                            command=toggle, width=2, cursor="hand2")
            btn.pack(side="right")
            
            # Hover effect
            btn.bind("<Enter>", lambda e: btn.config(bg="#3d3d3d"))
            btn.bind("<Leave>", lambda e: btn.config(bg=card_bg))
        else:
             # Just show status inline or always hidden? 
             # For single files, maybe no detail frame, or always visible?
             # Let's keep it simpler: hidden by default.
             pass

        # Progress
        pb = ttk.Progressbar(frame, orient="horizontal", mode="determinate", length=100)
        pb.pack(fill="x", pady=3)
        
        self.download_tasks[task_id] = {
            "border_frame": border_frame,
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
            data['pb']['value'] = max(0, min(100, float(progress)))

        if status is not None:
            # Keep the task title useful without adding another cramped line.
            data['detail_lbl'].config(fg=COLORS['text_secondary'])
            
        if detail is not None:
             data['detail_lbl'].config(text=detail)

    def complete_download_task(self, task_id):
        if task_id not in self.download_tasks: return
        
        data = self.download_tasks[task_id]
        data['pb']['value'] = 100
        data['detail_lbl'].config(text="Completed ✓", fg="#2ecc71")
        
        # Visual feedback - brief green highlight
        if 'border_frame' in data:
            data['border_frame'].config(bg="#2ecc71")
            self.root.after(300, lambda: data['border_frame'].config(bg="#3d3d3d") if task_id in self.download_tasks else None)
        
        # Fade out or remove
        def remove():
            if task_id in self.download_tasks:
                data = self.download_tasks[task_id]
                if 'border_frame' in data:
                    data['border_frame'].destroy()
                elif 'frame' in data:
                    data['frame'].destroy()
                del self.download_tasks[task_id]
            
            if not self.download_tasks:
                 self.queue_container.pack_forget()
        
        # Wait 2 sec
        self.root.after(2000, remove)
        if hasattr(self, "toast_manager"):
            self.toast_manager.show("Download completed", kind="success")

    def fail_download_task(self, task_id, message="Download failed"):
        if task_id not in self.download_tasks:
            return
        data = self.download_tasks[task_id]
        data['detail_lbl'].config(text=message, fg=COLORS.get('error_red', '#E74C3C'))
        if 'border_frame' in data:
            data['border_frame'].config(bg=COLORS.get('error_red', '#E74C3C'))

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
        if self._update_in_progress:
            return
        self._update_in_progress = True

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
            part_path = path + ".part"
            
            self.root.after(0, lambda: self.update_progress_label.config(text="Connecting to update server...") if hasattr(self, "update_progress_label") else None)

            # Download with explicit connect/read timeouts and throttled UI updates.
            with requests.get(url, stream=True, timeout=(8, 25)) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                block_size = 1024 * 64
                wrote = 0
                last_ui_tick = 0.0

                with open(part_path, 'wb') as f:
                    for data in r.iter_content(block_size):
                        if not data:
                            continue
                        wrote += len(data)
                        f.write(data)

                        # Throttle to avoid flooding Tk event queue, which can look like a freeze.
                        now = time.monotonic()
                        if (now - last_ui_tick) >= 0.08:
                            last_ui_tick = now
                            if total_size > 0:
                                self.root.after(0, lambda c=wrote, t=total_size: self.update_download_progress(c, t))
                            else:
                                self.root.after(
                                    0,
                                    lambda b=wrote: self.update_status_lbl.config(
                                        text=f"Downloading update... {b // (1024 * 1024)} MB",
                                        fg=COLORS['accent_blue']
                                    )
                                )

                # Final UI update to 100% for known-size downloads.
                if total_size > 0:
                    self.root.after(0, lambda c=wrote, t=total_size: self.update_download_progress(c, t))

            if wrote <= 0:
                raise RuntimeError("Downloaded file is empty.")

            with open(part_path, "rb") as f:
                mz = f.read(2)
            if mz != b"MZ":
                raise RuntimeError("Downloaded update is not a valid Windows executable.")

            os.replace(part_path, path)
            
            # On Finish
            self.root.after(0, self.hide_update_progress)
            self.root.after(0, lambda: self.update_status_lbl.config(text="Update downloaded.", fg=COLORS['success_green']))
            self.root.after(0, lambda: self._on_download_complete(path))
            
        except Exception as e:
            print(f"Update download failed: {e}")
            try:
                if 'part_path' in locals() and os.path.exists(part_path): # type: ignore
                    os.remove(part_path) # type: ignore
            except Exception:
                pass
            self.root.after(0, self.hide_update_progress)
            self.root.after(0, self._reset_update_state)
            self.root.after(0, lambda err=str(e): self.update_status_lbl.config(text=f"Update failed: {err}", fg=COLORS['error_red']))

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
            if path.endswith(".exe"):
                self._launch_updater_and_exit(path)
            else:
                custom_showinfo("Manual Install", f"Update saved to:\n{path}\nPlease run it manually.")
                self._reset_update_state()
        elif result == "manual":
             webbrowser.open("https://github.com/Amne-Dev/New-launcher/releases/latest")
             self._reset_update_state()
        else:
            self._reset_update_state()

    def _reset_update_state(self):
        self._update_in_progress = False

    def _launch_updater_and_exit(self, path):
        try:
            if not os.path.isfile(path):
                raise FileNotFoundError(path)

            self.update_status_lbl.config(text="Launching installer...", fg=COLORS['accent_blue'])
            self.root.after(0, self.hide_update_progress)

            launched = False
            if os.name == 'nt':
                try:
                    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    subprocess.Popen([path], cwd=os.path.dirname(path), close_fds=True, creationflags=creationflags)
                    launched = True
                except Exception:
                    # Fallback, e.g. if creation flags fail in specific environments.
                    os.startfile(path)
                    launched = True
            else:
                subprocess.Popen([path], cwd=os.path.dirname(path), close_fds=True)
                launched = True

            if launched:
                self._begin_update_shutdown()
            else:
                raise RuntimeError("Failed to start updater.")
        except Exception as e:
            custom_showerror("Error", f"Could not launch update: {e}")
            self._reset_update_state()

    def _begin_update_shutdown(self):
        if self._update_shutdown_started:
            return
        self._update_shutdown_started = True

        def _shutdown():
            try:
                self.stop_agent_process()
            except Exception:
                pass
            try:
                if hasattr(self, 'tray_icon') and self.tray_icon:
                    self.tray_icon.stop()
            except Exception:
                pass
            try:
                self.root.destroy()
            except Exception:
                pass
            os._exit(0)

        # Small delay lets spawned updater initialize before process exit.
        self.root.after(160, _shutdown)

    def show_whats_new(self, version):
        """Fetches the changelog for the current version and displays it on first launch after update."""
        dialog = tk.Toplevel(self.root)
        dialog.title("What's New")
        dialog.geometry("600x480")
        dialog.config(bg=COLORS['main_bg'])
        try:
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 300
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 240
            dialog.geometry(f"+{x}+{y}")
        except: pass
        if os.name != "nt":
            dialog.transient(self.root)
        
        dialog_root = self._apply_custom_toplevel_chrome(dialog, f"What's New in v{version}")
        
        # Header
        header = tk.Frame(dialog_root, bg=COLORS['sidebar_bg'], pady=15, padx=20)
        header.pack(fill="x")
        tk.Label(header, text="✨ Launcher Updated! ✨", font=("Segoe UI", 16, "bold"), 
                 bg=COLORS['sidebar_bg'], fg=COLORS['accent_blue']).pack(anchor="center")
        tk.Label(header, text=f"You are now running version {version}", font=("Segoe UI", 10), 
                 bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary']).pack(anchor="center")
        
        # Content
        content_frame = tk.Frame(dialog_root, bg=COLORS['main_bg'], padx=20, pady=20)
        content_frame.pack(fill="both", expand=True)

        text_area = scrolledtext.ScrolledText(content_frame, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                                              relief="flat", wrap="word", state="normal")
        text_area.pack(fill="both", expand=True)
        text_area.insert("1.0", "Fetching release notes from GitHub...\n\n")
        text_area.config(state="disabled")

        # Footer
        footer = tk.Frame(dialog_root, bg=COLORS['sidebar_bg'], pady=15)
        footer.pack(fill="x", side="bottom")
        self._make_btn(footer, "Awesome, Let's Game!", style="primary", font_size=10, 
                       command=dialog.destroy).pack(anchor="center")

        def fetch_changelog():
            try:
                # We specifically load the changelog for this version tag.
                url = f"https://api.github.com/repos/Amne-Dev/New-launcher/releases/tags/v{version}"
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    body = data.get("body", "No description provided for this release.")
                    
                    self.root.after(0, lambda b=body: update_text(b))
                else:
                    self.root.after(0, lambda: update_text(f"Could not load release notes automatically (Status {r.status_code}).\nCheck out the GitHub releases page!"))
            except Exception as e:
                self.root.after(0, lambda: update_text(f"Failed to fetch release notes: {e}"))

        def update_text(msg):
            try:
                if text_area.winfo_exists():
                    text_area.config(state="normal")
                    text_area.delete("1.0", "end")
                    text_area.insert("1.0", msg)
                    text_area.config(state="disabled")
            except: pass

        threading.Thread(target=fetch_changelog, daemon=True).start()

    def show_onboarding_wizard(self):
        """Shows the First Run Wizard — modern redesign with step indicators and smooth transitions."""
        existing_wizard = getattr(self, "_onboarding_wizard", None)
        if existing_wizard:
            try:
                if existing_wizard.winfo_exists():
                    if str(existing_wizard.state()) == "withdrawn":
                        existing_wizard.deiconify()
                    self._schedule_onboarding_raise()
                    existing_wizard.focus_force()
                    if os.name != "nt":
                        existing_wizard.grab_set()
                    return
            except Exception:
                self._onboarding_wizard = None
                self._onboarding_overlay = None

        try:
            # Clean up stale bindings/windows from prior onboarding implementations.
            self._clear_onboarding_focus_bindings()

            stale_overlay = getattr(self, "_onboarding_overlay", None)
            if stale_overlay and stale_overlay.winfo_exists():
                try:
                    stale_overlay.destroy()
                except Exception:
                    pass
            self._onboarding_overlay = None

            self.root.update_idletasks()
            rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
            rw, rh = self.root.winfo_width(), self.root.winfo_height()

            # ── Wizard Window ──
            wizard = tk.Toplevel(self.root)
            wizard.withdraw()
            wizard.title("Welcome")
            wizard.configure(bg=COLORS['main_bg'])
            if os.name != "nt":
                wizard.transient(self.root)
            wizard.resizable(False, False)

            wiz_w, wiz_h = 660, 520
            x = rx + (rw // 2) - (wiz_w // 2)
            y = ry + (rh // 2) - (wiz_h // 2)
            wizard.geometry(f"{wiz_w}x{wiz_h}+{x}+{y}")

            wizard.deiconify()
            wizard.lift()
            wizard.focus_force()
            if os.name != "nt":
                wizard.grab_set()
            self._onboarding_wizard = wizard

            def cleanup_onboarding_state(*_):
                if getattr(self, "_onboarding_wizard", None) is wizard:
                    self._onboarding_wizard = None
                    self._clear_onboarding_focus_bindings()
                    self._cancel_onboarding_raise_burst()
            wizard.bind("<Destroy>", cleanup_onboarding_state, add="+")
            wizard.bind("<FocusIn>", self._schedule_onboarding_raise, add="+")

            wizard_root = self._apply_custom_toplevel_chrome(wizard, "Welcome Setup")
            self._bind_onboarding_focus_tracking()
            self._schedule_onboarding_raise()

            # ── Rounded border effect ──
            border_frame = tk.Frame(wizard_root, bg="#3A3A3A", padx=1, pady=1)
            border_frame.pack(fill="both", expand=True)
            inner = tk.Frame(border_frame, bg=COLORS['main_bg'])
            inner.pack(fill="both", expand=True)

            # ── Step indicator (top bar) ──
            STEPS = ["Account", "Preferences", "Theme", "Ready"]
            step_bar = tk.Frame(inner, bg="#1A1A1A", height=52)
            step_bar.pack(fill="x")
            step_bar.pack_propagate(False)

            # Logo/title at left
            tk.Label(step_bar, text="NEW LAUNCHER", font=("Segoe UI", 9, "bold"),
                     bg="#1A1A1A", fg="#606060").pack(side="left", padx=18)

            # Step dots at right
            dots_frame = tk.Frame(step_bar, bg="#1A1A1A")
            dots_frame.pack(side="right", padx=18)
            dot_labels = []
            for i, step_name in enumerate(STEPS):
                dot_f = tk.Frame(dots_frame, bg="#1A1A1A")
                dot_f.pack(side="left", padx=6)
                dot = tk.Label(dot_f, text="●", font=("Segoe UI", 8),
                              bg="#1A1A1A", fg="#404040")
                dot.pack()
                lbl = tk.Label(dot_f, text=step_name, font=("Segoe UI", 7),
                              bg="#1A1A1A", fg="#505050")
                lbl.pack()
                dot_labels.append((dot, lbl))

            def update_dots(active_idx):
                for i, (dot, lbl) in enumerate(dot_labels):
                    if i < active_idx:
                        dot.config(fg=COLORS.get('success_green', '#2D8F36'))
                        lbl.config(fg=COLORS.get('success_green', '#2D8F36'))
                    elif i == active_idx:
                        dot.config(fg="white")
                        lbl.config(fg="white")
                    else:
                        dot.config(fg="#404040")
                        lbl.config(fg="#505050")

            # ── Content area ──
            content = tk.Frame(inner, bg=COLORS['main_bg'])
            content.pack(fill="both", expand=True)

            self.wizard_account_data = {}

            def clear_page():
                for w in content.winfo_children():
                    w.destroy()

            def make_btn(parent, text, bg_color, command, width=20, font_size=10, bold=True):
                """Utility to create consistent styled buttons."""
                weight = "bold" if bold else ""
                b = tk.Button(parent, text=text, font=("Segoe UI", font_size, weight),
                             bg=bg_color, fg="white", activebackground=bg_color,
                             activeforeground="white", relief="flat", cursor="hand2",
                             command=command, bd=0)
                b.config(padx=16, pady=8)
                return b

            def make_link(parent, text, command):
                """Utility to create text-link buttons."""
                l = tk.Label(parent, text=text, font=("Segoe UI", 9),
                            bg=COLORS['main_bg'], fg="#808080", cursor="hand2")
                l.bind("<Button-1>", lambda e: command())
                l.bind("<Enter>", lambda e: l.config(fg="white"))
                l.bind("<Leave>", lambda e: l.config(fg="#808080"))
                return l

            # ═══════════════════════════════════════════════════
            # STEP 0 — Account Type Selection
            # ═══════════════════════════════════════════════════
            def show_step_account_type():
                clear_page()
                update_dots(0)

                # Spacer
                tk.Frame(content, bg=COLORS['main_bg'], height=30).pack()

                tk.Label(content, text="Welcome to New Launcher",
                        font=("Segoe UI", 22, "bold"), fg="white",
                        bg=COLORS['main_bg']).pack()
                tk.Label(content, text="Choose how you want to sign in",
                        font=("Segoe UI", 11), fg="#909090",
                        bg=COLORS['main_bg']).pack(pady=(6, 30))

                # Card container
                cards = tk.Frame(content, bg=COLORS['main_bg'])
                cards.pack()

                options = [
                    ("Microsoft", "#0078D7", "Official Mojang account", show_step_microsoft),
                    ("Ely.by", "#3498DB", "Third-party auth server", show_step_elyby),
                    ("Offline", "#555555", "Play without authentication", show_step_offline),
                ]

                for name, color, desc, cmd in options:
                    card = tk.Frame(cards, bg=COLORS['card_bg'], cursor="hand2",
                                   highlightbackground="#404040", highlightthickness=1)
                    card.pack(side="left", padx=8, ipadx=0, ipady=0)
                    card.config(width=175, height=140)
                    card.pack_propagate(False)

                    # Color accent strip at top
                    strip = tk.Frame(card, bg=color, height=4)
                    strip.pack(fill="x")

                    # Inner content
                    inner_card = tk.Frame(card, bg=COLORS['card_bg'], cursor="hand2")
                    inner_card.pack(fill="both", expand=True, padx=16, pady=14)

                    tk.Label(inner_card, text=name, font=("Segoe UI", 13, "bold"),
                            fg="white", bg=COLORS['card_bg'], cursor="hand2",
                            anchor="w").pack(anchor="w")
                    tk.Label(inner_card, text=desc, font=("Segoe UI", 8),
                            fg="#808080", bg=COLORS['card_bg'], cursor="hand2",
                            anchor="w", wraplength=140).pack(anchor="w", pady=(4, 0))

                    # Hover + click
                    def on_enter(e, c=card):
                        c.config(highlightbackground="#808080")
                    def on_leave(e, c=card):
                        c.config(highlightbackground="#404040")
                    def on_click(e, fn=cmd):
                        fn()

                    for w in [card, inner_card] + inner_card.winfo_children():
                        w.bind("<Enter>", on_enter)
                        w.bind("<Leave>", on_leave)
                        w.bind("<Button-1>", on_click)
                    card.bind("<Enter>", on_enter)
                    card.bind("<Leave>", on_leave)
                    card.bind("<Button-1>", on_click)

            # ═══════════════════════════════════════════════════
            # STEP 1a — Microsoft Login
            # ═══════════════════════════════════════════════════
            def show_step_microsoft():
                clear_page()
                update_dots(0)

                tk.Frame(content, bg=COLORS['main_bg'], height=20).pack()
                tk.Label(content, text="Microsoft Account",
                        font=("Segoe UI", 18, "bold"), fg="white",
                        bg=COLORS['main_bg']).pack()

                status_lbl = tk.Label(content, text="Connecting to Microsoft...",
                                     font=("Segoe UI", 10), bg=COLORS['main_bg'],
                                     fg="#909090", wraplength=450)
                status_lbl.pack(pady=(12, 8))

                # Code display box
                code_frame = tk.Frame(content, bg=COLORS['card_bg'],
                                     highlightbackground="#404040", highlightthickness=1)
                code_frame.pack(pady=10, ipadx=30, ipady=12)

                code_lbl = tk.Label(code_frame, text="--------",
                                   font=("Consolas", 28, "bold"), bg=COLORS['card_bg'],
                                   fg="white")
                code_lbl.pack()

                url_lbl = tk.Label(content, text="", font=("Segoe UI", 10, "underline"),
                                  bg=COLORS['main_bg'], fg="#3498DB", cursor="hand2")
                url_lbl.pack(pady=4)

                btn_row = tk.Frame(content, bg=COLORS['main_bg'])
                btn_row.pack(pady=12)

                copy_btn = make_btn(btn_row, "Copy Code", "#404040",
                                   lambda: None, font_size=9, bold=False)
                copy_btn.pack(side="left", padx=6)
                copy_btn.config(state="disabled")

                make_link(btn_row, "Cancel", show_step_account_type).pack(side="left", padx=12)

                url_lbl.bind("<Button-1>", lambda e: webbrowser.open(url_lbl.cget("text")) if url_lbl.cget("text") else None)

                # Instructions
                inst_lbl = tk.Label(content, text="",
                                   font=("Segoe UI", 9), bg=COLORS['main_bg'],
                                   fg="#707070", justify="center")
                inst_lbl.pack(pady=(8, 0))

                def run_flow():
                    try:
                        client_id = MSA_CLIENT_ID
                        scope = "XboxLive.signin offline_access"
                        if not wizard.winfo_exists(): return
                        status_lbl.config(text="Requesting device code...")

                        r = requests.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode",
                                          data={"client_id": client_id, "scope": scope})
                        if r.status_code != 200:
                            if wizard.winfo_exists():
                                status_lbl.config(text=f"Error: {r.text}", fg=COLORS['error_red'])
                            return

                        data = r.json()
                        user_code = data.get("user_code")
                        verification_uri = data.get("verification_uri")
                        device_code = data.get("device_code")
                        interval = data.get("interval", 5)

                        if wizard.winfo_exists():
                            code_lbl.config(text=user_code)
                            url_lbl.config(text=verification_uri)
                            status_lbl.config(text="Enter the code above at the link below")
                            inst_lbl.config(text="1. Click the link  2. Paste the code  3. Sign in with Microsoft")
                            copy_btn.config(state="normal",
                                command=lambda: (self.root.clipboard_clear(),
                                                 self.root.clipboard_append(user_code),
                                                 copy_btn.config(text="Copied!", fg="#2D8F36"),
                                                 self.root.after(1500, lambda: copy_btn.config(text="Copy Code", fg="white") if copy_btn.winfo_exists() else None)))

                        while wizard.winfo_exists():
                            time.sleep(interval)
                            r_poll = requests.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
                                data={"grant_type": "device_code", "client_id": client_id, "device_code": device_code})

                            if r_poll.status_code == 200:
                                token_data = r_poll.json()
                                access_token = token_data["access_token"]
                                refresh_token = token_data["refresh_token"]

                                if wizard.winfo_exists(): status_lbl.config(text="Authenticating with Xbox Live...")
                                xbl = minecraft_launcher_lib.microsoft_account.authenticate_with_xbl(access_token)

                                if wizard.winfo_exists(): status_lbl.config(text="Authenticating with XSTS...")
                                xsts = minecraft_launcher_lib.microsoft_account.authenticate_with_xsts(xbl["Token"])

                                if wizard.winfo_exists(): status_lbl.config(text="Authenticating with Minecraft...")
                                mc_auth = minecraft_launcher_lib.microsoft_account.authenticate_with_minecraft(
                                    xbl["DisplayClaims"]["xui"][0]["uhs"], xsts["Token"])

                                if wizard.winfo_exists(): status_lbl.config(text="Fetching profile...")
                                profile = minecraft_launcher_lib.microsoft_account.get_profile(mc_auth["access_token"])

                                self.wizard_account_data = {
                                    "name": profile["name"], "uuid": profile["id"],
                                    "type": "microsoft", "skin_path": "",
                                    "access_token": mc_auth["access_token"],
                                    "refresh_token": refresh_token
                                }
                                if wizard.winfo_exists():
                                    wizard.after(0, save_account_and_continue)
                                break

                            err = r_poll.json()
                            err_code = err.get("error")
                            if err_code == "authorization_pending": continue
                            elif err_code == "slow_down": interval += 2
                            elif err_code == "expired_token":
                                if wizard.winfo_exists():
                                    status_lbl.config(text="Code expired. Please try again.", fg=COLORS['error_red'])
                                break
                            else:
                                if wizard.winfo_exists():
                                    status_lbl.config(text=f"Error: {err.get('error_description', 'Unknown')}", fg=COLORS['error_red'])
                                break
                    except Exception as e:
                        print(f"Wizard Login Error: {e}")
                        if wizard.winfo_exists():
                            status_lbl.config(text=f"Error: {e}", fg=COLORS['error_red'])

                threading.Thread(target=run_flow, daemon=True).start()

            # ═══════════════════════════════════════════════════
            # STEP 1b — Offline
            # ═══════════════════════════════════════════════════
            def show_step_offline():
                clear_page()
                update_dots(0)

                tk.Frame(content, bg=COLORS['main_bg'], height=40).pack()
                tk.Label(content, text="Offline Mode",
                        font=("Segoe UI", 18, "bold"), fg="white",
                        bg=COLORS['main_bg']).pack()
                tk.Label(content, text="Enter a username to play without authentication",
                        font=("Segoe UI", 10), fg="#808080",
                        bg=COLORS['main_bg']).pack(pady=(6, 30))

                form = tk.Frame(content, bg=COLORS['main_bg'])
                form.pack(fill="x", padx=180)

                tk.Label(form, text="USERNAME", font=("Segoe UI", 8, "bold"),
                        fg="#707070", bg=COLORS['main_bg']).pack(anchor="w")
                name_var = tk.StringVar(value="Player")
                e = tk.Entry(form, textvariable=name_var, font=("Segoe UI", 12),
                            bg=COLORS['input_bg'], fg="white", relief="flat",
                            insertbackground="white", bd=0)
                e.pack(fill="x", ipady=8, pady=(4, 0))
                # Underline accent
                tk.Frame(form, bg="#555555", height=2).pack(fill="x")
                e.focus_set()

                btn_frame = tk.Frame(form, bg=COLORS['main_bg'])
                btn_frame.pack(fill="x", pady=(24, 0))

                def do_next():
                    name = name_var.get().strip() or "Player"
                    self.wizard_account_data = {
                        "name": name, "type": "offline",
                        "skin_path": "", "uuid": ""
                    }
                    save_account_and_continue()

                make_btn(btn_frame, "Continue", COLORS.get('success_green', '#2D8F36'),
                        do_next).pack(fill="x")
                make_link(btn_frame, "← Back", show_step_account_type).pack(anchor="w", pady=(12, 0))

            # ═══════════════════════════════════════════════════
            # STEP 1c — Ely.by
            # ═══════════════════════════════════════════════════
            def show_step_elyby():
                clear_page()
                update_dots(0)

                tk.Frame(content, bg=COLORS['main_bg'], height=30).pack()
                tk.Label(content, text="Ely.by Login",
                        font=("Segoe UI", 18, "bold"), fg="white",
                        bg=COLORS['main_bg']).pack()
                tk.Label(content, text="Sign in with your Ely.by credentials",
                        font=("Segoe UI", 10), fg="#808080",
                        bg=COLORS['main_bg']).pack(pady=(6, 24))

                form = tk.Frame(content, bg=COLORS['main_bg'])
                form.pack(fill="x", padx=180)

                tk.Label(form, text="USERNAME / EMAIL", font=("Segoe UI", 8, "bold"),
                        fg="#707070", bg=COLORS['main_bg']).pack(anchor="w")
                ue = tk.Entry(form, font=("Segoe UI", 11), bg=COLORS['input_bg'],
                             fg="white", relief="flat", insertbackground="white", bd=0)
                ue.pack(fill="x", ipady=7, pady=(4, 0))
                tk.Frame(form, bg="#555555", height=2).pack(fill="x")

                tk.Frame(form, bg=COLORS['main_bg'], height=14).pack()

                tk.Label(form, text="PASSWORD", font=("Segoe UI", 8, "bold"),
                        fg="#707070", bg=COLORS['main_bg']).pack(anchor="w")
                pe = tk.Entry(form, font=("Segoe UI", 11), bg=COLORS['input_bg'],
                             fg="white", relief="flat", show="●",
                             insertbackground="white", bd=0)
                pe.pack(fill="x", ipady=7, pady=(4, 0))
                tk.Frame(form, bg="#555555", height=2).pack(fill="x")

                err_lbl = tk.Label(form, text="", font=("Segoe UI", 9),
                                  bg=COLORS['main_bg'], fg=COLORS['error_red'])
                err_lbl.pack(anchor="w", pady=(8, 0))

                ue.focus_set()

                btn_frame = tk.Frame(form, bg=COLORS['main_bg'])
                btn_frame.pack(fill="x", pady=(16, 0))

                def do_auth():
                    user_input = ue.get().strip()
                    pw = pe.get().strip()
                    if not user_input or not pw:
                        err_lbl.config(text="Please fill in both fields")
                        return
                    err_lbl.config(text="")
                    res = ElyByAuth.authenticate(user_input, pw)
                    if "error" in res:
                        err_lbl.config(text=res['error'])
                    else:
                        prof = cast(dict, res.get("selectedProfile", {}))
                        name = prof.get("name", user_input)
                        self.wizard_account_data = {
                            "name": name, "type": "ely.by",
                            "uuid": prof.get("id", ""),
                            "skin_path": ""
                        }
                        save_account_and_continue()

                make_btn(btn_frame, "Sign In", "#3498DB", do_auth).pack(fill="x")
                make_link(btn_frame, "← Back", show_step_account_type).pack(anchor="w", pady=(12, 0))

            # ═══════════════════════════════════════════════════
            # Save & transition
            # ═══════════════════════════════════════════════════
            def save_account_and_continue():
                is_default = False
                if len(self.profiles) == 1:
                    p = self.profiles[0]
                    if p.get("name") == "Steve" and p.get("type") == "offline" and not p.get("uuid"):
                        is_default = True

                if not self.profiles or is_default:
                    self.profiles = [self.wizard_account_data]
                    self.current_profile_index = 0
                else:
                    self.profiles.append(self.wizard_account_data)
                    self.current_profile_index = len(self.profiles) - 1

                self.save_config(sync_ui=False)
                self.update_active_profile()
                show_step_preferences()

            # ═══════════════════════════════════════════════════
            # STEP 2 — Preferences
            # ═══════════════════════════════════════════════════
            def show_step_preferences():
                clear_page()
                update_dots(1)

                tk.Frame(content, bg=COLORS['main_bg'], height=30).pack()
                tk.Label(content, text="Game Preferences",
                        font=("Segoe UI", 18, "bold"), fg="white",
                        bg=COLORS['main_bg']).pack()
                tk.Label(content, text="Configure memory and launcher behavior",
                        font=("Segoe UI", 10), fg="#808080",
                        bg=COLORS['main_bg']).pack(pady=(6, 24))

                form = tk.Frame(content, bg=COLORS['main_bg'])
                form.pack(fill="x", padx=100)

                # RAM section
                ram_card = tk.Frame(form, bg=COLORS['card_bg'], padx=18, pady=14)
                ram_card.pack(fill="x", pady=(0, 16))

                ram_header = tk.Frame(ram_card, bg=COLORS['card_bg'])
                ram_header.pack(fill="x")
                tk.Label(ram_header, text="Memory Allocation",
                        font=("Segoe UI", 11, "bold"), fg="white",
                        bg=COLORS['card_bg']).pack(side="left")
                ram_val_lbl = tk.Label(ram_header, text=f"{self.ram_allocation} MB",
                                      font=("Segoe UI", 10), fg=COLORS.get('success_green', '#2D8F36'),
                                      bg=COLORS['card_bg'])
                ram_val_lbl.pack(side="right")

                ram_v = tk.IntVar(value=self.ram_allocation)

                def on_ram_change(val):
                    ram_val_lbl.config(text=f"{int(float(val))} MB")

                ram_scale = tk.Scale(ram_card, from_=1024, to=16384, orient="horizontal",
                                    resolution=512, variable=ram_v, showvalue=False,
                                    bg=COLORS['card_bg'], fg="white",
                                    troughcolor=COLORS['input_bg'], highlightthickness=0,
                                    activebackground=COLORS.get('success_green', '#2D8F36'),
                                    command=on_ram_change, length=400)
                ram_scale.pack(fill="x", pady=(8, 0))

                # Toggles
                toggle_card = tk.Frame(form, bg=COLORS['card_bg'], padx=18, pady=14)
                toggle_card.pack(fill="x")

                c_launch = tk.BooleanVar(value=True)
                c_tray = tk.BooleanVar(value=False)

                for txt, var in [("Close launcher when game starts", c_launch),
                                 ("Minimize to system tray on close", c_tray)]:
                    row = tk.Frame(toggle_card, bg=COLORS['card_bg'])
                    row.pack(fill="x", pady=4)
                    tk.Checkbutton(row, text=txt, variable=var, font=("Segoe UI", 10),
                                  bg=COLORS['card_bg'], fg="white",
                                  selectcolor=COLORS['input_bg'],
                                  activebackground=COLORS['card_bg'],
                                  activeforeground="white").pack(anchor="w")

                btn_frame = tk.Frame(form, bg=COLORS['main_bg'])
                btn_frame.pack(fill="x", pady=(20, 0))

                def do_next():
                    self.ram_allocation = ram_v.get()
                    self.close_launcher = c_launch.get()
                    self.minimize_to_tray = c_tray.get()
                    self.save_config(sync_ui=False)
                    show_step_theme()

                make_btn(btn_frame, "Continue", COLORS.get('success_green', '#2D8F36'),
                        do_next).pack(fill="x")

            # ═══════════════════════════════════════════════════
            # STEP 3 — Theme / Accent Color
            # ═══════════════════════════════════════════════════
            def show_step_theme():
                clear_page()
                update_dots(2)

                tk.Frame(content, bg=COLORS['main_bg'], height=40).pack()
                tk.Label(content, text="Pick Your Color",
                        font=("Segoe UI", 18, "bold"), fg="white",
                        bg=COLORS['main_bg']).pack()
                tk.Label(content, text="Choose an accent color for the launcher",
                        font=("Segoe UI", 10), fg="#808080",
                        bg=COLORS['main_bg']).pack(pady=(6, 30))

                colors_list = [
                    ("Green",  "#2D8F36"),
                    ("Blue",   "#3498DB"),
                    ("Orange", "#E67E22"),
                    ("Purple", "#9B59B6"),
                    ("Red",    "#E74C3C"),
                ]

                palette = tk.Frame(content, bg=COLORS['main_bg'])
                palette.pack()

                selected = [getattr(self, "accent_color_name", "Green")]
                swatch_widgets = []

                def select_color(name, color):
                    selected[0] = name
                    self.apply_accent_color(name)
                    self.save_config(sync_ui=False)
                    # Update swatch highlights
                    for sn, sw, sl in swatch_widgets:
                        if sn == name:
                            sw.config(highlightbackground="white", highlightthickness=2)
                            sl.config(fg="white")
                        else:
                            sw.config(highlightbackground="#303030", highlightthickness=1)
                            sl.config(fg="#707070")
                    # Update finish button
                    if finish_btn:
                        finish_btn.config(bg=color, activebackground=color)

                finish_btn = None

                for name, color in colors_list:
                    col = tk.Frame(palette, bg=COLORS['main_bg'])
                    col.pack(side="left", padx=12)

                    is_active = (name == selected[0])
                    swatch = tk.Frame(col, bg=color, width=50, height=50, cursor="hand2",
                                     highlightbackground="white" if is_active else "#303030",
                                     highlightthickness=2 if is_active else 1)
                    swatch.pack()
                    swatch.pack_propagate(False)

                    lbl = tk.Label(col, text=name, font=("Segoe UI", 8),
                                  bg=COLORS['main_bg'],
                                  fg="white" if is_active else "#707070")
                    lbl.pack(pady=(4, 0))

                    swatch_widgets.append((name, swatch, lbl))

                    # Click handlers
                    swatch.bind("<Button-1>", lambda e, n=name, c=color: select_color(n, c))
                    for child in swatch.winfo_children():
                        child.bind("<Button-1>", lambda e, n=name, c=color: select_color(n, c))

                current_accent = dict(colors_list).get(selected[0], "#2D8F36")
                finish_btn = make_btn(content, "Finish Setup", current_accent, show_step_done)
                finish_btn.pack(pady=(40, 0), ipadx=24)

            # ═══════════════════════════════════════════════════
            # STEP 4 — Done
            # ═══════════════════════════════════════════════════
            def show_step_done():
                clear_page()
                update_dots(3)

                tk.Frame(content, bg=COLORS['main_bg'], height=50).pack()

                tk.Label(content, text="✓", font=("Segoe UI", 36),
                        fg=COLORS.get('success_green', '#2D8F36'),
                        bg=COLORS['main_bg']).pack()
                tk.Label(content, text="You're All Set!",
                        font=("Segoe UI", 20, "bold"), fg="white",
                        bg=COLORS['main_bg']).pack(pady=(8, 6))
                tk.Label(content, text="Create an installation to start playing",
                        font=("Segoe UI", 11), fg="#808080",
                        bg=COLORS['main_bg']).pack()

                def finish():
                    self.first_run = False
                    self.save_config()
                    if wizard.winfo_exists():
                        wizard.destroy()
                    self._focus_main_window()
                    self.show_tab("Installations")
                    self.root.after(80, self.update_active_profile)
                    self.root.after(180, self.refresh_skin)
                    # Start post-onboarding guidance cards after the wizard closes.
                    self.root.after(260, self.start_installations_tour)
                    self.root.after(420, self._focus_main_window)

                make_btn(content, "Get Started", COLORS.get('success_green', '#2D8F36'),
                        finish).pack(pady=(36, 0), ipadx=24)

            # ── Start ──
            show_step_account_type()

        except Exception as e:
            logging.exception("Error showing wizard")
            print(f"Error showing wizard: {e}")
            traceback.print_exc()
            try:
                if 'wizard' in locals() and wizard.winfo_exists(): # type: ignore
                    wizard.destroy() # type: ignore
                self._onboarding_wizard = None
                self._onboarding_overlay = None
                self._clear_onboarding_focus_bindings()
                self._cancel_onboarding_raise_burst()
            except: pass

    def start_installations_tour(self):
        """Step 2: Installations"""
        self.show_tab("Installations")
        self.root.update()
        self._focus_main_window()

        target = None
        try:
            if hasattr(self, 'new_inst_btn') and self.new_inst_btn.winfo_exists():
                target = self.new_inst_btn
        except Exception:
            target = None

        if not target and "Installations" in self.tabs:
            target = self.tabs["Installations"]

        if target:
            self.show_coach_mark(
                target,
                "Create and manage game installations here.\nUse New installation to add one quickly.",
                next_action=self.start_locker_tour
            )
        else:
            self.start_locker_tour()

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
            tip.transient(self.root)
            
            # Calc position (below-left aligned) with screen bounds checking
            tip.update_idletasks()
            tip_w = 350  # Approximate tooltip width
            tip_h = 120  # Approximate tooltip height
            
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            
            tip_x = x - 150 + w 
            tip_y = y + h + 10
            
            # Prevent tooltip from going off-screen
            if tip_x + tip_w > screen_w:
                tip_x = screen_w - tip_w - 10
            if tip_x < 0:
                tip_x = 10
            if tip_y + tip_h > screen_h:
                # Position above instead of below
                tip_y = y - tip_h - 10
            if tip_y < 0:
                tip_y = 10
                
            tip.geometry(f"+{tip_x}+{tip_y}")
            tip.deiconify()
            tip.lift()
            
            # Style
            bg = "#0078D7" # Blue accent
            fg = "white"
            border_color = "#1E90FF"
            
            # Outer border frame for subtle outline
            outer_frame = tk.Frame(tip, bg=border_color, padx=1, pady=1)
            outer_frame.pack()
            
            frame = tk.Frame(outer_frame, bg=bg, padx=2, pady=2)
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
        dialog.geometry("450x300")
        dialog.config(bg=COLORS['main_bg'])
        if os.name != "nt":
            dialog.transient(self.root)
        dialog.resizable(False, False)
        if os.name != "nt":
            dialog.grab_set()
        
        # Center on parent
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width()//2) - 225
        y = self.root.winfo_y() + (self.root.winfo_height()//2) - 150
        dialog.geometry(f"+{x}+{y}")
        
        # Ensure visibility
        dialog.deiconify()
        dialog.lift()
        dialog_root = self._apply_custom_toplevel_chrome(dialog, "Enable Mod Support")
        
        container = tk.Frame(dialog_root, bg=COLORS['main_bg'], padx=20, pady=20)
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
                 font=("Segoe UI", 10, "bold"), relief="flat", padx=15, pady=6, bd=0,
                 cursor="hand2", activebackground=COLORS.get('play_btn_green', '#2D8F36'), activeforeground="white",
                 command=enable).pack(side="right", padx=5)
                 
        tk.Button(btn_frame, text="No", bg="#404040", fg="#E0E0E0", 
                 font=("Segoe UI", 10), relief="flat", padx=15, pady=6, bd=0,
                 cursor="hand2", activebackground="#525252", activeforeground="white",
                 command=dialog.destroy).pack(side="right", padx=5)

    def set_active_sidebar(self, active_frame):
        for frame in getattr(self, 'sidebar_items', []):
            if frame == active_frame:
                frame.config(bg=COLORS.get('hover_bg', '#3A3B3C'))
                frame.is_active = True
                for child in frame.winfo_children():
                    if isinstance(child, tk.Label):
                        if not getattr(child, "_keep_sidebar_bg", False):
                            child.config(bg=COLORS.get('hover_bg', '#3A3B3C'), fg=COLORS['text_primary'])
            else:
                frame.config(bg=COLORS['sidebar_bg'])
                frame.is_active = False
                for child in frame.winfo_children():
                    if isinstance(child, tk.Label):
                        if not getattr(child, "_keep_sidebar_bg", False):
                            child.config(bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'])

    def _attach_sidebar_hover(self, frame):
        def on_enter(e):
            frame.config(bg=COLORS.get('hover_bg', '#3A3B3C'))
            for child in frame.winfo_children():
                if isinstance(child, tk.Label):
                    if not getattr(child, "_keep_sidebar_bg", False):
                        child.config(bg=COLORS.get('hover_bg', '#3A3B3C'), fg=COLORS['text_primary'])
        
        def on_leave(e):
            if getattr(frame, "is_active", False):
                 return
            
            frame.config(bg=COLORS['sidebar_bg'])
            for child in frame.winfo_children():
                if isinstance(child, tk.Label):
                    if not getattr(child, "_keep_sidebar_bg", False):
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
             
             indicator_label = tk.Label(frame, text=indicator_text, bg=bg_color, fg="white", 
                     font=("Segoe UI", 8, "bold"), width=4, cursor="hand2")
             indicator_label._keep_sidebar_bg = True  # type: ignore[attr-defined]
             indicator_label.pack(side="left", padx=(0,10))
        
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

    # --- Smooth Scroll Utilities ---
    def _get_scroll_impulse(self, event):
        """Normalise wheel and precision-touchpad input to pixel impulses."""
        try:
            delta = getattr(event, "delta", 0)
            if delta:
                # Windows wheel mice normally report ±120; precision touchpads
                # often report much smaller values.  The old conversion ignored
                # those small deltas because the animation stopped below 0.5.
                direction = -1 if delta > 0 else 1
                return direction * max(18, min(72, abs(float(delta)) / 3))
        except Exception:
            pass

        try:
            button_num = getattr(event, "num", None)
            if button_num == 4:
                return -40
            if button_num == 5:
                return 40
        except Exception:
            pass

        return 0

    def _bind_wheel_events(self, widget, handler, bind_tag):
        if not widget or not widget.winfo_exists():
            return
        attr_name = f"_nlc_wheel_bind_{bind_tag}"
        if getattr(widget, attr_name, False):
            return
        # Add, rather than replace, widget-native bindings (notably Combobox
        # and Text).  This fixes wheel support without breaking controls.
        widget.bind("<MouseWheel>", handler, add="+")
        widget.bind("<Button-4>", handler, add="+")
        widget.bind("<Button-5>", handler, add="+")
        setattr(widget, attr_name, True)
        if isinstance(widget, tk.Canvas):
            widget._nlc_canvas_wheel_bound = True  # type: ignore[attr-defined]

    def _smooth_scroll(self, canvas, event):
        """Smooth mousewheel scrolling with inertia for any canvas widget."""
        try:
            if not getattr(canvas, "_nlc_scroll_enabled", True):
                return
        except Exception:
            pass
        cid = id(canvas)
        # Cancel any existing animation for this canvas
        if cid in self._scroll_anim_ids:
            try: self.root.after_cancel(self._scroll_anim_ids[cid])
            except: pass
            self._scroll_anim_ids.pop(cid, None)
        
        # Add velocity from scroll event (accumulate for fast flicks)
        impulse = self._get_scroll_impulse(event)
        if not impulse:
            return
        current = self._scroll_velocities.get(cid, 0.0)
        # A hard cap prevents a burst of wheel events from coasting across an
        # entire page and makes scrolling predictable at all window sizes.
        self._scroll_velocities[cid] = max(-360.0, min(360.0, current + impulse))
        
        self._animate_scroll(canvas, cid)
    
    def _animate_scroll(self, canvas, cid):
        """Animate scroll with deceleration (inertia)."""
        try:
            if not canvas.winfo_exists():
                self._scroll_velocities.pop(cid, None)
                self._scroll_anim_ids.pop(cid, None)
                return
        except:
            self._scroll_velocities.pop(cid, None)
            self._scroll_anim_ids.pop(cid, None)
            return
        
        velocity = self._scroll_velocities.get(cid, 0)
        
        # Stop if velocity is negligible
        if abs(velocity) < 0.5:
            self._scroll_velocities.pop(cid, None)
            self._scroll_anim_ids.pop(cid, None)
            return
        
        # Clamp at boundaries
        top, bottom = canvas.yview()
        if (velocity < 0 and top <= 0) or (velocity > 0 and bottom >= 1.0):
            self._scroll_velocities.pop(cid, None)
            self._scroll_anim_ids.pop(cid, None)
            return
        
        # Scroll by velocity (convert pixels to fraction of total height)
        bbox = canvas.bbox("all")
        if not bbox:
            self._scroll_velocities.pop(cid, None)
            self._scroll_anim_ids.pop(cid, None)
            return
        total_height = bbox[3] - bbox[1]
        canvas_height = canvas.winfo_height()
        
        if total_height <= canvas_height:
            self._scroll_velocities.pop(cid, None)
            self._scroll_anim_ids.pop(cid, None)
            return
        
        fraction = velocity / total_height
        max_top = max(0.0, 1.0 - (canvas_height / total_height))
        canvas.yview_moveto(max(0.0, min(max_top, top + fraction)))
        callback = getattr(canvas, "_nlc_after_scroll", None)
        if callable(callback):
            callback()
        
        # Apply friction
        self._scroll_velocities[cid] = velocity * 0.78
        
        # Schedule next frame (~16ms for 60fps)
        self._scroll_anim_ids[cid] = self.root.after(16, self._animate_scroll, canvas, cid)

    def _bind_smooth_scroll(self, canvas, widget):
        """Bind smooth scrolling to a widget and all its children for a specific canvas."""
        if not widget or not widget.winfo_exists():
            return
        # Many panels previously bound the wheel only after entering a child
        # frame, so the blank area around content appeared unscrollable.  Give
        # every canvas a handler unless that panel already installed a custom
        # one (such as Modrinth pagination).
        if not getattr(canvas, "_nlc_canvas_wheel_bound", False):
            self._bind_wheel_events(
                canvas,
                lambda event, target=canvas: self._smooth_scroll(target, event),
                f"canvas_{id(canvas)}",
            )
        canvas_id = id(canvas)
        already_bound = getattr(widget, "_nlc_scroll_canvas_id", None)
        if already_bound != canvas_id:
            handler = lambda e, c=canvas: self._smooth_scroll(c, e)
            self._bind_wheel_events(widget, handler, f"smooth_{canvas_id}")
            setattr(widget, "_nlc_scroll_canvas_id", canvas_id)
        for child in widget.winfo_children():
            self._bind_smooth_scroll(canvas, child)

    def _make_btn(self, parent, text, style="secondary", command=None, font_size=9,
                  bold=False, icon=False, width=None, pack_opts=None):
        """Create a consistently styled button.
        
        Styles:
            primary   — Accent/green background, white text
            secondary — Dark gray background, white text
            danger    — Red background, white text
            text      — Transparent background, muted text, no padding
            icon      — Compact square for icon-only buttons (📁, ..., ⋮)
        """
        weight = "bold" if bold else ""
        cfg = {
            "primary":   {"bg": COLORS.get('play_btn_green', '#2D8F36'), "fg": "white",
                          "hover": COLORS.get('play_btn_green', '#2D8F36'), "active_fg": "white"},
            "secondary": {"bg": "#404040", "fg": "#E0E0E0",
                          "hover": "#525252", "active_fg": "white"},
            "danger":    {"bg": "#C0392B", "fg": "white",
                          "hover": "#E74C3C", "active_fg": "white"},
            "text":      {"bg": COLORS.get('main_bg', '#1E1E1E'), "fg": "#909090",
                          "hover": COLORS.get('main_bg', '#1E1E1E'), "active_fg": "white"},
            "icon":      {"bg": "#404040", "fg": "#C0C0C0",
                          "hover": "#525252", "active_fg": "white"},
        }.get(style, {"bg": "#404040", "fg": "white", "hover": "#525252", "active_fg": "white"})

        btn = tk.Button(parent, text=text, font=("Segoe UI", font_size, weight),
                       bg=cfg["bg"], fg=cfg["fg"],
                       activebackground=cfg["hover"], activeforeground=cfg["active_fg"],
                       relief="flat", bd=0, cursor="hand2", command=command) # type: ignore

        if os.name != "nt":
            btn.config(
                highlightthickness=0,
                takefocus=0,
                highlightbackground=cfg["bg"],
                highlightcolor=cfg["bg"],
                disabledforeground=cfg["fg"],
            )

        if style == "icon":
            btn.config(padx=6, pady=4)
        elif style == "text":
            btn.config(padx=2, pady=2)
        else:
            btn.config(padx=14, pady=6)

        if width is not None:
            btn.config(width=width)

        # Hover effects
        def on_enter(e):
            btn.config(bg=cfg["hover"])
        def on_leave(e):
            btn.config(bg=cfg["bg"])
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

        if os.name != "nt":
            def prime_linux_button():
                try:
                    if not btn.winfo_exists():
                        return
                    btn.config(
                        bg=cfg["bg"],
                        fg=cfg["fg"],
                        activebackground=cfg["hover"],
                        activeforeground=cfg["active_fg"],
                    )
                    btn.update_idletasks()
                except Exception:
                    pass

            btn.after_idle(prime_linux_button)
            btn.after(40, prime_linux_button)

        return btn

    def _animate_menu_open(self, menu, target_h, direction="down", pos_x=None, pos_y=None, pos_w=None):
        """Slide-open animation for dropdown menus.
        
        Args:
            pos_x, pos_y, pos_w: Explicit position/size to avoid re-parsing geometry.
                                 pos_y is the FINAL top-left y of the menu.
        """
        try:
            if pos_x is not None and pos_y is not None and pos_w is not None:
                w, x, base_y = pos_w, pos_x, pos_y
            else:
                geo = menu.geometry()
                parts = geo.split('+')
                size = parts[0].split('x')
                w = int(size[0])
                x = int(parts[1])
                base_y = int(parts[2])
        except:
            return
        
        steps = 6
        current_step = [0]
        
        if direction == "up":
            bottom_edge = base_y + target_h
        
        def step():
            if current_step[0] >= steps:
                menu.geometry(f"{w}x{target_h}+{x}+{base_y}")
                return
            try:
                if not menu.winfo_exists(): return
            except: return
            
            t = (current_step[0] + 1) / steps
            t_ease = 1 - (1 - t) ** 3
            h = max(1, int(t_ease * target_h))
            
            if direction == "up":
                y = bottom_edge - h # type: ignore
                menu.geometry(f"{w}x{h}+{x}+{y}")
            else:
                menu.geometry(f"{w}x{h}+{x}+{base_y}")
            
            current_step[0] += 1
            self.root.after(12, step)
        
        if direction == "up":
            menu.geometry(f"{w}x1+{x}+{bottom_edge - 1}") # type: ignore
        else:
            menu.geometry(f"{w}x1+{x}+{base_y}")
        step()

    def _close_all_menus(self):
        """Close all open dropdown menus when switching tabs or performing other actions"""
        # Close installation selector menu
        if hasattr(self, '_selector_menu') and self._selector_menu:
            try:
                if self._selector_menu.winfo_exists():
                    self._selector_menu.destroy()
            except:
                pass
            self._selector_menu = None
        
        # Close profile menu
        if hasattr(self, 'profile_menu') and self.profile_menu:
            try:
                if self.profile_menu.winfo_exists():
                    self.profile_menu.destroy()
            except:
                pass
            self.profile_menu = None
        
        # Close launch options menu
        if hasattr(self, '_launch_opts_menu') and self._launch_opts_menu:
            try:
                if self._launch_opts_menu.winfo_exists():
                    self._launch_opts_menu.destroy()
            except:
                pass
            self._launch_opts_menu = None
        
        # Close installation context menu
        if hasattr(self, 'installation_menu') and self.installation_menu:
            try:
                if self.installation_menu.winfo_exists():
                    self.installation_menu.destroy()
            except:
                pass
            self.installation_menu = None

    def create_nav_btn(self, text, command):
        def wrapped_command():
            # Automatically set Minecraft as active sidebar when top nav is clicked
            if hasattr(self, 'minecraft_btn_frame'):
                self.set_active_sidebar(self.minecraft_btn_frame) # type: ignore
            command()

        btn = tk.Button(self.nav_bar, text=text.upper(), font=("Segoe UI", 11, "bold"),
                       bg=COLORS['tab_bar_bg'], fg=COLORS['text_secondary'],
                       activebackground=COLORS['tab_bar_bg'], activeforeground=COLORS['text_primary'],
                       relief="flat", bd=0, cursor="hand2", command=wrapped_command)
        btn.pack(side="left", padx=30, pady=15)
        # Hover
        btn.bind("<Enter>", lambda e, b=btn: b.config(fg=COLORS['text_primary']))
        btn.bind("<Leave>", lambda e, b=btn: b.config(fg=COLORS['text_secondary']) if b.cget('bg') == COLORS['tab_bar_bg'] else None)
        self.nav_buttons[text] = btn

    def show_tab(self, tab_name):
        # Close any open dropdown menus
        self._close_all_menus()
        
        # Lazy Init Mods Tab
        if tab_name == "Mods" and "Mods" not in self.tabs:
             self.create_mods_tab()

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
        
        # Debounce resize events to prevent lag
        self._resize_timer = None
        def debounced_resize(event):
            if self._resize_timer:
                self.root.after_cancel(self._resize_timer)
            self._resize_timer = self.root.after(100, lambda: self._update_hero_layout(event))
        
        self.hero_canvas.bind("<Configure>", debounced_resize)

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
             w.bind("<Button-1>", lambda e, s=self: s.open_selector_menu(e), add="+")
        
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
        self.launch_btn.bind("<Enter>", lambda e: self.launch_btn.config(bg=COLORS['play_btn_hover']))
        self.launch_btn.bind("<Leave>", lambda e: self.launch_btn.config(bg=COLORS['play_btn_green']))
        
        # Divider line
        self.launch_sep = tk.Frame(self.play_container, width=1, bg=COLORS.get('play_btn_green', '#2D8F36')); self.launch_sep.pack(side="left", fill="y")

        self.launch_opts_btn = tk.Button(self.play_container, text="▼", font=("Segoe UI", 10),
                                        bg=COLORS['play_btn_green'], fg="white",
                                        activebackground=COLORS['play_btn_hover'], activeforeground="white",
                                        relief="flat", bd=0, cursor="hand2", width=3,
                                        command=self.open_launch_options)
        self.launch_opts_btn.pack(side="left", fill="y")
        self.launch_opts_btn.bind("<Enter>", lambda e: self.launch_opts_btn.config(bg=COLORS['play_btn_hover']))
        self.launch_opts_btn.bind("<Leave>", lambda e: self.launch_opts_btn.config(bg=COLORS['play_btn_green']))
        
        
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
        # Toggle: if already open, close it
        if hasattr(self, '_launch_opts_menu') and self._launch_opts_menu:
            try:
                if self._launch_opts_menu.winfo_exists():
                    self._launch_opts_menu.destroy()
                    self._launch_opts_menu = None
                    return
            except:
                self._launch_opts_menu = None
        
        # Close any other open menus first
        self._close_all_menus()
        
        # Popup near the arrow button
        menu = tk.Toplevel(self.root)
        menu.overrideredirect(True)
        menu.config(bg=COLORS['card_bg'])
        menu.transient(self.root)
        menu.attributes('-topmost', True)
        self._launch_opts_menu = menu
        
        target_h = 40
        try:
             x = self.launch_opts_btn.winfo_rootx() + self.launch_opts_btn.winfo_width() - 150
             y = self.launch_opts_btn.winfo_rooty() + self.launch_opts_btn.winfo_height() + 5
             menu.geometry(f"150x{target_h}+{x}+{y}") 
        except:
             menu.geometry(f"150x{target_h}")
        
        def close_menu():
            try:
                if menu.winfo_exists():
                    menu.destroy()
            except:
                pass
            self._launch_opts_menu = None
             
        def do_force():
            close_menu()
            self.start_launch(force_update=True)
            
        btn = tk.Label(menu, text="Force Update & Play", font=("Segoe UI", 10), 
                      bg=COLORS['card_bg'], fg=COLORS['text_primary'], anchor="w", padx=10, pady=8)
        btn.pack(fill="x")
        btn.bind("<Button-1>", lambda e: do_force())
        btn.bind("<Enter>", lambda e: btn.config(bg="#454545"))
        btn.bind("<Leave>", lambda e: btn.config(bg=COLORS['card_bg']))

        # Close on click outside or Escape
        menu.bind("<FocusOut>", lambda e: self.root.after(100, close_menu))
        menu.bind("<Escape>", lambda e: close_menu())
        
        # Ensure visibility with slide animation
        menu.update_idletasks()
        menu.deiconify()
        menu.lift()
        menu.focus_set()
        self._animate_menu_open(menu, target_h, direction="down")

    def update_bottom_gamertag(self):
        # Update the small gamertag in the bottom right corner
        if hasattr(self, 'bottom_gamertag') and self.profiles:
             p = self.profiles[self.current_profile_index]
             self.bottom_gamertag.config(text=self._get_streamer_safe_name(p.get("name", "")))

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
        self.new_inst_btn = self._make_btn(top_bar, "New installation", style="primary",
                                           font_size=10, bold=True, command=self.open_new_installation_modal)
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

        # Smooth mousewheel
        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
        list_container.bind("<Enter>", lambda e: self._bind_smooth_scroll(canvas, self.inst_list_frame))
        
        # Update Scrollbar visibility
        def update_scroll_state(e=None):
            self.inst_list_frame.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
            bbox = canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1]) > canvas.winfo_height():
                scrollbar.pack(side="right", fill="y")
            else:
                scrollbar.pack_forget()

        list_container.bind("<Configure>", update_scroll_state)
        self.inst_list_frame.bind("<Configure>", update_scroll_state)
        
        self.refresh_installations_list(lambda: [self._bind_smooth_scroll(canvas, self.inst_list_frame), update_scroll_state()])

    def refresh_installations_list(self, callback=None):
        if not hasattr(self, 'inst_list_frame'): return # Safety check
        
        # Clear existing widgets
        for w in self.inst_list_frame.winfo_children(): w.destroy()
        
        # Force update layout before repopulating
        self.inst_list_frame.update_idletasks()
        
        # Cache filter states to avoid repeated lookups
        show_releases = self.show_releases.get()
        show_snapshots = self.show_snapshots.get()
        show_modded = self.show_modded.get()
        
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
                if not show_modded: continue
            else:
                if is_snapshot:
                    if not show_snapshots: continue
                else:
                    # Release
                    if not show_releases: continue

            self.create_installation_item(self.inst_list_frame, idx, inst)

        if callback:
            self.root.after(100, callback)

    def get_icon_image(self, icon_identifier, size=(40, 40)):
        # icon_identifier can be a path "icons/grass.png" or just "grass" or an emoji
        if not icon_identifier: return None
        
        # Check if it's a known image file
        if str(icon_identifier).endswith(".png"):
            key = (icon_identifier, size)
            # Check cache first
            if key in self.icon_cache: 
                # Verify the cached image is still valid
                try:
                    if self.icon_cache[key].width() > 0:
                        return self.icon_cache[key]
                    else:
                        # Invalid cache entry, remove it
                        del self.icon_cache[key]
                except:
                    # Invalid cache entry, remove it
                    del self.icon_cache[key]
                
            try:
                # Try finding it
                path = resource_path(icon_identifier)
                if os.path.exists(path):
                    img = Image.open(path).convert("RGBA")
                    # For perfectly sharp pixel art scaling, convert back after mode change isn't strictly necessary, RGBA resizes fine
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
        play_btn = self._make_btn(actions, "Play", style="primary", bold=True, font_size=9,
                                  command=lambda i=idx: self.launch_installation(i))
        play_btn.pack(side="left", padx=5)
                 
        # Folder
        folder_btn = self._make_btn(actions, "📁", style="icon",
                                    command=lambda i=idx: self.open_installation_folder(i))
        folder_btn.pack(side="left", padx=5)
                 
        # Edit/Menu
        menu_btn = self._make_btn(actions, "⋮", style="icon", font_size=10, width=3)
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
                self.current_installation_index = current
            self.select_installation(current)
        else:
            # No installations - show placeholder
            if hasattr(self, 'inst_name_lbl'):
                self.inst_name_lbl.config(text="No Installations")
            if hasattr(self, 'inst_ver_lbl'):
                self.inst_ver_lbl.config(text="")
            if hasattr(self, 'inst_selector_icon'):
                self.inst_selector_icon.config(image="", text="?", font=("Segoe UI", 12), fg="white", width=4, height=2)

        self._refresh_quick_join_installation_values()

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
        if not self.installations: 
            print("No installations to show")
            return
        
        # Prevent duplication - properly check and destroy existing menu
        if hasattr(self, '_selector_menu') and self._selector_menu:
            try:
                if self._selector_menu.winfo_exists():
                    print("Closing existing selector menu")
                    self._selector_menu.destroy()
                    self._selector_menu = None
                    return
            except:
                self._selector_menu = None

        print("Opening installation selector menu")
        menu = tk.Toplevel(self.root)
        self._selector_menu = menu
        menu.wm_overrideredirect(True)
        menu.config(bg=COLORS['card_bg'])
        menu.transient(self.root)
        menu.attributes('-topmost', True)
        
        # Border Frame
        menu_frame = tk.Frame(menu, bg=COLORS['card_bg'], highlightbackground="#454545", highlightthickness=1)
        menu_frame.pack(fill="both", expand=True)

        w = max(self.inst_selector_frame.winfo_width(), 300) # Enforce min width for longer names
        item_h = 55
        count = len(self.installations)
        h = min(count * item_h, 400) 
        
        x = self.inst_selector_frame.winfo_rootx()
        target_y = self.inst_selector_frame.winfo_rooty() - h - 5
        
        # Screen bounds check
        screen_h = self.root.winfo_screenheight()
        if target_y < 0 or target_y + h > screen_h: 
            target_y = self.inst_selector_frame.winfo_rooty() + self.inst_selector_frame.winfo_height() + 5
            # If still off-screen, position above
            if target_y + h > screen_h:
                target_y = self.inst_selector_frame.winfo_rooty() - h - 5
            
        menu.geometry(f"{w}x{h}+{x}+{target_y}")
        
        # Determine animation direction
        _selector_direction = "up" if target_y < self.inst_selector_frame.winfo_rooty() else "down"
        _selector_target_h = h
        
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
        
        # Smooth mousewheel
        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
        
        # Close on click outside (Lose Focus) or Escape
        def on_focus_out(event):
            # Check if focus moved to scrollbar or inner element
            try:
                focused = menu.focus_get()
                if focused and (str(focused).startswith(str(menu)) or focused == menu):
                    return
            except:
                pass
            print("Installation menu lost focus, closing")
            self.root.after(150, lambda: menu.destroy() if menu.winfo_exists() else None)
        
        def close_menu():
            if menu.winfo_exists():
                print("Closing installation menu")
                menu.destroy()
            
        menu.bind("<FocusOut>", on_focus_out)
        menu.bind("<Escape>", lambda e: close_menu())
        
        # Ensure menu is visible and focused with slide animation
        menu.update_idletasks()
        menu.deiconify()
        menu.lift()
        menu.focus_force()
        self._animate_menu_open(menu, _selector_target_h, direction=_selector_direction,
                                pos_x=x, pos_y=target_y, pos_w=w)

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
        
        self._bind_smooth_scroll(canvas, scroll_frame)

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
        win.geometry("700x650")
        win.configure(bg="#1e1e1e")
        if os.name != "nt":
            win.transient(self.root)
        win.resizable(True, True) # Allow resizing to help fit content
        if os.name != "nt":
            win.grab_set()
        
        # Center on parent
        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width()//2) - 350
        y = self.root.winfo_y() + (self.root.winfo_height()//2) - 325
        win.geometry(f"+{x}+{y}")
        
        # Ensure visibility
        win.deiconify()
        win.lift()
        win.geometry(f"+{x}+{y}")
        win_root = self._apply_custom_toplevel_chrome(win, title)
        
        # Pre-load data if editing
        existing_data = {}
        if edit_mode and index is not None and 0 <= index < len(self.installations):
            existing_data = self.installations[index]

        # --- Header ---
        header = tk.Frame(win_root, bg="#1e1e1e")
        header.pack(fill="x", padx=25, pady=(25, 20))
        tk.Label(header, text=title, font=("Segoe UI", 16, "bold"), 
                bg="#1e1e1e", fg="white", anchor="w").pack(fill="x")

        # --- Content Area (Icon + Fields) ---
        content = tk.Frame(win_root, bg="#1e1e1e")
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
             sel_win.geometry("480x550")
             sel_win.configure(bg="#2d2d2d")
             sel_win.transient(win)
             # Don't use grab_set to allow parent window interaction
             sel_win.resizable(False, False)
             
             # Center on parent
             sel_win.update_idletasks()
             x = win.winfo_x() + (win.winfo_width()//2) - 240
             y = win.winfo_y() + (win.winfo_height()//2) - 275
             sel_win.geometry(f"+{x}+{y}")
             
             # Ensure visibility
             sel_win.deiconify()
             sel_win.lift()
             sel_root = self._apply_custom_toplevel_chrome(sel_win, "Select Icon")

             tk.Label(sel_root, text="Select Block", font=("Segoe UI", 12, "bold"), bg="#2d2d2d", fg="white").pack(pady=(15,10))
             

             # Scrollable Frame for Icons
             container = tk.Frame(sel_root, bg="#2d2d2d")
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
             
             # Bind scrolling to the window so it works when hovering anywhere in the modal
             self._bind_wheel_events(sel_win, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
             
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
        java_row = tk.Frame(opts_container, bg="#1e1e1e")
        java_row.pack(fill="x")
        java_entry = tk.Entry(java_row, bg=input_bg_color, fg=input_fg_color, relief="flat", font=("Segoe UI", 10))
        java_entry.pack(side="left", fill="x", expand=True, ipady=6)
        existing_java = str(existing_data.get("java_executable", "") or "")
        if existing_java:
            java_entry.insert(0, existing_java)

        def browse_java_executable():
            current_value = java_entry.get().strip()
            initial_dir = None
            if current_value:
                initial_dir = current_value if os.path.isdir(current_value) else os.path.dirname(current_value)
            elif os.path.isdir(self.minecraft_dir):
                initial_dir = self.minecraft_dir

            selected = filedialog.askopenfilename(
                parent=win,
                title="Select Java Executable",
                initialdir=initial_dir or None,
                filetypes=[("All Files", "*")],
            )
            if selected:
                java_entry.delete(0, tk.END)
                java_entry.insert(0, selected)

        self._make_btn(
            java_row,
            "Browse...",
            style="secondary",
            font_size=9,
            command=browse_java_executable,
        ).pack(side="left", padx=(8, 0))

        tk.Label(
            opts_container,
            text="Leave blank to use the bundled/runtime Java.",
            bg="#1e1e1e",
            fg="#7A7A7A",
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

        # Resolution
        create_label("RESOLUTION").pack(in_=opts_container, fill="x", pady=(15,5))
        res_frame = tk.Frame(opts_container, bg="#1e1e1e")
        res_frame.pack(fill="x")
        
        res_w = tk.Entry(res_frame, bg=input_bg_color, fg=input_fg_color, width=10, relief="flat", font=("Segoe UI", 10))
        res_w.pack(side="left", ipady=6)
        existing_res_w = existing_data.get("resolution_width")
        res_w.insert(0, str(existing_res_w) if existing_res_w else "Auto")
        
        tk.Label(res_frame, text=" x ", bg="#1e1e1e", fg="white").pack(side="left")
        
        res_h = tk.Entry(res_frame, bg=input_bg_color, fg=input_fg_color, width=10, relief="flat", font=("Segoe UI", 10))
        res_h.pack(side="left", ipady=6)
        existing_res_h = existing_data.get("resolution_height")
        res_h.insert(0, str(existing_res_h) if existing_res_h else "Auto")

        if existing_java or existing_res_w or existing_res_h:
            toggle_opts()


        # -- Logic --
        self.cached_loader_versions = [] 

        def check_installed(version_id, loader_type):
            try:
                installed_list = [v['id'] for v in minecraft_launcher_lib.utils.get_installed_versions(self.minecraft_dir)]
                if loader_type == "Vanilla":
                    return version_id in installed_list
                elif loader_type == "Fabric":
                    return any("fabric" in iv.lower() and version_id in iv.split('-') for iv in installed_list)
                elif loader_type == "Forge":
                    return any("forge" in iv.lower() and version_id in iv.split('-') for iv in installed_list)
                else: 
                     # For other clients, check exact match + client name usually
                     # Broad check for anything that looks like a version match in installed list
                     return any(version_id in iv.split('-') or version_id == iv for iv in installed_list)
            except:
                pass
            return False

        def fetch_versions_thread(loader_type):
            try:
                raw_versions = []
                if loader_type == "Vanilla":
                    cached = getattr(self, "cached_vanilla_versions", None)
                    if cached:
                        raw_versions = list(cached)
                    else:
                        vlist = minecraft_launcher_lib.utils.get_version_list()
                        raw_versions = [
                            {'id': v['id'], 'type': v.get('type', 'release')}
                            for v in vlist if isinstance(v, dict) and v.get('id')
                        ]
                        self.cached_vanilla_versions = list(raw_versions)
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
             try:
                 java_executable = self._normalize_java_executable_input(java_entry.get())
                 resolution_width = self._normalize_installation_resolution_value(res_w.get(), "width")
                 resolution_height = self._normalize_installation_resolution_value(res_h.get(), "height")
             except ValueError as e:
                 custom_showerror("Invalid Installation Settings", str(e), parent=win)
                 return

             if bool(resolution_width) != bool(resolution_height):
                 custom_showerror(
                     "Invalid Resolution",
                     "Set both width and height, or leave both as Auto.",
                     parent=win,
                 )
                 return
             
             new_profile = {
                 "id": existing_data.get("id", str(uuid.uuid4())),
                 "name": name,
                 "version": version_id,
                 "loader": loader,
                 "icon": icon_val,
                 "java_executable": java_executable,
                 "resolution_width": int(resolution_width) if resolution_width else None,
                 "resolution_height": int(resolution_height) if resolution_height else None,
                 "last_played": existing_data.get("last_played", "Never"),
                 "created": existing_data.get("created", datetime.now().isoformat())
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
        btn_row = tk.Frame(win_root, bg="#1e1e1e")
        btn_row.pack(side="bottom", fill="x", padx=25, pady=25)
        
        btn_text = "Save" if edit_mode else "Create"
        # Create/Save (Green)
        save_btn = self._make_btn(btn_row, btn_text, style="primary", font_size=10, bold=True,
                                  command=create_action)
        save_btn.pack(side="right", padx=(10, 0))
                 
        # Cancel (Text only typically, but we keep button style for consistency)
        self._make_btn(btn_row, "Cancel", style="text", font_size=10,
                      command=win.destroy).pack(side="right")
        
        # --- Onboarding Tour Logic ---
        # On first installation, no coach marks needed — the wizard already guided the user.

    def open_installation_menu(self, idx, btn_widget):
        # Toggle: close if already open
        if hasattr(self, 'installation_menu') and self.installation_menu:
            try:
                if self.installation_menu.winfo_exists():
                    self.installation_menu.destroy()
            except:
                pass
            self.installation_menu = None
            return
        
        # Create a popup menu (Edit, Delete)
        menu = tk.Toplevel(self.root)
        menu.wm_overrideredirect(True)
        menu.config(bg=COLORS['card_bg'])
        menu.transient(self.root)
        menu.attributes('-topmost', True)
        
        self.installation_menu = menu
        
        # Position with screen bounds check
        try:
             x = btn_widget.winfo_rootx()
             y = btn_widget.winfo_rooty() + btn_widget.winfo_height()
             screen_h = self.root.winfo_screenheight()
             # Check if menu would go off bottom of screen
             if y + 80 > screen_h:
                 y = btn_widget.winfo_rooty() - 80
             menu.geometry(f"120x80+{x-80}+{y}")
             menu.update_idletasks()
             menu.deiconify()
             menu.lift()
             self._animate_menu_open(menu, 80, direction="down")
        except:
             menu.geometry("120x80")
             menu.deiconify()
             menu.lift()
             self._animate_menu_open(menu, 80, direction="down")
        
        def close_menu():
            if menu.winfo_exists():
                menu.destroy()
             

        # Edit
        def do_edit():
            close_menu()
            self.edit_installation(idx)
            
        edit_btn = tk.Label(menu, text="Edit", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_primary'], anchor="w", padx=10, pady=5)
        edit_btn.pack(fill="x")
        edit_btn.bind("<Button-1>", lambda e: do_edit())
        edit_btn.bind("<Enter>", lambda e: edit_btn.config(bg="#454545"))
        edit_btn.bind("<Leave>", lambda e: edit_btn.config(bg=COLORS['card_bg']))

        # Delete
        def do_delete():
            close_menu()
            if custom_askyesno("Delete", "Are you sure you want to delete this installation?", parent=self.root):
                deleted_inst = self.installations.pop(idx)
                deleted_id = deleted_inst.get("id")
                
                # Update current index if necessary
                if self.current_installation_index >= len(self.installations):
                    self.current_installation_index = max(0, len(self.installations) - 1)
                    
                # Check if any modpack was linked to this installation
                for pack in self.modpacks:
                    if pack.get("linked_installation_id") == deleted_id:
                        pack["linked_installation_id"] = None
                
                self.save_modpacks()
                self.save_config()
                self.refresh_installations_list()
                self.update_installation_dropdown()
                self.refresh_modpacks_list()  # Refresh to show updated link status
            
        del_btn = tk.Label(menu, text="Delete", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['error_red'], anchor="w", padx=10, pady=5)
        del_btn.pack(fill="x")
        del_btn.bind("<Button-1>", lambda e: do_delete())
        del_btn.bind("<Enter>", lambda e: del_btn.config(bg="#454545"))
        del_btn.bind("<Leave>", lambda e: del_btn.config(bg=COLORS['card_bg']))

        # Close on click outside or Escape
        menu.bind("<FocusOut>", lambda e: self.root.after(100, close_menu))
        menu.bind("<Escape>", lambda e: close_menu())
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
             b = self._make_btn(btn_frame, v, style="secondary", font_size=10, bold=True,
                               command=lambda x=v: switch_view(x))
             b.config(padx=20, pady=5)
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
        
        upload_btn = self._make_btn(btn_grid, "Upload Skin File", style="secondary", font_size=10,
                                     command=self.select_skin)
        upload_btn.config(bg=COLORS['accent_blue'], activebackground="#2E86C1", pady=8, width=20)
        upload_btn.bind("<Enter>", lambda e: upload_btn.config(bg="#2E86C1"))
        upload_btn.bind("<Leave>", lambda e: upload_btn.config(bg=COLORS['accent_blue']))
        upload_btn.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self._make_btn(btn_grid, "Refresh", style="secondary", font_size=10,
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
        self._bind_wheel_events(self.history_canvas, lambda e, c=self.history_canvas: self._smooth_scroll(c, e), f"direct_{id(self.history_canvas)}")

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

        # Force re-render of skin preview
        self.render_preview()
        self.save_config(sync_ui=False)  # Save after rendering to avoid redundant updates

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
        btn = self._make_btn(self.wp_grid_frame, "+ Add Wallpaper", style="secondary",
                             font_size=12, command=self.add_custom_wallpaper)
        btn.config(width=20, height=5)
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

        # Smooth mousewheel
        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
        self._bind_smooth_scroll(canvas, self.wp_grid_frame)

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
            self.save_config(sync_ui=False)  # Optimize: don't sync UI fields
            
            # Always refresh UI if in Locker -> Wallpapers to show "SELECTED" indicator
            if hasattr(self, 'locker_view') and self.locker_view.get() == "Wallpapers":
                # Use after to ensure UI is ready
                self.root.after(100, self.refresh_locker_view)
                
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
        
        # Update model var before rendering
        if hasattr(self, 'skin_model_var'):
            self.skin_model_var.set(model)
            
        # Render preview with updated model
        self.render_preview()
        self.update_skin_indicator()
        
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
        self.save_config(sync_ui=False)  # Optimize: don't sync UI fields
        
        # Only refresh if currently viewing skin history
        if hasattr(self, 'history_frame') and self.history_frame.winfo_exists():
            self.render_skin_history()

    def toggle_profile_menu(self):
        if hasattr(self, 'profile_menu') and self.profile_menu:
            try:
                if self.profile_menu.winfo_exists():
                    print("Closing existing profile menu")
                    self.profile_menu.destroy()
                    self.profile_menu = None
                    return
            except:
                self.profile_menu = None

        print("Opening profile menu")
        menu = tk.Toplevel(self.root)
        menu.overrideredirect(True)
        menu.config(bg=COLORS['card_bg'])
        menu.transient(self.root)
        menu.attributes('-topmost', True)
        self.profile_menu = menu

        # Position with screen bounds check
        try:
            x = self.sidebar.winfo_rootx() + self.sidebar.winfo_width()
            y = self.profile_frame.winfo_rooty()
            
            # Check screen bounds
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            
            # Adjust if menu would go off-screen
            if x + 250 > screen_w:
                x = self.sidebar.winfo_rootx() - 250
            if y + 300 > screen_h:
                y = screen_h - 300 - 10
                
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
        
        # Smooth mousewheel
        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
        self._bind_smooth_scroll(canvas, list_frame)
        
        # Update Scrollbar visibility
        def update_scroll_state(e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            bbox = canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1]) > canvas.winfo_height():
                scrollbar.pack(side="right", fill="y")
            else:
                scrollbar.pack_forget()
            self._bind_smooth_scroll(canvas, list_frame)

        list_frame.bind("<Configure>", update_scroll_state)

        if not self.profiles:
             tk.Label(list_frame, text="No profiles", bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(pady=10)
        else:
            for idx, p in enumerate(self.profiles):
                self.create_profile_item(list_frame, idx, p)

        add_acct_btn = self._make_btn(footer, "+ Add Account", style="text", font_size=9,
                                       command=self.open_add_account_modal)
        add_acct_btn.config(bg=COLORS['bottom_bar_bg'], fg=COLORS['text_primary'])
        add_acct_btn.bind("<Enter>", lambda e: add_acct_btn.config(fg="white"))
        add_acct_btn.bind("<Leave>", lambda e: add_acct_btn.config(fg=COLORS['text_primary']))
        add_acct_btn.pack(side="left", padx=10, fill="y")

        # Ensure menu is visible and focused with slide animation
        menu.update_idletasks()
        menu.deiconify()
        menu.lift()
        menu.focus_set()
        self._animate_menu_open(menu, 300, direction="down")
        menu.bind("<FocusOut>", lambda e: self._close_menu_delayed(menu))

    def _close_menu_delayed(self, menu):
        # Small delay to allow button clicks inside
        try:
            if menu and menu.winfo_exists():
                # Check if focus is still in the menu tree
                focused = self.root.focus_displayof()
                if focused and str(focused).startswith(str(menu)):
                    return  # Don't close if focus is still inside
                menu.destroy()
        except:
            pass

    def delete_profile(self, idx):
        if not self.profiles or idx < 0 or idx >= len(self.profiles): return
        
        p_name = self.profiles[idx].get("name", "Account")
        display_name = self._get_streamer_safe_name(p_name)
        if custom_askyesno("Remove Account", f"Are you sure you want to remove account '{display_name}'?"):
            del self.profiles[idx]
            
            # Reset index if needed
            if self.current_profile_index >= len(self.profiles):
                self.current_profile_index = max(0, len(self.profiles) - 1)
            
            if not self.profiles:
                self.create_default_profile()
            
            # Update UI first, then save to avoid redundant syncs
            self.update_active_profile()
            self.save_config(sync_ui=False)
            
            # Close menu to refresh
            if hasattr(self, 'profile_menu') and self.profile_menu:
                try:
                    if self.profile_menu.winfo_exists():
                        self.profile_menu.destroy()
                except:
                    pass

    def create_profile_item(self, parent, idx, profile):
        is_active = (idx == self.current_profile_index)
        bg = "#454545" if is_active else COLORS['card_bg']
        
        frame = tk.Frame(parent, bg=bg, pady=8, padx=10, cursor="hand2")
        frame.pack(fill="x", pady=1)
        
        head = self.get_head_from_skin(profile.get("skin_path"), size=24)
        lbl_icon = tk.Label(frame, image=head, bg=bg) # type: ignore
        lbl_icon.image = head # type: ignore # keep ref
        lbl_icon.pack(side="left", padx=(0, 10))
        
        tk.Label(frame, text=self._get_streamer_safe_name(profile.get("name", "Unknown")), font=("Segoe UI", 10, "bold"),
                bg=bg, fg=COLORS['text_primary']).pack(side="left")
        
        # Delete Button
        del_btn = self._make_btn(frame, "-", style="danger", font_size=12, bold=True, icon=True,
                                 command=lambda: self.delete_profile(idx))
        del_btn.config(bg=bg, fg="#ff6b6b", activebackground=bg, activeforeground="#ff4444")
        del_btn.bind("<Enter>", lambda e: del_btn.config(fg="#ff4444"))
        del_btn.bind("<Leave>", lambda e: del_btn.config(fg="#ff6b6b"))
        
        # Only show delete if strictly more than 1 profile? Or allow deleting the last one (which resets to default)?
        # User said "right of every account".
        # Standard launcher behavior typically allows removing any added account.
        del_btn.pack(side="right", padx=(5, 0))

        tk.Label(frame, text=profile.get("type", "offline").title(), font=("Segoe UI", 8),
                bg=bg, fg=COLORS['text_secondary']).pack(side="right")
        
        def on_click(e):
            old_index = self.current_profile_index
            self.current_profile_index = idx
            
            # Only update if index actually changed
            if old_index != idx:
                self.update_active_profile()
                # Update installation dropdown in case settings changed
                if hasattr(self, 'update_installation_dropdown'):
                    self.update_installation_dropdown()
                    
            if hasattr(self, 'profile_menu') and self.profile_menu:
                try:
                    if self.profile_menu.winfo_exists():
                        self.profile_menu.destroy()
                except:
                    pass
            
        frame.bind("<Button-1>", on_click)
        for child in frame.winfo_children():
            if child != del_btn:
                child.bind("<Button-1>", on_click)

    def open_add_account_modal(self):
        print("Opening add account modal")
        if hasattr(self, 'profile_menu') and self.profile_menu:
            try:
                if self.profile_menu.winfo_exists():
                    self.profile_menu.destroy()
                    self.profile_menu = None
            except:
                pass
        
        win = tk.Toplevel(self.root)
        self._register_dialog_window(win)
        win.title("Add Account")
        win.geometry("450x350")
        win.config(bg=COLORS['main_bg'])
        if os.name != "nt":
            win.transient(self.root)
        win.resizable(False, False)
        if os.name != "nt":
            win.grab_set()
        
        # Center on parent
        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width()//2) - 225
        y = self.root.winfo_y() + (self.root.winfo_height()//2) - 175
        win.geometry(f"+{x}+{y}")
        
        # Ensure visibility
        win.deiconify()
        win.lift()
        win.geometry(f"+{x}+{y}")
        win_root = self._apply_custom_toplevel_chrome(win, "Add Account")
        self._schedule_dialog_raise()

        tk.Label(win_root, text="Add a new account", font=("Segoe UI", 16, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(30, 20))
        
        self._make_btn(win_root, "Microsoft Account", style="primary", font_size=11,
                      width=25, command=lambda: self.show_microsoft_login(win)).pack(pady=5, ipady=4)

        btn_ely = self._make_btn(win_root, "Ely.by Account", style="secondary", font_size=11,
                                 width=25, command=lambda: self.show_elyby_login(win))
        btn_ely.config(bg="#3498DB", activebackground="#2E86C1")
        btn_ely.bind("<Enter>", lambda e: btn_ely.config(bg="#2E86C1"))
        btn_ely.bind("<Leave>", lambda e: btn_ely.config(bg="#3498DB"))
        btn_ely.pack(pady=5, ipady=4)

        self._make_btn(win_root, "Offline Account", style="secondary", font_size=11,
                      width=25, command=lambda: self.show_offline_login(win)).pack(pady=5, ipady=4)

    def show_microsoft_login(self, parent):
        self._register_dialog_window(parent)
        try:
            parent._nlc_force_above_launcher = True  # type: ignore[attr-defined]
        except Exception:
            pass
        parent.title("Microsoft Login - Device Flow")
        self._apply_custom_toplevel_chrome(parent, "Microsoft Login")
        content_root = self._clear_toplevel_content(parent)
        parent.geometry("550x500")
        
        # Re-center after changing size
        parent.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width()//2) - 275
        y = self.root.winfo_y() + (self.root.winfo_height()//2) - 250
        parent.geometry(f"+{x}+{y}")
        self._schedule_dialog_raise()
        
        tk.Label(content_root, text="Microsoft Login", font=("Segoe UI", 16, "bold"), 
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(20, 10))
        
        # Status Label
        status_lbl = tk.Label(content_root, text="Initializing...", font=("Segoe UI", 10), 
                             bg=COLORS['main_bg'], fg=COLORS['text_secondary'], wraplength=450)
        status_lbl.pack(pady=10)
        
        # Code Display
        code_lbl = tk.Label(content_root, text="", font=("Segoe UI", 24, "bold"), 
                           bg=COLORS['main_bg'], fg=COLORS['success_green'])
        code_lbl.pack(pady=10)
        
        # URL Display
        url_lbl = tk.Label(content_root, text="", font=("Segoe UI", 11, "underline"), 
                          bg=COLORS['main_bg'], fg="#3498DB", cursor="hand2")
        url_lbl.pack(pady=5)
        
        # Copy Button
        copy_btn = self._make_btn(content_root, "Copy Code", style="secondary", font_size=10)
        copy_btn.config(state="disabled")
        copy_btn.pack(pady=10)
        
        self._make_btn(content_root, "Cancel", style="text", font_size=10,
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
        parent.title("Ely.by Login")
        self._apply_custom_toplevel_chrome(parent, "Ely.by Login")
        content_root = self._clear_toplevel_content(parent)
        self._schedule_dialog_raise()
        
        tk.Label(content_root, text="Ely.by Login", font=("Segoe UI", 16, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(20, 10))

        frame = tk.Frame(content_root, bg=COLORS['main_bg'])
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

        self._make_btn(content_root, "Login", style="primary", font_size=11, bold=True,
                      width=25, command=do_login).pack(pady=10, ipady=4)

    def show_offline_login(self, parent):
        parent.title("Offline Account")
        self._apply_custom_toplevel_chrome(parent, "Offline Account")
        content_root = self._clear_toplevel_content(parent)
        self._schedule_dialog_raise()
        
        tk.Label(content_root, text="Offline Account", font=("Segoe UI", 16, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(30, 10))
                
        tk.Label(content_root, text="Username", bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w", padx=60)
        entry = tk.Entry(content_root, font=("Segoe UI", 11), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", insertbackground="white")
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
        
        self._make_btn(content_root, "Add Account", style="primary", font_size=11, bold=True,
                      width=20, command=save).pack(pady=10, ipady=4)

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
                 
        create_mp_btn = self._make_btn(top_bar, "+ Create New Modpack", style="primary",
                                         font_size=10, bold=True, command=self.show_create_modpack_dialog)
        create_mp_btn.pack(side="right")
        self._make_btn(
            top_bar,
            "Import CurseForge Pack",
            style="secondary",
            font_size=10,
            command=self.show_import_curseforge_dialog,
        ).pack(side="right", padx=(0, 8))

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
        
        # Smooth mousewheel
        self._bind_wheel_events(self.mp_canvas, lambda e, c=self.mp_canvas: self._smooth_scroll(c, e), f"direct_{id(self.mp_canvas)}")
        container.bind("<Enter>", lambda e: self._bind_smooth_scroll(self.mp_canvas, self.mp_scrollable_frame))
        self.mp_canvas.bind("<Enter>", lambda e: self._bind_smooth_scroll(self.mp_canvas, self.mp_scrollable_frame))
        self.mp_scrollable_frame.bind("<Enter>", lambda e: self._bind_smooth_scroll(self.mp_canvas, self.mp_scrollable_frame))
        
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
        self._bind_smooth_scroll(self.mp_canvas, self.mp_scrollable_frame)
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

        selected_pack_version = pack.get("version_name")
        if selected_pack_version:
            tk.Label(
                info,
                text=f"Pack Release: {selected_pack_version}",
                font=("Segoe UI", 9),
                fg=COLORS['text_secondary'],
                bg=COLORS['card_bg'],
                anchor="w",
            ).pack(fill="x")

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

        # Link
        self._make_btn(btns, "Link", style="secondary", font_size=10,
                      command=lambda: self.show_link_modpack_dialog(pack)).pack(side="left", padx=2)

        # Show Mods
        sm_btn = self._make_btn(btns, "Show Mods", style="secondary", font_size=10,
                                command=lambda: self.show_modpack_contents_dialog(pack))
        sm_btn.config(bg=COLORS['accent_blue'], activebackground="#2E86C1")
        sm_btn.bind("<Enter>", lambda e: sm_btn.config(bg="#2E86C1"))
        sm_btn.bind("<Leave>", lambda e: sm_btn.config(bg=COLORS['accent_blue']))
        sm_btn.pack(side="left", padx=2)

        # Browse (+)
        def browse_action():
            self.select_modpack_and_browse(pack)

        self._make_btn(btns, "+", style="primary", font_size=10, icon=True, width=3,
                      command=browse_action).pack(side="left", padx=2)

        # Menu (⋮) - Now on Right
        menu_btn = self._make_btn(btns, "⋮", style="icon", font_size=10, width=3)
        menu_btn.pack(side="left", padx=2)

        menu = tk.Menu(menu_btn, tearoff=0, bg=COLORS['card_bg'], fg="white")
        menu.add_command(label="Open Folder", command=lambda: os.startfile(self.get_modpack_dir(pack['id'])))
        menu.add_separator()
        menu.add_command(label="Delete Modpack", command=lambda: self.delete_modpack(pack))

        menu_btn.config(command=lambda: menu.post(menu_btn.winfo_rootx(), menu_btn.winfo_rooty() + menu_btn.winfo_height()))
        self._bind_smooth_scroll(self.mp_canvas, card)

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
        
        # Refresh both list and dropdown
        self.refresh_modpacks_list()
        self.update_active_modpack_dropdown()
        
        # Reset active pack selection if deleted pack was active
        if hasattr(self, 'active_modpack_var') and self.active_modpack_var.get() == pack['name']:
            self.active_modpack_var.set("None")

    def show_modpack_contents_dialog(self, pack):
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Mods in {pack['name']}")
        dialog.geometry("700x600")
        dialog.config(bg=COLORS['main_bg'])
        # This is a destructive-management surface; it must be modal on every
        # supported platform so actions cannot land in the launcher behind it.
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center on parent
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width()//2) - 350
        y = self.root.winfo_y() + (self.root.winfo_height()//2) - 300
        dialog.geometry(f"+{x}+{y}")
        
        # Ensure visibility
        dialog.deiconify()
        dialog.lift()
        dialog_root = self._apply_custom_toplevel_chrome(dialog, f"Mods in {pack['name']}")
        
        mods_dir = os.path.join(self.get_modpack_dir(pack['id']), "mods")
        if not os.path.exists(mods_dir): os.makedirs(mods_dir)
        
        # Header
        header = tk.Frame(dialog_root, bg=COLORS['sidebar_bg'], pady=15, padx=20)
        header.pack(fill="x")
        
        title_frame = tk.Frame(header, bg=COLORS['sidebar_bg'])
        title_frame.pack(fill="x")
        
        tk.Label(title_frame, text=pack['name'], font=("Segoe UI", 16, "bold"),
                 bg=COLORS['sidebar_bg'], fg=COLORS['text_primary']).pack(side="left")
        
        # Action buttons in header
        actions = tk.Frame(title_frame, bg=COLORS['sidebar_bg'])
        actions.pack(side="right")
        
        def open_folder():
            self._open_path(mods_dir)
        
        def refresh_list():
            render_mods()
        
        self._make_btn(actions, "📁 Open Folder", style="secondary", font_size=9,
                      command=open_folder).pack(side="left", padx=5)

        self._make_btn(actions, "🔄 Refresh", style="secondary", font_size=9,
                      command=refresh_list).pack(side="left")

        view_mode_var = tk.StringVar(value=getattr(self, "installed_mods_view_mode", "grid"))
        grid_btn = self._make_btn(actions, "Grid", style="secondary", font_size=9)
        grid_btn.pack(side="left", padx=(12, 5))
        list_btn = self._make_btn(actions, "List", style="secondary", font_size=9)
        list_btn.pack(side="left")
        
        # Search bar
        search_frame = tk.Frame(header, bg=COLORS['input_bg'], padx=10, pady=8)
        search_frame.pack(fill="x", pady=(10, 0))
        
        tk.Label(search_frame, text="🔍", bg=COLORS['input_bg'], 
                fg=COLORS['text_secondary']).pack(side="left")
        
        search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=search_var, 
                               font=("Segoe UI", 10), bg=COLORS['input_bg'],
                               fg=COLORS['text_primary'], relief="flat", 
                               insertbackground="white")
        search_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        # Scrollable content area
        content_frame = tk.Frame(dialog_root, bg=COLORS['main_bg'])
        content_frame.pack(fill="both", expand=True)
        
        canvas = tk.Canvas(content_frame, bg=COLORS['main_bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(content_frame, orient="vertical",
                                 command=canvas.yview, style="Launcher.Vertical.TScrollbar")
        scroll_frame = tk.Frame(canvas, bg=COLORS['main_bg'])
        canvas._nlc_scroll_enabled = True # type: ignore[attr-defined]
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Rendering every card in a single event-loop turn makes a large pack
        # look like the launcher has hung.  Keep enough state to cancel a
        # stale render (search, refresh, resize, or view change) and resume in
        # short batches instead.
        layout_state = {
            "cols": None,
            "render_after_id": None,
            "batch_after_id": None,
            "render_generation": 0,
            "file_metadata": {},
        }

        def compute_grid_columns():
            try:
                canvas.update_idletasks()
                available_w = max(360, canvas.winfo_width() - 36)
                return max(1, min(4, available_w // 235))
            except Exception:
                return 3

        def update_view_buttons():
            current = view_mode_var.get()
            if current == "grid":
                grid_btn.config(bg=COLORS.get('play_btn_green', '#2D8F36'), fg="white",
                                activebackground=COLORS.get('play_btn_green', '#2D8F36'))
                list_btn.config(bg="#404040", fg="#E0E0E0", activebackground="#525252")
            else:
                list_btn.config(bg=COLORS.get('play_btn_green', '#2D8F36'), fg="white",
                                activebackground=COLORS.get('play_btn_green', '#2D8F36'))
                grid_btn.config(bg="#404040", fg="#E0E0E0", activebackground="#525252")

        def set_view_mode(mode):
            if mode not in ("grid", "list"):
                return
            if getattr(self, "installed_mods_view_mode", "grid") == mode and view_mode_var.get() == mode:
                update_view_buttons()
                return
            self.installed_mods_view_mode = mode
            view_mode_var.set(mode)
            update_view_buttons()
            self.save_config(sync_ui=False)
            render_mods(reset_scroll=False)

        grid_btn.config(command=lambda: set_view_mode("grid"))
        list_btn.config(command=lambda: set_view_mode("list"))
        update_view_buttons()

        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
            if view_mode_var.get() != "grid":
                return
            new_cols = compute_grid_columns()
            if layout_state["cols"] == new_cols:
                return
            layout_state["cols"] = new_cols
            after_id = layout_state.get("render_after_id")
            if after_id is not None:
                try:
                    dialog.after_cancel(after_id)
                except Exception:
                    pass
            layout_state["render_after_id"] = dialog.after(70, lambda: render_mods(reset_scroll=False))

        canvas.bind("<Configure>", on_canvas_configure)
        content_frame.bind("<Enter>", lambda e: self._bind_smooth_scroll(canvas, scroll_frame))
        canvas.bind("<Enter>", lambda e: self._bind_smooth_scroll(canvas, scroll_frame))
        scroll_frame.bind("<Enter>", lambda e: self._bind_smooth_scroll(canvas, scroll_frame))
        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"modpack_contents_{id(canvas)}")

        def get_mod_display_data(filename):
            display_name = filename[:-4] if filename.endswith('.jar') else filename
            initial = filename[0].upper() if filename else "M"
            colors = ["#3498DB", "#E67E22", "#9B59B6", "#2ECC71", "#E74C3C", "#F39C12"]
            icon_color = colors[ord(initial) % len(colors)]
            size_str = ""
            try:
                size_bytes = layout_state["file_metadata"].get(filename, 0)
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                else:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            except Exception:
                pass
            return display_name, initial, icon_color, size_str

        def delete_mod(filename, display_name):
            if custom_askyesno("Delete Mod",
                              f"Are you sure you want to delete '{display_name}'?",
                              parent=dialog):
                try:
                    os.remove(os.path.join(mods_dir, filename))
                    rem_meta = next((m for m in pack.get('mods', []) if m.get('filename') == filename), None)
                    if rem_meta:
                        pack['mods'].remove(rem_meta)
                        self.save_modpacks()
                    render_mods(reset_scroll=False)
                except Exception as e:
                    custom_showerror("Error", f"Failed to delete mod: {e}", parent=dialog)

        def bind_hover_surfaces(card, surfaces, info_widgets, del_btn):
            def on_enter_card(_event):
                for surface in surfaces:
                    surface.config(bg="#3A3A3A")
                for widget in info_widgets:
                    widget.config(bg="#3A3A3A") # type: ignore[arg-type]

            def on_leave_card(event):
                if del_btn.winfo_containing(event.x_root, event.y_root) == del_btn:
                    return
                for surface in surfaces:
                    surface.config(bg=COLORS['card_bg'])
                for widget in info_widgets:
                    widget.config(bg=COLORS['card_bg']) # type: ignore[arg-type]

            for surface in surfaces:
                surface.bind("<Enter>", on_enter_card)
                surface.bind("<Leave>", on_leave_card)

        def create_remove_button(parent, command):
            del_btn = tk.Button(parent, text="Remove", font=("Segoe UI", 9, "bold"),
                               bg="#552222", fg="#F2B5B5", relief="flat", bd=0,
                               cursor="hand2", command=command)
            del_btn.bind("<Enter>", lambda _e: del_btn.config(bg=COLORS['error_red'], fg="white"))
            del_btn.bind("<Leave>", lambda _e: del_btn.config(bg="#552222", fg="#F2B5B5"))
            return del_btn

        def create_mod_grid_card(parent, filename, row, col):
            display_name, initial, icon_color, size_str = get_mod_display_data(filename)
            card = tk.Frame(parent, bg=COLORS['card_bg'], padx=12, pady=10, width=220, height=128)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            card.grid_propagate(False)

            left = tk.Frame(card, bg=COLORS['card_bg'])
            left.pack(fill="both", expand=True)

            icon = tk.Label(left, text=initial, font=("Segoe UI", 14, "bold"),
                           bg=icon_color, fg="white", width=2, height=1)
            icon.pack(anchor="w")

            info = tk.Frame(left, bg=COLORS['card_bg'])
            info.pack(fill="both", expand=True, pady=(8, 0))

            name_lbl = tk.Label(info, text=display_name, font=("Segoe UI", 11, "bold"),
                               bg=COLORS['card_bg'], fg=COLORS['text_primary'], anchor="w",
                               wraplength=190, justify="left")
            name_lbl.pack(fill="x")

            size_lbl = None
            if size_str:
                size_lbl = tk.Label(info, text=f"Size: {size_str}", font=("Segoe UI", 9),
                                   bg=COLORS['card_bg'], fg=COLORS['text_secondary'], anchor="w")
                size_lbl.pack(fill="x", pady=(4, 0))

            actions_row = tk.Frame(card, bg=COLORS['card_bg'])
            actions_row.pack(fill="x", pady=(6, 0))
            del_btn = create_remove_button(actions_row, lambda f=filename, d=display_name: delete_mod(f, d))
            del_btn.pack(side="right")

            info_widgets = [name_lbl]
            if size_lbl is not None:
                info_widgets.append(size_lbl)
            bind_hover_surfaces(card, [card, left, info, actions_row], info_widgets, del_btn)
            self._bind_smooth_scroll(canvas, card)

        def create_mod_list_row(parent, filename):
            display_name, initial, icon_color, size_str = get_mod_display_data(filename)
            row = tk.Frame(parent, bg=COLORS['card_bg'], padx=14, pady=12)
            row.pack(fill="x", padx=12, pady=6)

            left = tk.Frame(row, bg=COLORS['card_bg'])
            left.pack(side="left", fill="both", expand=True)

            icon = tk.Label(left, text=initial, font=("Segoe UI", 14, "bold"),
                           bg=icon_color, fg="white", width=2, height=1)
            icon.pack(side="left", padx=(0, 12))

            info = tk.Frame(left, bg=COLORS['card_bg'])
            info.pack(side="left", fill="both", expand=True)

            name_lbl = tk.Label(info, text=display_name, font=("Segoe UI", 11, "bold"),
                               bg=COLORS['card_bg'], fg=COLORS['text_primary'], anchor="w")
            name_lbl.pack(fill="x")

            meta_text = filename if not size_str else f"{filename}  •  {size_str}"
            meta_lbl = tk.Label(info, text=meta_text, font=("Segoe UI", 9),
                               bg=COLORS['card_bg'], fg=COLORS['text_secondary'], anchor="w")
            meta_lbl.pack(fill="x", pady=(3, 0))

            actions_row = tk.Frame(row, bg=COLORS['card_bg'])
            actions_row.pack(side="right", padx=(10, 0))
            del_btn = create_remove_button(actions_row, lambda f=filename, d=display_name: delete_mod(f, d))
            del_btn.pack()

            bind_hover_surfaces(row, [row, left, info, actions_row], [name_lbl, meta_lbl], del_btn)
            self._bind_smooth_scroll(canvas, row)

        def render_mods(reset_scroll=True):
            after_id = layout_state.get("render_after_id")
            if after_id is not None:
                try:
                    dialog.after_cancel(after_id)
                except Exception:
                    pass
            layout_state["render_after_id"] = None

            batch_after_id = layout_state.get("batch_after_id")
            if batch_after_id is not None:
                try:
                    dialog.after_cancel(batch_after_id)
                except Exception:
                    pass
            layout_state["batch_after_id"] = None
            layout_state["render_generation"] += 1
            render_generation = layout_state["render_generation"]

            current_top = canvas.yview()[0] if not reset_scroll else 0.0

            for widget in scroll_frame.winfo_children():
                widget.destroy()

            # One scandir/stat pass per redraw keeps filtering responsive even
            # for large modpacks.  The previous implementation re-opened each
            # file again while building every card.
            file_metadata = {}
            with os.scandir(mods_dir) as entries:
                files = []
                for entry in entries:
                    if not entry.is_file() or not entry.name.lower().endswith(".jar"):
                        continue
                    try:
                        file_metadata[entry.name] = entry.stat().st_size
                    except OSError:
                        file_metadata[entry.name] = 0
                    files.append(entry.name)
            layout_state["file_metadata"] = file_metadata
            files.sort(key=str.lower)
            search_term = search_var.get().strip().lower()
            if search_term:
                files = [f for f in files if search_term in f.lower()]

            count_label = tk.Label(
                scroll_frame,
                text=f"{len(files)} mod{'s' if len(files) != 1 else ''} installed",
                font=("Segoe UI", 10),
                bg=COLORS['main_bg'],
                fg=COLORS['text_secondary'],
            )
            count_label.pack(anchor="w", padx=20, pady=(15, 10))

            if not files:
                empty_frame = tk.Frame(scroll_frame, bg=COLORS['main_bg'])
                empty_frame.pack(fill="both", expand=True, pady=50)

                tk.Label(empty_frame, text="📦", font=("Segoe UI", 48),
                        bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack()

                msg = "No mods found" if not search_term else "No mods match your search"
                tk.Label(empty_frame, text=msg, font=("Segoe UI", 12),
                        bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(pady=10)

                if not search_term:
                    tk.Label(empty_frame, text="Use the + button to add mods",
                            font=("Segoe UI", 10), bg=COLORS['main_bg'],
                            fg=COLORS['text_secondary']).pack()
            elif view_mode_var.get() == "list":
                layout_state["cols"] = None
                list_wrap = tk.Frame(scroll_frame, bg=COLORS['main_bg'])
                list_wrap.pack(fill="x", padx=8, pady=(0, 12))
                render_parent = list_wrap
                render_as_grid = False
            else:
                cols = compute_grid_columns()
                layout_state["cols"] = cols
                grid_wrap = tk.Frame(scroll_frame, bg=COLORS['main_bg'])
                grid_wrap.pack(fill="x", padx=16, pady=(0, 12))
                for c in range(cols):
                    grid_wrap.grid_columnconfigure(c, weight=1, uniform="modgrid")
                render_parent = grid_wrap
                render_as_grid = True

            if files:
                progress_label = tk.Label(
                    scroll_frame,
                    text=f"Loading mods… 0 / {len(files)}",
                    font=("Segoe UI", 9),
                    bg=COLORS['main_bg'],
                    fg=COLORS['text_secondary'],
                )
                progress_label.pack(anchor="w", padx=20, pady=(0, 14))
                render_state = {"index": 0, "restored_position": False}

                def render_batch():
                    # A render can become obsolete while its next batch is in
                    # Tk's queue.  Never let it append results to a newer view.
                    try:
                        if not dialog.winfo_exists() or layout_state["render_generation"] != render_generation:
                            return
                    except tk.TclError:
                        return

                    batch_end = min(render_state["index"] + 14, len(files))
                    for index in range(render_state["index"], batch_end):
                        filename = files[index]
                        if render_as_grid:
                            create_mod_grid_card(render_parent, filename, index // cols, index % cols)
                        else:
                            create_mod_list_row(render_parent, filename)
                    render_state["index"] = batch_end
                    progress_label.config(text=f"Loading mods… {batch_end} / {len(files)}")

                    scroll_frame.update_idletasks()
                    canvas.configure(scrollregion=canvas.bbox("all"))
                    if not render_state["restored_position"]:
                        canvas.yview_moveto(0.0 if reset_scroll else current_top)
                        render_state["restored_position"] = True

                    if batch_end < len(files):
                        layout_state["batch_after_id"] = dialog.after(6, render_batch)
                    else:
                        layout_state["batch_after_id"] = None
                        progress_label.destroy()
                        scroll_frame.update_idletasks()
                        canvas.configure(scrollregion=canvas.bbox("all"))

                # Give Tk a chance to paint the header/count before creating
                # the first card batch.
                layout_state["batch_after_id"] = dialog.after(1, render_batch)
            else:
                scroll_frame.update_idletasks()
                canvas.configure(scrollregion=canvas.bbox("all"))
                canvas.yview_moveto(0.0 if reset_scroll else current_top)

        # Let the popup paint immediately, then scan/render its installed
        # files. This avoids the blank flash on large modpack directories.
        self._show_skeleton_list(scroll_frame, rows=3, card_height=112, padx=12, pady=6)
        self._bind_smooth_scroll(canvas, scroll_frame)
        dialog.after(50, render_mods)
        
        # Bind search to debounced re-render
        search_state = {"after_id": None}

        def run_search_render():
            search_state["after_id"] = None
            render_mods()

        def schedule_search_render(*_args):
            after_id = search_state.get("after_id")
            if after_id is not None:
                try:
                    dialog.after_cancel(after_id)
                except Exception:
                    pass
            try:
                search_state["after_id"] = dialog.after(180, run_search_render) # type: ignore
            except Exception:
                search_state["after_id"] = None
                render_mods()

        search_var.trace_add("write", schedule_search_render)

    def show_import_curseforge_dialog(self):
        """Import a local CurseForge export, including its overrides folder.

        CurseForge manifests deliberately omit direct mod-file URLs.  Supplying
        an optional API key enables exact-file downloads through the official
        CurseForge API; without one, the launcher still imports all included
        overrides and retains the manifest's unresolved file list.
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("Import CurseForge Modpack")
        dialog.geometry("620x330")
        dialog.configure(bg=COLORS['main_bg'])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        _schedule_window_centering(dialog, self.root, width=620, height=330)
        dialog_root = self._apply_custom_toplevel_chrome(dialog, "Import CurseForge Modpack")

        content = tk.Frame(dialog_root, bg=COLORS['main_bg'], padx=24, pady=22)
        content.pack(fill="both", expand=True)
        tk.Label(content, text="Import CurseForge Modpack", font=("Segoe UI", 15, "bold"),
                 bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(anchor="w")
        tk.Label(
            content,
            text="Choose a CurseForge export (.zip). Overrides are imported securely. An API key is optional but required to download the manifest's mod files.",
            font=("Segoe UI", 9), bg=COLORS['main_bg'], fg=COLORS['text_secondary'],
            justify="left", wraplength=560,
        ).pack(anchor="w", pady=(6, 16))

        archive_var = tk.StringVar()
        archive_row = tk.Frame(content, bg=COLORS['main_bg'])
        archive_row.pack(fill="x")
        archive_entry = tk.Entry(archive_row, textvariable=archive_var, bg=COLORS['input_bg'],
                                 fg=COLORS['text_primary'], relief="flat", insertbackground="white")
        archive_entry.pack(side="left", fill="x", expand=True, ipady=6)

        def choose_archive():
            selected = filedialog.askopenfilename(
                parent=dialog,
                title="Choose CurseForge Modpack",
                filetypes=[("CurseForge Modpack", "*.zip"), ("All Files", "*")],
            )
            if selected:
                archive_var.set(selected)

        self._make_btn(archive_row, "Browse…", style="secondary", font_size=9, command=choose_archive).pack(side="left", padx=(8, 0))

        tk.Label(content, text="CurseForge API key (optional)", font=("Segoe UI", 9, "bold"),
                 bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(16, 5))
        api_key_var = tk.StringVar(value=str(self.addons_config.get("curseforge_api_key", "")))
        tk.Entry(content, textvariable=api_key_var, show="•", bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                 relief="flat", insertbackground="white").pack(fill="x", ipady=6)

        status = tk.Label(content, text="", font=("Segoe UI", 9), bg=COLORS['main_bg'], fg=COLORS['error_red'])
        status.pack(anchor="w", pady=(8, 0))
        actions = tk.Frame(content, bg=COLORS['main_bg'])
        actions.pack(side="bottom", fill="x")

        def begin_import():
            archive_path = archive_var.get().strip()
            if not archive_path or not os.path.isfile(archive_path):
                status.config(text="Choose a valid CurseForge .zip export first.")
                return
            api_key = api_key_var.get().strip()
            if api_key:
                self.addons_config["curseforge_api_key"] = api_key
                self.save_config(sync_ui=False)
            task_id = self.add_download_task(os.path.basename(archive_path), "modpack")
            dialog.destroy()
            self.download_manager.queue_modpack(
                lambda: self._import_curseforge_modpack_thread(archive_path, api_key, task_id),
                task_id,
            )

        self._make_btn(actions, "Cancel", style="secondary", font_size=9, command=dialog.destroy).pack(side="right")
        self._make_btn(actions, "Import", style="primary", font_size=9, bold=True, command=begin_import).pack(side="right", padx=(0, 8))

    def _curseforge_loader_from_manifest(self, manifest):
        minecraft = manifest.get("minecraft", {}) if isinstance(manifest, dict) else {}
        loader_records = minecraft.get("modLoaders", []) if isinstance(minecraft, dict) else []
        loader_ids = [str(item.get("id", "")).lower() for item in loader_records if isinstance(item, dict)]
        if any("fabric" in loader_id for loader_id in loader_ids):
            return "Fabric"
        if any("forge" in loader_id and "neoforge" not in loader_id for loader_id in loader_ids):
            return "Forge"
        return "Vanilla"

    def _import_curseforge_modpack_thread(self, archive_path, api_key, task_id):
        staging_dir = None
        try:
            self.root.after(0, lambda: self.update_download_task(task_id, 2, detail="Reading CurseForge manifest…"))
            with zipfile.ZipFile(archive_path, "r") as archive:
                try:
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8-sig"))
                except KeyError as exc:
                    raise ValueError("This archive is not a CurseForge export (manifest.json is missing).") from exc
            if not isinstance(manifest, dict) or not isinstance(manifest.get("minecraft"), dict):
                raise ValueError("The CurseForge manifest is malformed.")

            minecraft = manifest["minecraft"]
            minecraft_version = str(minecraft.get("version") or "").strip()
            if not minecraft_version:
                raise ValueError("The CurseForge manifest does not specify a Minecraft version.")
            pack_name = str(manifest.get("name") or os.path.splitext(os.path.basename(archive_path))[0]).strip() or "Imported CurseForge Pack"
            pack_id = str(uuid.uuid4())
            modpack_root = os.path.abspath(os.path.join(self.config_dir, "modpacks"))
            os.makedirs(modpack_root, exist_ok=True)
            staging_dir = os.path.join(modpack_root, f".import-{pack_id}")
            final_dir = os.path.join(modpack_root, pack_id)
            os.makedirs(staging_dir)

            self.root.after(0, lambda: self.update_download_task(task_id, 8, detail="Importing overrides…"))
            with tempfile.TemporaryDirectory() as extract_dir:
                _safe_extract_zip(archive_path, extract_dir)
                overrides_name = str(manifest.get("overrides") or "overrides").replace("\\", "/").strip("/")
                overrides_dir = os.path.realpath(os.path.join(extract_dir, overrides_name))
                extract_root = os.path.realpath(extract_dir)
                if os.path.commonpath((extract_root, overrides_dir)) != extract_root:
                    raise ValueError("The CurseForge overrides path is unsafe.")
                if os.path.isdir(overrides_dir):
                    shutil.copytree(overrides_dir, staging_dir, dirs_exist_ok=True)

            raw_files = manifest.get("files", [])
            required_files = [record for record in raw_files if isinstance(record, dict) and record.get("required", True)] if isinstance(raw_files, list) else []
            installed_files = []
            if api_key and required_files:
                mods_dir = os.path.join(staging_dir, "mods")
                os.makedirs(mods_dir, exist_ok=True)
                for index, record in enumerate(required_files, start=1):
                    if self.download_tasks.get(task_id, {}).get("cancel_event") and self.download_tasks[task_id]["cancel_event"].is_set():
                        raise RuntimeError("Cancelled")
                    project_id = record.get("projectID")
                    file_id = record.get("fileID")
                    if not project_id or not file_id:
                        raise ValueError("A CurseForge file entry is missing its project or file ID.")
                    self.root.after(0, lambda i=index, total=len(required_files): self.update_download_task(task_id, 10 + (i - 1) / max(1, total) * 85, detail=f"Downloading mod {i} of {total}…"))
                    response = requests.get(
                        f"https://api.curseforge.com/v1/mods/{project_id}/files/{file_id}/download-url",
                        headers={"x-api-key": api_key}, timeout=(10, 45),
                    )
                    if response.status_code in (401, 403):
                        raise PermissionError("CurseForge rejected the API key. Check that it is valid and has access to file downloads.")
                    response.raise_for_status()
                    download_url = response.json().get("data")
                    if not isinstance(download_url, str) or not download_url.startswith("https://"):
                        raise ValueError(f"CurseForge did not return a valid download URL for file {file_id}.")
                    filename = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(download_url).path)) or f"curseforge-{project_id}-{file_id}.jar"
                    target = os.path.join(mods_dir, filename)
                    _atomic_download(download_url, target, cancel_event=self.download_tasks.get(task_id, {}).get("cancel_event"))
                    installed_files.append({"project_id": project_id, "file_id": file_id, "filename": filename})

            os.replace(staging_dir, final_dir)
            staging_dir = None
            pack = {
                "id": pack_id,
                "name": pack_name,
                "loader": self._curseforge_loader_from_manifest(manifest),
                "mc_version": minecraft_version,
                "version_name": str(manifest.get("version") or ""),
                "source": "curseforge",
                "mods": installed_files,
                "curseforge_files": required_files,
                "linked_installation_id": None,
            }

            def complete_import():
                self.modpacks.append(pack)
                self.save_modpacks()
                self.refresh_modpacks_list()
                self.update_active_modpack_dropdown()
                self.complete_download_task(task_id)
                if required_files and not api_key:
                    self.toast_manager.show("Imported overrides; add a CurseForge API key to download listed mods.", kind="warning", duration=6000)
                else:
                    self.toast_manager.show(f"Imported {pack_name}", kind="success")

            self.root.after(0, complete_import)
        except Exception as exc:
            logging.exception("CurseForge import failed")
            if staging_dir and os.path.isdir(staging_dir):
                try:
                    shutil.rmtree(staging_dir)
                except OSError:
                    pass
            message = str(exc)
            self.root.after(0, lambda: [
                self.fail_download_task(task_id, "Import failed"),
                custom_showerror("CurseForge Import Failed", message, parent=self.root),
            ])

    def show_create_modpack_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("New Modpack")
        dialog.geometry("450x350")
        dialog.config(bg=COLORS['main_bg'])
        if os.name != "nt":
            dialog.transient(self.root)
        dialog.resizable(False, False)
        if os.name != "nt":
            dialog.grab_set()
        
        # Center on parent
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width()//2) - 225
        y = self.root.winfo_y() + (self.root.winfo_height()//2) - 175
        dialog.geometry(f"+{x}+{y}")
        
        # Ensure visibility
        dialog.deiconify()
        dialog.lift()
        x = self.root.winfo_x() + (self.root.winfo_width()//2) - 225
        y = self.root.winfo_y() + (self.root.winfo_height()//2) - 175
        dialog.geometry(f"+{x}+{y}")
        
        # Ensure visibility
        dialog.deiconify()
        dialog.lift()
        dialog_root = self._apply_custom_toplevel_chrome(dialog, "New Modpack")
        
        # Name
        tk.Label(dialog_root, text="Modpack Name", bg=COLORS['main_bg'], fg="white").pack(pady=(20,5))
        name_var = tk.StringVar()
        tk.Entry(dialog_root, textvariable=name_var).pack()
        
        # Loader
        tk.Label(dialog_root, text="Mod Loader", bg=COLORS['main_bg'], fg="white").pack(pady=(15,5))
        loader_var = tk.StringVar(value="fabric")
        ttk.Combobox(dialog_root, textvariable=loader_var, values=["fabric", "forge"], state="readonly").pack()
        
        # Version
        tk.Label(dialog_root, text="Minecraft Version", bg=COLORS['main_bg'], fg="white").pack(pady=(15,5))
        ver_var = tk.StringVar(value="Fetching...")
        ver_cb = ttk.Combobox(dialog_root, textvariable=ver_var, values=[], state="disabled")
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
             self.get_modpack_dir(new_pack['id']) # Create dir
             
             # Close dialog first for better UX
             dialog.destroy()
             
             # Then refresh UI (use after to ensure dialog is fully closed)
             self.root.after(50, lambda: [
                 self.refresh_modpacks_list(),
                 self.update_active_modpack_dropdown()
             ])
             
        self._make_btn(dialog_root, "Create", style="primary", font_size=10, bold=True,
                      command=create).pack(pady=20)

    def show_link_modpack_dialog(self, pack):
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Link '{pack['name']}'")
        dialog.geometry("450x450")
        dialog.config(bg=COLORS['main_bg'])
        if os.name != "nt":
            dialog.transient(self.root)
        dialog.resizable(False, False)
        if os.name != "nt":
            dialog.grab_set()
        
        # Center on parent
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width()//2) - 225
        y = self.root.winfo_y() + (self.root.winfo_height()//2) - 225
        dialog.geometry(f"+{x}+{y}")
        
        # Ensure visibility
        dialog.deiconify()
        dialog.lift()
        dialog_root = self._apply_custom_toplevel_chrome(dialog, f"Link '{pack['name']}'")
        
        tk.Label(dialog_root, text="Select Installation to Link", font=("Segoe UI", 12),
                 bg=COLORS['main_bg'], fg="white").pack(pady=15)
                 
        tk.Label(dialog_root, text=f"Requires: {pack['mc_version']} ({pack['loader']})", 
                 bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(pady=(0, 15))
                 
        # List Compatible Installs
        insts = self.get_installations().items()
        
        scroll = tk.Scrollbar(dialog_root)
        scroll.pack(side="right", fill="y")
        lb = tk.Listbox(dialog_root, bg=COLORS['input_bg'], fg="white", yscrollcommand=scroll.set, width=40)
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
            
            # Close dialog first
            dialog.destroy()
            
            # Then refresh UI
            self.root.after(50, self.refresh_modpacks_list)
        
        def create_match():
             threading.Thread(target=self._create_matching_installation_thread, args=(pack, dialog), daemon=True).start()

        create_match_btn = self._make_btn(dialog_root, "Create Matching Installation", style="secondary",
                                           font_size=10, bold=True, command=create_match)
        create_match_btn.pack(pady=(15, 5), fill="x", padx=30)
        link_btn = self._make_btn(dialog_root, "Link Selected", style="primary",
                                  font_size=10, bold=True, command=link)
        link_btn.pack(pady=(5, 15), fill="x", padx=30)

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
                 "java_executable": "",
                 "resolution_width": None,
                 "resolution_height": None,
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
            
            def update_ui():
                self.refresh_installations_list()
                self.update_installation_dropdown()
                self.refresh_modpacks_list()
                if dialog.winfo_exists():
                    dialog.destroy()
                messagebox.showinfo("Success", f"Created installation '{new_name}' and linked it.")
            
            self.root.after(0, update_ui)
            
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
        if not getattr(self, 'neo_style_enabled', True):
            mode_frame.pack(side="top", fill="x", pady=(0, 10))

        def switch_mode(m):
            self.browse_mode_var.set(m)
            self.search_mods_thread(reset=True)
            
            # Hide or show the modpack selection
            if m in ["modpack", "shader", "resourcepack"]:
                mp_frame.pack_forget()
            else:
                mp_frame.pack(side="top", fill="x", pady=(0, 10), before=mode_frame if not getattr(self, 'neo_style_enabled', True) else search_line)

            # visual update only if mode frame is packed
            if not getattr(self, 'neo_style_enabled', True):
                btn_mod.config(bg=COLORS['input_bg'])
                btn_pack.config(bg=COLORS['input_bg'])
                btn_rp.config(bg=COLORS['input_bg'])

                if m == "mod":
                    btn_mod.config(bg=COLORS['accent_blue'])
                elif m == "modpack":
                    btn_pack.config(bg=COLORS['accent_blue'])
                elif m == "resourcepack":
                    btn_rp.config(bg=COLORS['accent_blue'])

        # Expose the method globally
        self.switch_modrinth_mode = switch_mode
        btn_mod = self._make_btn(mode_frame, "Mods", style="secondary", font_size=9,
                                  width=12, command=lambda: switch_mode("mod"))
        btn_mod.config(bg=COLORS['accent_blue'], activebackground="#2E86C1")
        btn_mod.pack(side="left", padx=(0, 5))

        btn_pack = self._make_btn(mode_frame, "Modpacks", style="secondary", font_size=9,
                                   width=12, command=lambda: switch_mode("modpack"))
        btn_pack.pack(side="left", padx=5)

        btn_rp = self._make_btn(mode_frame, "Resource Packs", style="secondary", font_size=9,
                                   width=14, command=lambda: switch_mode("resourcepack"))
        btn_rp.pack(side="left", padx=5)
        
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
        self.mods_canvas.configure(yscrollcommand=self._on_scrollbar_update)
        
        self.mods_canvas.pack(side="left", fill="both", expand=True)
        self.mods_scrollbar.pack(side="right", fill="y")
        
        # Smooth mousewheel for Mods Tab with infinite scroll check
        self.last_scroll_check = 0.0
        
        def _mods_smooth_scroll(event):
            self._smooth_scroll(self.mods_canvas, event)
            # Also check for infinite scroll (pagination) on each scroll input
            now = time.time()
            if now - self.last_scroll_check > 0.2:
                self.last_scroll_check = now
                self._check_scroll_position()
        
        self._bind_wheel_events(self.mods_canvas, _mods_smooth_scroll, f"mods_{id(self.mods_canvas)}")
        frame.bind("<Enter>", lambda e: self._bind_smooth_scroll(self.mods_canvas, self.mods_scrollable_frame))
        self.mods_canvas._nlc_after_scroll = self._check_scroll_position  # type: ignore[attr-defined]

        self.mod_search_timer = None
        self._mod_load_more_after_id = None
        self._mod_search_generation = 0
        self._mod_page_size = 20
        self.cached_mod_images = {}
        self.mod_image_loading = set()
        self.mod_image_waiters = {}
        
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
        if self.mod_loading or self.mod_end_reached or getattr(self, "_mod_load_more_after_id", None):
            return
        try:
            # Keep enough content below the viewport that pagination feels
            # seamless, without immediately chaining page requests.
            if self.mods_canvas.yview()[1] >= 0.90:
                self._mod_load_more_after_id = self.root.after(90, self._run_scheduled_mod_page)
        except tk.TclError:
            return

    def _run_scheduled_mod_page(self):
        self._mod_load_more_after_id = None
        self.load_more_mods()

    def schedule_mod_search(self, *args):
        if self.mod_search_timer:
            try:
                self.root.after_cancel(self.mod_search_timer)
            except tk.TclError:
                pass
        self.mod_search_timer = self.root.after(800, self._run_debounced_mod_search)

    def _run_debounced_mod_search(self):
        self.mod_search_timer = None
        self.search_mods_thread(reset=True)

    def load_more_mods(self):
        if self.mod_loading or self.mod_end_reached: return
        self.search_mods_thread(reset=False)

    def search_mods_thread(self, reset=False):
        if self.mod_loading and not reset:
            return
        if reset:
            self._mod_search_generation += 1
            if self._mod_load_more_after_id:
                try:
                    self.root.after_cancel(self._mod_load_more_after_id)
                except tk.TclError:
                    pass
                self._mod_load_more_after_id = None
        generation = self._mod_search_generation
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

        payload = {
            "query": query,
            "limit": self._mod_page_size,
            "offset": self.mod_offset,
            "facets": []
        }
        
        # Project Type
        p_type = "mod"
        if hasattr(self, 'browse_mode_var'):
             p_type = self.browse_mode_var.get()
        payload["facets"].append(f'project_type:{p_type}')

        if loader and p_type not in ["resourcepack", "shader"]:
            payload["facets"].append(f'categories:{loader}')
        if version_facet:
            payload["facets"].append(f'versions:{version_facet}')

        # The helper process performs network work; no extra Python thread is
        # required here.  A generation token rejects stale responses from a
        # query/filter that the user has already replaced.
        self.send_agent_request(
            "search_mods", payload,
            lambda res, g=generation, is_reset=reset: self._on_mod_search_result(res, is_reset, g),
        )

    def _on_mod_search_result(self, result, reset, generation=None):
        if generation is not None and generation != self._mod_search_generation:
            return
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

        self._display_mod_results(hits, reset, generation)

    def _display_mod_error(self, msg):
        tk.Label(self.mods_scrollable_frame, text=f"Error: {msg}", 
                 fg=COLORS['error_red'], bg=COLORS['main_bg']).pack(pady=20)

    def _display_mod_results(self, hits, reset, generation=None):
        if generation is not None and generation != self._mod_search_generation:
            return
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
        self._bind_smooth_scroll(self.mods_canvas, self.mods_scrollable_frame)

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
                 fg="white", bg=COLORS['card_bg'], anchor="w", justify="left", wraplength=460).pack(fill="x")
        
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

        project_type = mod.get('project_type', 'mod')

        # INSTALL BUTTON (If pack selected or Modpack Browse)
        if project_type == 'modpack':
             btn = self._make_btn(btn_frame, "Download", style="primary", font_size=9, bold=True)
             btn.pack(side="right", padx=5)
             btn.config(command=lambda m=mod, b=btn: self._install_mr_modpack(m, b))
             
        elif project_type in ['resourcepack', 'shader']:
             btn = self._make_btn(btn_frame, "Install", style="primary", font_size=9, bold=True)
             btn.pack(side="right", padx=5)
             btn.config(command=lambda m=mod, b=btn: self._install_global_resource(m, b))

        else:
            active_pack_name = self.active_modpack_var.get()
            if active_pack_name != "None":
                # Check if installed
                pack = next((p for p in self.modpacks if p['name'] == active_pack_name), None)
                is_installed = False
                if pack:
                    # Check meta
                    mod_slug = mod.get('slug')
                    if any(m.get('slug') == mod_slug for m in pack['mods']):
                        is_installed = True
                
                if is_installed:
                    tk.Label(btn_frame, text="✔ Installed", font=("Segoe UI", 9, "bold"), 
                            fg=COLORS['success_green'], bg=COLORS['card_bg']).pack(side="right", padx=10)
                else:
                    btn = self._make_btn(btn_frame, "Install", style="primary", font_size=9, bold=True)
                    btn.pack(side="right", padx=5)
                    btn.config(command=lambda b=btn, m=mod, p=active_pack_name: self._install_mod_to_pack(m, p, b))

        self._make_btn(btn_frame, "Web", style="secondary", font_size=9,
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
                if mod_data.get('project_type') == 'resourcepack':
                    v_url = f"https://api.modrinth.com/v2/project/{mod_id}/version?game_versions=[%22{pack['mc_version']}%22]"
                else:
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
                if mod_data.get('project_type') == 'resourcepack':
                    target_dir = os.path.join(self.minecraft_dir, "resourcepacks")
                else:
                    target_dir = os.path.join(self.get_modpack_dir(pack['id']), "mods")
                
                if not os.path.exists(target_dir): os.makedirs(target_dir)
                
                target_path = os.path.join(target_dir, filename)
                
                self.root.after(0, lambda: self.update_download_task(task_id, 0, detail=f"Downloading {filename}..."))
                cancel_event = self.download_tasks.get(task_id, {}).get('cancel_event')
                rate_limit = getattr(self, 'max_download_speed', 2048) if getattr(self, 'limit_download_speed_enabled', False) else 0
                _atomic_download(
                    download_url,
                    target_path,
                    cancel_event=cancel_event,
                    rate_limit_kib=rate_limit,
                    expected_sha1=(primary_file.get("hashes") or {}).get("sha1"),
                    progress=lambda current, total: self.root.after(
                        0, lambda: self.update_download_task(task_id, (current / total) * 100)
                    ) if total else None,
                )
                            
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
                if success:
                    self.complete_download_task(task_id)
                    btn_widget.destroy() # Remove install button (or replace with checkmark)
                else:
                    self.fail_download_task(task_id, "Download failed — retry available")
                    btn_widget.config(state="normal", text="Install", bg=COLORS['play_btn_green'])
            
            self.root.after(0, finish)
        
        self.download_manager.queue_mod(run_install, task_id)

    def _install_global_resource(self, mod_data, btn_widget):
        btn_widget.config(state="disabled", text="Queued...", bg=COLORS['text_secondary'])
        item_type = mod_data.get('project_type', 'shader')
        task_id = self.add_download_task(mod_data.get('title', 'Resource'), item_type)

        def run_install():
            self.root.after(0, lambda: btn_widget.config(text="Installing..."))
            try:
                mod_id = mod_data['slug']
                self.root.after(0, lambda: self.update_download_task(task_id, 0, detail="Fetching versions..."))
                
                v_url = f"https://api.modrinth.com/v2/project/{mod_id}/version"
                r = requests.get(v_url, timeout=10)
                if r.status_code != 200:
                    raise Exception(f"Failed to fetch versions: {r.status_code}")
                    
                versions = r.json()
                if not versions:
                    raise Exception("No versions found.")
                    
                best_ver = versions[0]
                files = best_ver.get('files', [])
                if not files:
                    raise Exception("No files in version.")
                
                primary_file = next((f for f in files if f.get('primary', False)), files[0])
                download_url = primary_file['url']
                filename = primary_file['filename']
                
                target_dir = os.path.join(self.minecraft_dir, "shaderpacks" if item_type == "shader" else "resourcepacks")
                if not os.path.exists(target_dir): os.makedirs(target_dir)
                target_path = os.path.join(target_dir, filename)
                
                self.root.after(0, lambda: self.update_download_task(task_id, 0, detail=f"Downloading {filename}..."))
                _atomic_download(
                    download_url,
                    target_path,
                    cancel_event=self.download_tasks.get(task_id, {}).get("cancel_event"),
                    expected_sha1=(primary_file.get("hashes") or {}).get("sha1"),
                )
                
                self.root.after(0, lambda: self.complete_download_task(task_id))
                self.root.after(0, lambda: btn_widget.config(text="✔ Installed", bg=COLORS['success_green'], fg="white"))
                
            except Exception as e:
                msg = str(e)
                if msg != "Cancelled":
                    self.root.after(0, lambda: self.update_download_task(task_id, status="Error", detail=msg))
                self.root.after(0, lambda: btn_widget.config(state="normal", text="Retry", bg=COLORS['error_red']))
        
        self.download_manager.queue_mod(run_install, task_id)

    def _get_modpack_version_file(self, version_data):
        try:
            files = version_data.get('files', [])
            return next(
                (f for f in files if str(f.get('filename', '')).endswith('.mrpack') and f.get('url')),
                None
            )
        except Exception:
            return None

    def _format_modpack_version_option(self, version_data):
        version_name = version_data.get('version_number') or version_data.get('name') or version_data.get('id', 'Unknown')
        game_versions = [str(v) for v in version_data.get('game_versions', []) if v]
        loaders = [str(v) for v in version_data.get('loaders', []) if v]
        published = str(version_data.get('date_published', '')).replace('T', ' ')[:16]

        meta_parts = []
        if game_versions:
            meta_parts.append(", ".join(game_versions[:2]))
        if loaders:
            meta_parts.append("/".join(loaders[:2]))
        if published:
            meta_parts.append(published)

        return version_name if not meta_parts else f"{version_name}  •  " + "  •  ".join(meta_parts)

    def _prompt_modpack_version(self, mod_data, versions):
        result = {"version": None}
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Choose Version - {mod_data.get('title', 'Modpack')}")
        dialog.geometry("560x280")
        dialog.config(bg=COLORS['main_bg'])
        if os.name != "nt":
            dialog.transient(self.root)
            dialog.grab_set()

        dialog_root = self._apply_custom_toplevel_chrome(dialog, f"Install {mod_data.get('title', 'Modpack')}")

        container = tk.Frame(dialog_root, bg=COLORS['main_bg'], padx=24, pady=24)
        container.pack(fill="both", expand=True)

        tk.Label(
            container,
            text="Select Modpack Version",
            font=("Segoe UI", 14, "bold"),
            bg=COLORS['main_bg'],
            fg=COLORS['text_primary'],
        ).pack(anchor="w")

        tk.Label(
            container,
            text="Choose which version of this modpack to install.",
            font=("Segoe UI", 10),
            bg=COLORS['main_bg'],
            fg=COLORS['text_secondary'],
        ).pack(anchor="w", pady=(6, 16))

        options = [self._format_modpack_version_option(version) for version in versions]
        selected_index = {"value": 0}
        version_var = tk.StringVar(value=options[0] if options else "")

        combo = ttk.Combobox(
            container,
            textvariable=version_var,
            values=options,
            state="readonly",
            style="Launcher.TCombobox",
        )
        combo.pack(fill="x", ipady=6)
        if options:
            combo.current(0)

        detail_lbl = tk.Label(
            container,
            text="",
            font=("Segoe UI", 9),
            bg=COLORS['main_bg'],
            fg=COLORS['text_secondary'],
            justify="left",
            anchor="w",
        )
        detail_lbl.pack(fill="x", pady=(14, 0))

        def update_version_details(*_args):
            try:
                idx = combo.current()
            except Exception:
                idx = selected_index["value"]
            if idx is None or idx < 0 or idx >= len(versions):
                idx = 0
            selected_index["value"] = idx
            version = versions[idx]
            mrpack_file = self._get_modpack_version_file(version)
            game_versions = ", ".join(str(v) for v in version.get('game_versions', [])[:3]) or "Unknown"
            loaders = ", ".join(str(v) for v in version.get('loaders', [])[:3]) or "Unknown"
            file_name = mrpack_file.get('filename', 'Unknown') if mrpack_file else "Missing .mrpack"
            detail_lbl.config(
                text=f"Minecraft: {game_versions}\nLoader: {loaders}\nFile: {file_name}"
            )

        combo.bind("<<ComboboxSelected>>", update_version_details)
        update_version_details()

        btn_row = tk.Frame(container, bg=COLORS['main_bg'])
        btn_row.pack(side="bottom", fill="x", pady=(20, 0))

        def confirm_install():
            idx = selected_index["value"]
            if 0 <= idx < len(versions):
                result["version"] = versions[idx]
            dialog.destroy()

        self._make_btn(
            btn_row, "Cancel", style="secondary", font_size=10, command=dialog.destroy
        ).pack(side="right")
        self._make_btn(
            btn_row, "Install", style="primary", font_size=10, bold=True, command=confirm_install
        ).pack(side="right", padx=(0, 8))

        self.root.wait_window(dialog)
        return result["version"]

    def _install_mr_modpack(self, mod_data, btn_widget):
        original_text = btn_widget.cget("text")
        btn_widget.config(state="disabled", text="Loading...")

        try:
            mod_id = mod_data['slug']
            v_url = f"https://api.modrinth.com/v2/project/{mod_id}/version"
            r = requests.get(v_url, headers={"User-Agent": "AmneDev/NewLauncher"}, timeout=10)
            if r.status_code != 200:
                raise Exception(f"Failed to fetch versions: {r.status_code}")

            versions = [v for v in r.json() if self._get_modpack_version_file(v)]
            if not versions:
                raise Exception("No installable .mrpack versions were found for this modpack.")

            selected_version = self._prompt_modpack_version(mod_data, versions)
            if not selected_version:
                btn_widget.config(state="normal", text=original_text, bg=COLORS['play_btn_green'])
                return
        except Exception as e:
            btn_widget.config(state="normal", text=original_text, bg=COLORS['play_btn_green'])
            custom_showerror("Error", str(e), parent=self.root)
            return

        btn_widget.config(state="disabled", text="Queued...", bg=COLORS['text_secondary'])
        task_id = self.add_download_task(mod_data['title'], "modpack")
        
        def run():
             self.root.after(0, lambda: btn_widget.config(text="Installing..."))
             self._install_mr_modpack_thread(mod_data, selected_version, btn_widget, task_id)
             
        self.download_manager.queue_modpack(run, task_id)

    def _install_mr_modpack_thread(self, mod_data, version_data, btn_widget, task_id):
        try:
             self.root.after(0, lambda: self.update_download_task(task_id, 0, detail="Fetching info..."))
             best = version_data
             
             mrpack_file = self._get_modpack_version_file(best)
             
             if not mrpack_file:
                 raise Exception("No .mrpack file found in selected version")
                 
             # Create Pack Entry
             pack_name = mod_data['title']
             mc_ver = next((str(v) for v in best.get('game_versions', []) if v), "unknown")
             loader = next((str(v) for v in best.get('loaders', []) if v), "vanilla")
             version_name = best.get('version_number') or best.get('name') or best.get('id', 'unknown')
             
             new_id = str(uuid.uuid4())
             new_pack = {
                 "id": new_id,
                 "name": pack_name,
                 "loader": loader,
                 "mc_version": mc_ver,
                 "version_id": best.get('id', ''),
                 "version_name": version_name,
                 "mods": [],
                 "linked_installation_id": None
             }
             
             # Download .mrpack to temp
             self.root.after(0, lambda: self.update_download_task(task_id, 5, detail=f"Downloading {version_name}..."))
             with tempfile.TemporaryDirectory() as temp_dir:
                 mr_path = os.path.join(temp_dir, "pack.mrpack")
                 cancel_event = self.download_tasks.get(task_id, {}).get('cancel_event')
                 _atomic_download(mrpack_file['url'], mr_path, cancel_event=cancel_event)
                         
                 # Extract
                 if task_id in self.download_tasks and self.download_tasks[task_id]['cancel_event'].is_set(): raise Exception("Cancelled")

                 self.root.after(0, lambda: self.update_download_task(task_id, 10, detail="Extracting..."))
                 _safe_extract_zip(mr_path, temp_dir)
                     
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

                     downloads = file_def.get('downloads') or []
                     d_url = downloads[0] if downloads else ""
                     f_path = str(file_def.get('path') or "")
                     f_name = os.path.basename(f_path)
                     
                     # Allow subdirectories 
                     # Modrinth packs put mods in 'mods/...' usually.
                     # We flatten? No, keep it in mods dir.
                     # If path starts with 'mods/', it goes to target_dir.
                     # If path is 'config/', we ignore for now as requested (simple implementation)
                     if f_path.startswith("mods/"):
                         pack_dir = os.path.abspath(self.get_modpack_dir(new_id))
                         dest = os.path.abspath(os.path.join(pack_dir, f_path))
                         if not d_url or os.path.commonpath((pack_dir, dest)) != pack_dir:
                             raise ValueError(f"Unsafe or incomplete modpack entry: {f_path}")
                         # Ensure dir exists
                         os.makedirs(os.path.dirname(dest), exist_ok=True)
                         
                         self.root.after(0, lambda n=f_name: self.update_download_task(task_id, detail=f"Downloading {n}"))
                         _atomic_download(
                             d_url,
                             dest,
                             cancel_event=cancel_event,
                             expected_sha1=(file_def.get("hashes") or {}).get("sha1"),
                         )
                                 
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
                 messagebox.showinfo("Success", f"Installed modpack '{pack_name}' ({version_name})"),
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
        if url in self.mod_image_loading:
            self.mod_image_waiters.setdefault(url, []).append(label)
            return
        self.mod_image_loading.add(url)
        self.mod_image_waiters[url] = [label]

        def fetch():
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    with Image.open(io.BytesIO(r.content)) as source:
                        image = source.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)

                    # PIL decoding is safe off-thread; Tk PhotoImage creation
                    # is not.  Keeping all Tk operations on the UI thread
                    # avoids intermittent freezes when a result page appears.
                    def update_ui():
                        self.mod_image_loading.discard(url)
                        try:
                            photo = ImageTk.PhotoImage(image)
                            self.cached_mod_images[url] = photo
                            for waiting_label in self.mod_image_waiters.pop(url, []):
                                if waiting_label.winfo_exists():
                                    waiting_label.config(image=photo, text="", width=64, height=64)
                        except tk.TclError:
                            pass

                    self.root.after(0, update_ui)
                    return
            except (requests.RequestException, OSError, ValueError) as exc:
                logging.debug("Could not load Modrinth icon %s: %s", url, exc)
            finally:
                # Success is released by update_ui; failures must also be
                # released so the image can be retried after a transient error.
                if url in self.mod_image_loading:
                    try:
                        self.root.after(0, lambda: (self.mod_image_loading.discard(url), self.mod_image_waiters.pop(url, None)))
                    except tk.TclError:
                        pass
        
        threading.Thread(target=fetch, daemon=True).start()

    def create_settings_tab(self):
        if getattr(self, 'neo_style_enabled', True):
            self._create_neo_settings_tab()
        else:
            self._create_classic_settings_tab()

    def _create_neo_settings_tab(self):
        container = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Settings"] = container
        
        # Top Header & Nav
        header_frame = tk.Frame(container, bg=COLORS['sidebar_bg'], height=60)
        header_frame.pack(side="top", fill="x")
        
        title = tk.Label(header_frame, text="SETTINGS", font=("Segoe UI", 14, "bold"), 
                         bg=COLORS['sidebar_bg'], fg=COLORS['text_primary'])
        title.pack(side="left", padx=30, pady=15)

        nav_frame = tk.Frame(header_frame, bg=COLORS['sidebar_bg'])
        nav_frame.pack(side="right", padx=30, pady=15)

        content_container = tk.Frame(container, bg=COLORS['main_bg'])
        content_container.pack(side="top", fill="both", expand=True)
        
        # We need a scrollable area for each tab if it overflows, or just let neo be scrollable overall?
        # Actually, let's just make the whole container scrollable, but using anchors in a top nav!
        # Wait, if it's cards, we just use a unified smooth-scrolling wrapper like classic, but NO left nav, and put the cards in a responsive-like grid or wide cards centering!
        
        # Content Canvas
        canvas = tk.Canvas(content_container, bg=COLORS['main_bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(content_container, orient="vertical", command=canvas.yview, style="Launcher.Vertical.TScrollbar")
        
        scrollable_frame = tk.Frame(canvas, bg=COLORS['main_bg'])
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        
        # Center the content slightly
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=content_container.winfo_reqwidth())

        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
        
        def on_canvas_configure(event):
            # Center content if wide enough, else fill
            w = max(event.width, 600)
            canvas.itemconfig(canvas_window, width=w)
            
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        content_container.bind("<Enter>", lambda e: self._bind_smooth_scroll(canvas, scrollable_frame))

        # Main wrapper to hold cards
        main_wrapper = tk.Frame(scrollable_frame, bg=COLORS['main_bg'])
        main_wrapper.pack(fill="both", expand=True, padx=40, pady=30)
        
        def scroll_to_widget(widget):
             try:
                 scrollable_frame.update_idletasks()
                 canvas.update_idletasks()
                 widget_y = widget.winfo_y()
                 canvas_height = canvas.winfo_height()
                 total_height = scrollable_frame.winfo_reqheight()
                 if total_height > canvas_height:
                     target_y = max(0, widget_y - 20)
                     fraction = max(0.0, min(1.0, target_y / (total_height - canvas_height)))
                     canvas.yview_moveto(fraction)
                 else:
                     canvas.yview_moveto(0)
             except: pass

        def create_top_nav_btn(text, target_widget):
            btn = tk.Button(nav_frame, text=text.upper(), font=("Segoe UI", 9, "bold"),
                           bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'],
                           relief="flat", cursor="hand2", command=lambda w=target_widget: scroll_to_widget(w))
            btn.pack(side="left", padx=10)
            btn.bind("<Enter>", lambda e, b=btn: b.config(fg="white"))
            btn.bind("<Leave>", lambda e, b=btn: b.config(fg=COLORS['text_secondary']))

        # Helper to make neat cards
        def create_card(parent, title_text):
            card = tk.Frame(parent, bg=COLORS['card_bg'], padx=25, pady=25)
            card.pack(fill="x", pady=(0, 20))
            lbl = tk.Label(card, text=title_text, font=("Segoe UI", 12, "bold"),
                          bg=COLORS['card_bg'], fg=COLORS['text_primary'])
            lbl.pack(anchor="w", pady=(0, 15))
            return card, lbl
            
        def card_check(card, text, var, cmd=None):
            cmd = cmd or self.save_config
            cb = tk.Checkbutton(card, text=text, variable=var,
                          bg=COLORS['card_bg'], fg=COLORS['text_primary'],
                          selectcolor=COLORS['card_bg'], activebackground=COLORS['card_bg'],
                          command=cmd)
            cb.pack(anchor="w", pady=(0, 8))
            
        def card_label(card, text):
            tk.Label(card, text=text, font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(10, 5))

        # --- Cards ---
        
        # GENERAL
        card_gen, lbl_gen = create_card(main_wrapper, "GENERAL")
        create_top_nav_btn("General", card_gen)
        
        self.close_launcher_var = tk.BooleanVar(value=getattr(self, 'close_launcher', True))
        card_check(card_gen, "Close launcher when game starts", self.close_launcher_var)
        self.minimize_to_tray_var = tk.BooleanVar(value=getattr(self, 'minimize_to_tray', False))
        card_check(card_gen, "Minimize to tray on close", self.minimize_to_tray_var)
        self.show_console_var = tk.BooleanVar(value=getattr(self, 'show_console', False))
        card_check(card_gen, "Keep output console open (Debug)", self.show_console_var)

        # APPEARANCE
        card_app, lbl_app = create_card(main_wrapper, "APPEARANCE")
        create_top_nav_btn("Appearance", card_app)
        
        self.custom_titlebar_var = tk.BooleanVar(value=getattr(self, 'custom_titlebar_enabled', True))
        def on_titlebar_toggle():
             val = self.custom_titlebar_var.get(); self.custom_titlebar_enabled = val; self.save_config()
             if hasattr(self, 'root'): custom_showinfo("Restart Required", "Restart to apply titlebar changes.")
        card_check(card_app, "Use Custom Titlebar (Windows only)", self.custom_titlebar_var, on_titlebar_toggle)

        self.neo_style_var = tk.BooleanVar(value=getattr(self, 'neo_style_enabled', True))
        def on_neo_toggle():
             val = self.neo_style_var.get(); self.neo_style_enabled = val; self.save_config()
             if hasattr(self, 'root'): custom_showinfo("Restart Required", "Restart to apply Neo Style changes.")
        card_check(card_app, "Use Neo Style (OLED Black Theme)", self.neo_style_var, on_neo_toggle)

        card_label(card_app, "Accent Color")
        accent_frame = tk.Frame(card_app, bg=COLORS['card_bg'])
        accent_frame.pack(fill="x", pady=(0, 10))
        
        _current = getattr(self, "accent_color_name", "Green")
        _attrs = [("Green", "#2D8F36"), ("Blue", "#3498DB"), ("Orange", "#E67E22"), ("Purple", "#9B59B6"), ("Red", "#E74C3C")]
        
        for name, col in _attrs:
            f = tk.Frame(accent_frame, bg=COLORS['card_bg'], padx=3, pady=3)
            f.pack(side="left", padx=5)
            if name == _current: f.config(bg="gray")
            btn = tk.Button(f, bg=col, width=6, height=2, relief="flat", bd=0, cursor="hand2",
                           command=lambda n=name: self.apply_accent_color(n))
            btn.config(activebackground=col)
            btn.pack()

        # JAVA
        card_java, lbl_java = create_card(main_wrapper, "JAVA & DIRECTORY")
        create_top_nav_btn("Java", card_java)

        card_label(card_java, "Minecraft Directory")
        dir_frame = tk.Frame(card_java, bg=COLORS['card_bg'])
        dir_frame.pack(fill="x", pady=(0, 10))
        self.dir_entry = tk.Entry(dir_frame, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", insertbackground="white")
        self.dir_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self._make_btn(dir_frame, "Change", style="secondary", font_size=9, command=self.change_minecraft_dir).pack(side="left", padx=(10, 0))
        self._make_btn(dir_frame, "Open", style="secondary", font_size=9, command=self.open_minecraft_dir).pack(side="left", padx=(5, 0)) # type: ignore
        
        card_label(card_java, "Java Arguments (JVM Flags)")
        self.java_args_entry = tk.Entry(card_java, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", insertbackground="white")
        self.java_args_entry.pack(fill="x", pady=(0, 10), ipady=6)
        self.java_args_entry.bind("<FocusOut>", self.save_config)

        card_label(card_java, "Allocated Memory (MB)")
        self.ram_var = tk.IntVar(value=DEFAULT_RAM)
        self.ram_entry_var = tk.StringVar(value=str(DEFAULT_RAM))
        self.ram_entry_var.trace_add("write", self._on_ram_entry_change)
        
        ram_row = tk.Frame(card_java, bg=COLORS['card_bg'])
        ram_row.pack(fill="x", pady=(0, 10))
        tk.Scale(ram_row, from_=1024, to=16384, orient="horizontal", resolution=512, variable=self.ram_var, showvalue=0, bg=COLORS['card_bg'], fg=COLORS['text_primary'], troughcolor=COLORS['input_bg'], highlightthickness=0, command=self._on_ram_slider_change).pack(side="left", fill="x", expand=True) # type: ignore
        tk.Entry(ram_row, textvariable=self.ram_entry_var, width=8, bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", insertbackground="white").pack(side="left", padx=(10, 0), ipady=4)

        # DOWNLOADS & FEATURES
        card_down, lbl_down = create_card(main_wrapper, "DOWNLOADS")
        create_top_nav_btn("Downloads", card_down)

        card_label(card_down, "Download Limits")
        lim_frame = tk.Frame(card_down, bg=COLORS['card_bg'])
        lim_frame.pack(fill="x", pady=(0, 10))
        
        def update_limits(*args):
             try: self.max_concurrent_packs = int(self.limit_packs_var.get()); self.max_concurrent_mods = int(self.limit_mods_var.get()); self.save_config(sync_ui=False)
             except: pass

        tk.Label(lim_frame, text="Max Modpacks:", bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(side="left")
        self.limit_packs_var = tk.StringVar(value=str(getattr(self, 'max_concurrent_packs', 1)))
        self.limit_packs_var.trace_add("write", update_limits)
        tk.Entry(lim_frame, textvariable=self.limit_packs_var, width=5, bg=COLORS['input_bg'], fg="white", relief="flat").pack(side="left", padx=(5, 15))

        tk.Label(lim_frame, text="Max Mods:", bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(side="left")
        self.limit_mods_var = tk.StringVar(value=str(getattr(self, 'max_concurrent_mods', 3)))
        self.limit_mods_var.trace_add("write", update_limits)
        tk.Entry(lim_frame, textvariable=self.limit_mods_var, width=5, bg=COLORS['input_bg'], fg="white", relief="flat").pack(side="left", padx=5)

        card_label(card_down, "Speed Limit (KB/s)")
        speed_frame = tk.Frame(card_down, bg=COLORS['card_bg'])
        speed_frame.pack(fill="x", pady=0)
        self.limit_speed_enc_var = tk.BooleanVar(value=getattr(self, 'limit_download_speed_enabled', False))
        tk.Checkbutton(speed_frame, text="Limit Speed", variable=self.limit_speed_enc_var, bg=COLORS['card_bg'], fg=COLORS['text_primary'], selectcolor=COLORS['card_bg'], activebackground=COLORS['card_bg'], command=lambda: [setattr(self, 'limit_download_speed_enabled', self.limit_speed_enc_var.get()), self.save_config(sync_ui=False)]).pack(side="left")
        self.limit_speed_val_var = tk.StringVar(value=str(getattr(self, 'max_download_speed', 2048)))
        def update_speed(*args):
             try: self.max_download_speed = int(self.limit_speed_val_var.get()); self.save_config(sync_ui=False)
             except: pass
        self.limit_speed_val_var.trace_add("write", update_speed)
        tk.Entry(speed_frame, textvariable=self.limit_speed_val_var, width=8, bg=COLORS['input_bg'], fg="white", relief="flat").pack(side="left", padx=(10, 5))

        # DISCORD & ACCOUNT
        card_rpc, lbl_rpc = create_card(main_wrapper, "ACCOUNT & RPC")
        create_top_nav_btn("Account", card_rpc)
        
        card_label(card_rpc, "Account Username")
        self.user_entry = tk.Entry(card_rpc, font=("Segoe UI", 11), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", insertbackground="white")
        self.user_entry.config(show="*" if self._is_streamer_mode_enabled() else "")
        self.user_entry.pack(fill="x", pady=(0, 15), ipady=8)
        self.user_entry.bind("<FocusOut>", self.save_config)

        self.rpc_var = tk.BooleanVar(value=True)
        self.rpc_detail_mode_var = tk.StringVar(value="Show Version")
        card_check(card_rpc, "Enable Discord Rich Presence", self.rpc_var, self._on_rpc_toggle)
        
        card_label(card_rpc, "RPC Second Line Detail")
        rpc_combo = ttk.Combobox(card_rpc, textvariable=self.rpc_detail_mode_var, state="readonly", values=["Show Version", "Show Server IP", "Hidden"], style="Launcher.TCombobox", width=30)
        rpc_combo.pack(anchor="w", pady=(0, 10))
        rpc_combo.bind("<<ComboboxSelected>>", lambda e: self.save_config())

        # LOGS & UPDATES
        card_sys, lbl_sys = create_card(main_wrapper, "SYSTEM & LOGS")
        create_top_nav_btn("System", card_sys)
        
        update_frame = tk.Frame(card_sys, bg=COLORS['card_bg'])
        update_frame.pack(fill="x", pady=(0, 10))
        tk.Label(update_frame, text=f"Current Version: {CURRENT_VERSION}", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(side="left", padx=(0, 20))
        self._make_btn(update_frame, "Check Updates", style="secondary", font_size=9, command=self.check_for_updates).pack(side="left")
        
        self.update_status_lbl = tk.Label(card_sys, text="", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary'])
        self.update_status_lbl.pack(anchor="w")
        
        self.auto_update_var = tk.BooleanVar(value=self.auto_update_check)
        card_check(card_sys, "Auto-check updates on startup", self.auto_update_var)
        
        card_label(card_sys, "Launcher Logs")
        self.log_area = scrolledtext.ScrolledText(card_sys, height=6, bg=COLORS['input_bg'], fg=COLORS['text_secondary'], font=("Consolas", 9), relief="flat")
        self.log_area.pack(fill="x")

        # DANGER ZONE
        card_danger, lbl_danger = create_card(main_wrapper, "DANGER ZONE")
        lbl_danger.config(fg="#E74C3C")
        self._make_btn(card_danger, "Review Onboarding", style="secondary", font_size=9, command=lambda: self.show_onboarding_wizard()).pack(anchor="w", pady=(0, 10))
        self._make_btn(card_danger, "Reset to Defaults", style="danger", font_size=9, bold=True, command=self.reset_to_defaults).pack(anchor="w")
        
        self._bind_smooth_scroll(canvas, scrollable_frame)

    def _create_classic_settings_tab(self):
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

        # Smooth mousewheel
        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
        
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Bind mousewheel when entering the settings content area
        content_frame.bind("<Enter>", lambda e: self._bind_smooth_scroll(canvas, scrollable_frame))

        # Scroll helper
        def scroll_to_widget(widget):
             try:
                 # Force update to get accurate coords
                 scrollable_frame.update_idletasks()
                 canvas.update_idletasks()
                 
                 # Get widget position relative to scrollable_frame
                 widget_y = widget.winfo_y()
                 canvas_height = canvas.winfo_height()
                 
                 # Get total content height
                 scrollable_frame.update_idletasks()
                 total_height = scrollable_frame.winfo_reqheight()
                 
                 # Only scroll if content is taller than canvas
                 if total_height > canvas_height:
                     # Calculate position to show widget near top (with 20px offset)
                     target_y = max(0, widget_y - 20)
                     
                     # Convert to fraction (0.0 to 1.0)
                     scrollable_height = total_height - canvas_height
                     if scrollable_height > 0:
                         fraction = target_y / scrollable_height
                         fraction = max(0.0, min(1.0, fraction))
                         canvas.yview_moveto(fraction)
                 else:
                     # Content fits in view, scroll to top
                     canvas.yview_moveto(0)
             except Exception as e:
                 print(f"Scroll error: {e}")

        # Nav Buttons logic
        def create_nav_btn(text, target_widget):
            btn = tk.Button(nav_frame, text=text, font=("Segoe UI", 10),
                           bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'],
                           relief="flat", anchor="w", padx=20, pady=8,
                           cursor="hand2",
                           command=lambda w=target_widget: scroll_to_widget(w))
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

        # --- APPEARANCE ---
        lbl_appear = tk.Label(main_container, text="LAUNCHER APPEARANCE", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        lbl_appear.pack(anchor="w", pady=(10, 15))
        
        self.custom_titlebar_var = tk.BooleanVar(value=getattr(self, 'custom_titlebar_enabled', True))
        def on_titlebar_toggle():
             # Requires restart
             val = self.custom_titlebar_var.get()
             self.custom_titlebar_enabled = val
             self.save_config()
             if hasattr(self, 'root'):
                 custom_showinfo("Restart Required", "Please restart the launcher to apply changes to the titlebar.")

        tk.Checkbutton(main_container, text="Use Custom Titlebar (Windows only)", variable=self.custom_titlebar_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=on_titlebar_toggle).pack(anchor="w", pady=(0, 5))

        self.neo_style_var = tk.BooleanVar(value=getattr(self, 'neo_style_enabled', True))
        def on_neo_toggle():
             val = self.neo_style_var.get()
             self.neo_style_enabled = val
             self.save_config()
             if hasattr(self, 'root'):
                 custom_showinfo("Restart Required", "Please restart the launcher to apply Neo Style changes.")

        tk.Checkbutton(main_container, text="Use Neo Style (OLED Black Theme)", variable=self.neo_style_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=on_neo_toggle).pack(anchor="w", pady=(0, 15))
        
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

            btn = tk.Button(f, bg=col, width=6, height=2, relief="flat", bd=0, cursor="hand2",
                           command=lambda n=name: set_accent(n))
            # Hover — lighten slightly
            _hov = col
            btn.config(activebackground=col)
            btn.bind("<Enter>", lambda e, b=btn, c=col: b.config(relief="solid", bd=1))
            btn.bind("<Leave>", lambda e, b=btn: b.config(relief="flat", bd=0))
            btn.pack()

        # Review Onboarding
        tk.Label(main_container, text="Onboarding", font=("Segoe UI", 10),
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(10, 5))
                
        self._make_btn(main_container, "Review setup wizard", style="secondary", font_size=9,
                      command=lambda: self.show_onboarding_wizard()).pack(anchor="w")

        # --- JAVA SETTINGS ---
        lbl_java = tk.Label(main_container, text="JAVA SETTINGS", font=("Segoe UI", 14, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        lbl_java.pack(anchor="w", pady=(30, 15))
        
        # Minecraft Directory
        tk.Label(main_container, text="Minecraft Directory", font=("Segoe UI", 10),
                bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        
        dir_frame = tk.Frame(main_container, bg=COLORS['main_bg'])
        dir_frame.pack(fill="x", pady=(5, 15))
        
        self.dir_entry = tk.Entry(dir_frame, font=("Segoe UI", 10),
                                 bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                                 relief="flat", insertbackground="white")
        self.dir_entry.pack(side="left", fill="x", expand=True, ipady=5)
        
        self._make_btn(dir_frame, "Change", style="secondary", font_size=9,
                      command=self.change_minecraft_dir).pack(side="left", padx=(10, 0))

        self._make_btn(dir_frame, "Open", style="secondary", font_size=9,
                      command=self.open_minecraft_dir).pack(side="left", padx=(5, 0)) # type: ignore

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
        self.user_entry.config(show="*" if self._is_streamer_mode_enabled() else "")
        self.user_entry.pack(fill="x", pady=(5, 0), ipady=8)
        self.user_entry.bind("<FocusOut>", self.save_config)

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
        
        self._make_btn(update_frame, "Check for Updates", style="secondary", font_size=9,
                      command=self.check_for_updates).pack(side="left")

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
        
        self._make_btn(main_container, "Reset to Defaults", style="danger", font_size=9, bold=True,
                      command=self.reset_to_defaults).pack(anchor="w")

        # Initial binding
        self._bind_smooth_scroll(canvas, scrollable_frame)
        
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
        
        # Auto-hide scrollbar when not needed
        def update_scrollbar_visibility(*args):
            try:
                scroll_frame.update_idletasks()
                canvas.update_idletasks()
                content_height = scroll_frame.winfo_reqheight()
                canvas_height = canvas.winfo_height()
                
                if content_height > canvas_height:
                    scrollbar.pack(side="right", fill="y")
                else:
                    scrollbar.pack_forget()
            except:
                pass
        
        # Preserve the scrollregion updater when tracking scrollbar visibility;
        # replacing this binding made Addons appear to stop scrolling whenever
        # a collapsible card changed height.
        canvas.bind("<Configure>", lambda e: [on_canvas_configure(e), update_scrollbar_visibility()])
        scroll_frame.bind("<Configure>", lambda e: update_scrollbar_visibility(), add="+")

        self.addons_canvas = canvas
        self.addons_scroll_frame = scroll_frame
        self._addons_update_scrollbar_visibility = update_scrollbar_visibility

        # Smooth mousewheel
        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")

        # Keep wheel scrolling active anywhere over the Addons page content.
        for bind_target in (frame, canvas, scroll_frame):
            bind_target.bind("<Enter>", lambda e, c=canvas, sf=scroll_frame: self._bind_smooth_scroll(c, sf))
        
        # --- content ---
        content = tk.Frame(scroll_frame, bg=COLORS['main_bg'], padx=30, pady=10)
        content.pack(fill="x")
        content.bind("<Enter>", lambda e, c=canvas, ct=content: self._bind_smooth_scroll(c, ct))
        self.addons_content_frame = content

        if not hasattr(self, '_addons_collapsible_state'):
            self._addons_collapsible_state = {}

        def create_collapsible_card(parent, title, subtitle, state_key, default_open=True, title_badge_text=None, title_badge_fg=None):
            card = tk.Frame(parent, bg=COLORS['card_bg'], padx=20, pady=20)
            card.pack(fill="x", pady=(0, 20))

            is_open = bool(self._addons_collapsible_state.get(state_key, default_open))
            body = tk.Frame(card, bg=COLORS['card_bg'])
            icon_font = ("Segoe UI Symbol", 13, "bold")
            icon_open = "⌄"
            icon_closed = "›"

            header = tk.Frame(card, bg=COLORS['card_bg'], cursor="hand2")
            header.pack(fill="x")

            text_wrap = tk.Frame(header, bg=COLORS['card_bg'])
            text_wrap.pack(side="left", fill="x", expand=True)

            icon_wrap = tk.Frame(header, bg=COLORS['card_bg'])
            icon_wrap.pack(side="right", anchor="ne")
            chevron = tk.Label(
                icon_wrap,
                text=icon_open if is_open else icon_closed,
                font=icon_font,
                bg=COLORS['card_bg'],
                fg=COLORS['text_primary'],
                cursor="hand2",
                anchor="ne",
            )
            chevron.pack(anchor="ne")

            title_row = tk.Frame(text_wrap, bg=COLORS['card_bg'])
            title_row.pack(anchor="w", fill="x")
            title_lbl = tk.Label(title_row, text=title, font=("Segoe UI", 16, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary'], anchor="w", cursor="hand2")
            title_lbl.pack(side="left", anchor="w")
            badge_lbl = None
            if title_badge_text:
                badge_lbl = tk.Label(
                    title_row,
                    text=title_badge_text,
                    font=("Segoe UI", 15, "bold"),
                    bg=COLORS['card_bg'],
                    fg=title_badge_fg or COLORS['accent_blue'],
                    anchor="w",
                    cursor="hand2",
                )
                badge_lbl.pack(side="left", padx=(8, 0), anchor="w")
            subtitle_lbl = tk.Label(text_wrap, text=subtitle, font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary'], anchor="w", cursor="hand2")
            subtitle_lbl.pack(anchor="w", pady=(4, 0))

            def toggle_section(_event=None):
                is_now_open = not bool(self._addons_collapsible_state.get(state_key, default_open))
                self._addons_collapsible_state[state_key] = is_now_open
                chevron.config(text=icon_open if is_now_open else icon_closed)
                if is_now_open:
                    body.pack(fill="x", pady=(15, 0))
                else:
                    body.pack_forget()

            bind_widgets = [header, text_wrap, title_row, icon_wrap, title_lbl, subtitle_lbl, chevron]
            if badge_lbl is not None:
                bind_widgets.append(badge_lbl)
            for widget in bind_widgets:
                widget.bind("<Button-1>", toggle_section)

            if is_open:
                body.pack(fill="x", pady=(15, 0))

            return card, body

        self._addons_create_collapsible_card = create_collapsible_card

        # Playtime Tracker
        playtime_frame = tk.Frame(content, bg=COLORS['card_bg'], padx=20, pady=20)
        playtime_frame.pack(fill="x", pady=(0, 20))
        tk.Label(playtime_frame, text="Playtime Tracker", font=("Segoe UI", 16, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 5))
        tk.Label(playtime_frame, text="Tracks session time and launch counts for each installation.", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")

        playtime_summary = tk.Frame(playtime_frame, bg=COLORS['card_bg'])
        playtime_summary.pack(fill="x", pady=(15, 12))
        self.playtime_total_lbl = tk.Label(playtime_summary, text="Total Time: 0m", font=("Segoe UI", 11, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary'])
        self.playtime_total_lbl.pack(side="left")
        self.playtime_launches_lbl = tk.Label(playtime_summary, text="Launches: 0", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary'])
        self.playtime_launches_lbl.pack(side="left", padx=(18, 0))
        self._make_btn(playtime_summary, "Reset Stats", style="secondary", font_size=9, command=self.reset_playtime_tracker).pack(side="right")

        self.playtime_list_frame = tk.Frame(playtime_frame, bg=COLORS['card_bg'])
        self.playtime_list_frame.pack(fill="x")

        # GitHub Skin Sync
        _sync_card, sync_frame = create_collapsible_card(
            content,
            "GitHub Skin Sync",
            "Link a GitHub repository to sync skins with your friends.",
            "github_skin_sync",
            default_open=False,
        )

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
        self.gh_repo_entry.grid(row=0, column=1, sticky="ew", padx=10, ipady=5)

        # Token
        tk.Label(grid_frame, text="Access Token (PAT):", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).grid(row=1, column=0, sticky="w", pady=5)
        self.gh_token_entry = tk.Entry(grid_frame, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg="white", relief="flat", show="*")
        self.gh_token_entry.grid(row=1, column=1, sticky="ew", padx=10, ipady=5)
        
        # Save Button
        save_sync_btn = self._make_btn(sync_frame, "Save & Sync", style="secondary", font_size=10,
                                       command=self._save_gh_sync_settings)
        save_sync_btn.config(bg=COLORS['accent_blue'], activebackground="#2E86C1")
        save_sync_btn.bind("<Enter>", lambda e: save_sync_btn.config(bg="#2E86C1"))
        save_sync_btn.bind("<Leave>", lambda e: save_sync_btn.config(bg=COLORS['accent_blue']))
        save_sync_btn.pack(anchor="w", pady=(20, 0))

        # Streamer Mode
        _streamer_card, streamer_frame = create_collapsible_card(
            content,
            "Streamer Mode",
            "Hide your account name across launcher-controlled surfaces while keeping the real server username.",
            "streamer_mode",
            default_open=False,
        )

        self.streamer_mode_var = tk.BooleanVar(value=bool(self.addons_config.get("streamer_mode_enabled", False)))
        tk.Checkbutton(
            streamer_frame,
            text="Hide my username locally in the launcher and game-adjacent overlays",
            variable=self.streamer_mode_var,
            bg=COLORS['card_bg'],
            fg=COLORS['text_primary'],
            selectcolor=COLORS['card_bg'],
            activebackground=COLORS['card_bg'],
            command=self._save_streamer_mode_settings,
        ).pack(anchor="w")
        tk.Label(
            streamer_frame,
            text="This masks launcher UI, local logs, and Discord/status surfaces we control. Your real username is still used for launches and servers.",
            font=("Segoe UI", 9),
            bg=COLORS['card_bg'],
            fg=COLORS['text_secondary'],
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        # Server Quick Join
        _server_card, server_frame = create_collapsible_card(
            content,
            "Server Quick Join",
            "Save favorite servers and launch directly into them.",
            "server_quick_join",
            default_open=True,
        )

        install_row = tk.Frame(server_frame, bg=COLORS['card_bg'])
        install_row.pack(fill="x", pady=(0, 12))
        tk.Label(install_row, text="Installation", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(side="left")
        self.quick_join_install_var = tk.StringVar()
        self.quick_join_install_combo = ttk.Combobox(install_row, textvariable=self.quick_join_install_var, state="readonly", style="Launcher.TCombobox", width=36)
        self.quick_join_install_combo.pack(side="left", padx=(10, 0), fill="x", expand=True)

        server_form = tk.Frame(server_frame, bg=COLORS['card_bg'])
        server_form.pack(fill="x")
        server_form.columnconfigure(1, weight=1)

        self.quick_join_name_var = tk.StringVar()
        self.quick_join_address_var = tk.StringVar()
        self.quick_join_port_var = tk.StringVar(value="25565")

        tk.Label(server_form, text="Name", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).grid(row=0, column=0, sticky="w", pady=5)
        tk.Entry(server_form, textvariable=self.quick_join_name_var, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg="white", relief="flat").grid(row=0, column=1, sticky="ew", ipady=5)
        tk.Label(server_form, text="Address", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).grid(row=1, column=0, sticky="w", pady=5)
        tk.Entry(server_form, textvariable=self.quick_join_address_var, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg="white", relief="flat").grid(row=1, column=1, sticky="ew", ipady=5)
        tk.Label(server_form, text="Port", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).grid(row=2, column=0, sticky="w", pady=5)
        tk.Entry(server_form, textvariable=self.quick_join_port_var, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg="white", relief="flat", width=12).grid(row=2, column=1, sticky="w", ipady=5)

        self._make_btn(server_frame, "Save Server", style="primary", font_size=10, bold=True, command=self.add_quick_join_server).pack(anchor="w", pady=(14, 0))
        self.saved_servers_list_frame = tk.Frame(server_frame, bg=COLORS['card_bg'])
        self.saved_servers_list_frame.pack(fill="x", pady=(14, 0))

        # Screenshot Browser
        _screenshot_card, screenshot_frame = create_collapsible_card(
            content,
            "Screenshot Browser",
            "Browse recent screenshots from your Minecraft directory.",
            "screenshot_browser",
            default_open=False,
        )

        screenshot_actions = tk.Frame(screenshot_frame, bg=COLORS['card_bg'])
        screenshot_actions.pack(fill="x", pady=(0, 12))
        self.screenshot_status_lbl = tk.Label(screenshot_actions, text="", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary'])
        self.screenshot_status_lbl.pack(side="left")
        self._make_btn(screenshot_actions, "Refresh", style="secondary", font_size=9, command=self.render_screenshot_browser).pack(side="right")
        self._make_btn(screenshot_actions, "Open Folder", style="secondary", font_size=9, command=lambda: self._open_path(self.get_screenshots_dir())).pack(side="right", padx=(0, 8))

        self.screenshot_grid_frame = tk.Frame(screenshot_frame, bg=COLORS['card_bg'])
        self.screenshot_grid_frame.pack(fill="x")

        third_party_top = tk.Frame(content, bg=COLORS['main_bg'])
        third_party_top.pack(fill="x", pady=(0, 8))
        self.third_party_addons_status_lbl = tk.Label(
            third_party_top,
            text="",
            font=("Segoe UI", 9),
            bg=COLORS['main_bg'],
            fg=COLORS['text_secondary'],
        )
        self.third_party_addons_status_lbl.pack(side="left")
        self._make_btn(
            third_party_top,
            "Refresh",
            style="secondary",
            font_size=9,
            command=self.refresh_third_party_addons,
        ).pack(side="right")
        self._make_btn(
            third_party_top,
            "Open Folder",
            style="secondary",
            font_size=9,
            command=self.open_third_party_addons_folder,
        ).pack(side="right", padx=(0, 8))

        self.third_party_addons_path_lbl = tk.Label(
            content,
            text="",
            font=("Consolas", 8),
            bg=COLORS['main_bg'],
            fg=COLORS['text_secondary'],
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.third_party_addons_path_lbl.pack(fill="x", pady=(0, 12))

        self.third_party_addons_cards_frame = tk.Frame(content, bg=COLORS['main_bg'])
        self.third_party_addons_cards_frame.pack(fill="x")

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

        self._bind_smooth_scroll(canvas, scroll_frame)
        self._bind_smooth_scroll(canvas, content)
        update_scrollbar_visibility()
        self.refresh_addons_tab_state()

    def _ensure_addons_config_defaults(self):
        self.addons_config = addon_normalize_config(getattr(self, "addons_config", {}))

    def _refresh_addons_scroll_bindings(self):
        canvas = getattr(self, "addons_canvas", None)
        scroll_frame = getattr(self, "addons_scroll_frame", None)
        content = getattr(self, "addons_content_frame", None)
        if not canvas or not scroll_frame or not content:
            return

        try:
            self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
            self._bind_smooth_scroll(canvas, scroll_frame)
            self._bind_smooth_scroll(canvas, content)
            update_scrollbar_visibility = getattr(self, "_addons_update_scrollbar_visibility", None)
            if callable(update_scrollbar_visibility):
                update_scrollbar_visibility()
        except Exception:
            pass

    def _get_installation_display_label(self, inst):
        return f"{inst.get('name', 'Unnamed')} • {inst.get('loader', 'Vanilla')} {inst.get('version', 'latest-release')}"

    def _is_streamer_mode_enabled(self):
        return bool(getattr(self, "addons_config", {}).get("streamer_mode_enabled", False))

    def _get_streamer_safe_name(self, name=None):
        if not self._is_streamer_mode_enabled():
            return str(name or "Steve")
        return _get_streamer_hidden_name()

    def _mask_streamer_text(self, text):
        if not self._is_streamer_mode_enabled():
            return text
        masked_text = str(text)
        for profile in getattr(self, "profiles", []):
            name = str(profile.get("name", "")).strip()
            if name:
                masked_text = masked_text.replace(name, _get_streamer_hidden_name())
        return masked_text

    def _apply_streamer_mode_ui(self):
        try:
            if hasattr(self, 'user_entry') and self.user_entry.winfo_exists():
                self.user_entry.config(show="*" if self._is_streamer_mode_enabled() else "")
        except Exception:
            pass

        try:
            self.update_profile_btn()
        except Exception:
            pass

        try:
            if hasattr(self, 'update_bottom_gamertag'):
                self.update_bottom_gamertag()
        except Exception:
            pass

        try:
            if hasattr(self, 'profile_menu') and self.profile_menu and self.profile_menu.winfo_exists():
                self.profile_menu.destroy()
                self.profile_menu = None
        except Exception:
            pass

        try:
            if getattr(self, "rpc_connected", False) and getattr(self, "rpc", None):
                self.update_rpc(
                    getattr(self, "_last_rpc_state", "Idle"),
                    getattr(self, "_last_rpc_details", "In Launcher"),
                    getattr(self, "_last_rpc_start", None),
                )
        except Exception:
            pass

    def _save_streamer_mode_settings(self):
        self._ensure_addons_config_defaults()
        enabled = bool(self.streamer_mode_var.get()) if hasattr(self, 'streamer_mode_var') else False
        self.addons_config = addon_set_streamer_mode(self.addons_config, enabled)
        self._apply_streamer_mode_ui()
        self.save_config(sync_ui=False)

    def _refresh_quick_join_installation_values(self):
        if not hasattr(self, 'quick_join_install_combo'):
            return
        labels = {}
        values = []
        for idx, inst in enumerate(self.installations):
            label = self._get_installation_display_label(inst)
            values.append(label)
            labels[label] = idx
        self.quick_join_installation_labels = labels
        self.quick_join_install_combo.config(values=values, state="readonly" if values else "disabled")

        selected = self.quick_join_install_var.get() if hasattr(self, 'quick_join_install_var') else ""
        if selected in labels:
            return

        fallback = ""
        current_idx = getattr(self, 'current_installation_index', 0)
        if 0 <= current_idx < len(values):
            fallback = values[current_idx]
        elif values:
            fallback = values[0]
        self.quick_join_install_var.set(fallback)

    def _format_duration(self, total_seconds):
        total_seconds = max(0, int(total_seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _seconds = divmod(remainder, 60)
        if hours and minutes:
            return f"{hours}h {minutes}m"
        if hours:
            return f"{hours}h"
        return f"{minutes}m"

    def _format_timestamp_short(self, iso_value):
        if not iso_value:
            return "Never"
        try:
            return datetime.fromisoformat(str(iso_value)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(iso_value)

    def render_playtime_tracker(self):
        if not hasattr(self, 'playtime_list_frame'):
            return

        self._ensure_addons_config_defaults()
        for widget in self.playtime_list_frame.winfo_children():
            widget.destroy()

        tracker = self.addons_config.get("playtime_tracker", {})
        total_seconds = 0
        total_launches = 0
        entries = []
        installations_by_id = {
            inst.get("id"): inst for inst in self.installations if inst.get("id")
        }

        for inst_id, stats in tracker.items():
            if not isinstance(stats, dict):
                continue
            seconds = int(stats.get("seconds", 0) or 0)
            launches = int(stats.get("launches", 0) or 0)
            total_seconds += seconds
            total_launches += launches
            inst = installations_by_id.get(inst_id, {"name": "Unknown Installation", "loader": "-", "version": "-"})
            entries.append((inst_id, inst, stats, seconds, launches))

        self.playtime_total_lbl.config(text=f"Total Time: {self._format_duration(total_seconds)}")
        self.playtime_launches_lbl.config(text=f"Launches: {total_launches}")

        if not entries:
            tk.Label(self.playtime_list_frame, text="No tracked play sessions yet. Launch a game to start collecting stats.", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
            self._refresh_addons_scroll_bindings()
            return

        entries.sort(key=lambda item: item[3], reverse=True)
        for _inst_id, inst, stats, seconds, launches in entries:
            row = tk.Frame(self.playtime_list_frame, bg=COLORS['card_bg'], pady=8)
            row.pack(fill="x")
            left = tk.Frame(row, bg=COLORS['card_bg'])
            left.pack(side="left", fill="x", expand=True)
            tk.Label(left, text=inst.get("name", "Unknown Installation"), font=("Segoe UI", 10, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(anchor="w")
            tk.Label(left, text=f"{inst.get('loader', 'Vanilla')} {inst.get('version', 'latest-release')}  •  Last Played: {self._format_timestamp_short(stats.get('last_played_at'))}", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")

            right = tk.Frame(row, bg=COLORS['card_bg'])
            right.pack(side="right")
            tk.Label(right, text=self._format_duration(seconds), font=("Segoe UI", 10, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(anchor="e")
            tk.Label(right, text=f"{launches} launches", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="e")

        self._refresh_addons_scroll_bindings()

    def reset_playtime_tracker(self):
        if not custom_askyesno("Reset Playtime", "Clear all tracked playtime and launch counts?", parent=self.root):
            return
        self._ensure_addons_config_defaults()
        self.addons_config = addon_reset_playtime_tracker(self.addons_config)
        self.save_config(sync_ui=False)
        self.render_playtime_tracker()

    def _record_play_session(self, inst_id, session_seconds, server_address=None, server_port=None):
        if not inst_id:
            return
        self._ensure_addons_config_defaults()
        self.addons_config = addon_record_play_session(
            self.addons_config,
            inst_id,
            session_seconds,
            server_address=server_address,
            server_port=server_port,
        )

        for inst in self.installations:
            if inst.get("id") == inst_id:
                inst["last_played"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                break

        self.save_config(sync_ui=False)
        self.render_playtime_tracker()

    def add_quick_join_server(self):
        self._ensure_addons_config_defaults()
        name = self.quick_join_name_var.get().strip() if hasattr(self, 'quick_join_name_var') else ""
        address = self.quick_join_address_var.get().strip() if hasattr(self, 'quick_join_address_var') else ""
        port = self.quick_join_port_var.get().strip() if hasattr(self, 'quick_join_port_var') else "25565"

        try:
            self.addons_config = addon_add_saved_server(self.addons_config, name, address, port)
        except ValueError as e:
            title = "Missing Address" if "address" in str(e).lower() else "Invalid Port"
            custom_showerror(title, str(e), parent=self.root)
            return

        self.quick_join_name_var.set("")
        self.quick_join_address_var.set("")
        self.quick_join_port_var.set("25565")
        self.save_config(sync_ui=False)
        self.render_quick_join_servers()

    def remove_quick_join_server(self, server_id):
        self._ensure_addons_config_defaults()
        self.addons_config = addon_remove_saved_server(self.addons_config, server_id)
        self.save_config(sync_ui=False)
        self.render_quick_join_servers()

    def launch_saved_server(self, server_data):
        if not self.installations:
            custom_showerror("No Installation", "Create an installation before using Quick Join.", parent=self.root)
            return

        self._refresh_quick_join_installation_values()
        selected_label = self.quick_join_install_var.get() if hasattr(self, 'quick_join_install_var') else ""
        install_idx = self.quick_join_installation_labels.get(selected_label, getattr(self, 'current_installation_index', 0))
        if install_idx is None or not (0 <= install_idx < len(self.installations)):
            custom_showerror("Invalid Installation", "Select a valid installation for Quick Join.", parent=self.root)
            return

        self.launch_installation(
            install_idx,
            server_address=str(server_data.get("address", "")).strip(),
            server_port=server_data.get("port"),
        )

    def render_quick_join_servers(self):
        if not hasattr(self, 'saved_servers_list_frame'):
            return

        self._ensure_addons_config_defaults()
        for widget in self.saved_servers_list_frame.winfo_children():
            widget.destroy()

        saved_servers = self.addons_config.get("saved_servers", [])
        if not saved_servers:
            tk.Label(self.saved_servers_list_frame, text="No saved servers yet.", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
            self._refresh_addons_scroll_bindings()
            return

        for server in saved_servers:
            row = tk.Frame(self.saved_servers_list_frame, bg=COLORS['card_bg'], pady=8)
            row.pack(fill="x")
            info = tk.Frame(row, bg=COLORS['card_bg'])
            info.pack(side="left", fill="x", expand=True)
            port = server.get("port", 25565)
            tk.Label(info, text=server.get("name", "Unnamed Server"), font=("Segoe UI", 10, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(anchor="w")
            tk.Label(info, text=f"{server.get('address', '')}:{port}", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")

            btns = tk.Frame(row, bg=COLORS['card_bg'])
            btns.pack(side="right")
            self._make_btn(btns, "Join", style="primary", font_size=9, bold=True, command=lambda s=server: self.launch_saved_server(s)).pack(side="left", padx=(0, 6))
            self._make_btn(btns, "Delete", style="secondary", font_size=9, command=lambda sid=server.get("id"): self.remove_quick_join_server(sid)).pack(side="left")

        self._refresh_addons_scroll_bindings()

    def get_screenshots_dir(self):
        return os.path.join(self.minecraft_dir, "screenshots")

    def get_third_party_addons_dir(self):
        addons_dir = os.path.join(self.config_dir, "addons")
        try:
            os.makedirs(addons_dir, exist_ok=True)
        except Exception:
            pass
        return addons_dir

    def open_third_party_addons_folder(self):
        self._open_path(self.get_third_party_addons_dir())

    def refresh_third_party_addons(self):
        if not hasattr(self, 'third_party_addons_cards_frame'):
            return

        addons_dir = self.get_third_party_addons_dir()
        if hasattr(self, 'third_party_addons_path_lbl'):
            self.third_party_addons_path_lbl.config(text=f"Folder: {addons_dir}")
        if hasattr(self, 'third_party_addons_status_lbl'):
            self.third_party_addons_status_lbl.config(text="Scanning third-party addons...")
        self._show_skeleton_list(self.third_party_addons_cards_frame, rows=2, card_height=82, padx=0, pady=6)
        self._refresh_addons_scroll_bindings()

        payload = {
            "minecraft_dir": self.minecraft_dir,
        }
        self.send_agent_request("list_third_party_addons", payload, self._on_third_party_addons_loaded)

    def _on_third_party_addons_loaded(self, result):
        if not isinstance(result, dict):
            if hasattr(self, 'third_party_addons_status_lbl'):
                self.third_party_addons_status_lbl.config(text="Failed to load third-party addons.")
            return

        if result.get("status") != "success":
            if hasattr(self, 'third_party_addons_status_lbl'):
                self.third_party_addons_status_lbl.config(text=str(result.get("msg", "Failed to load third-party addons.")))
            self.third_party_addons = []
            self.render_third_party_addons()
            return

        data = result.get("data", {})
        if isinstance(data, dict):
            self.third_party_addons = data.get("addons", []) if isinstance(data.get("addons"), list) else []
            if hasattr(self, 'third_party_addons_path_lbl'):
                self.third_party_addons_path_lbl.config(text=f"Folder: {data.get('addons_dir', self.get_third_party_addons_dir())}")
        else:
            self.third_party_addons = []

        addon_count = len(self.third_party_addons)
        if hasattr(self, 'third_party_addons_status_lbl'):
            self.third_party_addons_status_lbl.config(text=f"{addon_count} addon{'s' if addon_count != 1 else ''} detected.")
        self.render_third_party_addons()

    def _coerce_third_party_addon_input(self, input_type, var):
        if input_type == "checkbox":
            return bool(var.get())
        if input_type == "number":
            raw = str(var.get()).strip()
            if not raw:
                return ""
            try:
                if "." in raw:
                    return float(raw)
                return int(raw)
            except Exception:
                return raw
        return str(var.get())

    def run_third_party_addon_action(self, addon_data, action_data):
        addon_id = str(addon_data.get("id", "")).strip()
        action_id = str(action_data.get("id", "")).strip()
        if not addon_id or not action_id:
            return

        inputs = {}
        input_map = self.third_party_addon_input_vars.get((addon_id, action_id), {})
        for input_id, data in input_map.items():
            inputs[input_id] = self._coerce_third_party_addon_input(data.get("type"), data.get("var"))

        if hasattr(self, 'third_party_addons_status_lbl'):
            self.third_party_addons_status_lbl.config(text=f"Running {addon_data.get('name', addon_id)}...")

        payload = {
            "addon_id": addon_id,
            "action_id": action_id,
            "inputs": inputs,
            "minecraft_dir": self.minecraft_dir,
        }
        self.send_agent_request(
            "run_third_party_addon_action",
            payload,
            lambda result, addon=addon_data, action=action_data: self._on_third_party_addon_action_result(addon, action, result),
        )

    def _on_third_party_addon_action_result(self, addon_data, action_data, result):
        addon_name = str(addon_data.get("name", addon_data.get("id", "Addon")))
        action_label = str(action_data.get("label", action_data.get("id", "Action")))

        if not isinstance(result, dict):
            custom_showerror("Addon Error", f"{addon_name} returned an invalid response.")
            return

        status = result.get("status")
        message = str(result.get("msg", "") or "")
        extra_data = result.get("data", {})

        if hasattr(self, 'third_party_addons_status_lbl'):
            if status == "success":
                self.third_party_addons_status_lbl.config(text=f"{addon_name}: {message or 'Completed successfully.'}")
            else:
                self.third_party_addons_status_lbl.config(text=f"{addon_name}: {message or 'Action failed.'}")

        if isinstance(extra_data, dict):
            open_path = extra_data.get("open_path")
            open_url = extra_data.get("open_url")
            if open_path:
                self._open_path(str(open_path))
            if open_url:
                webbrowser.open(str(open_url))
            if extra_data.get("refresh_addons"):
                self.refresh_third_party_addons()

        if status == "success":
            if message:
                custom_showinfo(f"{addon_name} - {action_label}", message, parent=self.root)
        else:
            custom_showerror(f"{addon_name} - {action_label}", message or "Action failed.", parent=self.root)

    def render_third_party_addons(self):
        if not hasattr(self, 'third_party_addons_cards_frame'):
            return

        for widget in self.third_party_addons_cards_frame.winfo_children():
            widget.destroy()
        self.third_party_addon_input_vars = {}

        addons = self.third_party_addons if isinstance(self.third_party_addons, list) else []
        if not addons:
            tk.Label(
                self.third_party_addons_cards_frame,
                text="No third-party addons found yet. Drop addon folders here and click Refresh.",
                font=("Segoe UI", 10),
                bg=COLORS['main_bg'],
                fg=COLORS['text_secondary'],
                justify="left",
                wraplength=760,
            ).pack(anchor="w")
            self._refresh_addons_scroll_bindings()
            return

        create_card = getattr(self, "_addons_create_collapsible_card", None)
        if not callable(create_card):
            return

        for addon in addons:
            addon_name = str(addon.get("name", addon.get("id", "Addon")))
            addon_version = str(addon.get("version", "0.0.0"))
            addon_id = str(addon.get("id", addon_name)).strip() or addon_name
            card, body = create_card(
                self.third_party_addons_cards_frame,
                addon_name,
                str(addon.get("description", "Third-party addon")),
                f"third_party_addon::{addon_id}",
                default_open=False,
                title_badge_text="+",
                title_badge_fg=COLORS['accent_blue'],
            )

            meta_text = f"By {addon.get('author', 'Unknown')}"
            tk.Label(
                body,
                text=f"{meta_text}  •  v{addon_version}",
                font=("Segoe UI", 9),
                bg=COLORS['card_bg'],
                fg=COLORS['text_secondary'],
                anchor="w",
            ).pack(fill="x")

            if addon.get("load_error"):
                tk.Label(
                    body,
                    text=f"Load Error:\n{addon.get('load_error')}",
                    font=("Consolas", 8),
                    bg=COLORS['card_bg'],
                    fg=COLORS['error_red'],
                    justify="left",
                    wraplength=740,
                    anchor="w",
                ).pack(fill="x", pady=(10, 0))
                continue

            actions = addon.get("actions", [])
            if not isinstance(actions, list) or not actions:
                tk.Label(
                    body,
                    text="This addon does not expose any launcher actions.",
                    font=("Segoe UI", 9),
                    bg=COLORS['card_bg'],
                    fg=COLORS['text_secondary'],
                    anchor="w",
                ).pack(fill="x", pady=(10, 0))
                continue

            for action in actions:
                action_frame = tk.Frame(body, bg=COLORS['card_bg'])
                action_frame.pack(fill="x", pady=(10, 0))

                tk.Label(
                    action_frame,
                    text=str(action.get("label", action.get("id", "Action"))),
                    font=("Segoe UI", 9, "bold"),
                    bg=COLORS['card_bg'],
                    fg=COLORS['text_primary'],
                    anchor="w",
                ).pack(fill="x")

                if action.get("description"):
                    tk.Label(
                        action_frame,
                        text=str(action.get("description", "")),
                        font=("Segoe UI", 8),
                        bg=COLORS['card_bg'],
                        fg=COLORS['text_secondary'],
                        justify="left",
                        wraplength=720,
                        anchor="w",
                    ).pack(fill="x", pady=(2, 6))

                action_inputs = {}
                for input_spec in action.get("inputs", []) or []:
                    input_id = str(input_spec.get("id", "")).strip()
                    input_type = str(input_spec.get("type", "text")).strip().lower()
                    label = str(input_spec.get("label", input_id))

                    if input_type == "checkbox":
                        var = tk.BooleanVar(value=bool(input_spec.get("default", False)))
                        tk.Checkbutton(
                            action_frame,
                            text=label,
                            variable=var,
                            bg=COLORS['card_bg'],
                            fg=COLORS['text_primary'],
                            selectcolor=COLORS['card_bg'],
                            activebackground=COLORS['card_bg'],
                        ).pack(anchor="w", pady=(2, 4))
                    else:
                        tk.Label(
                            action_frame,
                            text=label,
                            font=("Segoe UI", 8),
                            bg=COLORS['card_bg'],
                            fg=COLORS['text_secondary'],
                            anchor="w",
                        ).pack(fill="x")
                        var = tk.StringVar(value=str(input_spec.get("default", "")))
                        entry = tk.Entry(
                            action_frame,
                            textvariable=var,
                            font=("Segoe UI", 9),
                            bg=COLORS['input_bg'],
                            fg="white",
                            relief="flat",
                            insertbackground="white",
                            show="*" if input_type == "password" else "",
                        )
                        entry.pack(fill="x", ipady=5, pady=(2, 6))

                    action_inputs[input_id] = {"type": input_type, "var": var}

                self.third_party_addon_input_vars[(str(addon.get("id", "")), str(action.get("id", "")))] = action_inputs
                self._make_btn(
                    action_frame,
                    str(action.get("label", "Run")),
                    style=str(action.get("style", "secondary")),
                    font_size=9,
                    bold=True,
                    command=lambda addon_data=addon, action_data=action: self.run_third_party_addon_action(addon_data, action_data),
                ).pack(anchor="w", pady=(2, 0))

        self._refresh_addons_scroll_bindings()

    def _open_path(self, path):
        try:
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path], close_fds=True)
            else:
                subprocess.Popen(["xdg-open", path], close_fds=True)
        except Exception as e:
            custom_showerror("Open Failed", f"Could not open:\n{path}\n\n{e}", parent=self.root)

    def _list_screenshot_files(self):
        return addon_list_screenshot_files(self.minecraft_dir).get("items", [])

    def _get_screenshot_thumbnail(self, path, size=(170, 96)):
        try:
            mtime = os.path.getmtime(path)
            cache_key = (path, mtime, size)
            if cache_key in self.screenshot_thumbnail_cache:
                return self.screenshot_thumbnail_cache[cache_key]

            img = Image.open(path).convert("RGB")
            img.thumbnail(size, Image.Resampling.LANCZOS)
            background = Image.new("RGB", size, COLORS.get('input_bg', '#1A1A1A'))
            offset_x = max(0, (size[0] - img.width) // 2)
            offset_y = max(0, (size[1] - img.height) // 2)
            background.paste(img, (offset_x, offset_y))
            photo = ImageTk.PhotoImage(background)
            self.screenshot_thumbnail_cache[cache_key] = photo
            return photo
        except Exception:
            return None

    def delete_screenshot(self, path):
        if not custom_askyesno("Delete Screenshot", f"Delete '{os.path.basename(path)}'?", parent=self.root):
            return
        try:
            addon_delete_screenshot(path, self.minecraft_dir)
            self.save_config(sync_ui=False)
            self.render_screenshot_browser()
        except Exception as e:
            custom_showerror("Delete Failed", f"Could not delete screenshot:\n{e}", parent=self.root)

    def render_screenshot_browser(self):
        if not hasattr(self, 'screenshot_grid_frame'):
            return

        for widget in self.screenshot_grid_frame.winfo_children():
            widget.destroy()

        screenshots = self._list_screenshot_files()
        screenshots_dir = self.get_screenshots_dir()
        if hasattr(self, 'screenshot_status_lbl'):
            count = len(screenshots)
            self.screenshot_status_lbl.config(text=f"{count} screenshot{'s' if count != 1 else ''} in {screenshots_dir}")

        if not screenshots:
            tk.Label(self.screenshot_grid_frame, text="No screenshots found yet.", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
            self._refresh_addons_scroll_bindings()
            return

        columns = 3
        for column in range(columns):
            self.screenshot_grid_frame.grid_columnconfigure(column, weight=1)

        for index, path in enumerate(screenshots[:18]):
            card = tk.Frame(self.screenshot_grid_frame, bg=COLORS.get('input_bg', '#1A1A1A'), padx=10, pady=10)
            card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=6, pady=6)

            thumbnail = self._get_screenshot_thumbnail(path)
            if thumbnail:
                preview = tk.Label(card, image=thumbnail, bg=COLORS.get('input_bg', '#1A1A1A'))
                preview.image = thumbnail  # type: ignore[attr-defined]
            else:
                preview = tk.Label(card, text="No Preview", width=20, height=6, bg=COLORS.get('input_bg', '#1A1A1A'), fg=COLORS['text_secondary'])
            preview.pack(fill="x")

            tk.Label(card, text=os.path.basename(path), font=("Segoe UI", 9, "bold"), bg=COLORS.get('input_bg', '#1A1A1A'), fg=COLORS['text_primary'], anchor="w").pack(fill="x", pady=(8, 2))
            tk.Label(card, text=datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"), font=("Segoe UI", 8), bg=COLORS.get('input_bg', '#1A1A1A'), fg=COLORS['text_secondary'], anchor="w").pack(fill="x")

            btns = tk.Frame(card, bg=COLORS.get('input_bg', '#1A1A1A'))
            btns.pack(fill="x", pady=(8, 0))
            self._make_btn(btns, "Open", style="secondary", font_size=8, command=lambda p=path: self._open_path(p)).pack(side="left")
            self._make_btn(btns, "Delete", style="secondary", font_size=8, command=lambda p=path: self.delete_screenshot(p)).pack(side="right")

        self._refresh_addons_scroll_bindings()

    def refresh_addons_tab_state(self):
        self._ensure_addons_config_defaults()

        if hasattr(self, 'streamer_mode_var'):
            self.streamer_mode_var.set(bool(self.addons_config.get("streamer_mode_enabled", False)))
        if hasattr(self, 'gh_sync_enabled'):
            self.gh_sync_enabled.set(bool(self.addons_config.get("gh_sync_enabled", False)))
        if hasattr(self, 'gh_repo_entry'):
            self.gh_repo_entry.delete(0, tk.END)
            self.gh_repo_entry.insert(0, str(self.addons_config.get("gh_repo", "")))
        if hasattr(self, 'gh_token_entry'):
            self.gh_token_entry.delete(0, tk.END)
            self.gh_token_entry.insert(0, str(self.addons_config.get("gh_token", "")))

        self._refresh_quick_join_installation_values()
        self.render_playtime_tracker()
        self.render_quick_join_servers()
        self.render_screenshot_browser()
        self.refresh_third_party_addons()
        self._apply_streamer_mode_ui()
        self._refresh_addons_scroll_bindings()

    def _save_addons_config(self):
        self._ensure_addons_config_defaults()
        self.addons_config["gh_sync_enabled"] = self.gh_sync_enabled.get()
        self.save_config()

    def _save_gh_sync_settings(self):
        self._ensure_addons_config_defaults()
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
                agent_candidates = [
                    os.path.join(base_dir, "agent.exe"),
                    os.path.join(base_dir, "agent"),
                ]
                agent_exe = next((path for path in agent_candidates if os.path.exists(path)), agent_candidates[0])
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
            self.render_screenshot_browser()

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
                    assets = data.get("assets", [])
                    preferred_asset = None

                    # Auto-update must use the full installer so dependencies are included.
                    for asset in assets:
                        name = str(asset.get("name", ""))
                        if name.lower() == "nlcsetup.exe":
                            preferred_asset = asset
                            break
                    if preferred_asset is None:
                        for asset in assets:
                            name = str(asset.get("name", "")).lower()
                            if name.endswith(".exe") and ("setup" in name or "installer" in name):
                                preferred_asset = asset
                                break

                    asset_url = preferred_asset.get("browser_download_url") if preferred_asset else None
                    asset_name = preferred_asset.get("name") if preferred_asset else ""
                    self.root.after(
                        0,
                        lambda: self._on_update_found(
                            latest_tag,
                            data.get("html_url"),
                            asset_url,
                            asset_name,
                        ),
                    )
                else:
                     self.root.after(0, lambda: self.update_status_lbl.config(text="You are on the latest version.", fg=COLORS['success_green']))
            else:
                 self.root.after(0, lambda: self.update_status_lbl.config(text=f"Failed to check: {response.status_code}", fg=COLORS['error_red']))
        except Exception as e:
            self.root.after(0, lambda: self.update_status_lbl.config(text=f"Error checking updates", fg=COLORS['error_red']))
            print(f"Update check error: {e}")

    def _on_update_found(self, version, html_url, asset_url, asset_name=""):
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
            is_setup_asset = str(asset_name).lower().endswith("setup.exe") or str(asset_name).lower() == "nlcsetup.exe"
            if asset_url and is_setup_asset:
                try:
                    self.root.grab_release()
                except Exception:
                    pass
                self.root.after(0, lambda u=asset_url, v=version: self.perform_auto_update(u, v))
            else:
                custom_showerror(
                    "Error",
                    "Auto-update installer (NLCSetup.exe) was not found in this release.\n"
                    "Opening release page instead."
                )
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
        self._cancel_window_animation()
        wx, wy, ww, wh = self._get_work_area()

        if self._pre_minimize_was_maximized:
            target = (wx, wy, max(1, ww), max(1, wh))
        elif self._pre_minimize_geometry:
            target = self._pre_minimize_geometry
        else:
            fallback = self._windowed_geometry if self._windowed_geometry else (wx + 80, wy + 80, 1080, 720)
            target = (
                int(fallback[0]),
                int(fallback[1]),
                max(1, int(fallback[2])),
                max(1, int(fallback[3]))
            )

        if self._pre_minimize_anchor_geometry:
            start = self._pre_minimize_anchor_geometry
        else:
            tw = max(280, int(target[2] * 0.45))
            th = max(180, int(target[3] * 0.45))
            tx = wx + (ww - tw) // 2
            ty = wy + wh - th - 10
            start = (tx, ty, tw, th)

        def on_restore_done():
            self._window_is_maximized = bool(self._pre_minimize_was_maximized)
            if hasattr(self, 'window_max_btn'):
                self.window_max_btn.config(text="❐" if self._window_is_maximized else "□")
            self._update_titlebar_controls_offset()
            self.root.lift()
            try:
                self.root.focus_force()
            except Exception:
                pass
            self._pre_minimize_geometry = None
            self._pre_minimize_anchor_geometry = None
            self._pre_minimize_was_maximized = False

        def finalize_restore():
            self.root.deiconify()
            self.root.state('normal')
            self._set_geometry_tuple(target)
            self._set_custom_window_chrome(True)
            self._ensure_taskbar_visibility()

        self._run_transition_with_overlay(
            start,
            target,
            duration=140,
            steps=12,
            subtitle="Restoring window",
            finalize=finalize_restore,
            on_done=on_restore_done
        )
        
    def _on_close(self):
        try:
            self.save_config(sync_ui=True, immediate=True)
        except Exception:
            pass

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
            self._last_rpc_state = state
            self._last_rpc_details = details
            self._last_rpc_start = start
            # User Info for formatted Rich Presence
            user_text = "Steve"
            small_key = "steve" # Fallback asset key
            
            if self.profiles and hasattr(self, 'current_profile_index') and 0 <= self.current_profile_index < len(self.profiles):
                p = self.profiles[self.current_profile_index]
                user_text = p.get("name", "Steve")
                # Use MC-Heads for dynamic avatar if UUID exists (Microsoft/Ely.by)
                if p.get("uuid"):
                    small_key = f"https://mc-heads.net/avatar/{p.get('uuid')}"
            user_text = self._get_streamer_safe_name(user_text)
            
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
                line = f"[{timestamp}] {self._mask_streamer_text(message)}"
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

        return _build_missing_skin_head(size)

    def update_active_profile(self):
        if not self.profiles:
            self.skin_path = ""
            if hasattr(self, 'user_entry'):
                self.user_entry.delete(0, tk.END)
            self.update_profile_btn()
            return

        p = self.profiles[self.current_profile_index]
        old_skin_path = self.skin_path
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
            self.user_entry.config(show="*" if self._is_streamer_mode_enabled() else "")
        
        # Update Model Radio var BEFORE rendering
        if hasattr(self, 'skin_model_var'):
            self.skin_model_var.set(p.get("skin_model", "classic"))
        
        # Only render if skin path changed or is set
        if self.skin_path and (self.skin_path != old_skin_path or not old_skin_path):
            self.render_preview()
        elif not self.skin_path and hasattr(self, 'preview_canvas'):
            self.preview_canvas.delete("all")  # Clear preview if no skin

        self.update_skin_indicator()
        self.update_profile_btn()
        if hasattr(self, 'update_bottom_gamertag'): self.update_bottom_gamertag()
        
        # Refresh skin history if on Locker tab
        if self.current_tab == "Locker" and hasattr(self, 'locker_view') and self.locker_view.get() == "Skins":
            if hasattr(self, 'render_skin_history'):
                self.render_skin_history()
        
    def update_profile_btn(self):
        # Update text labels
        if not self.profiles: return
        p = self.profiles[self.current_profile_index]
        
        if hasattr(self, 'sidebar_username'):
            self.sidebar_username.config(text=self._get_streamer_safe_name(p.get("name", "Steve")))
        
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
                    if not isinstance(data, dict):
                        raise ValueError("Configuration root must be a JSON object.")

                    # Old, partially-written, or hand-edited configuration
                    # should not crash the launcher.  Keep valid records and
                    # let the regular atomic save migrate the rest.
                    raw_profiles = data.get("profiles", [])
                    data["profiles"] = [item for item in raw_profiles if isinstance(item, dict)] if isinstance(raw_profiles, list) else []
                    raw_installations = data.get("installations", [])
                    data["installations"] = [item for item in raw_installations if isinstance(item, dict)] if isinstance(raw_installations, list) else []
                    if not isinstance(data.get("addons", {}), dict):
                        data["addons"] = {}

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
                            "java_executable": "",
                            "resolution_width": None,
                            "resolution_height": None,
                            "last_played": "Never",
                            "created": "2024-01-01"
                        }]
                        print("Initialized default installations")
                    else:
                        # Ensure IDs
                        for inst in self.installations:
                            if "id" not in inst:
                                inst["id"] = str(uuid.uuid4())
                            inst.setdefault("java_executable", "")
                            inst.setdefault("resolution_width", None)
                            inst.setdefault("resolution_height", None)
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
                    try:
                        self.ram_allocation = max(512, int(data.get("ram_allocation", DEFAULT_RAM)))
                    except (TypeError, ValueError):
                        self.ram_allocation = DEFAULT_RAM
                    self.ram_var.set(self.ram_allocation)
                    self.ram_entry_var.set(str(self.ram_allocation))

                    # Downloads & Features
                    try:
                        self.max_concurrent_packs = max(1, min(3, int(data.get("max_concurrent_packs", 1))))
                    except (TypeError, ValueError):
                        self.max_concurrent_packs = 1
                    try:
                        self.max_concurrent_mods = max(1, min(8, int(data.get("max_concurrent_mods", 3))))
                    except (TypeError, ValueError):
                        self.max_concurrent_mods = 3
                    self.limit_download_speed_enabled = data.get("limit_download_speed_enabled", False)
                    self.max_download_speed = data.get("max_download_speed", 2048) # KB/s
                    self.enable_modrinth = True
                    loaded_mods_view = str(data.get("installed_mods_view_mode", "grid")).lower()
                    self.installed_mods_view_mode = loaded_mods_view if loaded_mods_view in ("grid", "list") else "grid"
                    
                    # Addons
                    if "addons" in data:
                        self.addons_config.update(data["addons"])
                    self._ensure_addons_config_defaults()

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
                    self.custom_titlebar_enabled = data.get("custom_titlebar_enabled", True)
                    self.neo_style_enabled = data.get("neo_style_enabled", True)
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

                    self.refresh_addons_tab_state()

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
            self.create_default_profile()
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

    def _build_config_payload(self, sync_ui=True):
        if sync_ui and self.profiles and 0 <= self.current_profile_index < len(self.profiles):
            self.profiles[self.current_profile_index]["skin_path"] = self.skin_path
            if hasattr(self, 'user_entry'):
                name = self.user_entry.get().strip()
                if name:
                    self.profiles[self.current_profile_index]["name"] = name

        if sync_ui and hasattr(self, 'java_args_entry'):
            self.java_args = self.java_args_entry.get().strip()

        rpc_mode = "Show Version"
        if hasattr(self, 'rpc_detail_mode_var'):
            rpc_mode = self.rpc_detail_mode_var.get()
        if hasattr(self, 'auto_update_var'):
            self.auto_update_check = self.auto_update_var.get()

        self.rpc_show_version = (rpc_mode == "Show Version")
        self.rpc_show_server = (rpc_mode == "Show Server IP")

        close_launcher_val = getattr(self, 'close_launcher', True)
        if hasattr(self, 'close_launcher_var'):
            close_launcher_val = self.close_launcher_var.get()

        minimize_to_tray_val = getattr(self, 'minimize_to_tray', False)
        if hasattr(self, 'minimize_to_tray_var'):
            minimize_to_tray_val = self.minimize_to_tray_var.get()

        show_console_val = getattr(self, 'show_console', False)
        if hasattr(self, 'show_console_var'):
            show_console_val = self.show_console_var.get()

        return {
            "last_version": getattr(self, "last_version", ""),
            "first_run_completed": not self.first_run,
            "accent_color": getattr(self, "accent_color_name", "Green"),
            "profiles": self.profiles,
            "installations": self.installations,
            "current_profile_index": self.current_profile_index,
            "current_installation_index": getattr(self, 'current_installation_index', 0),
            "loader": self.loader_var.get() if hasattr(self, 'loader_var') else "Vanilla",
            "auto_download_mod": self.auto_download_mod,
            "ram_allocation": self.ram_allocation,
            "java_args": self.java_args,
            "minecraft_dir": self.minecraft_dir,
            "rpc_enabled": self.rpc_enabled,
            "rpc_detail_mode": rpc_mode,
            "rpc_show_version": self.rpc_show_version,
            "rpc_show_server": self.rpc_show_server,
            "auto_update_check": self.auto_update_check,
            "custom_titlebar_enabled": getattr(self, 'custom_titlebar_enabled', True),
            "neo_style_enabled": getattr(self, 'neo_style_enabled', True),
            "max_concurrent_packs": getattr(self, 'max_concurrent_packs', 1),
            "max_concurrent_mods": getattr(self, 'max_concurrent_mods', 3),
            "limit_download_speed_enabled": getattr(self, 'limit_download_speed_enabled', False),
            "max_download_speed": getattr(self, 'max_download_speed', 2048),
            "enable_modrinth": True,
            "installed_mods_view_mode": getattr(self, 'installed_mods_view_mode', 'grid'),
            "close_launcher": close_launcher_val,
            "minimize_to_tray": minimize_to_tray_val,
            "show_console": show_console_val,
            "current_wallpaper": getattr(self, 'current_wallpaper', None),
            "addons": getattr(self, "addons_config", {})
        }

    def _write_config_payload(self, config):
        tmp_path = f"{self.config_file}.tmp"
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.config_file)
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            print(f"Failed to save config: {e}")

    def _flush_pending_config_save(self):
        self._config_save_after_id = None
        sync_ui = bool(getattr(self, "_config_sync_ui_pending", False))
        self._config_sync_ui_pending = False
        self._write_config_payload(self._build_config_payload(sync_ui=sync_ui))

    def save_config(self, *args, sync_ui=True, immediate=False):
        self._config_sync_ui_pending = bool(getattr(self, "_config_sync_ui_pending", False) or bool(sync_ui))

        if immediate:
            if getattr(self, "_config_save_after_id", None) is not None:
                try:
                    self.root.after_cancel(self._config_save_after_id)
                except Exception:
                    pass
                self._config_save_after_id = None
            self._flush_pending_config_save()
            return

        delay = max(50, int(getattr(self, "_config_save_delay_ms", 250)))
        if self._config_save_after_id is not None:
            try:
                self.root.after_cancel(self._config_save_after_id)
            except Exception:
                pass
        try:
            self._config_save_after_id = self.root.after(delay, self._flush_pending_config_save)
        except Exception:
            self._config_save_after_id = None
            self._flush_pending_config_save()

    def create_default_profile(self):
        self.profiles = [{"name": DEFAULT_USERNAME, "type": "offline", "skin_path": "", "uuid": ""}]
        self.installations = [{
            "id": str(uuid.uuid4()),
            "name": "Latest Release",
            "version": "latest-release",
            "loader": "Vanilla",
            "icon": "icons/grass_block_side.png",
            "java_executable": "",
            "resolution_width": None,
            "resolution_height": None,
            "last_played": "Never",
            "created": "2024-01-01"
        }]
        self.current_profile_index = 0
        self.current_installation_index = 0
        self.update_active_profile()

    def load_versions(self):
        """Warm the metadata cache without blocking launcher startup.

        The installation editor owns the actual selector; this cache keeps it
        responsive when users open it for the first time.
        """
        if getattr(self, "_version_load_started", False):
            return
        self._version_load_started = True

        def fetch():
            try:
                versions = minecraft_launcher_lib.utils.get_version_list()
                cleaned = [
                    {"id": str(item.get("id")), "type": str(item.get("type", "release"))}
                    for item in versions if isinstance(item, dict) and item.get("id")
                ]
                self.cached_vanilla_versions = cleaned
                self.log(f"Loaded {len(cleaned)} Minecraft versions.")
            except Exception as exc:
                self.cached_vanilla_versions = []
                self.log(f"Could not load Minecraft version metadata: {exc}")
            finally:
                self._version_load_started = False

        threading.Thread(target=fetch, daemon=True, name="version-metadata").start()

    def _apply_version_list(self, loader, display_list):
        """Compatibility hook for older UI surfaces that expose a combobox."""
        for widget_name in ("version_combo", "version_dropdown"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget["values"] = display_list
                if display_list and not self.version_var.get():
                    self.version_var.set(display_list[0])
            except (tk.TclError, TypeError):
                pass

    def on_loader_change(self, event):
        self.load_versions()
        self.save_config()

    def on_version_change(self, event):
        self.save_config()

    def launch_installation(self, idx, server_address=None, server_port=None):
        if 0 <= idx < len(self.installations):
            self.current_installation_index = idx
            self.show_tab("Play")
            self.update_installation_dropdown()
            self.start_launch(server_address=server_address, server_port=server_port)

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
        if os.name != "nt":
            dialog.transient(self.root)
        dialog.resizable(False, False)
        if os.name != "nt":
            dialog.grab_set()
        dialog_root = self._apply_custom_toplevel_chrome(dialog, "Skin Model")
        
        tk.Label(dialog_root, text="Select Skin Model", font=("Segoe UI", 12, "bold"), 
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=15)
        
        tk.Label(dialog_root, text="Does your skin have 3px (Slim) or 4px (Classic) arms?", 
                 font=("Segoe UI", 9), bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(pady=(0, 20))
        
        btn_frame = tk.Frame(dialog_root, bg=COLORS['main_bg'])
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
        b1 = self._make_btn(btn_frame, "Classic (Steve)\n4px Arms", 
                           style="primary" if current_model == "classic" else "secondary",
                           font_size=10, width=15, command=set_classic)
        b1.config(bg=b1_bg, pady=10)
        if current_model == "classic": 
            b1.config(fg="white")
            b1.bind("<Enter>", lambda e: b1.config(bg=COLORS.get('play_btn_green', '#2D8F36')))
            b1.bind("<Leave>", lambda e: b1.config(bg=COLORS['success_green']))
        b1.pack(side="left", padx=5)
        
        # Slim (Alex)
        b2_bg = COLORS['success_green'] if current_model == "slim" else COLORS['card_bg']
        b2 = self._make_btn(btn_frame, "Slim (Alex)\n3px Arms",
                           style="primary" if current_model == "slim" else "secondary",
                           font_size=10, width=15, command=set_slim)
        b2.config(bg=b2_bg, pady=10)
        if current_model == "slim":
            b2.config(fg="white")
            b2.bind("<Enter>", lambda e: b2.config(bg=COLORS.get('play_btn_green', '#2D8F36')))
            b2.bind("<Leave>", lambda e: b2.config(bg=COLORS['success_green']))
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
            # Check if preview canvas exists and is visible
            if not hasattr(self, 'preview_canvas') or not self.preview_canvas.winfo_exists():
                return
                
            if not self.skin_path or not os.path.exists(self.skin_path): 
                self.preview_canvas.delete("all")
                return
            
            # Determine model
            model = "classic"
            if self.profiles:
                 model = self.profiles[self.current_profile_index].get("skin_model", "classic")

            # Use 3D Renderer
            w = self.preview_canvas.winfo_width()
            h = self.preview_canvas.winfo_height()
            # Defaults if not mapped yet
            if w < 50: w = 300
            if h < 50: h = 360
            
            # Cache key for rendered skin
            cache_key = (self.skin_path, model, h)
            
            # Check if we already have this rendered (optimization)
            if hasattr(self, '_preview_cache') and cache_key in self._preview_cache:
                self.preview_photo = self._preview_cache[cache_key]
                self.preview_canvas.delete("all")
                self.preview_canvas.create_image(w//2, h//2, image=self.preview_photo, anchor="center")
                return
            
            rendered = SkinRenderer3D.render(self.skin_path, model, height=int(h * 0.9))
            if rendered:
                self.preview_photo = ImageTk.PhotoImage(rendered)
                
                # Cache the rendered image
                if not hasattr(self, '_preview_cache'):
                    self._preview_cache = {}
                self._preview_cache[cache_key] = self.preview_photo
                
                # Limit cache size
                if len(self._preview_cache) > 10:
                    # Remove oldest (first) entry
                    self._preview_cache.pop(next(iter(self._preview_cache)))
                
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
                     
                     # Update UI
                     self.skin_path = path
                     if hasattr(self, 'skin_model_var'):
                         self.skin_model_var.set(variant)
                     self.render_preview()
                     self.update_skin_indicator()
                     
                     # Add to history and save once
                     self.add_skin_to_history(path, variant)
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
            # Ask model for offline usage too (for correct injections/rendering)
            variant = self.custom_skin_model_popup() or "classic"
            
            self.skin_path = path
            if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
                self.profiles[self.current_profile_index]["skin_path"] = path
                self.profiles[self.current_profile_index]["skin_model"] = variant
            
            # Update UI
            if hasattr(self, 'skin_model_var'):
                self.skin_model_var.set(variant)
            self.render_preview()
            self.update_skin_indicator()
            
            # Add to history (will save config)
            self.add_skin_to_history(path, variant)

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

    def _normalize_java_executable_input(self, value):
        raw_value = os.path.expandvars(os.path.expanduser(str(value or "").strip()))
        if not raw_value or raw_value == "<Use Bundled Java Runtime>":
            return ""

        if os.path.isdir(raw_value):
            candidates = [
                os.path.join(raw_value, "bin", "java.exe"),
                os.path.join(raw_value, "bin", "javaw.exe"),
                os.path.join(raw_value, "bin", "java"),
            ]
            for candidate in candidates:
                if os.path.isfile(candidate):
                    return candidate
            raise ValueError(f"No Java executable was found inside '{raw_value}'.")

        if os.path.isfile(raw_value):
            return raw_value

        if shutil.which(raw_value):
            return raw_value

        raise ValueError(f"Java executable not found: {raw_value}")

    def _normalize_installation_resolution_value(self, value, label):
        raw_value = str(value or "").strip()
        if not raw_value or raw_value.lower() == "auto":
            return ""
        if not raw_value.isdigit():
            raise ValueError(f"Resolution {label} must be a number or 'Auto'.")

        numeric_value = int(raw_value)
        if numeric_value <= 0:
            raise ValueError(f"Resolution {label} must be greater than 0.")
        return str(numeric_value)

    def start_launch(self, force_update=False, server_address=None, server_port=None):
        # Close any open menus
        self._close_all_menus()
        if self._launch_in_progress:
            self.toast_manager.show("Minecraft is already being prepared.", kind="info")
            return
        
        if not self.installations: return
        
        idx = getattr(self, 'current_installation_index', 0)
        if not (0 <= idx < len(self.installations)): return
        
        inst = self.installations[idx]
        version_id = inst.get("version")
        loader = inst.get("loader", "Vanilla")
        java_executable = inst.get("java_executable", "")
        resolution_width = inst.get("resolution_width")
        resolution_height = inst.get("resolution_height")
        
        if not version_id:
            version_id = "latest-release"

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

        self._launch_in_progress = True
        self.launch_btn.config(state="disabled", text="PREPARING...")
        self.launch_opts_btn.config(state="disabled")
        # self.set_status("Launching Minecraft...") # Redundant with overlay
        inst_id = inst.get("id")
        threading.Thread(
            target=self.launch_logic,
            args=(version_id, username, loader, force_update, inst_id, java_executable, resolution_width, resolution_height, server_address, server_port),
            daemon=True,
        ).start()

    def launch_logic(self, version, username, loader, force_update=False, inst_id=None, custom_java_executable="", resolution_width=None, resolution_height=None, server_address=None, server_port=None):
        mods_backup_path = None
        modpack_stage_path = None
        modpack_sync_active = False
        # Callback wrapper to update overlay
        def update_status(t):
            self.log(f"Status: {t}")
            status_text = str(t)
            def apply_status():
                if hasattr(self, 'update_progress_label'):
                    self.update_progress_label.config(text=status_text)
                if hasattr(self, 'launch_btn') and self._launch_in_progress:
                    compact = status_text.upper().replace("DOWNLOADING", "DOWNLOADING")
                    self.launch_btn.config(text=(compact[:20] + "…") if len(compact) > 21 else compact)
            self.root.after(0, apply_status)

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
            if version in ("latest-release", "latest-snapshot"):
                update_status("Resolving Minecraft version…")
                latest = minecraft_launcher_lib.utils.get_latest_version()
                version = latest["snapshot" if version == "latest-snapshot" else "release"]
            launch_id = version
            normalized_java_executable = self._normalize_java_executable_input(custom_java_executable)
            
            # --- Check for existing installations to avoid re-downloading ---
            installed_versions = [v['id'] for v in minecraft_launcher_lib.utils.get_installed_versions(self.minecraft_dir)]

            # Resolve Java for Installers (Fabric/Forge need Java to run their installer)
            java_install_path = normalized_java_executable or "java"
            if normalized_java_executable:
                self.log(f"Using custom Java executable: {normalized_java_executable}")
            else:
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
                        if "fabric" in vid and version in vid.split('-'):
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
                        if "forge" in vid and version in vid.split('-'):
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
                     skin_path = current_profile.get("skin_path") or self.skin_path
                     if skin_path and os.path.exists(skin_path):
                         use_injection = True
                         injector_path = self.ensure_authlib_injector()
                         
                         # Start Local Skin Server only when a real local skin exists.
                         try:
                             local_skin_server = LocalSkinServer(port=0)
                             skin_model = current_profile.get("skin_model", "classic")
                             skin_server_url = local_skin_server.start(skin_path, username, launch_uuid, skin_model)
                             self.log(f"Local Skin Server active at {skin_server_url}")
                         except Exception as e:
                             self.log(f"Failed to start local skin server: {e}")
                             use_injection = False
                     else:
                         self.log("Skin injection is enabled, but no local skin is selected. Launching without authlib-injector.")

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

            # --- MODPACK SYNC ---
            # The game still launches from the shared Minecraft directory, so
            # make a fresh, transactional copy of the linked pack's mods just
            # before building its command.  This deliberately also applies an
            # empty/missing pack mods folder: removing mods from a modpack must
            # not accidentally launch the global mods from a previous profile.
            if inst_id:
                pack = next((p for p in self.modpacks if p.get('linked_installation_id') == inst_id), None)
                if pack:
                    pack_name = str(pack.get('name') or 'modpack')
                    update_status(f"Updating {pack_name}…")
                    self.log(f"Updating linked modpack before launch: {pack_name}")

                    mods_dir = os.path.abspath(os.path.join(self.minecraft_dir, "mods"))
                    pack_root = os.path.abspath(self.get_modpack_dir(pack['id']))
                    pack_mods_dir = os.path.abspath(os.path.join(pack_root, "mods"))
                    if os.path.commonpath((pack_root, pack_mods_dir)) != pack_root:
                        raise ValueError("The linked modpack has an unsafe mods path.")
                    if os.path.exists(pack_mods_dir) and not os.path.isdir(pack_mods_dir):
                        raise ValueError("The linked modpack's mods path is not a folder.")

                    os.makedirs(self.minecraft_dir, exist_ok=True)
                    sync_token = uuid.uuid4().hex
                    modpack_stage_path = os.path.join(self.minecraft_dir, f".nlc_modpack_stage_{sync_token}")
                    if os.path.isdir(pack_mods_dir):
                        shutil.copytree(pack_mods_dir, modpack_stage_path)
                    else:
                        os.makedirs(modpack_stage_path)

                    if os.path.lexists(mods_dir):
                        mods_backup_path = os.path.join(self.minecraft_dir, f"mods_backup_{sync_token}")
                        os.rename(mods_dir, mods_backup_path)
                    try:
                        os.rename(modpack_stage_path, mods_dir)
                        modpack_stage_path = None
                        modpack_sync_active = True
                    except Exception:
                        # Do not leave the launcher using a partial pack if the
                        # final rename fails (for example, due to an antivirus
                        # lock).  Restore the original state before reporting
                        # the launch failure.
                        if mods_backup_path and os.path.lexists(mods_backup_path):
                            os.rename(mods_backup_path, mods_dir)
                            mods_backup_path = None
                        raise
                    self.log("Linked modpack is up to date for this launch.")

            options = {
                "username": username, 
                "uuid": launch_uuid, 
                "token": launch_token,
                "jvmArguments": jvm_args,
                "launcherName": "MinecraftLauncher",
                "gameDirectory": self.minecraft_dir
            }

            if normalized_java_executable:
                options["executablePath"] = normalized_java_executable

            if resolution_width and resolution_height:
                options["customResolution"] = True
                options["resolutionWidth"] = str(resolution_width)
                options["resolutionHeight"] = str(resolution_height)

            if server_address:
                options["server"] = str(server_address)
                if server_port:
                    options["port"] = str(server_port)
            
            self.log(f"Generating command for: {launch_id}")
            command = minecraft_launcher_lib.command.get_minecraft_command(launch_id, self.minecraft_dir, options) # type: ignore
            
            self.root.after(0, self.root.withdraw)
            
            # RPC Logic
            rpc_details = "Playing Minecraft"
            if getattr(self, 'rpc_show_version', True):
                 rpc_details = f"Playing {version} ({loader})"
            if server_address:
                 rpc_details = f"Connecting to {server_address}"
            
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
                encoding='utf-8',
                errors='replace',
                creationflags=creationflags
            )
            self.root.after(0, lambda: self.launch_btn.config(text="RUNNING") if hasattr(self, 'launch_btn') else None)
            session_started_at = time.time()
            
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
            if inst_id:
                session_seconds = max(0, int(time.time() - session_started_at))
                self.root.after(0, lambda iid=inst_id, secs=session_seconds, srv=server_address, prt=server_port: self._record_play_session(iid, secs, srv, prt))
            self.root.after(0, self.root.deiconify)
            self.root.after(0, lambda: self.update_rpc("Idle", "In Launcher"))
        except Exception as e:
            self.log(f"Error: {e}")
            logging.exception("Launch failed")
            
            err_msg = str(e)
            if isinstance(e, KeyError) and e.args == ("value",):
                err_msg = "The selected version has malformed launch metadata.\nThe launcher skipped a broken launch entry, but this install may still need Force Update & Play."
            if "launchermeta.mojang.com" in err_msg or "getaddrinfo failed" in err_msg:
                 err_msg = "Network Error: Could not connect to Mojang servers.\nPlease check your internet connection."
            elif "SSL" in err_msg or "DECRYPTION_FAILED" in err_msg:
                 err_msg = "Network connection interrupted (SSL error).\nThis is usually a temporary hiccup or antivirus block.\n\nPlease try clicking PLAY again."
            
            self.root.after(0, lambda: custom_showerror("Launch Error", err_msg))
            self.root.after(0, lambda: self.update_rpc("Idle", "In Launcher"))
        finally:
            # If the final swap failed after the original folder was moved,
            # this fallback also repairs it before the launcher returns to an
            # idle state.
            if modpack_sync_active or (mods_backup_path and os.path.lexists(mods_backup_path)):
                try:
                    current_mods = os.path.join(self.minecraft_dir, "mods")
                    if os.path.isdir(current_mods):
                        shutil.rmtree(current_mods)
                    elif os.path.lexists(current_mods):
                        os.remove(current_mods)
                    if mods_backup_path and os.path.lexists(mods_backup_path):
                        os.rename(mods_backup_path, current_mods)
                        self.log("Restored original mods folder.")
                    else:
                        self.log("Removed temporary modpack mods folder.")
                except Exception as e:
                    self.log(f"Error restoring mods: {e}")

            if modpack_stage_path and os.path.isdir(modpack_stage_path):
                try:
                    shutil.rmtree(modpack_stage_path)
                except OSError as e:
                    self.log(f"Error cleaning modpack staging folder: {e}")

            if local_skin_server:
                self.log("Stopping local skin server...")
                try: local_skin_server.stop()
                except: pass
                
            def reset_ui():
                self._launch_in_progress = False
                self.launch_btn.config(state="normal", text="PLAY")
                self.launch_opts_btn.config(state="normal")
                self.update_skin_indicator()
                self.hide_progress_overlay()
                
            self.root.after(0, reset_ui)

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    splash = tk.Toplevel(root)
    splash.overrideredirect(True)
    
    # Make background transparent if possible (Windows)
    try:
        splash.attributes("-transparentcolor", "#050505")
    except Exception:
        pass
    splash.configure(bg="#050505")
    
    splash_width = 300
    splash_height = 300
    x = (root.winfo_screenwidth() // 2) - (splash_width // 2)
    y = (root.winfo_screenheight() // 2) - (splash_height // 2)
    splash.geometry(f"{splash_width}x{splash_height}+{x}+{y}")
    
    try:
        from PIL import Image, ImageTk
        # Make logo bigger (e.g. 256x256)
        img = Image.open(resource_path("logo.png")).resize((256, 256), Image.Resampling.LANCZOS)
        splash_logo = ImageTk.PhotoImage(img)
        logo_lbl = tk.Label(splash, image=splash_logo, bg="#050505")
        logo_lbl.image = splash_logo # type: ignore
        logo_lbl.pack(expand=True)
    except Exception:
        tk.Label(splash, text="NLC", font=("Segoe UI", 48, "bold"), fg="white", bg="#050505").pack(expand=True)
        
    alpha = 0.0
    fading_in = True
    splash.attributes("-alpha", alpha)
    
    def pulsate_splash():
        global alpha, fading_in
        if not splash.winfo_exists():
            return
        
        if fading_in:
            alpha += 0.05
            if alpha >= 1.0:
                alpha = 1.0
                fading_in = False
        else:
            alpha -= 0.05
            if alpha <= 0.3:
                alpha = 0.3
                fading_in = True
                
        splash.attributes("-alpha", alpha)
        splash.after(40, pulsate_splash)

    def finish_loading():
        splash.destroy()
        root.deiconify()

    # Start the pulsation
    pulsate_splash()

    # Initialize the app in the background so it doesn't wait
    def init_app():
        app = MinecraftLauncher(root)
        # Once initialization is done, give it a bit of time then show
        root.after(1000, finish_loading)
        
    # Schedule app init slightly so UI handles splash first
    root.after(100, init_app)
    
    root.mainloop()
