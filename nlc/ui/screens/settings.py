"""
nlc.ui.screens.settings - Settings tab implementation (Neo and Classic styles)
"""

import logging
import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext
from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno
from nlc.storage.config import DEFAULT_RAM, CURRENT_VERSION

logger = logging.getLogger(__name__)

class SettingsScreenMixin:
    """Mixin for settings view in both Neo and Classic layouts."""
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


