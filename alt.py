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
from PIL import Image, ImageTk
from datetime import datetime
from typing import Any, cast
import time

import hashlib

try:
    from pypresence import Presence # type: ignore
    RPC_AVAILABLE = True
except ImportError:
    RPC_AVAILABLE = False

# Detect resampling constant for compatibility with Pillow versions
try:
    RESAMPLE_NEAREST = Image.Resampling.NEAREST  # Pillow >= 9.1
except AttributeError:
    RESAMPLE_NEAREST = Image.NEAREST  # type: ignore # Older Pillow

CURRENT_VERSION = "1.2"

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
        frame.pack(fill="x", side=pack_side)
        
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
        
        # Removed label "INSTALLATION"
        
        self.installation_var = tk.StringVar()
        style = ttk.Style()
        style.configure("Large.TCombobox", padding=5, font=("Segoe UI", 11))
        
        self.installation_dropdown = ttk.Combobox(left_frame, textvariable=self.installation_var, 
                                                 state="readonly", width=35,
                                                 style="Large.TCombobox")
        self.installation_dropdown.pack(fill="x", ipady=4)
        self.installation_dropdown.bind("<<ComboboxSelected>>", self.on_installation_change)
        
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

    def create_installation_item(self, parent, idx, inst):
        item = tk.Frame(parent, bg=COLORS['card_bg'], pady=15, padx=20)
        item.pack(fill="x", pady=2)
        
        # Determine Icon
        loader = inst.get("loader", "Vanilla")
        icon_char = "⬜" # Default grass block
        if loader == "Fabric": icon_char = "🧵"
        elif loader == "Forge": icon_char = "🔨"
        
        icon_lbl = tk.Label(item, text=icon_char, bg=COLORS['card_bg'], fg=COLORS['text_secondary'], font=("Segoe UI", 16))
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
        # Update values of self.installation_dropdown based on self.installations
        if not hasattr(self, 'installation_dropdown'): return
        
        # Format: "Name (Version - Loader)"
        values = []
        for p in self.installations:
            name = p.get("name", "Unnamed")
            ver = p.get("version", "Latest") 
            loader = p.get("loader", "Vanilla")
            values.append(f"{name} ({ver} - {loader})")
            
        self.installation_dropdown['values'] = values
        if values:
            # Restore selection
            current = getattr(self, 'current_installation_index', 0)
            if 0 <= current < len(values):
                 self.installation_dropdown.current(current)
            else:
                 self.installation_dropdown.current(0)
            # Trigger update state
            self.on_installation_change(None)

    def on_installation_change(self, event):
        idx = self.installation_dropdown.current()
        if idx >= 0:
            self.current_installation_index = idx
            inst = self.installations[idx]
            ver = inst.get("version", "")
            loader = inst.get("loader", "")
            self.set_status(f"Selected: {ver} ({loader})")

    def open_new_installation_modal(self, edit_mode=False, index=None):
        # Modal for Name, Version, etc.
        win = tk.Toplevel(self.root)
        title = "Edit installation" if edit_mode else "Create new installation"
        win.title(title)
        win.geometry("500x650")
        win.configure(bg="#1e1e1e") # Darker modal
        
        # Pre-load data if editing
        existing_data = {}
        if edit_mode and index is not None and 0 <= index < len(self.installations):
            existing_data = self.installations[index]

        # Icon + Name
        top_sec = tk.Frame(win, bg="#1e1e1e")
        top_sec.pack(fill="x", padx=20, pady=20)
        
        tk.Label(top_sec, text="Name", font=("Segoe UI", 9, "bold"), fg=COLORS['text_secondary'], bg="#1e1e1e").pack(anchor="w")
        name_entry = tk.Entry(top_sec, bg="black", fg="white", insertbackground="white", relief="flat", font=("Segoe UI", 11))
        name_entry.pack(fill="x", pady=(5, 15), ipady=8)
        
        if edit_mode: name_entry.insert(0, existing_data.get("name", ""))
        
        # Mod Loader
        tk.Label(top_sec, text="Client / Loader", font=("Segoe UI", 9, "bold"), fg=COLORS['text_secondary'], bg="#1e1e1e").pack(anchor="w")
        loader_var = tk.StringVar()
        loader_combo = ttk.Combobox(top_sec, textvariable=loader_var, values=["Vanilla", "Fabric", "Forge", "BatMod", "LabyMod", "Lunar Client"], state="readonly", font=("Segoe UI", 10))
        loader_combo.pack(fill="x", pady=(5, 15), ipady=5)
        
        if edit_mode: loader_combo.set(existing_data.get("loader", "Vanilla"))
        
        # Game Version
        tk.Label(top_sec, text="Game Version", font=("Segoe UI", 9, "bold"), fg=COLORS['text_secondary'], bg="#1e1e1e").pack(anchor="w")
        
        self.modal_version_var = tk.StringVar()
        self.modal_ver_combo = ttk.Combobox(top_sec, textvariable=self.modal_version_var, state="disabled", font=("Segoe UI", 10))
        self.modal_ver_combo.pack(fill="x", pady=(5, 15), ipady=5)
        
        if edit_mode:
            self.modal_version_var.set(existing_data.get("version", ""))
        
        # Helper Label
        self.modal_status_lbl = tk.Label(top_sec, text="Select a loader to fetch versions", bg="#1e1e1e", fg=COLORS['text_secondary'], font=("Segoe UI", 8))
        self.modal_status_lbl.pack(anchor="w", pady=(0, 5))

        # Version Filters in Modal
        filter_frame = tk.Frame(top_sec, bg="#1e1e1e")
        filter_frame.pack(fill="x", pady=(0, 15))
        
        self.modal_show_snapshots = tk.BooleanVar(value=False)
        tk.Checkbutton(filter_frame, text="Show Snapshots", variable=self.modal_show_snapshots, 
                      bg="#1e1e1e", fg="white", selectcolor="#1e1e1e", activebackground="#1e1e1e",
                      command=lambda: self.update_modal_versions_list()).pack(side="left")

        # Logic
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
                     return any(loader_type.lower() in iv.lower() and version_id in iv for iv in installed_list)
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
                
                # --- 3RD PARTY CLIENTS (Simulated for now, can be expanded to real APIs) ---
                elif loader_type in ["BatMod", "LabyMod", "Lunar Client"]:
                     # These usually support specific versions
                     supported = ["1.8.9", "1.12.2", "1.16.5", "1.17.1", "1.18.2", "1.19.4", "1.20.1"]
                     for v in supported:
                         raw_versions.append({'id': v, 'type': 'release'})

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
                     if loader in ["BatMod", "LabyMod", "Lunar Client"]:
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
             
             new_profile = {
                 "name": name,
                 "version": version_id,
                 "loader": loader,
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

        # Actions
        btn_row = tk.Frame(win, bg="#1e1e1e")
        btn_row.pack(side="bottom", fill="x", padx=20, pady=20)
        
        btn_text = "Save" if edit_mode else "Create"
        tk.Button(btn_row, text=btn_text, bg=COLORS['success_green'], fg="white", font=("Segoe UI", 10, "bold"),
                 relief="flat", padx=20, pady=8, cursor="hand2",
                 command=create_action).pack(side="right", padx=5)
                 
        tk.Button(btn_row, text="Cancel", bg="#1e1e1e", fg=COLORS['text_primary'], font=("Segoe UI", 10),
                 relief="flat", padx=10, pady=8, cursor="hand2",
                 command=win.destroy).pack(side="right", padx=5)

    def open_installation_menu(self, idx, btn_widget):
        # Create a popup menu (Edit, Delete)
        menu = tk.Toplevel(self.root)
        menu.overrideredirect(True)
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
        container = tk.Frame(parent, bg=COLORS['main_bg'])
        container.pack(expand=True)
        
        # Skin Preview Card
        card = tk.Frame(container, bg=COLORS['card_bg'], padx=20, pady=20)
        card.pack(pady=20)
        
        tk.Label(card, text="CURRENT SKIN", font=("Segoe UI", 12, "bold"), 
                bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(pady=(0, 15))
        
        self.preview_canvas = tk.Canvas(card, width=160, height=320, 
                                       bg=COLORS['card_bg'], highlightthickness=0)
        self.preview_canvas.pack()
        
        self.skin_indicator = tk.Label(card, text="No Skin Selected", 
                                      font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary'])
        self.skin_indicator.pack(pady=(15, 0))
        
        # Actions
        btn_frame = tk.Frame(container, bg=COLORS['main_bg'])
        btn_frame.pack(pady=20)
        
        tk.Button(btn_frame, text="Browse Skin...", font=("Segoe UI", 10),
                 bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                 relief="flat", bd=0, padx=20, pady=8,
                 command=self.select_skin).pack(side="left", padx=10)
                 
        self.auto_download_var = tk.BooleanVar(value=self.auto_download_mod)
        tk.Checkbutton(btn_frame, text="Auto-download Mod", variable=self.auto_download_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=lambda: self._set_auto_download(self.auto_download_var.get())).pack(side="left", padx=10)
        
        # Trigger render if profile loaded
        if self.profiles: self.update_active_profile()

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
        
        tk.Label(frame, text=profile.get("type", "offline").title(), font=("Segoe UI", 8),
                bg=bg, fg=COLORS['text_secondary']).pack(side="right")
        
        def on_click(e):
            self.current_profile_index = idx
            self.update_active_profile()
            if hasattr(self, 'profile_menu'): self.profile_menu.destroy()
            
        frame.bind("<Button-1>", on_click)
        for child in frame.winfo_children():
            child.bind("<Button-1>", on_click)

    def open_add_account_modal(self):
        if hasattr(self, 'profile_menu'): self.profile_menu.destroy()
        
        win = tk.Toplevel(self.root)
        win.title("Add Account")
        win.geometry("400x350")
        win.config(bg=COLORS['main_bg'])
        try:
            win.geometry(f"+{self.root.winfo_x() + 340}+{self.root.winfo_y() + 180}")
        except: pass
        win.transient(self.root)
        win.resizable(False, False)

        tk.Label(win, text="Add a new account", font=("Segoe UI", 16, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(30, 20))
        
        tk.Button(win, text="Microsoft Account", font=("Segoe UI", 11),
                 bg=COLORS['play_btn_green'], fg="white", width=25, pady=8, relief="flat", cursor="hand2",
                 command=lambda: messagebox.showinfo("Info", "Microsoft Auth placeholder")).pack(pady=10)
                 
        tk.Button(win, text="Offline Account", font=("Segoe UI", 11),
                 bg=COLORS['input_bg'], fg=COLORS['text_primary'], width=25, pady=8, relief="flat", cursor="hand2",
                 command=lambda: self.show_offline_login(win)).pack(pady=10)

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
            label_text = "Microsoft Account" if t == "microsoft" else "Offline Account"
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
                with open(self.config_file, "r") as f:
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
            with open(self.config_file, "w") as f: json.dump(config, f, indent=4)
            print("Config saved successfully")
        except Exception as e:
            print(f"Failed to save config: {e}")

    def create_default_profile(self):
        self.profiles = [{"name": DEFAULT_USERNAME, "type": "offline", "skin_path": "", "uuid": ""}]
        self.installations = [{
            "name": "Latest Release",
            "version": "latest-release",
            "loader": "Vanilla",
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

    def _matching_mod_filename(self, loader, version):
        mods_dir = os.path.join(self.minecraft_dir, "mods")
        if not os.path.isdir(mods_dir): return None
        loader_token = loader.lower() if loader else ""
        version_token = version.lower() if version else ""
        for filename in os.listdir(mods_dir):
            lower = filename.lower()
            if not lower.endswith(".jar") or "offlineskins" not in lower: continue
            if loader_token and loader_token not in lower: continue
            if version_token and version_token not in lower: continue
            return filename
        return None

    def _cleanup_conflicting_mods(self, loader, version):
        mods_dir = os.path.join(self.minecraft_dir, "mods")
        if not os.path.isdir(mods_dir) or not version: return
        loader_token = loader.lower()
        version_token = version.lower()
        for filename in os.listdir(mods_dir):
            lower = filename.lower()
            if not lower.endswith(".jar") or "offlineskins" not in lower: continue
            if loader_token not in lower: continue
            if version_token in lower: continue
            try: os.remove(os.path.join(mods_dir, filename))
            except: pass

    def check_mod_present(self, loader=None, version=None):
        if not self.installations: return False
        if not loader or not version:
             idx = getattr(self, 'current_installation_index', 0)
             if idx < len(self.installations):
                 inst = self.installations[idx]
                 loader = inst.get("loader", "Vanilla")
                 version = inst.get("version", "")
        
        if not version: return False
        return bool(self._matching_mod_filename(loader, version))

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

        # Get stats from current installation
        idx = getattr(self, 'current_installation_index', 0)
        loader = "Vanilla"
        version = ""
        if self.installations and 0 <= idx < len(self.installations):
            inst = self.installations[idx]
            loader = inst.get("loader", "Vanilla")
            version = inst.get("version", "")

        mod_exists = bool(version and self.check_mod_present(loader, version))
        
        if not self.skin_path:
            self.skin_indicator.config(text="No Skin Selected", fg=COLORS['text_secondary'])
        elif loader == "Vanilla":
            self.skin_indicator.config(text="Vanilla: Local skin not supported", fg=COLORS['accent_blue'])
        elif mod_exists:
            self.skin_indicator.config(text="Ready: Skin & Mod found", fg=COLORS['success_green'])
        elif self.mod_available_online:
            self.skin_indicator.config(text="Mod will be downloaded", fg=COLORS['accent_blue'])
        else:
            self.skin_indicator.config(text="Incompatible: Mod not found", fg=COLORS['error_red'])

    def check_mod_online(self, mc_version, loader):
        self.mod_available_online = False
        self.root.after(0, self.update_skin_indicator)
        if loader not in MOD_COMPATIBLE_LOADERS: return
        api_url = "https://api.github.com/repos/zlainsama/OfflineSkins/releases"
        try:
            r = requests.get(api_url, timeout=5)
            if r.status_code == 200:
                releases = r.json()
                if isinstance(releases, list):
                    search_loader = loader.lower()
                    for release in releases:
                        for asset in release.get("assets", []):
                            if search_loader in asset["name"].lower() and mc_version in asset["name"]:
                                self.mod_available_online = True
                                self.root.after(0, self.update_skin_indicator)
                                return
        except: pass
        self.root.after(0, self.update_skin_indicator)

    def render_preview(self):
        try:
            if not self.skin_path or not os.path.exists(self.skin_path): return
            img = Image.open(self.skin_path)
            head = img.crop((8, 8, 16, 16))
            body = img.crop((20, 20, 28, 32))
            arm = img.crop((44, 20, 48, 32))
            leg = img.crop((4, 20, 8, 32))
            scale = 10
            full_view = Image.new("RGBA", (16*scale, 32*scale), (0, 0, 0, 0))
            full_view.paste(head.resize((8*scale, 8*scale), RESAMPLE_NEAREST), (4*scale, 0))
            full_view.paste(body.resize((8*scale, 12*scale), RESAMPLE_NEAREST), (4*scale, 8*scale))
            full_view.paste(arm.resize((4*scale, 12*scale), RESAMPLE_NEAREST), (0, 8*scale))
            full_view.paste(arm.resize((4*scale, 12*scale), RESAMPLE_NEAREST), (12*scale, 8*scale))
            full_view.paste(leg.resize((4*scale, 12*scale), RESAMPLE_NEAREST), (4*scale, 20*scale))
            full_view.paste(leg.resize((4*scale, 12*scale), RESAMPLE_NEAREST), (8*scale, 20*scale))
            self.tk_preview = ImageTk.PhotoImage(full_view)
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(80, 160, image=self.tk_preview)
        except Exception as e: self.log(f"Preview Error: {e}")

    def select_skin(self):
        if not self.auto_download_mod:
            if messagebox.askyesno("Mod Requirement", "Allow launcher to manage OfflineSkins mod?"):
                self.auto_download_mod = True
                self.auto_download_var.set(True)
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.png")])
        if path:
            self.skin_path = path
            if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
                self.profiles[self.current_profile_index]["skin_path"] = path
            self.update_active_profile()
            self.save_config()

    def download_offlineskins(self, mc_version, loader):
        repo = "zlainsama/OfflineSkins"
        api_url = f"https://api.github.com/repos/{repo}/releases"
        self._cleanup_conflicting_mods(loader, mc_version)
        try:
            r = requests.get(api_url, timeout=10)
            if r.status_code == 200:
                releases = r.json()
                if not isinstance(releases, list): return False
                search_loader = loader.lower()
                for release in releases:
                    for asset in release.get("assets", []):
                        if search_loader in asset["name"].lower() and mc_version in asset["name"]:
                            dest = os.path.join(self.minecraft_dir, "mods", asset["name"])
                            self.log(f"Downloading mod: {asset['name']}...")
                            r_mod = requests.get(asset["browser_download_url"], stream=True)
                            with open(dest, "wb") as f:
                                for chunk in r_mod.iter_content(8192): f.write(chunk)
                            return True
        except Exception as e: self.log(f"Download Error: {e}")
        return False

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
        try:
            launch_id = version
            
            # --- Check for existing installations to avoid re-downloading ---
            installed_versions = [v['id'] for v in minecraft_launcher_lib.utils.get_installed_versions(self.minecraft_dir)]
            
            if force_update:
                self.log("Force Update enabled: Verifying and re-installing versions...")
            
            if loader == "Fabric":
                # Look for existing fabric version matching this MC version
                # Expected format: fabric-loader-<loader>-<mc_version>
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
                # Vanilla: Check if version exists, if not install
                # Note: get_minecraft_command expects the version to be present for assets
                if force_update or (version not in installed_versions and launch_id not in installed_versions):
                     self.log(f"Installing/Updating Vanilla version {version}...")
                     minecraft_launcher_lib.install.install_minecraft_version(version, self.minecraft_dir, callback=callback)

            if self.auto_download_mod and loader in ["Forge", "Fabric"] and (force_update or not self.check_mod_present()):
                self.download_offlineskins(version, loader)

            if self.skin_path and os.path.exists(self.skin_path):
                try:
                    shutil.copy(self.skin_path, os.path.join(self.minecraft_dir, "launcher_skin.png"))
                except: pass

            # Build Options
            jvm_args = [f"-Xmx{self.ram_allocation}M"]
            if self.java_args:
                jvm_args.extend(self.java_args.split())

            options = {
                "username": username, 
                "uuid": "", 
                "token": "",
                "jvmArguments": jvm_args,
                "launcherName": "MinecraftLauncher",
                "gameDirectory": self.minecraft_dir
            }
            
            self.log(f"Generating command for: {launch_id}")
            command = minecraft_launcher_lib.command.get_minecraft_command(launch_id, self.minecraft_dir, options) # type: ignore
            
            # Log command for debugging
            # self.log(f"Command: {command}") 

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
                    
                    # Check for server connection in logs
                    # Example: [12:34:56] [Render thread/INFO]: Connecting to mc.hypixel.net, 25565
                    if "Connecting to" in line_stripped and "," in line_stripped:
                         if getattr(self, 'rpc_show_server', True):
                            try:
                                # Extract server
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