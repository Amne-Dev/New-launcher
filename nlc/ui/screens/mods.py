"""
nlc.ui.screens.mods - Modrinth browser, search, modpack installation
"""

import io
import os
import sys
import json
import uuid
import time
import shutil
import logging
import threading
import webbrowser
import tempfile
import urllib.parse
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import requests
import minecraft_launcher_lib

from nlc.storage.paths import resource_path
from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno
from nlc.net.http import get_http_session
from nlc.net.downloader import _atomic_download
from nlc.core.launch import safe_extract_zip as _safe_extract_zip

logger = logging.getLogger(__name__)

class ModsScreenMixin:
    """Mixin providing Modrinth mod/modpack browser, search, and installation."""
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

        def handle_response(res):
            if res and res.get("status") == "success":
                self._on_mod_search_result(res, reset, generation)
            else:
                # If agent is unavailable or returns an error, fallback to direct search
                threading.Thread(
                    target=self._direct_search_mods_worker,
                    args=(payload, reset, generation),
                    daemon=True
                ).start()

        # Try agent if running, otherwise use direct worker
        if getattr(self, "agent_process", None) and self.agent_process.poll() is None:
            self.send_agent_request("search_mods", payload, handle_response)
        else:
            threading.Thread(
                target=self._direct_search_mods_worker,
                args=(payload, reset, generation),
                daemon=True
            ).start()

    def _direct_search_mods_worker(self, payload, reset, generation):
        if generation != self._mod_search_generation:
            return
        try:
            query = payload.get("query", "")
            limit = payload.get("limit", 20)
            offset = payload.get("offset", 0)
            facets = payload.get("facets", [])
            
            params = f"limit={limit}&offset={offset}"
            if query:
                params += f"&query={urllib.parse.quote(query)}"
            else:
                params += "&index=downloads"

            if facets:
                facet_str = ",".join(f'["{f}"]' for f in facets)
                enc = urllib.parse.quote(f'[{facet_str}]')
                params += f'&facets={enc}'

            url = f"https://api.modrinth.com/v2/search?{params}"
            session = get_http_session()
            response = session.get(url, headers={"User-Agent": "AmneDev/NewLauncher"}, timeout=15)
            if response.status_code == 200:
                result = {"status": "success", "data": response.json()}
            else:
                result = {"status": "error", "code": response.status_code, "msg": response.text}
        except Exception as e:
            result = {"status": "error", "msg": str(e)}

        self.root.after(0, lambda: self._on_mod_search_result(result, reset, generation))

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


