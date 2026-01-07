import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import minecraft_launcher_lib
import subprocess
import threading
import os
import json
import shutil
import requests
from PIL import Image, ImageTk
from datetime import datetime

# --- Color Scheme (Minecraft Launcher Inspired) ---
COLORS = {
    'bg_dark': '#1E1E1E',
    'bg_medium': '#2D2D2D',
    'bg_light': '#3C3C3C',
    'accent_green': '#5CB85C',
    'accent_green_hover': '#4CAF50',
    'accent_red': '#D9534F',
    'text_primary': '#FFFFFF',
    'text_secondary': '#B0B0B0',
    'border': '#404040',
    'mc_green': '#57A64E',
    'mc_green_dark': '#467A3C',
    'mc_dirt': '#8B7355',
    'mc_grass': '#7FC251',
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
        self.root.title("Minecraft Launcher")
        self.root.geometry("900x600")
        self.root.configure(bg=COLORS['bg_dark'])
        self.minecraft_dir = get_minecraft_dir()
        self.config_file = "launcher_config.json"
        
        self.last_version = ""
        self.skin_path = ""
        self.auto_download_mod = False
        self.mod_available_online = False
        self.logs_visible = False
        self.ram_allocation = DEFAULT_RAM

        # Configure ttk styles
        self.setup_styles()

        # Header
        header = tk.Frame(root, bg=COLORS['bg_medium'], height=60)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        
        title_label = tk.Label(header, text="MINECRAFT LAUNCHER", 
                              font=("Minecraft", 20, "bold"), 
                              bg=COLORS['bg_medium'], 
                              fg=COLORS['text_primary'])
        title_label.pack(side="left", padx=20, pady=15)
        
        subtitle = tk.Label(header, text="29th Edition", 
                           font=("Arial", 10), 
                           bg=COLORS['bg_medium'], 
                           fg=COLORS['text_secondary'])
        subtitle.pack(side="left", pady=15)

        # Main container
        self.main_container = tk.Frame(root, bg=COLORS['bg_dark'])
        self.main_container.pack(fill="both", expand=True, padx=0, pady=0)

        # --- LEFT COLUMN ---
        self.left_col = tk.Frame(self.main_container, bg=COLORS['bg_dark'])
        self.left_col.pack(side="left", fill="both", expand=True, padx=30, pady=20)

        # Username section
        username_frame = tk.Frame(self.left_col, bg=COLORS['bg_dark'])
        username_frame.pack(fill="x", pady=(0, 15))
        
        tk.Label(username_frame, text="USERNAME", 
                font=("Arial", 9, "bold"), 
                bg=COLORS['bg_dark'], 
                fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 5))
        
        self.user_entry = tk.Entry(username_frame, 
                                   font=("Arial", 11),
                                   bg=COLORS['bg_light'],
                                   fg=COLORS['text_primary'],
                                   insertbackground=COLORS['text_primary'],
                                   relief="flat",
                                   bd=0,
                                   highlightthickness=2,
                                   highlightbackground=COLORS['border'],
                                   highlightcolor=COLORS['mc_green'])
        self.user_entry.pack(fill="x", ipady=8, ipadx=10)

        # Loader section
        loader_frame = tk.Frame(self.left_col, bg=COLORS['bg_dark'])
        loader_frame.pack(fill="x", pady=(15, 15))
        
        tk.Label(loader_frame, text="MOD LOADER", 
                font=("Arial", 9, "bold"), 
                bg=COLORS['bg_dark'], 
                fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 5))
        
        self.loader_var = tk.StringVar(value=LOADERS[0])
        self.loader_dropdown = ttk.Combobox(loader_frame, 
                                           textvariable=self.loader_var, 
                                           state="readonly", 
                                           values=LOADERS,
                                           font=("Arial", 10),
                                           style="Dark.TCombobox")
        self.loader_dropdown.pack(fill="x", ipady=4)
        self.loader_dropdown.bind("<<ComboboxSelected>>", self.on_loader_change)

        # Version section
        version_frame = tk.Frame(self.left_col, bg=COLORS['bg_dark'])
        version_frame.pack(fill="x", pady=(15, 15))
        
        tk.Label(version_frame, text="VERSION", 
                font=("Arial", 9, "bold"), 
                bg=COLORS['bg_dark'], 
                fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 5))
        
        self.version_var = tk.StringVar()
        self.version_dropdown = ttk.Combobox(version_frame, 
                                            textvariable=self.version_var, 
                                            state="readonly",
                                            font=("Arial", 10),
                                            style="Dark.TCombobox")
        self.version_dropdown.pack(fill="x", ipady=4)
        self.version_dropdown.bind("<<ComboboxSelected>>", self.on_version_change)

        self.auto_download_var = tk.BooleanVar(value=self.auto_download_mod)
        self.ram_var = tk.IntVar(value=DEFAULT_RAM)
        self.ram_entry_var = tk.StringVar(value=str(DEFAULT_RAM))

        # Status and progress
        status_frame = tk.Frame(self.left_col, bg=COLORS['bg_dark'])
        status_frame.pack(fill="x", pady=(20, 5))
        
        self.status_label = tk.Label(status_frame, text="Ready to launch", 
                                     font=("Arial", 9),
                                     bg=COLORS['bg_dark'], 
                                     fg=COLORS['mc_green'])
        self.status_label.pack(anchor="w")
        
        self.progress_bar = ttk.Progressbar(status_frame, 
                                           orient='horizontal', 
                                           mode='determinate',
                                           style="Dark.Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x", pady=(5, 0))

        # Launch button
        launch_frame = tk.Frame(self.left_col, bg=COLORS['bg_dark'])
        launch_frame.pack(fill="x", pady=(20, 0))
        
        self.launch_btn = tk.Button(launch_frame, 
                                    text="PLAY", 
                                    font=("Arial", 14, "bold"), 
                                    bg=COLORS['mc_green'], 
                                    fg=COLORS['text_primary'],
                                    activebackground=COLORS['mc_green_dark'],
                                    activeforeground=COLORS['text_primary'],
                                    relief="flat",
                                    bd=0,
                                    cursor="hand2",
                                    command=self.start_launch)
        self.launch_btn.pack(fill="x", ipady=12)
        self.launch_btn.bind("<Enter>", lambda e: self.launch_btn.config(bg=COLORS['mc_green_dark']))
        self.launch_btn.bind("<Leave>", lambda e: self._restore_launch_color())

        # --- RIGHT COLUMN ---
        self.right_col = tk.Frame(self.main_container, bg=COLORS['bg_medium'], width=280)
        self.right_col.pack(side="right", fill="both", padx=0, pady=0)
        self.right_col.pack_propagate(False)

        right_inner = tk.Frame(self.right_col, bg=COLORS['bg_medium'])
        right_inner.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(right_inner, text="SKIN PREVIEW", 
                font=("Arial", 9, "bold"), 
                bg=COLORS['bg_medium'], 
                fg=COLORS['text_secondary']).pack(pady=(0, 10))
        
        canvas_frame = tk.Frame(right_inner, bg=COLORS['bg_dark'], highlightthickness=2, highlightbackground=COLORS['border'])
        canvas_frame.pack(pady=(0, 15))
        
        self.preview_canvas = tk.Canvas(canvas_frame, 
                                       width=160, 
                                       height=240, 
                                       bg=COLORS['bg_dark'],
                                       highlightthickness=0)
        self.preview_canvas.pack(padx=2, pady=2)

        self.skin_indicator = tk.Label(right_inner, 
                                      text="⚪ No Skin Selected", 
                                      font=("Arial", 9), 
                                      wraplength=200,
                                      bg=COLORS['bg_medium'], 
                                      fg=COLORS['text_secondary'],
                                      justify="center")
        self.skin_indicator.pack(pady=(0, 15))

        self.select_skin_btn = tk.Button(right_inner, 
                                        text="SELECT SKIN", 
                                        font=("Arial", 9, "bold"),
                                        bg=COLORS['bg_light'],
                                        fg=COLORS['text_primary'],
                                        activebackground=COLORS['border'],
                                        activeforeground=COLORS['text_primary'],
                                        relief="flat",
                                        bd=0,
                                        cursor="hand2",
                                        command=self.select_skin)
        self.select_skin_btn.pack(fill="x", ipady=8)
        self.select_skin_btn.bind("<Enter>", lambda e: self.select_skin_btn.config(bg=COLORS['border']))
        self.select_skin_btn.bind("<Leave>", lambda e: self.select_skin_btn.config(bg=COLORS['bg_light']))

        # Bottom bar
        self.bottom_bar = tk.Frame(root, bg=COLORS['bg_medium'], height=50)
        self.bottom_bar.pack(fill="x", side="bottom")
        self.bottom_bar.pack_propagate(False)

        btn_container = tk.Frame(self.bottom_bar, bg=COLORS['bg_medium'])
        btn_container.pack(side="right", padx=20, pady=10)

        self.settings_bar_btn = tk.Button(btn_container, 
                                         text="⚙ Settings", 
                                         font=("Arial", 9),
                                         bg=COLORS['bg_light'],
                                         fg=COLORS['text_primary'],
                                         activebackground=COLORS['border'],
                                         relief="flat",
                                         bd=0,
                                         cursor="hand2",
                                         command=self.open_settings_modal)
        self.settings_bar_btn.pack(side="left", padx=(0, 5), ipady=5, ipadx=10)
        self.settings_bar_btn.bind("<Enter>", lambda e: self.settings_bar_btn.config(bg=COLORS['border']))
        self.settings_bar_btn.bind("<Leave>", lambda e: self.settings_bar_btn.config(bg=COLORS['bg_light']))

        self.open_mods_btn = tk.Button(btn_container, 
                                      text="📁 Mods", 
                                      font=("Arial", 9),
                                      bg=COLORS['bg_light'],
                                      fg=COLORS['text_primary'],
                                      activebackground=COLORS['border'],
                                      relief="flat",
                                      bd=0,
                                      cursor="hand2",
                                      command=self.open_mods)
        self.open_mods_btn.pack(side="left", ipady=5, ipadx=10)
        self.open_mods_btn.bind("<Enter>", lambda e: self.open_mods_btn.config(bg=COLORS['border']))
        self.open_mods_btn.bind("<Leave>", lambda e: self.open_mods_btn.config(bg=COLORS['bg_light']))

        self.toggle_btn = tk.Button(self.bottom_bar, 
                                    text="▶ Show Logs", 
                                    font=("Arial", 9),
                                    bg=COLORS['bg_medium'],
                                    fg=COLORS['text_secondary'],
                                    activebackground=COLORS['bg_medium'],
                                    relief="flat",
                                    bd=0,
                                    cursor="hand2",
                                    command=self.toggle_logs)
        self.toggle_btn.pack(side="left", padx=20, pady=10)

        # --- LOGS SECTION ---
        self.log_frame = tk.Frame(root, bg=COLORS['bg_dark'])
        self.log_area = scrolledtext.ScrolledText(self.log_frame, 
                                                  height=12, 
                                                  bg="#0D0D0D", 
                                                  fg="#00FF00", 
                                                  font=("Consolas", 9),
                                                  relief="flat",
                                                  bd=0,
                                                  insertbackground="#00FF00")
        self.log_area.pack(fill="both", expand=True, padx=20, pady=(10, 20))

        self.log("Launcher initialized successfully.")
        self.load_from_config()
        self.load_versions()

    def setup_styles(self):
        style = ttk.Style()
        
        # Combobox style
        style.theme_use('clam')
        style.configure("Dark.TCombobox",
                       fieldbackground=COLORS['bg_light'],
                       background=COLORS['bg_light'],
                       foreground=COLORS['text_primary'],
                       arrowcolor=COLORS['text_primary'],
                       bordercolor=COLORS['border'],
                       lightcolor=COLORS['bg_light'],
                       darkcolor=COLORS['bg_light'],
                       borderwidth=1,
                       relief="flat")
        
        style.map('Dark.TCombobox',
                 fieldbackground=[('readonly', COLORS['bg_light'])],
                 selectbackground=[('readonly', COLORS['bg_light'])],
                 selectforeground=[('readonly', COLORS['text_primary'])],
                 arrowcolor=[('disabled', COLORS['text_secondary'])])
        
        # Progressbar style
        style.configure("Dark.Horizontal.TProgressbar",
                       troughcolor=COLORS['bg_light'],
                       background=COLORS['mc_green'],
                       bordercolor=COLORS['border'],
                       lightcolor=COLORS['mc_green'],
                       darkcolor=COLORS['mc_green'],
                       thickness=8)

    def _restore_launch_color(self):
        """Restore launch button color based on current state"""
        loader = self.loader_var.get()
        version = normalize_version_text(self.version_var.get())
        mod_exists = bool(version and self.check_mod_present(loader, version))
        
        if not self.skin_path:
            color = COLORS['mc_green']
        elif loader == "Vanilla":
            color = "#F39C12"
        elif mod_exists:
            color = "#2ECC71"
        elif self.mod_available_online:
            color = "#3498DB"
        else:
            color = "#E74C3C"
        
        self.launch_btn.config(bg=color)

    def toggle_logs(self):
        if not self.logs_visible:
            self.log_frame.pack(fill="both", expand=True, before=self.bottom_bar)
            self.toggle_btn.config(text="▼ Hide Logs")
            self.root.geometry("900x850")
            self.logs_visible = True
        else:
            self.log_frame.pack_forget()
            self.toggle_btn.config(text="▶ Show Logs")
            self.root.geometry("900x600")
            self.logs_visible = False

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_area.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_area.see(tk.END)

    def set_status(self, text, color=None):
        if color is None:
            color = COLORS['mc_green']
        self.status_label.config(text=text, fg=color)

    def _on_ram_slider_change(self, value):
        try:
            val = int(float(value))
        except ValueError:
            return
        self.ram_entry_var.set(str(val))
        self.ram_allocation = val

    def _on_ram_entry_commit(self):
        try:
            val = int(self.ram_entry_var.get())
        except ValueError:
            val = DEFAULT_RAM
        val = max(1024, min(8192, val))
        self.ram_entry_var.set(str(val))
        self.ram_var.set(val)
        self.ram_allocation = val

    def _set_auto_download(self, enabled):
        self.auto_download_mod = bool(enabled)

    def open_launcher_folder(self):
        launcher_path = os.path.abspath('.')
        try:
            if os.name == 'nt':
                os.startfile(launcher_path)
            else:
                subprocess.Popen(['xdg-open', launcher_path])
        except Exception as exc:
            self.log(f"Unable to open launcher folder: {exc}")

    def open_settings_modal(self):
        if getattr(self, "settings_window", None) and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
            return

        win = tk.Toplevel(self.root)
        self.settings_window = win
        win.title("Launcher Settings")
        win.geometry("450x350")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=COLORS['bg_dark'])

        # Header
        header = tk.Frame(win, bg=COLORS['bg_medium'], height=50)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="SETTINGS", 
                font=("Arial", 14, "bold"), 
                bg=COLORS['bg_medium'], 
                fg=COLORS['text_primary']).pack(side="left", padx=20, pady=15)

        container = tk.Frame(win, bg=COLORS['bg_dark'], padx=20, pady=20)
        container.pack(fill="both", expand=True)

        # RAM Section
        tk.Label(container, text="RAM ALLOCATION (MB)", 
                font=("Arial", 9, "bold"), 
                bg=COLORS['bg_dark'], 
                fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 5))
        
        ram_scale = tk.Scale(container, 
                            from_=1024, to=8192, 
                            orient="horizontal", 
                            resolution=256, 
                            showvalue=0,
                            variable=self.ram_var, 
                            command=self._on_ram_slider_change, 
                            bg=COLORS['bg_dark'],
                            fg=COLORS['text_primary'],
                            troughcolor=COLORS['bg_light'],
                            highlightthickness=0,
                            activebackground=COLORS['mc_green'])
        ram_scale.pack(fill="x", pady=(0, 10))

        entry_row = tk.Frame(container, bg=COLORS['bg_dark'])
        entry_row.pack(fill="x", pady=(0, 15))
        tk.Label(entry_row, text="Value:", 
                bg=COLORS['bg_dark'], 
                fg=COLORS['text_secondary']).pack(side="left")
        ram_entry = tk.Entry(entry_row, width=8, 
                            textvariable=self.ram_entry_var,
                            bg=COLORS['bg_light'],
                            fg=COLORS['text_primary'],
                            insertbackground=COLORS['text_primary'],
                            relief="flat",
                            bd=0,
                            highlightthickness=1,
                            highlightbackground=COLORS['border'])
        ram_entry.pack(side="left", padx=(8, 0), ipady=4, ipadx=8)
        ram_entry.bind("<FocusOut>", lambda e: self._on_ram_entry_commit())
        ram_entry.bind("<Return>", lambda e: self._on_ram_entry_commit())

        # Auto download checkbox
        auto_frame = tk.Frame(container, bg=COLORS['bg_dark'])
        auto_frame.pack(fill="x", pady=(15, 0))
        
        auto_chk = tk.Checkbutton(auto_frame, 
                                 text="Auto download OfflineSkins mod",
                                 variable=self.auto_download_var,
                                 command=lambda: self._set_auto_download(self.auto_download_var.get()),
                                 bg=COLORS['bg_dark'],
                                 fg=COLORS['text_primary'],
                                 selectcolor=COLORS['bg_light'],
                                 activebackground=COLORS['bg_dark'],
                                 activeforeground=COLORS['text_primary'],
                                 font=("Arial", 10))
        auto_chk.pack(anchor="w")

        # Buttons
        button_row = tk.Frame(container, bg=COLORS['bg_dark'])
        button_row.pack(fill="x", pady=(25, 0))
        
        btn_launch = tk.Button(button_row, text="Launcher Folder", 
                              command=self.open_launcher_folder,
                              bg=COLORS['bg_light'],
                              fg=COLORS['text_primary'],
                              activebackground=COLORS['border'],
                              relief="flat",
                              bd=0,
                              cursor="hand2",
                              font=("Arial", 9))
        btn_launch.pack(side="left", ipady=6, ipadx=12)
        
        btn_refresh = tk.Button(button_row, text="Refresh Versions", 
                               command=self.load_versions,
                               bg=COLORS['bg_light'],
                               fg=COLORS['text_primary'],
                               activebackground=COLORS['border'],
                               relief="flat",
                               bd=0,
                               cursor="hand2",
                               font=("Arial", 9))
        btn_refresh.pack(side="left", padx=(10, 0), ipady=6, ipadx=12)
        
        btn_close = tk.Button(button_row, text="Close", 
                             command=win.destroy,
                             bg=COLORS['mc_green'],
                             fg=COLORS['text_primary'],
                             activebackground=COLORS['mc_green_dark'],
                             relief="flat",
                             bd=0,
                             cursor="hand2",
                             font=("Arial", 9, "bold"))
        btn_close.pack(side="right", ipady=6, ipadx=20)
        
        tk.Label(container, text="Built by @amne-dev", 
                font=("Arial", 8), 
                bg=COLORS['bg_dark'], 
                fg=COLORS['text_secondary']).pack(anchor="e", pady=(15, 0))

        def _on_close():
            self.settings_window = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_close)

    def _matching_mod_filename(self, loader, version):
        mods_dir = os.path.join(self.minecraft_dir, "mods")
        if not os.path.isdir(mods_dir):
            return None
        loader_token = loader.lower() if loader else ""
        version_token = version.lower() if version else ""
        for filename in os.listdir(mods_dir):
            lower = filename.lower()
            if not lower.endswith(".jar") or "offlineskins" not in lower:
                continue
            if loader_token and loader_token not in lower:
                continue
            if version_token and version_token not in lower:
                continue
            return filename
        return None

    def _cleanup_conflicting_mods(self, loader, version):
        mods_dir = os.path.join(self.minecraft_dir, "mods")
        if not os.path.isdir(mods_dir):
            return
        if not version:
            return
        loader_token = loader.lower()
        version_token = version.lower()
        for filename in os.listdir(mods_dir):
            lower = filename.lower()
            if not lower.endswith(".jar") or "offlineskins" not in lower:
                continue
            if loader_token not in lower:
                continue
            if version_token in lower:
                continue
            try:
                os.remove(os.path.join(mods_dir, filename))
            except Exception as exc:
                self.log(f"Mod cleanup failed for {filename}: {exc}")

    def check_mod_present(self, loader=None, version=None):
        loader = loader or self.loader_var.get()
        version = version or normalize_version_text(self.version_var.get())
        if not version:
            return False
        return bool(self._matching_mod_filename(loader, version))

    def on_loader_change(self, event):
        self.mod_available_online = False
        self.update_skin_indicator()
        self.load_versions()

    def on_version_change(self, event):
        version = normalize_version_text(self.version_var.get())
        self.mod_available_online = False
        self.update_skin_indicator()
        threading.Thread(target=self.check_mod_online, args=(version, self.loader_var.get()), daemon=True).start()

    def update_skin_indicator(self):
        loader = self.loader_var.get()
        version = normalize_version_text(self.version_var.get())
        mod_exists = bool(version and self.check_mod_present(loader, version))
        
        if not self.skin_path:
            self.skin_indicator.config(text="⚪ No Skin Selected", fg=COLORS['text_secondary'])
            self.launch_btn.config(bg=COLORS['mc_green'])
        elif loader == "Vanilla":
            self.skin_indicator.config(text="⚠️ Vanilla: Local skin not supported", fg="#F39C12")
            self.launch_btn.config(bg="#F39C12")
        elif mod_exists:
            self.skin_indicator.config(text="✅ Ready: Skin & Mod found", fg="#2ECC71")
            self.launch_btn.config(bg="#2ECC71")
        elif self.mod_available_online:
            self.skin_indicator.config(text="⬇️ Mod will be downloaded", fg="#3498DB")
            self.launch_btn.config(bg="#3498DB")
        else:
            self.skin_indicator.config(text="❌ Incompatible: Mod not found", fg="#E74C3C")
            self.launch_btn.config(bg="#E74C3C")

    def check_mod_online(self, mc_version, loader):
        self.mod_available_online = False
        self.root.after(0, self.update_skin_indicator)
        if loader not in MOD_COMPATIBLE_LOADERS:
            return
        api_url = "https://api.github.com/repos/zlainsama/OfflineSkins/releases"
        try:
            r = requests.get(api_url, timeout=5)
            if r.status_code == 200:
                search_loader = loader.lower()
                for release in r.json():
                    for asset in release.get("assets", []):
                        if search_loader in asset["name"].lower() and mc_version in asset["name"]:
                            self.mod_available_online = True
                            self.root.after(0, self.update_skin_indicator)
                            return
            self.mod_available_online = False
        except: 
            self.mod_available_online = False
        self.root.after(0, self.update_skin_indicator)

    def render_preview(self):
        try:
            if not self.skin_path or not os.path.exists(self.skin_path):
                return
            img = Image.open(self.skin_path)
            head = img.crop((8, 8, 16, 16))
            body = img.crop((20, 20, 28, 32))
            arm = img.crop((44, 20, 48, 32))
            leg = img.crop((4, 20, 8, 32))
            scale = 8
            full_view = Image.new("RGBA", (16*scale, 32*scale), (0, 0, 0, 0))
            full_view.paste(head.resize((8*scale, 8*scale), Image.NEAREST), (4*scale, 0))
            full_view.paste(body.resize((8*scale, 12*scale), Image.NEAREST), (4*scale, 8*scale))
            full_view.paste(arm.resize((4*scale, 12*scale), Image.NEAREST), (0, 8*scale))
            full_view.paste(arm.resize((4*scale, 12*scale), Image.NEAREST), (12*scale, 8*scale))
            full_view.paste(leg.resize((4*scale, 12*scale), Image.NEAREST), (4*scale, 20*scale))
            full_view.paste(leg.resize((4*scale, 12*scale), Image.NEAREST), (8*scale, 20*scale))
            self.tk_preview = ImageTk.PhotoImage(full_view)
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(80, 120, image=self.tk_preview)
        except Exception as e: 
            self.log(f"Preview Error: {e}")

    def select_skin(self):
        if not self.auto_download_mod:
            if messagebox.askyesno("Mod Requirement", "Allow launcher to manage OfflineSkins mod?"):
                self.auto_download_mod = True
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.png")])
        if path:
            self.skin_path = path
            self.render_preview()
            self.update_skin_indicator()

    def open_mods(self):
        path = os.path.join(self.minecraft_dir, "mods")
        os.makedirs(path, exist_ok=True)
        if os.name == 'nt':
            os.startfile(path)
        else:
            subprocess.call(['open', path])

    def load_from_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                    self.user_entry.insert(0, data.get("username", DEFAULT_USERNAME))
                    loader_choice = data.get("loader", LOADERS[0])
                    self.loader_var.set(loader_choice if loader_choice in LOADERS else LOADERS[0])
                    self.last_version = data.get("last_version", "")
                    self.skin_path = data.get("skin_path", "")
                    self.auto_download_mod = data.get("auto_download_mod", False)
                    self.auto_download_var.set(self.auto_download_mod)
                    self.ram_allocation = data.get("ram_allocation", DEFAULT_RAM)
                    self.ram_var.set(self.ram_allocation)
                    self.ram_entry_var.set(str(self.ram_allocation))
                    if self.skin_path:
                        self.render_preview()
                        self.update_skin_indicator()
            except: 
                self.user_entry.insert(0, DEFAULT_USERNAME)
        else: 
            self.user_entry.insert(0, DEFAULT_USERNAME)

    def load_versions(self):
        loader = self.loader_var.get()
        self.set_status(f"Refreshing {loader} versions...", COLORS['text_secondary'])
        threading.Thread(target=self._fetch_logic, args=(loader,), daemon=True).start()

    def _fetch_logic(self, loader):
        try:
            raw_list = self._fetch_versions_for_loader(loader)
            display_list = [format_version_display(v_id) for v_id in raw_list]
            self.root.after(0, lambda: self._apply_version_list(loader, display_list))
        except Exception as e:
            self.log(f"Fetch Error: {e}")
            self.root.after(0, lambda err=str(e): self.set_status(f"Error: {err}", "#E74C3C"))

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
        self.set_status(f"{loader} ready", COLORS['mc_green'])
        version = normalize_version_text(self.version_var.get())
        if version:
            self.mod_available_online = False
            threading.Thread(target=self.check_mod_online, args=(version, loader), daemon=True).start()
        self.update_skin_indicator()

    def download_offlineskins(self, mc_version, loader):
        repo = "zlainsama/OfflineSkins"
        api_url = f"https://api.github.com/repos/{repo}/releases"
        self._cleanup_conflicting_mods(loader, mc_version)
        try:
            releases = requests.get(api_url).json()
            search_loader = loader.lower()
            for release in releases:
                for asset in release.get("assets", []):
                    if search_loader in asset["name"].lower() and mc_version in asset["name"]:
                        dest = os.path.join(self.minecraft_dir, "mods", asset["name"])
                        self.log(f"Downloading mod: {asset['name']}...")
                        r = requests.get(asset["browser_download_url"], stream=True)
                        with open(dest, "wb") as f:
                            for chunk in r.iter_content(8192): 
                                f.write(chunk)
                        return True
        except Exception as e: 
            self.log(f"Download Error: {e}")
        return False

    def start_launch(self):
        v_text = self.version_var.get()
        if not v_text:
            return
        version = normalize_version_text(v_text)
        username = self.user_entry.get().strip() or DEFAULT_USERNAME
        self.last_version = v_text
        config = {
            "username": username, 
            "loader": self.loader_var.get(), 
            "last_version": v_text, 
            "skin_path": self.skin_path, 
            "auto_download_mod": self.auto_download_mod, 
            "ram_allocation": self.ram_allocation
        }
        with open(self.config_file, "w") as f: 
            json.dump(config, f)
        self.launch_btn.config(state="disabled", text="LAUNCHING...")
        self.set_status("Launching Minecraft...", COLORS['text_secondary'])
        threading.Thread(target=self.launch_logic, args=(version, username, self.loader_var.get()), daemon=True).start()

    def launch_logic(self, version, username, loader):
        callback = {
            "setStatus": lambda t: self.log(f"Status: {t}"),
            "setProgress": lambda v: self.root.after(0, lambda: self.progress_bar.config(value=v)),
            "setMax": lambda m: self.root.after(0, lambda: self.progress_bar.config(maximum=m))
        }
        try:
            launch_id = version
            if loader == "Fabric":
                self.log(f"Installing Fabric for {version}...")
                result = minecraft_launcher_lib.fabric.install_fabric(version, self.minecraft_dir, callback=callback)
                if result:
                    launch_id = result
                else:
                    loader_v = minecraft_launcher_lib.fabric.get_latest_loader_version()
                    launch_id = f"fabric-loader-{loader_v}-{version}"
                    self.log(f"Library returned None. Falling back to ID: {launch_id}")
            elif loader == "Forge":
                forge_v = minecraft_launcher_lib.forge.find_forge_version(version)
                if forge_v:
                    minecraft_launcher_lib.forge.install_forge_version(forge_v, self.minecraft_dir, callback=callback)
                    launch_id = forge_v

            if self.auto_download_mod and loader in ["Forge", "Fabric"] and not self.check_mod_present():
                self.download_offlineskins(version, loader)

            if self.skin_path and os.path.exists(self.skin_path):
                shutil.copy(self.skin_path, os.path.join(self.minecraft_dir, "launcher_skin.png"))

            options = {"username": username, "uuid": "", "token": "", "javaArgs": f"-Xmx{self.ram_allocation}M"}
            self.log(f"Generating command for: {launch_id}")
            command = minecraft_launcher_lib.command.get_minecraft_command(launch_id, self.minecraft_dir, options)
            
            self.root.after(0, self.root.withdraw)
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                self.root.after(0, lambda l=line: self.log(f"[GAME] {l.strip()}"))
            process.wait()
            self.root.after(0, self.root.deiconify)
        except Exception as e:
            self.log(f"Error: {e}")
            self.root.after(0, lambda: messagebox.showerror("Launch Error", str(e)))
        finally:
            self.root.after(0, lambda: self.launch_btn.config(state="normal", text="PLAY"))
            self.root.after(0, self.update_skin_indicator)

if __name__ == "__main__":
    root = tk.Tk()
    app = MinecraftLauncher(root)
    root.mainloop()