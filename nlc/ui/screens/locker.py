"""
nlc.ui.screens.locker - Locker tab (skins, wallpapers, skin history)
"""

import os
import sys
import shutil
import logging
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from PIL import Image, ImageTk

from typing import cast
from nlc.storage.paths import resource_path
from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_showwarning, custom_askyesno

logger = logging.getLogger(__name__)

class LockerScreenMixin:
    """Mixin providing Locker tab with skins, wallpapers, and skin history."""
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


