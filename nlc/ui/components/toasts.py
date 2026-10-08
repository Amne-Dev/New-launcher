"""
nlc.ui.components.toasts - In-app toast notifications and deduplicated popup manager.
Renders directly within the main window frame to eliminate Wayland (0,0) floating window bugs.
"""

import logging
import tkinter as tk
from typing import Optional
from nlc.ui.theme import COLORS, FONT_FAMILY

logger = logging.getLogger(__name__)


class PopupManager:
    """Manages application dialogs with duplicate suppression."""
    def __init__(self, root: tk.Tk):
        self.root = root.winfo_toplevel()
        self._active = set()

    def show(self, title: str, message: str, *, type="info", buttons=None, parent=None):
        signature = (type, str(title), str(message))
        if signature in self._active:
            logger.info("Suppressed duplicate popup: %s", title)
            return None
        self._active.add(signature)
        try:
            from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno
            target_parent = parent or self.root
            if type == "error":
                return custom_showerror(title, message, parent=target_parent)
            elif type == "yesno":
                return custom_askyesno(title, message, parent=target_parent)
            else:
                return custom_showinfo(title, message, parent=target_parent)
        finally:
            self._active.discard(signature)


class ToastManager:
    """Non-blocking, deduplicated in-app toast notifications contained within the launcher window."""
    def __init__(self, root: tk.Widget):
        self.root = root.winfo_toplevel()
        self._toasts = []
        self._signatures = set()
        self._container = None

    def _ensure_container(self):
        if self._container is None or not self._container.winfo_exists():
            self._container = tk.Frame(self.root, bg=COLORS.get('main_bg', '#13151A'))
            # Position at bottom-right inside the window, above status bar
            self._container.place(relx=1.0, rely=1.0, x=-24, y=-90, anchor="se")
            self._container.lift()
        return self._container

    def show(self, message: str, *, kind="success", duration=3600):
        signature = (kind, str(message))
        if signature in self._signatures:
            return
        self._signatures.add(signature)

        container = self._ensure_container()
        container.lift()

        colors = {
            "success": COLORS.get("success_green", "#2ECC71"),
            "warning": COLORS.get("warning_orange", "#F39C12"),
            "error": COLORS.get("error_red", "#EF4444"),
            "info": COLORS.get("accent_blue", "#3498DB"),
        }
        kind_col = colors.get(kind, colors["info"])
        card_bg = COLORS.get("card_bg", "#222630")

        toast_card = tk.Frame(
            container,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=kind_col,
            padx=14,
            pady=10
        )
        toast_card.pack(side="top", pady=4, fill="x", anchor="e")

        dot = tk.Label(
            toast_card,
            text="●",
            fg=kind_col,
            bg=card_bg,
            font=(FONT_FAMILY, 10, "bold")
        )
        dot.pack(side="left", padx=(0, 8))

        lbl = tk.Label(
            toast_card,
            text=str(message),
            fg=COLORS.get("text_primary", "#FFFFFF"),
            bg=card_bg,
            font=(FONT_FAMILY, 9),
            wraplength=340,
            justify="left"
        )
        lbl.pack(side="left")

        def dismiss():
            if toast_card in self._toasts:
                self._toasts.remove(toast_card)
            self._signatures.discard(signature)
            try:
                if toast_card.winfo_exists():
                    toast_card.destroy()
            except Exception:
                pass
            if not self._toasts and self._container and self._container.winfo_exists():
                try:
                    self._container.place_forget()
                except Exception:
                    pass

        for w in (toast_card, dot, lbl):
            w.bind("<Button-1>", lambda _e: dismiss())

        self._toasts.append(toast_card)
        toast_card.after(duration, dismiss)
