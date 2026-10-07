"""
nlc.ui.screens.modpacks - Modpacks management screen and dialogs
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
import requests

from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno
from nlc.net.http import get_http_session

logger = logging.getLogger(__name__)

class ModpacksScreenMixin:
    """Mixin providing Modpacks tab, CurseForge import, and modpack linking dialogs."""
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


