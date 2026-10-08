"""
nlc.ui.components.downloads - Download queue manager, task tracking, and progress UI
"""

import uuid
import threading
import logging
import tkinter as tk
from tkinter import ttk

from nlc.ui.theme import COLORS, FONT_FAMILY

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
        # Container - packed at bottom of sidebar (stacking upwards above previous bottom items)
        self.queue_container = tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'])
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
        # Show container if hidden with fade-in effect
        if not self.queue_container.winfo_viewable():
             self.queue_container.pack(side="bottom", fill="x", padx=10, pady=10)

        task_id = str(uuid.uuid4())
        
        # Card style with subtle border
        card_bg = COLORS.get('card_bg', '#242830')
        border_color = COLORS.get('border_subtle', '#2D3139')
        hover_bg = COLORS.get('hover_bg', '#282C36')
        text_sec = COLORS.get('text_secondary', '#A6ACB8')
        
        border_frame = tk.Frame(self.queue_list_frame, bg=border_color, padx=1, pady=1)
        border_frame.pack(fill="x", pady=3)
        
        frame = tk.Frame(border_frame, bg=card_bg, pady=6, padx=10)
        frame.pack(fill="x")
        
        # Title Row
        top = tk.Frame(frame, bg=card_bg)
        top.pack(fill="x")
        
        # Truncate name
        disp_name = (name[:18] + '..') if len(name) > 18 else name
        tk.Label(top, text=disp_name, font=("Segoe UI", 8, "bold"), fg="white", bg=card_bg, anchor="w").pack(side="left")
        
        # Detail Frame (Container)
        detail_frame = tk.Frame(frame, bg=card_bg)
        detail_lbl = tk.Label(detail_frame, text="Starting...", font=("Segoe UI", 7), fg=text_sec, bg=card_bg, anchor="w")
        detail_lbl.pack(fill="x")
        
        # Dropdown/Expand capability
        if type_str == "modpack":
            def toggle():
                if detail_frame.winfo_viewable():
                    detail_frame.pack_forget()
                    btn.config(text="▼")
                else:
                    detail_frame.pack(fill="x", pady=(2,0))
                    btn.config(text="▲")
            
            btn = tk.Button(top, text="▼", font=("Segoe UI", 6), bg=card_bg, fg="white", 
                            bd=0, activebackground=hover_bg, activeforeground="white",
                            command=toggle, width=2, cursor="hand2")
            btn.pack(side="right")
            
            # Hover effect
            btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
            btn.bind("<Leave>", lambda e: btn.config(bg=card_bg))
        else:
             # Just show status inline or always hidden? 
             # For single files, maybe no detail frame, or always visible?
             # Let's keep it simpler: hidden by default.
             pass

        # Progress
        pb = ttk.Progressbar(frame, orient="horizontal", mode="determinate", length=100)
        pb.pack(fill="x", pady=3)
        
        self.download_tasks[task_id] = {
            "border_frame": border_frame,
            "frame": frame,
            "pb": pb,
            "detail_lbl": detail_lbl,
            "detail_frame": detail_frame,
            "type": type_str,
            "cancel_event": threading.Event()
        }
        
        # Context Menu for Cancellation
        menu = tk.Menu(frame, tearoff=0, bg=card_bg, fg="white")
        menu.add_command(label="Cancel", command=lambda: self.cancel_download(task_id))
        
        def show_menu(e):
            menu.post(e.x_root, e.y_root)
            
        # Bind to everything in the card
        frame.bind("<Button-3>", show_menu)
        top.bind("<Button-3>", show_menu)
        detail_frame.bind("<Button-3>", show_menu)
        detail_lbl.bind("<Button-3>", show_menu)
        
        return task_id

    def cancel_download(self, task_id):
        if task_id in self.download_tasks:
            self.download_tasks[task_id]['cancel_event'].set()
            self.update_download_task(task_id, detail="Cancelling...")

    def update_download_task(self, task_id, progress=None, status=None, detail=None):
        if task_id not in self.download_tasks: return
        data = self.download_tasks[task_id]
        
        if progress is not None:
            data['pb']['value'] = max(0, min(100, float(progress)))

        if status is not None:
            # Keep the task title useful without adding another cramped line.
            data['detail_lbl'].config(fg=COLORS['text_secondary'])
            
        if detail is not None:
             data['detail_lbl'].config(text=detail)

    def complete_download_task(self, task_id):
        if task_id not in self.download_tasks: return
        
        success_col = COLORS.get('success_green', '#10B981')
        subtle_border = COLORS.get('border_subtle', '#2D3139')
        data = self.download_tasks[task_id]
        data['pb']['value'] = 100
        data['detail_lbl'].config(text="Completed ✓", fg=success_col)
        
        # Visual feedback - brief green highlight
        if 'border_frame' in data:
            data['border_frame'].config(bg=success_col)
            self.root.after(300, lambda: data['border_frame'].config(bg=subtle_border) if task_id in self.download_tasks else None)
        
        # Fade out or remove
        def remove():
            if task_id in self.download_tasks:
                data = self.download_tasks[task_id]
                if 'border_frame' in data:
                    data['border_frame'].destroy()
                elif 'frame' in data:
                    data['frame'].destroy()
                del self.download_tasks[task_id]
            
            if not self.download_tasks:
                 self.queue_container.pack_forget()
        
        # Wait 2 sec
        self.root.after(2000, remove)
        if hasattr(self, "toast_manager"):
            self.toast_manager.show("Download completed", kind="success")

    def fail_download_task(self, task_id, message="Download failed"):
        if task_id not in self.download_tasks:
            return
        data = self.download_tasks[task_id]
        data['detail_lbl'].config(text=message, fg=COLORS.get('error_red', '#E74C3C'))
        if 'border_frame' in data:
            data['border_frame'].config(bg=COLORS.get('error_red', '#E74C3C'))


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

