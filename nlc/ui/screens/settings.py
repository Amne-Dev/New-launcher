"""
nlc.ui.screens.settings - Overhauled modern two-pane Settings screen.
Provides categorized navigation, SettingRow components, tactile toggle switches,
visual RAM gauge with quick-select chips, Java runtime auto-detection, and log viewer.
"""

import logging
import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog
from typing import Dict, List, Optional, Tuple, Any

from nlc.ui.theme import COLORS, FONT_FAMILY, THEMES, THEME_MANAGER
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno
from nlc.ui.components.settings_row import (
    create_setting_row, create_toggle_switch, create_segmented_chips, ToggleSwitch
)
from nlc.ui.components.buttons import make_button, make_badge
from nlc.ui.components.cards import create_card
from nlc.core.system_info import get_total_ram_mb, detect_installed_javas, get_system_specs
from nlc.storage.config import DEFAULT_RAM, CURRENT_VERSION

logger = logging.getLogger(__name__)

CATEGORIES = [
    ("General", "command_block_front.png", "Startup, window behavior, and launcher setup"),
    ("Appearance", "painting.png", "Themes, custom accent colors, and 60 FPS animations"),
    ("Java & Memory", "furnace_front_on.png", "RAM allocation, JVM runtime scanner, and directory"),
    ("Downloads", "hopper_top.png", "Concurrent download limits and speed throttling"),
    ("Integrations", "jukebox_top.png", "Discord Rich Presence and streamer privacy mode"),
    ("Logs & Diagnostics", "lectern_top.png", "System hardware diagnostics and launcher console"),
    ("About & Reset", "anvil.png", "Version information and factory settings reset"),
]


class SettingsScreenMixin:
    """Mixin for the modern categorized Settings panel."""

    def _init_settings_vars(self):
        """Ensure all persistent Tkinter variables for settings exist upfront."""
        if not hasattr(self, 'ram_var'):
            self.ram_var = tk.IntVar(value=getattr(self, 'ram_allocation', DEFAULT_RAM))
        if not hasattr(self, 'ram_entry_var'):
            self.ram_entry_var = tk.StringVar(value=str(self.ram_var.get()))
            self.ram_entry_var.trace_add("write", self._on_ram_entry_change)

        if not hasattr(self, 'close_launcher_var'):
            self.close_launcher_var = tk.BooleanVar(value=getattr(self, 'close_launcher', True))
        if not hasattr(self, 'minimize_to_tray_var'):
            self.minimize_to_tray_var = tk.BooleanVar(value=getattr(self, 'minimize_to_tray', False))
        if not hasattr(self, 'show_console_var'):
            self.show_console_var = tk.BooleanVar(value=getattr(self, 'show_console', False))
        if not hasattr(self, 'animations_enabled_var'):
            self.animations_enabled_var = tk.BooleanVar(value=getattr(self, 'animations_enabled', True))
        if not hasattr(self, 'custom_titlebar_var'):
            self.custom_titlebar_var = tk.BooleanVar(value=getattr(self, 'custom_titlebar_enabled', True if os.name == 'nt' else False))
        if not hasattr(self, 'limit_packs_var'):
            self.limit_packs_var = tk.IntVar(value=getattr(self, 'max_concurrent_packs', 1))
        if not hasattr(self, 'limit_mods_var'):
            self.limit_mods_var = tk.IntVar(value=getattr(self, 'max_concurrent_mods', 3))
        if not hasattr(self, 'limit_speed_enc_var'):
            self.limit_speed_enc_var = tk.BooleanVar(value=getattr(self, 'limit_download_speed_enabled', False))
        if not hasattr(self, 'limit_speed_val_var'):
            self.limit_speed_val_var = tk.IntVar(value=getattr(self, 'max_download_speed', 2048))
        if not hasattr(self, 'auto_update_var'):
            self.auto_update_var = tk.BooleanVar(value=getattr(self, 'auto_update_check', True))
        if not hasattr(self, 'rpc_var'):
            self.rpc_var = tk.BooleanVar(value=getattr(self, 'rpc_enabled', True))
        if not hasattr(self, 'rpc_detail_mode_var'):
            self.rpc_detail_mode_var = tk.StringVar(value=getattr(self, 'rpc_detail_mode', "Show Version"))
        if not hasattr(self, 'streamer_mode_var'):
            self.streamer_mode_var = tk.BooleanVar(value=self._is_streamer_mode_enabled())
        if not hasattr(self, 'username_var'):
            self.username_var = tk.StringVar(value=getattr(self, 'username', 'Steve'))
            self.username_var.trace_add("write", lambda *a: setattr(self, 'username', self.username_var.get()))

    def create_settings_tab(self):
        """Construct the modern two-pane categorized settings workspace."""
        self._init_settings_vars()
        container = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Settings"] = container

        self.current_settings_category = getattr(self, "current_settings_category", "General")
        self._category_buttons = {}

        # --- Top Header ---
        header_frame = tk.Frame(container, bg=COLORS['sidebar_bg'], height=60)
        header_frame.pack(side="top", fill="x")
        self.settings_header_frame = header_frame

        title_box = tk.Frame(header_frame, bg=COLORS['sidebar_bg'])
        title_box.pack(side="left", padx=25, pady=12)
        self.settings_title_box = title_box

        self.settings_title_lbl = tk.Label(
            title_box,
            text="SETTINGS",
            font=(FONT_FAMILY, 13, "bold"),
            bg=COLORS['sidebar_bg'],
            fg=COLORS['text_primary']
        )
        self.settings_title_lbl.pack(side="left")

        self.header_breadcrumb_lbl = tk.Label(
            title_box,
            text=f"  /  {self.current_settings_category.upper()}",
            font=(FONT_FAMILY, 9),
            bg=COLORS['sidebar_bg'],
            fg=COLORS.get('accent_color', '#2ECC71')
        )
        self.header_breadcrumb_lbl.pack(side="left")

        # --- Main Content Scroll Area (Full width; navigation integrated into main dynamic sidebar) ---
        self.nav_rail = None
        content_wrapper = tk.Frame(container, bg=COLORS['main_bg'])
        content_wrapper.pack(side="top", fill="both", expand=True)
        self.settings_content_wrapper = content_wrapper

        canvas = tk.Canvas(content_wrapper, bg=COLORS['main_bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(content_wrapper, orient="vertical", command=canvas.yview, style="Launcher.Vertical.TScrollbar")
        self.settings_canvas = canvas

        self.settings_scroll_frame = tk.Frame(canvas, bg=COLORS['main_bg'])
        self.settings_scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_window = canvas.create_window((0, 0), window=self.settings_scroll_frame, anchor="nw", width=content_wrapper.winfo_reqwidth())

        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        if hasattr(self, '_bind_wheel_events') and hasattr(self, '_smooth_scroll'):
            self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
        if hasattr(self, '_bind_smooth_scroll'):
            content_wrapper.bind("<Enter>", lambda e: self._bind_smooth_scroll(canvas, self.settings_scroll_frame))

        # Render initially selected category
        self.switch_settings_category(self.current_settings_category)

    def refresh_settings_screen_theme(self):
        """Update Settings screen header, canvas, and active category content with new theme colors."""
        sidebar_bg = COLORS['sidebar_bg']
        main_bg = COLORS['main_bg']
        accent_col = COLORS.get('accent_color', '#2ECC71')
        text_primary = COLORS['text_primary']

        if hasattr(self, 'tabs') and 'Settings' in self.tabs and self.tabs['Settings'].winfo_exists():
            self.tabs['Settings'].config(bg=main_bg)
        if hasattr(self, 'settings_header_frame') and self.settings_header_frame.winfo_exists():
            self.settings_header_frame.config(bg=sidebar_bg)
        if hasattr(self, 'settings_title_box') and self.settings_title_box.winfo_exists():
            self.settings_title_box.config(bg=sidebar_bg)
        if hasattr(self, 'settings_title_lbl') and self.settings_title_lbl.winfo_exists():
            self.settings_title_lbl.config(bg=sidebar_bg, fg=text_primary)
        if hasattr(self, 'header_breadcrumb_lbl') and self.header_breadcrumb_lbl.winfo_exists():
            self.header_breadcrumb_lbl.config(bg=sidebar_bg, fg=accent_col)
        if hasattr(self, 'settings_content_wrapper') and self.settings_content_wrapper.winfo_exists():
            self.settings_content_wrapper.config(bg=main_bg)
        if hasattr(self, 'settings_canvas') and self.settings_canvas.winfo_exists():
            self.settings_canvas.config(bg=main_bg)
        if hasattr(self, 'settings_scroll_frame') and self.settings_scroll_frame.winfo_exists():
            self.settings_scroll_frame.config(bg=main_bg)

        # Re-render active settings category so all cards, setting rows, buttons, toggles and text use the new theme!
        current_cat = getattr(self, 'current_settings_category', 'General')
        if hasattr(self, 'switch_settings_category'):
            self.switch_settings_category(current_cat)

    def switch_settings_category(self, category_name: str):
        """Switch active category in the right content pane."""
        self.current_settings_category = category_name
        sidebar_bg = COLORS['sidebar_bg']
        main_bg = COLORS['main_bg']
        accent_col = COLORS.get('accent_color', '#2ECC71')
        text_primary = COLORS['text_primary']

        if hasattr(self, 'header_breadcrumb_lbl') and self.header_breadcrumb_lbl.winfo_exists():
            self.header_breadcrumb_lbl.config(
                text=f"  /  {category_name.upper()}",
                bg=sidebar_bg,
                fg=accent_col
            )
        if hasattr(self, 'settings_title_lbl') and self.settings_title_lbl.winfo_exists():
            self.settings_title_lbl.config(bg=sidebar_bg, fg=text_primary)
        if hasattr(self, 'settings_header_frame') and self.settings_header_frame.winfo_exists():
            self.settings_header_frame.config(bg=sidebar_bg)
        if hasattr(self, 'settings_title_box') and self.settings_title_box.winfo_exists():
            self.settings_title_box.config(bg=sidebar_bg)
        if hasattr(self, 'settings_content_wrapper') and self.settings_content_wrapper.winfo_exists():
            self.settings_content_wrapper.config(bg=main_bg)
        if hasattr(self, 'settings_canvas') and self.settings_canvas.winfo_exists():
            self.settings_canvas.config(bg=main_bg)
        if hasattr(self, 'settings_scroll_frame') and self.settings_scroll_frame.winfo_exists():
            self.settings_scroll_frame.config(bg=main_bg)

        # Update dynamic sidebar highlight if sidebar buttons exist
        sidebar_items = getattr(self, 'settings_nav_items', {})
        target_frame = sidebar_items.get(category_name)
        if target_frame and hasattr(self, 'set_active_sidebar'):
            try:
                self.set_active_sidebar(target_frame)
            except Exception:
                pass

        # Clear and re-populate the content pane
        if hasattr(self, 'settings_scroll_frame') and self.settings_scroll_frame.winfo_exists():
            for child in self.settings_scroll_frame.winfo_children():
                child.destroy()

        if hasattr(self, 'settings_canvas') and self.settings_canvas.winfo_exists():
            self.settings_canvas.yview_moveto(0)

        main_box = tk.Frame(self.settings_scroll_frame, bg=COLORS['main_bg'], padx=35, pady=25)
        main_box.pack(fill="both", expand=True)

        if category_name == "General":
            self._render_general_settings(main_box)
        elif category_name == "Appearance":
            self._render_appearance_settings(main_box)
        elif category_name == "Java & Memory":
            self._render_java_settings(main_box)
        elif category_name == "Downloads":
            self._render_downloads_settings(main_box)
        elif category_name == "Integrations":
            self._render_integrations_settings(main_box)
        elif category_name == "Logs & Diagnostics":
            self._render_logs_settings(main_box)
        elif category_name == "About & Reset":
            self._render_about_settings(main_box)

    # -------------------------------------------------------------------------
    # Category Renders
    # -------------------------------------------------------------------------

    def _render_general_settings(self, parent: tk.Widget):
        """Render General category cards."""
        card1 = create_card(parent, padx=22, pady=18)
        card1.pack(fill="x", pady=(0, 16))

        tk.Label(card1, text="LAUNCHER LIFECYCLE", font=(FONT_FAMILY, 11, "bold"), bg=card1.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 10))

        self.close_launcher_var = tk.BooleanVar(value=getattr(self, 'close_launcher', True))
        t1 = create_toggle_switch(card1, self.close_launcher_var, command=self.save_config, animator=getattr(self, 'animator', None))
        create_setting_row(card1, "Close Launcher on Launch", "Automatically closes the launcher window once Minecraft initializes.", t1)

        self.minimize_to_tray_var = tk.BooleanVar(value=getattr(self, 'minimize_to_tray', False))
        t2 = create_toggle_switch(card1, self.minimize_to_tray_var, command=self.save_config, animator=getattr(self, 'animator', None))
        create_setting_row(card1, "Minimize to System Tray on Close", "Keeps the launcher running quietly in the tray when the window is closed.", t2)

        self.show_console_var = tk.BooleanVar(value=getattr(self, 'show_console', False))
        t3 = create_toggle_switch(card1, self.show_console_var, command=self.save_config, animator=getattr(self, 'animator', None))
        create_setting_row(card1, "Keep Output Console Open (Debug)", "Displays a dedicated real-time console window for debugging mods and crashes.", t3)

        # Onboarding Card
        card2 = create_card(parent, padx=22, pady=18)
        card2.pack(fill="x")

        tk.Label(card2, text="SETUP & WIZARD", font=(FONT_FAMILY, 11, "bold"), bg=card2.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 10))

        btn_wiz = make_button(card2, "Replay Setup Wizard", style="secondary", command=lambda: getattr(self, 'show_onboarding_wizard', lambda: None)())
        create_setting_row(card2, "Onboarding Setup Wizard", "Re-run the initial configuration walk-through for accounts and game directories.", btn_wiz)

    def _render_appearance_settings(self, parent: tk.Widget):
        """Render Appearance, Themes, and Animation settings."""
        # 1. Motion & Animations
        card_motion = create_card(parent, padx=22, pady=18)
        card_motion.pack(fill="x", pady=(0, 16))

        tk.Label(card_motion, text="MOTION & ANIMATIONS", font=(FONT_FAMILY, 11, "bold"), bg=card_motion.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 10))

        self.animations_enabled_var = tk.BooleanVar(value=getattr(self, 'animations_enabled', True))
        def on_anim_toggle():
            val = self.animations_enabled_var.get()
            self.animations_enabled = val
            self.save_config()

        t_anim = create_toggle_switch(card_motion, self.animations_enabled_var, command=on_anim_toggle, animator=getattr(self, 'animator', None))
        create_setting_row(
            card_motion,
            "Enable Smooth Transitions & Micro-Animations (60 FPS)",
            "Enables smooth tab slides, hover glows, and progress smoothing. Turn off for instant 0ms state changes and zero CPU overhead on low-end hardware.",
            t_anim
        )

        # 2. Curated Themes Grid
        card_themes = create_card(parent, padx=22, pady=18)
        card_themes.pack(fill="x", pady=(0, 16))

        tk.Label(card_themes, text="CURATED DESIGNER THEMES", font=(FONT_FAMILY, 11, "bold"), bg=card_themes.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 4))
        tk.Label(card_themes, text="Click any palette to instantly re-skin the launcher in real-time.", font=(FONT_FAMILY, 8), bg=card_themes.cget("bg"), fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 14))

        theme_grid = tk.Frame(card_themes, bg=card_themes.cget("bg"))
        theme_grid.pack(fill="x")

        current_theme = getattr(self, "theme_id", "dark_slate")

        for i, (t_key, t_info) in enumerate(THEMES.items()):
            col_idx = i % 3
            row_idx = i // 3
            is_active = (t_key == current_theme)

            t_card = tk.Frame(
                theme_grid,
                bg=t_info['card_bg'],
                cursor="hand2",
                padx=12,
                pady=10,
                highlightthickness=2 if is_active else 1,
                highlightbackground=COLORS.get('accent_color', '#2ECC71') if is_active else COLORS.get('border_subtle', '#2B303A')
            )
            t_card.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="ew")
            theme_grid.columnconfigure(col_idx, weight=1)

            # Header row inside theme card
            t_hdr = tk.Frame(t_card, bg=t_info['card_bg'])
            t_hdr.pack(fill="x")

            t_dot = tk.Label(t_hdr, text="●", font=(FONT_FAMILY, 9), bg=t_info['card_bg'], fg=t_info.get('default_accent', '#2ECC71'))
            t_dot.pack(side="left", padx=(0, 6))

            t_name = tk.Label(t_hdr, text=t_info['name'], font=(FONT_FAMILY, 9, "bold"), bg=t_info['card_bg'], fg="white", cursor="hand2")
            t_name.pack(side="left")

            t_sub = tk.Label(t_card, text=t_info['description'], font=(FONT_FAMILY, 8), bg=t_info['card_bg'], fg=COLORS.get('text_secondary', '#A6ACB8'), cursor="hand2", wraplength=180, justify="left")
            t_sub.pack(anchor="w", pady=(4, 0))

            def _make_theme_click(k=t_key):
                return lambda e: getattr(self, "apply_theme", lambda *a, **kw: None)(k, custom_accent=None)

            for w in [t_card, t_hdr, t_dot, t_name, t_sub]:
                w.bind("<Button-1>", _make_theme_click(t_key))

        # 3. Accent Color & Custom Hex
        card_accent = create_card(parent, padx=22, pady=18)
        card_accent.pack(fill="x", pady=(0, 16))

        tk.Label(card_accent, text="ACCENT COLOR & LIVE SWATCHES", font=(FONT_FAMILY, 11, "bold"), bg=card_accent.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 10))

        swatch_frame = tk.Frame(card_accent, bg=card_accent.cget("bg"))
        swatch_frame.pack(fill="x", pady=(0, 10))

        _current_acc = getattr(self, "custom_accent", None) or getattr(self, "accent_color_name", "Emerald")
        _swatches = [
            ("Emerald", "#2ECC71"),
            ("Neon Cyan", "#00E5FF"),
            ("Sapphire", "#3498DB"),
            ("Violet", "#9B59B6"),
            ("Sunset", "#F39C12"),
            ("Crimson", "#E74C3C"),
            ("Hot Pink", "#EC4899"),
        ]

        for name, col in _swatches:
            f = tk.Frame(swatch_frame, bg=card_accent.cget("bg"), padx=2, pady=2)
            f.pack(side="left", padx=4)
            is_sel = (_current_acc == name or _current_acc == col)
            if is_sel:
                f.config(bg="white")
            btn = tk.Button(
                f, bg=col, width=4, height=1, relief="flat", bd=0, cursor="hand2",
                command=lambda c=col: [getattr(self, "apply_accent_color", lambda x: None)(c), self.switch_settings_category("Appearance")]
            )
            btn.config(activebackground=col)
            btn.pack()

        # Custom Hex row
        hex_row = tk.Frame(card_accent, bg=card_accent.cget("bg"))
        hex_row.pack(fill="x", pady=(6, 0))
        tk.Label(hex_row, text="Custom Hex Code:", font=(FONT_FAMILY, 9), bg=card_accent.cget("bg"), fg=COLORS['text_secondary']).pack(side="left", padx=(0, 8))
        self.custom_hex_entry = tk.Entry(hex_row, font=(FONT_FAMILY, 9), bg=COLORS['input_bg'], fg="white", width=10, relief="flat", insertbackground="white")
        self.custom_hex_entry.insert(0, getattr(self, "custom_accent", "") or "#2ECC71")
        self.custom_hex_entry.pack(side="left", ipady=3)

        def on_apply_hex():
            val = self.custom_hex_entry.get().strip()
            if not val.startswith("#"):
                val = f"#{val}"
            if len(val) == 7 and all(c in "0123456789abcdefABCDEF" for c in val[1:]):
                getattr(self, "apply_accent_color", lambda x: None)(val)
                self.switch_settings_category("Appearance")
            else:
                custom_showerror("Invalid Hex", "Please enter a valid 6-character hex code (e.g. #00E5FF).")

        make_button(hex_row, "Apply Hex", style="secondary", command=on_apply_hex).pack(side="left", padx=(8, 0))

        # 4. Windows Titlebar
        if os.name == "nt":
            card_tb = create_card(parent, padx=22, pady=18)
            card_tb.pack(fill="x")
            self.custom_titlebar_var = tk.BooleanVar(value=getattr(self, 'custom_titlebar_enabled', True))
            def on_titlebar_toggle():
                val = self.custom_titlebar_var.get()
                self.custom_titlebar_enabled = val
                self.save_config()
                if hasattr(self, 'root'):
                    custom_showinfo("Restart Required", "Restart the launcher to apply titlebar changes.")
            t_tb = create_toggle_switch(card_tb, self.custom_titlebar_var, command=on_titlebar_toggle, animator=getattr(self, 'animator', None))
            create_setting_row(card_tb, "Custom Dark Titlebar", "Enables seamless dark custom titlebar on Windows 10/11.", t_tb)

    def _render_java_settings(self, parent: tk.Widget):
        """Render Memory gauge, Java runtime auto-detector, and arguments."""
        # 1. RAM Allocation Card
        card_ram = create_card(parent, padx=22, pady=18)
        card_ram.pack(fill="x", pady=(0, 16))

        total_system_mb = get_total_ram_mb()
        total_system_gb = round(total_system_mb / 1024.0, 1)

        tk.Label(card_ram, text="MEMORY ALLOCATION (RAM)", font=(FONT_FAMILY, 11, "bold"), bg=card_ram.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w")
        tk.Label(card_ram, text=f"Total Physical System Memory: {total_system_gb} GB", font=(FONT_FAMILY, 8), bg=card_ram.cget("bg"), fg=COLORS.get('accent_color', '#2ECC71')).pack(anchor="w", pady=(2, 12))

        # Quick Chips
        chip_opts = [
            ("2 GB", 2048),
            ("4 GB", 4096),
            ("6 GB", 6144),
            ("8 GB", 8192),
            ("12 GB", 12288),
        ]
        # Filter chips exceeding total RAM
        chip_opts = [opt for opt in chip_opts if opt[1] <= total_system_mb]

        if not hasattr(self, 'ram_var'):
            self.ram_var = tk.IntVar(value=getattr(self, 'ram_allocation', DEFAULT_RAM))
        if not hasattr(self, 'ram_entry_var'):
            self.ram_entry_var = tk.StringVar(value=str(self.ram_var.get()))
            self.ram_entry_var.trace_add("write", self._on_ram_entry_change)
        else:
            self.ram_entry_var.set(str(self.ram_var.get()))

        def _on_chip_select(val):
            self.ram_var.set(val)
            self._on_ram_slider_change(val)

        tk.Label(card_ram, text="Quick Allocation Presets:", font=(FONT_FAMILY, 8, "bold"), bg=card_ram.cget("bg"), fg=COLORS['text_secondary']).pack(anchor="w")
        create_segmented_chips(card_ram, chip_opts, self.ram_var, command=_on_chip_select)

        # Slider + Number box
        slider_frame = tk.Frame(card_ram, bg=card_ram.cget("bg"))
        slider_frame.pack(fill="x", pady=(6, 8))

        scale_max = max(total_system_mb, 16384)
        tk.Scale(
            slider_frame,
            from_=1024,
            to=scale_max,
            orient="horizontal",
            resolution=256,
            variable=self.ram_var,
            showvalue=0,
            bg=card_ram.cget("bg"),
            fg=COLORS['text_primary'],
            troughcolor=COLORS['input_bg'],
            highlightthickness=0,
            command=self._on_ram_slider_change
        ).pack(side="left", fill="x", expand=True)

        entry_box = tk.Entry(slider_frame, textvariable=self.ram_entry_var, width=6, font=(FONT_FAMILY, 9), bg=COLORS['input_bg'], fg="white", relief="flat", insertbackground="white")
        entry_box.pack(side="left", padx=(12, 4), ipady=3)
        tk.Label(slider_frame, text="MB", font=(FONT_FAMILY, 9), bg=card_ram.cget("bg"), fg=COLORS['text_secondary']).pack(side="left")

        # 2. Java Runtime Auto-Detector Card
        card_java = create_card(parent, padx=22, pady=18)
        card_java.pack(fill="x", pady=(0, 16))

        tk.Label(card_java, text="JAVA RUNTIME EXECUTABLE", font=(FONT_FAMILY, 11, "bold"), bg=card_java.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 4))
        tk.Label(card_java, text="Minecraft 1.20.5+ requires Java 21; 1.17–1.20.4 requires Java 17; older versions use Java 8.", font=(FONT_FAMILY, 8), bg=card_java.cget("bg"), fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 10))

        detected_javas = detect_installed_javas()
        java_display_labels = [j["label"] for j in detected_javas] or ["System Default (java)"]

        java_combo_var = tk.StringVar(value=java_display_labels[0] if java_display_labels else "")
        java_combo = ttk.Combobox(card_java, textvariable=java_combo_var, state="readonly", values=java_display_labels, width=45)
        java_combo.pack(anchor="w", pady=(0, 8))

        def on_java_combo_select(e):
            sel_text = java_combo_var.get()
            for j in detected_javas:
                if j["label"] == sel_text:
                    self.java_path_entry.delete(0, tk.END)
                    self.java_path_entry.insert(0, j["path"])
                    self.save_config()
                    break

        java_combo.bind("<<ComboboxSelected>>", on_java_combo_select)

        # Path Entry + Browse + Auto-Detect
        j_path_row = tk.Frame(card_java, bg=card_java.cget("bg"))
        j_path_row.pack(fill="x", pady=(2, 0))

        self.java_path_entry = tk.Entry(j_path_row, font=(FONT_FAMILY, 9), bg=COLORS['input_bg'], fg="white", relief="flat", insertbackground="white")
        if detected_javas:
            self.java_path_entry.insert(0, detected_javas[0]["path"])
        self.java_path_entry.pack(side="left", fill="x", expand=True, ipady=4)

        def on_browse_java():
            f = filedialog.askopenfilename(title="Select Java Executable")
            if f:
                self.java_path_entry.delete(0, tk.END)
                self.java_path_entry.insert(0, f)
                self.save_config()

        def on_refresh_javas():
            j_list = detect_installed_javas()
            if j_list:
                java_combo["values"] = [j["label"] for j in j_list]
                java_combo_var.set(j_list[0]["label"])
                self.java_path_entry.delete(0, tk.END)
                self.java_path_entry.insert(0, j_list[0]["path"])
                self.save_config()
                custom_showinfo("Java Detected", f"Found {len(j_list)} Java installation(s) on your system.")
            else:
                custom_showerror("No Java Found", "Could not locate standard Java runtimes automatically. Please browse manually.")

        make_button(j_path_row, "Browse...", style="secondary", command=on_browse_java).pack(side="left", padx=(8, 4))
        make_button(j_path_row, "Auto-Detect", style="secondary", command=on_refresh_javas).pack(side="left")

        # 3. JVM Arguments & Directory
        card_dir = create_card(parent, padx=22, pady=18)
        card_dir.pack(fill="x")

        tk.Label(card_dir, text="JVM ARGUMENTS & GAME DIRECTORY", font=(FONT_FAMILY, 11, "bold"), bg=card_dir.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 10))

        tk.Label(card_dir, text="Java Virtual Machine Arguments (JVM Flags):", font=(FONT_FAMILY, 8, "bold"), bg=card_dir.cget("bg"), fg=COLORS['text_secondary']).pack(anchor="w")
        self.java_args_entry = tk.Entry(card_dir, font=(FONT_FAMILY, 9), bg=COLORS['input_bg'], fg="white", relief="flat", insertbackground="white")
        self.java_args_entry.insert(0, getattr(self, "java_args", ""))
        self.java_args_entry.pack(fill="x", pady=(4, 12), ipady=5)
        self.java_args_entry.bind("<FocusOut>", self.save_config)

        tk.Label(card_dir, text="Minecraft Data Directory:", font=(FONT_FAMILY, 8, "bold"), bg=card_dir.cget("bg"), fg=COLORS['text_secondary']).pack(anchor="w")
        d_row = tk.Frame(card_dir, bg=card_dir.cget("bg"))
        d_row.pack(fill="x", pady=(4, 0))

        self.dir_entry = tk.Entry(d_row, font=(FONT_FAMILY, 9), bg=COLORS['input_bg'], fg="white", relief="flat", insertbackground="white")
        self.dir_entry.insert(0, getattr(self, "minecraft_dir", ""))
        self.dir_entry.pack(side="left", fill="x", expand=True, ipady=4)

        make_button(d_row, "Change", style="secondary", command=getattr(self, 'change_minecraft_dir', lambda: None)).pack(side="left", padx=(8, 4))
        make_button(d_row, "Open Folder", style="secondary", command=getattr(self, 'open_minecraft_dir', lambda: None)).pack(side="left")

    def _render_downloads_settings(self, parent: tk.Widget):
        """Render Concurrent limits, speed limits, and auto-update."""
        card_lim = create_card(parent, padx=22, pady=18)
        card_lim.pack(fill="x", pady=(0, 16))

        tk.Label(card_lim, text="DOWNLOAD CONCURRENCY & LIMITS", font=(FONT_FAMILY, 11, "bold"), bg=card_lim.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 10))

        def update_limits(*args):
            try:
                self.max_concurrent_packs = int(self.limit_packs_var.get())
                self.max_concurrent_mods = int(self.limit_mods_var.get())
                self.save_config(sync_ui=False)
            except Exception:
                pass

        self.limit_packs_var = tk.StringVar(value=str(getattr(self, 'max_concurrent_packs', 1)))
        self.limit_packs_var.trace_add("write", update_limits)
        e_packs = tk.Entry(card_lim, textvariable=self.limit_packs_var, width=5, bg=COLORS['input_bg'], fg="white", relief="flat")
        create_setting_row(card_lim, "Max Concurrent Modpack Downloads", "Simultaneous modpacks downloaded in parallel (1–3).", e_packs)

        self.limit_mods_var = tk.StringVar(value=str(getattr(self, 'max_concurrent_mods', 3)))
        self.limit_mods_var.trace_add("write", update_limits)
        e_mods = tk.Entry(card_lim, textvariable=self.limit_mods_var, width=5, bg=COLORS['input_bg'], fg="white", relief="flat")
        create_setting_row(card_lim, "Max Concurrent Mod Downloads", "Simultaneous individual mods/files downloaded in parallel (1–8).", e_mods)

        # Speed limit
        self.limit_speed_enc_var = tk.BooleanVar(value=getattr(self, 'limit_download_speed_enabled', False))
        t_spd = create_toggle_switch(
            card_lim, self.limit_speed_enc_var,
            command=lambda: [setattr(self, 'limit_download_speed_enabled', self.limit_speed_enc_var.get()), self.save_config(sync_ui=False)],
            animator=getattr(self, 'animator', None)
        )
        create_setting_row(card_lim, "Throttle Download Bandwidth", "Limit maximum download speed to avoid saturating network.", t_spd)

        self.limit_speed_val_var = tk.StringVar(value=str(getattr(self, 'max_download_speed', 2048)))
        def update_spd(*args):
            try:
                self.max_download_speed = int(self.limit_speed_val_var.get())
                self.save_config(sync_ui=False)
            except Exception:
                pass
        self.limit_speed_val_var.trace_add("write", update_spd)
        e_spd = tk.Entry(card_lim, textvariable=self.limit_speed_val_var, width=7, bg=COLORS['input_bg'], fg="white", relief="flat")
        create_setting_row(card_lim, "Maximum Speed (KB/s)", "Rate limit threshold applied when bandwidth throttling is enabled.", e_spd)

        # Updates Card
        card_upd = create_card(parent, padx=22, pady=18)
        card_upd.pack(fill="x")

        tk.Label(card_upd, text="SOFTWARE UPDATES", font=(FONT_FAMILY, 11, "bold"), bg=card_upd.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 10))

        self.auto_update_var = tk.BooleanVar(value=getattr(self, 'auto_update_check', True))
        t_upd = create_toggle_switch(card_upd, self.auto_update_var, command=self.save_config, animator=getattr(self, 'animator', None))
        create_setting_row(card_upd, "Check for Updates on Startup", "Automatically queries GitHub releases on startup for new launcher versions.", t_upd)

        btn_chk = make_button(card_upd, "Check Updates Now", style="secondary", command=self.check_for_updates)
        create_setting_row(card_upd, f"Launcher Version: {CURRENT_VERSION}", "Check GitHub for newer releases and download assets.", btn_chk)

        self.update_status_lbl = tk.Label(card_upd, text="", font=(FONT_FAMILY, 9), bg=card_upd.cget("bg"), fg=COLORS['text_secondary'])
        self.update_status_lbl.pack(anchor="w", pady=(4, 0))

    def _render_integrations_settings(self, parent: tk.Widget):
        """Render Discord Rich Presence, streamer privacy, and account options."""
        card_rpc = create_card(parent, padx=22, pady=18)
        card_rpc.pack(fill="x", pady=(0, 16))

        tk.Label(card_rpc, text="DISCORD RICH PRESENCE (RPC)", font=(FONT_FAMILY, 11, "bold"), bg=card_rpc.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 10))

        self.rpc_var = tk.BooleanVar(value=getattr(self, 'rpc_enabled', True))
        t_rpc = create_toggle_switch(card_rpc, self.rpc_var, command=self._on_rpc_toggle, animator=getattr(self, 'animator', None))
        create_setting_row(card_rpc, "Enable Discord RPC", "Displays launcher status and active Minecraft installation in Discord.", t_rpc)

        self.rpc_detail_mode_var = tk.StringVar(value=getattr(self, 'rpc_detail_mode_var', tk.StringVar(value="Show Version")).get())
        rpc_combo = ttk.Combobox(card_rpc, textvariable=self.rpc_detail_mode_var, state="readonly", values=["Show Version", "Show Server IP", "Hidden"], width=18)
        rpc_combo.bind("<<ComboboxSelected>>", lambda e: self.save_config())
        create_setting_row(card_rpc, "Activity Second Line Detail", "Information shown on the secondary Discord activity line.", rpc_combo)

        # Privacy Card
        card_priv = create_card(parent, padx=22, pady=18)
        card_priv.pack(fill="x")

        tk.Label(card_priv, text="ACCOUNT & STREAMER PRIVACY", font=(FONT_FAMILY, 11, "bold"), bg=card_priv.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 10))

        self.streamer_mode_var = tk.BooleanVar(value=self._is_streamer_mode_enabled())
        def on_streamer_toggle():
            val = self.streamer_mode_var.get()
            self.streamer_mode = val
            self.save_config()
            if hasattr(self, 'user_entry'):
                self.user_entry.config(show="*" if val else "")

        t_stream = create_toggle_switch(card_priv, self.streamer_mode_var, command=on_streamer_toggle, animator=getattr(self, 'animator', None))
        create_setting_row(card_priv, "Streamer Privacy Mode", "Masks account usernames and sensitive file system directories from view.", t_stream)

        self.user_entry = tk.Entry(card_priv, textvariable=self.username_var, font=(FONT_FAMILY, 10), bg=COLORS['input_bg'], fg="white", relief="flat", insertbackground="white", width=20)
        self.user_entry.config(show="*" if self._is_streamer_mode_enabled() else "")
        self.user_entry.bind("<FocusOut>", lambda e: self.save_config())
        create_setting_row(card_priv, "Default Offline Username", "Fallback player name used for offline sessions.", self.user_entry)

    def _render_logs_settings(self, parent: tk.Widget):
        """Render system hardware diagnostics and interactive log console."""
        # 1. System Info Banner
        card_sys = create_card(parent, padx=22, pady=18)
        card_sys.pack(fill="x", pady=(0, 16))

        tk.Label(card_sys, text="SYSTEM HARDWARE & DIAGNOSTICS", font=(FONT_FAMILY, 11, "bold"), bg=card_sys.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 10))

        specs = get_system_specs()
        for k, v in [("Operating System", specs["os"]), ("Python Runtime", specs["python"]), ("Physical Memory", specs["ram"]), ("CPU Architecture", specs["processor"])]:
            r = tk.Frame(card_sys, bg=card_sys.cget("bg"), pady=2)
            r.pack(fill="x")
            tk.Label(r, text=f"{k}:", font=(FONT_FAMILY, 9, "bold"), bg=card_sys.cget("bg"), fg=COLORS['text_secondary'], width=18, anchor="w").pack(side="left")
            tk.Label(r, text=v, font=(FONT_FAMILY, 9), bg=card_sys.cget("bg"), fg=COLORS['text_primary'], anchor="w").pack(side="left")

        # 2. Live Log Viewer
        card_log = create_card(parent, padx=22, pady=18)
        card_log.pack(fill="both", expand=True)

        tk.Label(card_log, text="LAUNCHER CONSOLE & LOGS", font=(FONT_FAMILY, 11, "bold"), bg=card_log.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 8))

        # Toolbar
        tb = tk.Frame(card_log, bg=card_log.cget("bg"))
        tb.pack(fill="x", pady=(0, 8))

        def copy_all_logs():
            try:
                txt = self.log_area.get("1.0", tk.END)
                self.root.clipboard_clear()
                self.root.clipboard_append(txt)
                custom_showinfo("Copied", "All logs copied to clipboard.")
            except Exception as e:
                custom_showerror("Error", f"Failed to copy logs: {e}")

        def open_logs_folder():
            log_dir = os.path.join(self.config_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            try:
                if os.name == 'nt':
                    os.startfile(log_dir)
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', log_dir])
                else:
                    subprocess.Popen(['xdg-open', log_dir])
            except Exception as e:
                custom_showerror("Error", f"Failed to open logs folder: {e}")

        def clear_logs_view():
            self.log_area.delete("1.0", tk.END)

        make_button(tb, "Copy All", style="secondary", font_size=8, command=copy_all_logs).pack(side="left", padx=(0, 6))
        make_button(tb, "Open Folder", style="secondary", font_size=8, command=open_logs_folder).pack(side="left", padx=(0, 6))
        make_button(tb, "Clear Display", style="secondary", font_size=8, command=clear_logs_view).pack(side="left")

        self.log_area = scrolledtext.ScrolledText(
            card_log,
            height=12,
            bg=COLORS['input_bg'],
            fg=COLORS.get('text_secondary', '#A6ACB8'),
            font=("Consolas" if os.name == "nt" else "Monospace", 9),
            relief="flat"
        )
        self.log_area.pack(fill="both", expand=True)

        # Load existing log file content into view if available
        try:
            log_dir = os.path.join(self.config_dir, "logs")
            if os.path.exists(log_dir):
                logs = sorted([os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.endswith(".log")])
                if logs:
                    latest_log = logs[-1]
                    with open(latest_log, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        recent_lines = "".join(lines[-200:])  # last 200 lines
                        self.log_area.insert("1.0", recent_lines)
                        self.log_area.see(tk.END)
        except Exception:
            pass

    def _render_about_settings(self, parent: tk.Widget):
        """Render About and Factory Reset cards."""
        card_about = create_card(parent, padx=22, pady=18)
        card_about.pack(fill="x", pady=(0, 16))

        tk.Label(card_about, text="ABOUT NEW LAUNCHER (NLC)", font=(FONT_FAMILY, 11, "bold"), bg=card_about.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 6))
        tk.Label(card_about, text=f"Version: {CURRENT_VERSION}  •  Python/Tkinter Native  •  MIT License", font=(FONT_FAMILY, 9), bg=card_about.cget("bg"), fg=COLORS.get('accent_color', '#2ECC71')).pack(anchor="w", pady=(0, 6))
        tk.Label(card_about, text="Fast, lightweight, open-source Minecraft launcher supporting Vanilla, Fabric, Forge, NeoForged, and Modrinth modpacks.", font=(FONT_FAMILY, 8), bg=card_about.cget("bg"), fg=COLORS['text_secondary'], wraplength=520, justify="left").pack(anchor="w", pady=(0, 10))

        btn_gh = make_button(card_about, "Open GitHub Repository", style="secondary", font_size=8, command=lambda: getattr(self, "open_url", lambda u: None)("https://github.com/Amne-Dev/New-launcher"))
        create_setting_row(card_about, "Source Code & Issue Tracker", "Visit the official repository for releases, updates, and feedback.", btn_gh)

        # Updates Card
        card_updates = create_card(parent, padx=22, pady=18)
        card_updates.pack(fill="x", pady=(0, 16))

        tk.Label(card_updates, text="LAUNCHER UPDATES", font=(FONT_FAMILY, 11, "bold"), bg=card_updates.cget("bg"), fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 6))

        upd_row = tk.Frame(card_updates, bg=card_updates.cget("bg"))
        upd_row.pack(fill="x", pady=(4, 0))

        status_txt = getattr(self, '_update_status_text', f"Installed version: {CURRENT_VERSION}")
        status_col = getattr(self, '_update_status_color', COLORS.get('accent_color', '#2ECC71'))

        self.update_status_lbl = tk.Label(
            upd_row,
            text=status_txt,
            font=(FONT_FAMILY, 9),
            bg=card_updates.cget("bg"),
            fg=status_col
        )
        self.update_status_lbl.pack(side="left")

        make_button(upd_row, "Check Now", style="secondary", font_size=8, command=lambda: getattr(self, 'check_for_updates', lambda: None)()).pack(side="right")

        # Danger Zone
        card_danger = create_card(parent, padx=22, pady=18, border_color="#B91C1C")
        card_danger.pack(fill="x")

        tk.Label(card_danger, text="DANGER ZONE", font=(FONT_FAMILY, 11, "bold"), bg=card_danger.cget("bg"), fg="#EF4444").pack(anchor="w", pady=(0, 10))

        btn_reset = make_button(card_danger, "Reset All to Defaults", style="danger", font_size=9, bold=True, command=self.reset_to_defaults)
        create_setting_row(
            card_danger,
            "Reset Launcher to Factory Defaults",
            "Permanently wipes local configuration, custom profiles, and cached launcher assets. The launcher will automatically restart.",
            btn_reset
        )

    # -------------------------------------------------------------------------
    # Actions & Lifecycle
    # -------------------------------------------------------------------------

    def reset_to_defaults(self):
        """Prompt and reset configuration to factory settings with clean restart."""
        if custom_askyesno("Confirm Reset", "Are you sure you want to reset all settings?\nThis will delete your profiles and configurations.\nThe launcher will restart."):
            try:
                if os.path.exists(self.config_file):
                    try:
                        os.remove(self.config_file)
                    except Exception:
                        pass

                wp_dir = os.path.join(self.config_dir, "wallpapers")
                if os.path.exists(wp_dir):
                    try:
                        shutil.rmtree(wp_dir, ignore_errors=True)
                    except Exception:
                        pass

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

                self.root.after(500, self.root.quit)

            except Exception as e:
                custom_showerror("Error", f"Failed to reset: {e}")

    def _on_ram_slider_change(self, value):
        """Handle RAM slider adjustments."""
        try:
            val = int(float(value))
            if hasattr(self, 'ram_entry_var'):
                self.ram_entry_var.set(str(val))
            self.ram_allocation = val
            if hasattr(self, 'save_config'):
                self.save_config()
        except Exception:
            pass

    def _on_ram_entry_change(self, *args):
        """Handle manual text entry in RAM allocation box."""
        try:
            if hasattr(self, 'ram_entry_var') and self.ram_entry_var.get().strip():
                val = int(self.ram_entry_var.get().strip())
                self.ram_allocation = val
                if hasattr(self, 'ram_var'):
                    self.ram_var.set(val)
                if hasattr(self, 'save_config'):
                    self.save_config()
        except ValueError:
            pass

    def _on_rpc_toggle(self):
        """Handle Discord RPC toggle switch."""
        if hasattr(self, 'rpc_var'):
            self.rpc_enabled = self.rpc_var.get()
            if self.rpc_enabled:
                if hasattr(self, 'connect_rpc'):
                    self.connect_rpc()
            else:
                if hasattr(self, 'close_rpc'):
                    self.close_rpc()
            if hasattr(self, 'save_config'):
                self.save_config()

    def _is_streamer_mode_enabled(self) -> bool:
        """Check if streamer mode is enabled."""
        if hasattr(self, 'streamer_mode'):
            return bool(self.streamer_mode)
        if hasattr(self, 'config') and isinstance(self.config, dict):
            return bool(self.config.get('streamer_mode', False))
        return False


