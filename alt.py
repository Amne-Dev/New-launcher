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
from PIL import Image, ImageTk
from datetime import datetime
from typing import Any, cast
import time

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

LOADERS = ["Vanilla", "Forge", "Fabric"]
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
        self.config_file = "launcher_config.json"
        
        self.last_version = ""
        self.profiles = [] # List of {"name": str, "type": "offline", "skin_path": str, "uuid": str}
        self.current_profile_index = -1
        self.auto_download_mod = False
        self.mod_available_online = False
        self.ram_allocation = DEFAULT_RAM
        self.java_args = ""
        self.rpc_enabled = True # Default True
        self.rpc = None
        self.rpc_connected = False
        self.start_time = None
        self.current_tab = None
        self.log_file_path = None

        self.setup_logging()
        self.setup_styles()
        self.create_layout()
        self.load_from_config()
        self.load_versions()

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
        # 1. Sidebar (Left)
        self.sidebar = tk.Frame(self.root, bg=COLORS['sidebar_bg'], width=70)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        
        # Sidebar Icon
        try:
            logo_img = Image.open(resource_path("logo.png"))
            logo_img = logo_img.resize((50, 50), RESAMPLE_NEAREST)
            self.sidebar_logo = ImageTk.PhotoImage(logo_img)
            tk.Label(self.sidebar, image=self.sidebar_logo, bg=COLORS['sidebar_bg']).pack(pady=(20, 20))
        except Exception:
            tk.Label(self.sidebar, text="M", font=("Georgia", 24, "bold"), 
                    bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary']).pack(pady=(20, 20))
        
        # Profile Button
        self.profile_btn = tk.Label(self.sidebar, bg=COLORS['sidebar_bg'], cursor="hand2")
        self.profile_btn.pack(pady=10)
        self.profile_btn.bind("<Button-1>", lambda e: self.toggle_profile_menu())
        
        # 2. Main Content Area
        self.content_area = tk.Frame(self.root, bg=COLORS['main_bg'])
        self.content_area.pack(side="right", fill="both", expand=True)
        
        # 3. Top Navigation Bar
        self.nav_bar = tk.Frame(self.content_area, bg=COLORS['tab_bar_bg'], height=50)
        self.nav_bar.pack(fill="x", side="top")
        self.nav_bar.pack_propagate(False)
        
        self.nav_buttons = {}
        self.create_nav_btn("PLAY", lambda: self.show_tab("Play"))
        self.create_nav_btn("SKINS", lambda: self.show_tab("Skins"))
        self.create_nav_btn("SETTINGS", lambda: self.show_tab("Settings"))

        # 4. Tab Container
        self.tab_container = tk.Frame(self.content_area, bg=COLORS['main_bg'])
        self.tab_container.pack(fill="both", expand=True)
        
        # Initialize Tabs
        self.tabs = {}
        self.create_play_tab()
        self.create_skins_tab()
        self.create_settings_tab()
        
        self.show_tab("Play")

    def create_nav_btn(self, text, command):
        btn = tk.Button(self.nav_bar, text=text, font=("Segoe UI", 10, "bold"),
                       bg=COLORS['tab_bar_bg'], fg=COLORS['text_secondary'],
                       activebackground=COLORS['tab_bar_bg'], activeforeground=COLORS['text_primary'],
                       relief="flat", bd=0, cursor="hand2", command=command)
        btn.pack(side="left", padx=20, pady=10)
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
        
        # Hero Section (Background)
        self.hero_canvas = tk.Canvas(frame, bg="#181818", highlightthickness=0)
        self.hero_canvas.pack(fill="both", expand=True, padx=0, pady=0)
        
        # Try load background
        self.hero_img_raw = None
        try:
            bg_path = resource_path("background.png")
            if os.path.exists(bg_path):
                self.hero_img_raw = Image.open(bg_path)
        except Exception: 
            pass
            
        self.hero_canvas.bind("<Configure>", self._update_hero_layout)

        # Bottom Action Bar
        bottom_bar = tk.Frame(frame, bg=COLORS['bottom_bar_bg'], height=90)
        bottom_bar.pack(fill="x", side="bottom")
        bottom_bar.pack_propagate(False)
        
        # Controls Container
        controls = tk.Frame(bottom_bar, bg=COLORS['bottom_bar_bg'])
        controls.pack(expand=True, fill="y", pady=15)
        
        # Version Selector Group
        ver_group = tk.Frame(controls, bg=COLORS['bottom_bar_bg'])
        ver_group.pack(side="left", padx=(0, 20))
        
        # Loader Dropdown
        self.loader_var = tk.StringVar(value=LOADERS[0])
        self.loader_dropdown = ttk.Combobox(ver_group, textvariable=self.loader_var, 
                                           values=LOADERS, state="readonly", width=10,
                                           style="Launcher.TCombobox")
        self.loader_dropdown.pack(fill="x", pady=(0, 5))
        self.loader_dropdown.bind("<<ComboboxSelected>>", self.on_loader_change)
        
        # Version Dropdown
        self.version_var = tk.StringVar()
        self.version_dropdown = ttk.Combobox(ver_group, textvariable=self.version_var, 
                                            state="readonly", width=25,
                                            style="Launcher.TCombobox")
        self.version_dropdown.pack(fill="x")
        self.version_dropdown.bind("<<ComboboxSelected>>", self.on_version_change)

        # Play Button
        self.launch_btn = tk.Button(controls, text="PLAY", font=("Segoe UI", 16, "bold"),
                                   bg=COLORS['play_btn_green'], fg="white",
                                   activebackground=COLORS['play_btn_hover'], activeforeground="white",
                                   relief="flat", bd=0, cursor="hand2", width=15,
                                   command=self.start_launch)
        self.launch_btn.pack(side="left")
        
        # Status Text
        self.status_label = tk.Label(bottom_bar, text="Ready to launch", 
                                    font=("Segoe UI", 9), bg=COLORS['bottom_bar_bg'], fg=COLORS['text_secondary'])
        self.status_label.place(relx=0.5, rely=0.85, anchor="center")
        
        # Progress Bar
        self.progress_bar = ttk.Progressbar(bottom_bar, orient='horizontal', mode='determinate',
                                           style="Launcher.Horizontal.TProgressbar")
        # self.progress_bar.place(relx=0, rely=0.96, relwidth=1, height=4) # Hidden by default

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

    # --- SKINS TAB ---
    def create_skins_tab(self):
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Skins"] = frame
        
        container = tk.Frame(frame, bg=COLORS['main_bg'])
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
                 
        self.auto_download_var = tk.BooleanVar()
        tk.Checkbutton(btn_frame, text="Auto-download Mod", variable=self.auto_download_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=lambda: self._set_auto_download(self.auto_download_var.get())).pack(side="left", padx=10)

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
            y = self.profile_btn.winfo_rooty()
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
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Settings"] = frame
        
        # Main container with padding
        main_container = tk.Frame(frame, bg=COLORS['main_bg'])
        main_container.pack(fill="both", expand=True, padx=40, pady=30)
        
        # Scrollable area could be added here if needed, but for now using simple packing
        
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
        self.rpc_var = tk.BooleanVar()
        tk.Checkbutton(main_container, text="Enable Discord Rich Presence", variable=self.rpc_var,
                      bg=COLORS['main_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['main_bg'], activebackground=COLORS['main_bg'],
                      command=self._on_rpc_toggle).pack(anchor="w", pady=(0, 20))

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

    def change_minecraft_dir(self):
        path = filedialog.askdirectory(initialdir=self.minecraft_dir)
        if path:
            self.minecraft_dir = path
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, path)
            self.load_versions()
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
        self.save_config()

    def update_profile_btn(self):
        if not hasattr(self, 'profile_btn'): return
        img = self.get_head_from_skin(self.skin_path)
        if img:
            self.profile_btn_img = img 
            self.profile_btn.config(image=img)

    def load_from_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                    
                    # Profiles
                    self.profiles = data.get("profiles", [])
                    if not self.profiles:
                        old_user = data.get("username", DEFAULT_USERNAME)
                        old_skin = data.get("skin_path", "")
                        self.profiles = [{"name": old_user, "type": "offline", "skin_path": old_skin, "uuid": ""}]
                    
                    idx = data.get("current_profile_index", 0)
                    self.current_profile_index = idx if 0 <= idx < len(self.profiles) else 0

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
            except: 
                self.create_default_profile()
        else: 
            self.create_default_profile()

    def save_config(self, *args):
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
        
        config = {
            "profiles": self.profiles,
            "current_profile_index": self.current_profile_index,
            "loader": self.loader_var.get(), 
            "last_version": self.version_var.get(), 
            "auto_download_mod": self.auto_download_mod, 
            "ram_allocation": self.ram_allocation,
            "java_args": self.java_args,
            "minecraft_dir": self.minecraft_dir,
            "rpc_enabled": self.rpc_enabled
        }
        try:
            with open(self.config_file, "w") as f: json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def create_default_profile(self):
        self.profiles = [{"name": DEFAULT_USERNAME, "type": "offline", "skin_path": "", "uuid": ""}]
        self.current_profile_index = 0
        self.update_active_profile()

    def load_versions(self):
        loader = self.loader_var.get()
        self.set_status(f"Refreshing {loader} versions...")
        threading.Thread(target=self._fetch_logic, args=(loader,), daemon=True).start()

    def _fetch_logic(self, loader):
        try:
            raw_list = self._fetch_versions_for_loader(loader)
            display_list = [self.format_version_display(v_id) for v_id in raw_list]
            self.root.after(0, lambda: self._apply_version_list(loader, display_list))
        except Exception as e:
            self.log(f"Fetch Error: {e}")

    def is_version_installed(self, version_id):
        path = os.path.join(self.minecraft_dir, "versions", version_id, f"{version_id}.json")
        return os.path.exists(path)

    def format_version_display(self, version_id):
        return f"{INSTALL_MARK}{version_id}" if self.is_version_installed(version_id) else version_id

    def _fetch_versions_for_loader(self, loader):
        if loader in {"Vanilla", "Forge"}:
            versions = minecraft_launcher_lib.utils.get_available_versions(self.minecraft_dir) or []
            return [v["id"] for v in versions if isinstance(v, dict) and v.get("type") == "release" and isinstance(v.get("id"), str)]
        if loader == "Fabric":
            fabric_versions = minecraft_launcher_lib.fabric.get_stable_minecraft_versions() or []
            return [v for v in fabric_versions if isinstance(v, str)]
        return []

    def _apply_version_list(self, loader, display_list):
        self.version_dropdown.config(values=display_list)
        if self.last_version in display_list:
            self.version_dropdown.set(self.last_version)
        elif display_list:
            self.version_dropdown.current(0)
        else:
            self.version_var.set("")
        self.set_status(f"Ready to play {loader}")
        version = normalize_version_text(self.version_var.get())
        if version:
            self.mod_available_online = False
            threading.Thread(target=self.check_mod_online, args=(version, loader), daemon=True).start()
        self.update_skin_indicator()

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
        loader = loader or self.loader_var.get()
        version = version or normalize_version_text(self.version_var.get())
        if not version: return False
        return bool(self._matching_mod_filename(loader, version))

    def on_loader_change(self, event):
        self.mod_available_online = False
        self.update_skin_indicator()
        self.load_versions()
        self.save_config()

    def on_version_change(self, event):
        version = normalize_version_text(self.version_var.get())
        self.mod_available_online = False
        self.update_skin_indicator()
        threading.Thread(target=self.check_mod_online, args=(version, self.loader_var.get()), daemon=True).start()
        self.save_config()

    def update_skin_indicator(self):
        loader = self.loader_var.get()
        version = normalize_version_text(self.version_var.get())
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

    def start_launch(self):
        v_text = self.version_var.get()
        if not v_text: return
        version = normalize_version_text(v_text)
        
        # Get username from current profile or entry
        username = self.user_entry.get().strip()
        if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
             # Sync back to profile
             self.profiles[self.current_profile_index]["name"] = username
        
        if not username: username = DEFAULT_USERNAME

        self.last_version = v_text
        
        # Save config
        self.save_config()
        
        # Show Progress Bar
        self.progress_bar.place(relx=0, rely=0.96, relwidth=1, height=4)
        
        self.update_rpc("Launching...", f"Version: {v_text}")

        self.launch_btn.config(state="disabled", text="LAUNCHING...")
        self.set_status("Launching Minecraft...")
        threading.Thread(target=self.launch_logic, args=(version, username, self.loader_var.get()), daemon=True).start()

    def launch_logic(self, version, username, loader):
        callback = cast(Any, {
            "setStatus": lambda t: self.log(f"Status: {t}"),
            "setProgress": lambda v: self.root.after(0, lambda: self.progress_bar.config(value=v)),
            "setMax": lambda m: self.root.after(0, lambda: self.progress_bar.config(maximum=m))
        })
        try:
            launch_id = version
            if loader == "Fabric":
                self.log(f"Installing Fabric for {version}...")
                result = minecraft_launcher_lib.fabric.install_fabric(version, self.minecraft_dir, callback=callback)
                if result: launch_id = result
                else:
                    loader_v = minecraft_launcher_lib.fabric.get_latest_loader_version()
                    launch_id = f"fabric-loader-{loader_v}-{version}"
            elif loader == "Forge":
                forge_v = minecraft_launcher_lib.forge.find_forge_version(version)
                if forge_v:
                    minecraft_launcher_lib.forge.install_forge_version(forge_v, self.minecraft_dir, callback=callback)
                    launch_id = forge_v

            if self.auto_download_mod and loader in ["Forge", "Fabric"] and not self.check_mod_present():
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
            self.root.after(0, lambda: self.update_rpc("In Game", f"Playing {version}", start=time.time()))
            
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
                    self.root.after(0, lambda l=line: self.log(f"[GAME] {l.strip()}"))
            process.wait()
            self.root.after(0, self.root.deiconify)
            self.root.after(0, lambda: self.update_rpc("Idle", "In Launcher"))
        except Exception as e:
            self.log(f"Error: {e}")
            self.root.after(0, lambda: messagebox.showerror("Launch Error", str(e)))
            self.root.after(0, lambda: self.update_rpc("Idle", "In Launcher"))
        finally:
            self.root.after(0, lambda: self.launch_btn.config(state="normal", text="PLAY"))
            self.root.after(0, self.update_skin_indicator)
            self.root.after(0, self.progress_bar.place_forget)

if __name__ == "__main__":
    root = tk.Tk()
    app = MinecraftLauncher(root)
    root.mainloop()