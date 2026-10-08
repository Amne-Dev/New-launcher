"""
nlc.ui.components.downloads - Download queue manager, task tracking, and progress UI
"""

import uuid
import threading
import logging
import tkinter as tk
from tkinter import ttk

from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.context_menu import NeoContextMenu, attach_context_menu

logger = logging.getLogger(__name__)

class DownloadManager:
    def __init__(self, app):
        self.app = app
        self.mod_queue = []     # List of (func, task_id)
        self.pack_queue = []    # List of (func, task_id)
        self.active_mods = 0
        self.active_packs = 0
        self.MAX_MODS = 3
        self.MAX_PACKS = 1
        
    def queue_mod(self, func, task_id):
        self.mod_queue.append((func, task_id))
        self.app.root.after(0, lambda: self.app.update_download_task(task_id, detail="Queued..."))
        self.process_queues()

    def queue_modpack(self, func, task_id):
        self.pack_queue.append((func, task_id))
        self.app.root.after(0, lambda: self.app.update_download_task(task_id, detail="Queued..."))
        self.process_queues()

    def process_queues(self):
        max_p = getattr(self.app, 'max_concurrent_packs', 1)
        max_m = getattr(self.app, 'max_concurrent_mods', 3)
        
        # Process Packs
        while self.active_packs < max_p and self.pack_queue:
            self.active_packs += 1
            func, task_id = self.pack_queue.pop(0)
            self.start_task(func, task_id, is_pack=True)
            
        # Process Mods
        while self.active_mods < max_m and self.mod_queue:
            self.active_mods += 1
            func, task_id = self.mod_queue.pop(0)
            self.start_task(func, task_id, is_pack=False)

    def start_task(self, func, task_id, is_pack):
        self.app.root.after(0, lambda: self.app.update_download_task(task_id, status="Downloading", detail="Starting..."))
        
        def wrapper():
            try:
                func() 
            finally:
                self.app.root.after(0, lambda: self.task_finished(is_pack))

        threading.Thread(target=wrapper, daemon=True).start()

    def task_finished(self, is_pack):
        if is_pack: self.active_packs -= 1
        else: self.active_mods -= 1
        self.process_queues()



class DownloadQueueMixin:
    """Mixin providing download queue widgets, tasks, and progress overlay."""
    def create_download_queue_ui(self):
        parent = getattr(self, 'sidebar_bottom_frame', self.sidebar)
        self.queue_container = tk.Frame(parent, bg=COLORS['sidebar_bg'])
        # Hidden initially
        # self.queue_container.pack(side="bottom", fill="x", padx=10, pady=10)
        
        # Header
        self.queue_header = tk.Label(self.queue_container, text="Downloads", font=("Segoe UI", 9, "bold"), 
                                     fg=COLORS['text_secondary'], bg=COLORS['sidebar_bg'], anchor="w")
        self.queue_header.pack(fill="x", pady=(0, 5))
        
        # List Frame
        self.queue_list_frame = tk.Frame(self.queue_container, bg=COLORS['sidebar_bg'])
        self.queue_list_frame.pack(fill="x")

    def _show_skeleton_list(self, parent, *, rows=3, card_height=96, padx=20, pady=8):
        """Render lightweight structural placeholders while async content loads."""
        for child in parent.winfo_children():
            child.destroy()

        surface = COLORS.get('card_bg', '#3A3B3C')
        placeholder = COLORS.get('input_bg', '#48494A')
        muted_placeholder = COLORS.get('separator', '#454545')
        for index in range(rows):
            card = tk.Frame(parent, bg=surface, height=card_height, padx=14, pady=12)
            card.pack(fill="x", padx=padx, pady=(pady if index else 0, pady))
            card.pack_propagate(False)

            avatar = tk.Frame(card, bg=placeholder, width=52, height=52)
            avatar.pack(side="left", padx=(0, 14))
            avatar.pack_propagate(False)

            lines = tk.Frame(card, bg=surface)
            lines.pack(side="left", fill="both", expand=True, pady=2)
            tk.Frame(lines, bg=placeholder, height=13, width=210).pack(anchor="w", pady=(2, 10))
            tk.Frame(lines, bg=muted_placeholder, height=9, width=320).pack(anchor="w", pady=(0, 7))
            tk.Frame(lines, bg=muted_placeholder, height=9, width=160).pack(anchor="w")

            action = tk.Frame(card, bg=placeholder, width=70, height=30)
            action.pack(side="right", padx=(12, 0))
            action.pack_propagate(False)

    def add_download_task(self, name, type_str="file"):
        task_id = str(uuid.uuid4())
        disp_name = (name[:24] + '..') if len(name) > 24 else name

        # 1. Register with NotificationStore
        if hasattr(self, 'notifications') and self.notifications:
            self.notifications.add(
                category="download",
                title=name,
                message="Starting download...",
                item_id=task_id,
                progress=0.0,
                status="active"
            )

        # 2. Trigger rich Toast notification with Radial Progress Bar
        if hasattr(self, 'toast_manager') and self.toast_manager:
            self.toast_manager.show_download_toast(
                task_id=task_id,
                title=disp_name,
                detail="Starting...",
                initial_progress=0.0,
                on_cancel=lambda: self.cancel_download(task_id)
            )

        cancel_ev = threading.Event()
        self.download_tasks[task_id] = {
            "name": name,
            "type": type_str,
            "cancel_event": cancel_ev
        }
        return task_id

    def cancel_download(self, task_id):
        if task_id in self.download_tasks:
            self.download_tasks[task_id]['cancel_event'].set()
            self.update_download_task(task_id, detail="Cancelling...")

    def update_download_task(self, task_id, progress=None, status=None, detail=None):
        pct = max(0.0, min(100.0, float(progress))) if progress is not None else None

        if hasattr(self, 'toast_manager') and self.toast_manager:
            self.toast_manager.update_download_toast(task_id, progress=pct, detail=detail)

        if hasattr(self, 'notifications') and self.notifications:
            self.notifications.update(task_id, progress=pct, message=detail)

    def complete_download_task(self, task_id):
        if hasattr(self, 'toast_manager') and self.toast_manager:
            self.toast_manager.complete_download_toast(task_id, message="Completed ✓")

        if hasattr(self, 'notifications') and self.notifications:
            self.notifications.update(task_id, progress=100.0, status="completed", message="Completed successfully")

        if task_id in self.download_tasks:
            del self.download_tasks[task_id]

    def fail_download_task(self, task_id, message="Download failed"):
        if hasattr(self, 'toast_manager') and self.toast_manager:
            self.toast_manager.fail_download_toast(task_id, message=message)

        if hasattr(self, 'notifications') and self.notifications:
            self.notifications.update(task_id, status="failed", message=message)

        if task_id in self.download_tasks:
            del self.download_tasks[task_id]


    def show_progress_overlay(self, task_name="Loading..."):
        # Update Container (Hides bottom bar/content behind it)
        if not hasattr(self, 'update_frame'):
            self.update_frame = tk.Frame(self.root, bg=COLORS['bottom_bar_bg'])
            
            # Label
            self.update_progress_label = tk.Label(self.update_frame, text=task_name, 
                                                 font=("Segoe UI", 10, "bold"), 
                                                 bg=COLORS['bottom_bar_bg'], fg="white")
            self.update_progress_label.pack(side="top", pady=(15, 10))

            # Counter Label (Top Right of Bar area)
            self.update_counter_label = tk.Label(self.update_frame, text="", 
                                                font=("Segoe UI", 9), 
                                                bg=COLORS['bottom_bar_bg'], fg=COLORS['text_secondary'])
            self.update_counter_label.place(relx=0.98, rely=0.75, anchor="e")
            
            # Progress Bar
            self.update_progress_bar = ttk.Progressbar(self.update_frame, orient='horizontal', mode='determinate', 
                                                      style="Launcher.Horizontal.TProgressbar")
            self.update_progress_bar.pack(side="bottom", fill="x", ipady=10) # Thicker bar inside frame
            
        else:
            self.update_progress_label.config(text=task_name)
            self.update_progress_bar['value'] = 0
            if hasattr(self, 'update_counter_label'): self.update_counter_label.config(text="")

        # Show Frame
        # Height 100 to match bottom_bar height
        # x=200 to start after Sidebar, width=-200 + relwidth=1 to fill remaining space
        self.update_frame.place(x=200, rely=1.0, anchor="sw", relwidth=1, width=-200, height=100) 
        self.update_frame.lift()

    def hide_progress_overlay(self):
        if hasattr(self, 'update_frame'):
            self.update_frame.place_forget()

    def update_download_progress(self, current, total):
        if hasattr(self, 'update_progress_bar'):
            if total > 0:
                pct = (current / total) * 100
                self.update_progress_bar['value'] = pct
                
                # Update text (Status)
                if hasattr(self, 'update_progress_label'):
                    self.update_progress_label.config(text=f"Downloading Update... {int(pct)}%")
                
                # Clear/Hide Counter (User requested to remove it for updates)
                if hasattr(self, 'update_counter_label'):
                    self.update_counter_label.config(text="")
    
    # Alias for backward compat / shared usage if needed
    show_update_progress = lambda self: self.show_progress_overlay("Preparing Update...")
    hide_update_progress = hide_progress_overlay

