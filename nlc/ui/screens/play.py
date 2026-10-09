"""
nlc.ui.screens.play - Play tab, hero wallpaper, launch options popup, and status bar
"""

import os
import sys
import logging
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

try:
    RESAMPLE_NEAREST = Image.Resampling.NEAREST
except AttributeError:
    RESAMPLE_NEAREST = Image.NEAREST

from nlc.ui.theme import COLORS, FONT_FAMILY

logger = logging.getLogger(__name__)

class PlayScreenMixin:
    """Mixin providing Play tab hero view, launch options popup, and gamertag update."""
    def create_play_tab(self):
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Play"] = frame
        
        # P3 Menu is now a game injection, not a launcher UI replacement
        # if self.addons_config.get("p3_menu", False): ... (Removed)

        # Hero Section (Background) - fills most of the space except bottom bar
        self.hero_canvas = tk.Canvas(frame, bg=COLORS['main_bg'], highlightthickness=0)
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
        self.bottom_bar = bottom_bar

        # We use grid for 3 distinct sections in the bottom bar to ensure centering
        bottom_bar.columnconfigure(0, weight=1) # Left
        bottom_bar.columnconfigure(1, weight=1) # Center
        bottom_bar.columnconfigure(2, weight=1) # Right
        
        # 1. Left (Installation Selector)
        left_frame = tk.Frame(bottom_bar, bg=COLORS['bottom_bar_bg'])
        left_frame.grid(row=0, column=0, sticky="w", padx=30)
        self.bottom_bar_left = left_frame
        
        # Custom Dropdown Trigger
        self.inst_selector_frame = tk.Frame(left_frame, bg=COLORS['bottom_bar_bg'], cursor="hand2")
        self.inst_selector_frame.pack(fill="x", ipadx=10, ipady=5)
        
        # Text (Left) - Name and version
        self.inst_selector_text_frame = tk.Frame(self.inst_selector_frame, bg=COLORS['bottom_bar_bg']) 
        self.inst_selector_text_frame.pack(side="left", padx=(10, 0))
        
        self.inst_name_lbl = tk.Label(self.inst_selector_text_frame, text="", font=(FONT_FAMILY, 11, "bold"), 
                                     bg=COLORS['bottom_bar_bg'], fg="white", cursor="hand2", anchor="w")
        self.inst_name_lbl.pack(anchor="w")
        
        self.inst_ver_lbl = tk.Label(self.inst_selector_text_frame, text="", font=(FONT_FAMILY, 9), 
                                    bg=COLORS['bottom_bar_bg'], fg=COLORS['text_secondary'], cursor="hand2", anchor="w")
        self.inst_ver_lbl.pack(anchor="w")

        # Icon (Right)
        self.inst_selector_icon = tk.Label(self.inst_selector_frame, bg=COLORS['bottom_bar_bg'], cursor="hand2")
        self.inst_selector_icon.pack(side="left", before=self.inst_selector_text_frame)

        # Chevron (Far Right)
        self.inst_selector_arrow = tk.Label(self.inst_selector_arrow if hasattr(self, 'inst_selector_arrow') else self.inst_selector_frame, text="▼", font=(FONT_FAMILY, 8), 
                                           bg=COLORS['bottom_bar_bg'], fg=COLORS['text_secondary'], cursor="hand2")
        self.inst_selector_arrow.pack(side="right", padx=(15, 5))

        # Hover logic
        selector_widgets = [self.inst_selector_frame, self.inst_selector_text_frame, self.inst_name_lbl, self.inst_ver_lbl, self.inst_selector_icon, self.inst_selector_arrow]
        hover_state = {"is_hovered": False}

        def _is_selector_pointer_inside():
            try:
                if not self.inst_selector_frame.winfo_exists():
                    return False
                x, y = self.inst_selector_frame.winfo_pointerxy()
                under = self.inst_selector_frame.winfo_containing(x, y)
                if under is None:
                    return False
                curr = under
                while curr is not None:
                    if curr == self.inst_selector_frame:
                        return True
                    curr = getattr(curr, "master", None)
                return False
            except Exception:
                return False

        def _update_selector_bg(bg_col):
            for w in selector_widgets:
                try:
                    if w and w.winfo_exists():
                        w.config(bg=bg_col)
                except Exception:
                    pass

        def on_hover(e=None):
            if hover_state["is_hovered"]:
                return
            hover_state["is_hovered"] = True
            bg = COLORS.get('hover_bg', '#3A3F4D')
            if getattr(self, 'animator', None) and self.animator.is_enabled:
                self.animator.animate_color(
                    self.inst_selector_frame, "bg", self.inst_selector_frame.cget("bg"), bg,
                    duration_ms=80,
                    on_step=_update_selector_bg
                )
            else:
                _update_selector_bg(bg)

        def on_leave(e=None):
            if _is_selector_pointer_inside():
                return
            hover_state["is_hovered"] = False
            bg = COLORS['bottom_bar_bg']
            if getattr(self, 'animator', None) and self.animator.is_enabled:
                self.animator.animate_color(
                    self.inst_selector_frame, "bg", self.inst_selector_frame.cget("bg"), bg,
                    duration_ms=80,
                    on_step=_update_selector_bg
                )
            else:
                _update_selector_bg(bg)

        for w in selector_widgets:
            w.bind("<Enter>", on_hover, add="+")
            w.bind("<Leave>", on_leave, add="+")
            w.bind("<Button-1>", lambda e, s=self: s.open_selector_menu(e), add="+")
        
        # Populate with installations
        self.update_installation_dropdown()

        # 2. Center (Play Button)
        center_frame = tk.Frame(bottom_bar, bg=COLORS['bottom_bar_bg'])
        center_frame.grid(row=0, column=1, pady=25)
        self.bottom_bar_center = center_frame

        # Composite Play Button (Frame)
        self.play_container = tk.Frame(center_frame, bg=COLORS['play_btn_green'])
        self.play_container.pack()

        play_fg = COLORS.get('play_btn_text', 'white')
        self.launch_btn = tk.Button(self.play_container, text="PLAY", font=(FONT_FAMILY, 14, "bold"),
                                   bg=COLORS['play_btn_green'], fg=play_fg,
                                   activebackground=COLORS['play_btn_hover'], activeforeground=play_fg,
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
        self.bottom_bar_right = right_frame
        
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

        from nlc.ui.components.context_menu import NeoContextMenu
        menu = NeoContextMenu(self.root, min_width=180)
        menu.add_item("⚡ Force Update & Play", lambda: self.start_launch(force_update=True))
        menu.show_at_widget(self.launch_opts_btn, direction="below")
        self._launch_opts_menu = menu

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

    def refresh_play_screen_theme(self):
        """Update Play tab widgets with active design tokens."""
        main_bg = COLORS['main_bg']
        bottom_bg = COLORS['bottom_bar_bg']
        text_primary = COLORS['text_primary']
        text_secondary = COLORS['text_secondary']
        play_green = COLORS['play_btn_green']
        play_hover = COLORS['play_btn_hover']
        play_fg = COLORS.get('play_btn_text', 'white')

        if hasattr(self, 'tabs') and 'Play' in self.tabs and self.tabs['Play'].winfo_exists():
            self.tabs['Play'].config(bg=main_bg)
        if hasattr(self, 'hero_canvas') and self.hero_canvas.winfo_exists():
            self.hero_canvas.config(bg=main_bg)
            try:
                w = self.hero_canvas.winfo_width()
                h = self.hero_canvas.winfo_height()
                if w > 10 and h > 10:
                    self._update_hero_layout(type('Event', (), {'width': w, 'height': h})())
            except Exception:
                pass

        if hasattr(self, 'bottom_bar') and self.bottom_bar.winfo_exists():
            self.bottom_bar.config(bg=bottom_bg)
        for attr in ['bottom_bar_left', 'bottom_bar_center', 'bottom_bar_right',
                     'inst_selector_frame', 'inst_selector_text_frame',
                     'inst_selector_icon']:
            w = getattr(self, attr, None)
            if w and w.winfo_exists():
                w.config(bg=bottom_bg)

        if hasattr(self, 'inst_name_lbl') and self.inst_name_lbl.winfo_exists():
            self.inst_name_lbl.config(bg=bottom_bg, fg=text_primary)
        if hasattr(self, 'inst_ver_lbl') and self.inst_ver_lbl.winfo_exists():
            self.inst_ver_lbl.config(bg=bottom_bg, fg=text_secondary)
        if hasattr(self, 'inst_selector_arrow') and self.inst_selector_arrow.winfo_exists():
            self.inst_selector_arrow.config(bg=bottom_bg, fg=text_secondary)
        if hasattr(self, 'status_label') and self.status_label.winfo_exists():
            self.status_label.config(bg=bottom_bg, fg=text_secondary)
        if hasattr(self, 'bottom_gamertag') and self.bottom_gamertag.winfo_exists():
            self.bottom_gamertag.config(bg=bottom_bg, fg=text_secondary)

        if hasattr(self, 'play_container') and self.play_container.winfo_exists():
            self.play_container.config(bg=play_green)
        if hasattr(self, 'launch_sep') and self.launch_sep.winfo_exists():
            self.launch_sep.config(bg=play_green)
        if hasattr(self, 'launch_btn') and self.launch_btn.winfo_exists():
            self.launch_btn.config(bg=play_green, fg=play_fg, activebackground=play_hover, activeforeground=play_fg)
        if hasattr(self, 'launch_opts_btn') and self.launch_opts_btn.winfo_exists():
            self.launch_opts_btn.config(bg=play_green, fg=play_fg, activebackground=play_hover, activeforeground=play_fg)
