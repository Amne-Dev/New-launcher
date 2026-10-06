"""
nlc.ui.components.toasts - Toast notifications and deduplicated popup manager
"""

import logging
import tkinter as tk
from typing import Optional
from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.dialogs import CustomMessagebox

logger = logging.getLogger(__name__)

class PopupManager:
    """Manages application dialogs with duplicate suppression."""
    def __init__(self, root: tk.Tk):
        self.root = root
        self._active = set()

    def show(self, title: str, message: str, *, type="info", buttons=None, parent=None):
        signature = (type, str(title), str(message))
        if signature in self._active:
            logger.info("Suppressed duplicate popup: %s", title)
            return None
        self._active.add(signature)
        try:
            dialog = CustomMessagebox(title, message, type=type, buttons=buttons, parent=parent or self.root)
            return dialog.result
        finally:
            self._active.discard(signature)

class ToastManager:
    """Non-blocking, deduplicated toast notifications."""
    def __init__(self, root: tk.Tk):
        self.root = root
        self._toasts = []
        self._signatures = set()

    def show(self, message: str, *, kind="success", duration=3600):
        signature = (kind, str(message))
        if signature in self._signatures:
            return
        self._signatures.add(signature)

        colors = {
            "success": COLORS["success_green"],
            "warning": COLORS["warning_orange"],
            "error": COLORS["error_red"],
            "info": COLORS["accent_blue"],
        }

        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.configure(bg=COLORS["card_bg"])
        try:
            toast.attributes("-topmost", True)
        except Exception:
            pass

        body = tk.Frame(toast, bg=COLORS["card_bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="●",
            fg=colors.get(kind, colors["info"]),
            bg=COLORS["card_bg"],
            font=(FONT_FAMILY, 10, "bold")
        ).pack(side="left", padx=(0, 8))

        tk.Label(
            body,
            text=str(message),
            fg=COLORS["text_primary"],
            bg=COLORS["card_bg"],
            font=(FONT_FAMILY, 9),
            wraplength=330,
            justify="left"
        ).pack(side="left")

        def dismiss():
            if toast in self._toasts:
                self._toasts.remove(toast)
            self._signatures.discard(signature)
            try:
                toast.destroy()
            except tk.TclError:
                pass
            self._reposition()

        toast.bind("<Button-1>", lambda _e: dismiss())
        body.bind("<Button-1>", lambda _e: dismiss())
        self._toasts.append(toast)
        self._reposition()
        toast.after(duration, dismiss)

    def _reposition(self):
        self._toasts[:] = [t for t in self._toasts if t.winfo_exists()]
        try:
            self.root.update_idletasks()
            x = self.root.winfo_rootx() + self.root.winfo_width() - 20
            y = self.root.winfo_rooty() + 54
            for toast in self._toasts:
                toast.update_idletasks()
                w, h = toast.winfo_reqwidth(), toast.winfo_reqheight()
                toast.geometry(f"+{x - w}+{y}")
                y += h + 8
        except tk.TclError:
            pass
