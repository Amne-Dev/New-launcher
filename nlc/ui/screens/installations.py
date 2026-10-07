"""
nlc.ui.screens.installations - Installations tab and installation editor/selector
"""

import os
import sys
import json
import uuid
import shutil
import zipfile
import logging
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog
from PIL import Image, ImageTk

try:
    RESAMPLE_NEAREST = Image.Resampling.NEAREST
except AttributeError:
    RESAMPLE_NEAREST = Image.NEAREST

from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno

logger = logging.getLogger(__name__)

class InstallationsScreenMixin:
    """Mixin providing Installations tab, profile/installation items, and installation editor."""
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

