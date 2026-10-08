"""
nlc.ui.components.dialogs - Modal dialogs and themed message boxes
"""

import logging
import os
import tkinter as tk
from typing import Any, List, Optional, Tuple
from nlc.ui.theme import COLORS, FONT_FAMILY, derive_hover_color

logger = logging.getLogger(__name__)

class CustomMessagebox(tk.Toplevel):
    """Themed modal message box replacing stock Tk messagebox."""
    def __init__(self, title: str, message: str, type: str = "info", buttons: Optional[List[Tuple[str, Any, str]]] = None, parent: Optional[tk.Widget] = None):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=COLORS['card_bg'])
        self.result = None
        self._target_parent = parent
        self._default_button = None

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Escape>", lambda _e: self.on_close())

        # Main frame
        frame = tk.Frame(self, bg=COLORS['card_bg'], padx=25, pady=25)
        frame.pack(fill="both", expand=True)

        # Message label
        msg_lbl = tk.Label(
            frame,
            text=message,
            bg=COLORS['card_bg'],
            fg=COLORS['text_primary'],
            font=(FONT_FAMILY, 10),
            wraplength=380,
            justify="center"
        )
        msg_lbl.pack(pady=(5, 20))

        # Buttons Setup
        btn_frame = tk.Frame(frame, bg=COLORS['card_bg'])
        btn_frame.pack(fill="x", pady=(10, 0))
        btn_inner = tk.Frame(btn_frame, bg=COLORS['card_bg'])
        btn_inner.pack(anchor="center")

        if buttons is None:
            if type == "yesno":
                buttons = [("Yes", True, "primary"), ("No", False, "secondary")]
            elif type == "error":
                buttons = [("Close", False, "secondary")]
            else:
                buttons = [("OK", True, "primary")]

        for text, val, style in buttons:
            is_danger = style == "danger"
            err_col = COLORS.get('error_red', '#EF4444')
            sec_bg = COLORS.get('input_bg', '#2E333E')
            sec_hover = COLORS.get('card_hover', '#3A3F4D')
            primary_bg = COLORS.get('play_btn_green', COLORS.get('accent_color', '#2ECC71'))
            primary_hover = COLORS.get('play_btn_hover', COLORS.get('accent_hover', '#27AE60'))
            b_bg = err_col if is_danger else (primary_bg if style == "primary" else sec_bg)
            b_hover = derive_hover_color(err_col) if is_danger else (primary_hover if style == "primary" else sec_hover)

            btn = tk.Button(
                btn_inner,
                text=text,
                bg=b_bg,
                fg=COLORS['text_primary'],
                font=(FONT_FAMILY, 9, "bold"),
                relief="flat",
                activebackground=b_hover,
                activeforeground=COLORS['text_primary'],
                bd=0,
                padx=20,
                pady=6,
                cursor="hand2",
                command=lambda v=val: self.on_click(v)
            )
            btn.pack(side="left", padx=10)

            def on_enter(e, b=btn, h=b_hover): b.config(bg=h)
            def on_leave(e, b=btn, bg=b_bg): b.config(bg=bg)
            btn.bind("<Enter>", on_enter)
            btn.bind("<Leave>", on_leave)

            if self._default_button is None and style in ("primary", "danger"):
                self._default_button = btn

        # Centering
        self.update_idletasks()
        w, h = 440, max(160, self.winfo_reqheight())
        if parent and parent.winfo_exists():
            x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (w // 2)
            y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (h // 2)
            self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
            self.transient(parent)
        else:
            self.geometry(f"{w}x{h}")

        try:
            self.grab_set()
        except tk.TclError:
            pass

        if self._default_button:
            self.bind("<Return>", lambda _e: self._default_button.invoke())
            self._default_button.focus_set()

        self.wait_window()

    def on_click(self, val):
        self.result = val
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def on_close(self):
        self.result = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

def custom_showinfo(title: str, message: str, parent=None):
    box = CustomMessagebox(title, message, type="info", parent=parent)
    return box.result

def custom_showwarning(title: str, message: str, parent=None):
    box = CustomMessagebox(title, message, type="warning", parent=parent)
    return box.result

def custom_showerror(title: str, message: str, parent=None):
    box = CustomMessagebox(title, message, type="error", parent=parent)
    return box.result

def custom_askyesno(title: str, message: str, parent=None) -> bool:
    box = CustomMessagebox(title, message, type="yesno", parent=parent)
    return bool(box.result)

def _build_missing_skin_head(size: int = 35):
    """Build a pixel-art Steve placeholder question mark head when skin is missing."""
    try:
        from PIL import Image, ImageDraw, ImageTk
        from nlc.storage.paths import RESAMPLE_NEAREST
        pattern = [
            "..###...",
            ".#...#..",
            "....#...",
            "...#....",
            "...#....",
            "........",
            "...#....",
            "........",
        ]
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for y, row in enumerate(pattern):
            for x, cell in enumerate(row):
                if cell == "#":
                    draw.point((x, y), fill=(255, 255, 255, 255))
        return ImageTk.PhotoImage(img.resize((size, size), RESAMPLE_NEAREST))
    except Exception:
        return None

def schedule_window_centering(win, parent=None, width=None, height=None):
    def apply_center():
        try:
            if not win.winfo_exists():
                return
            win.update_idletasks()
            w = width or win.winfo_width() or win.winfo_reqwidth()
            h = height or win.winfo_height() or win.winfo_reqheight()
            if parent and parent.winfo_exists():
                px = parent.winfo_rootx()
                py = parent.winfo_rooty()
                pw = parent.winfo_width()
                ph = parent.winfo_height()
                x = px + (pw // 2) - (w // 2)
                y = py + (ph // 2) - (h // 2)
            else:
                sw = win.winfo_screenwidth()
                sh = win.winfo_screenheight()
                x = (sw // 2) - (w // 2)
                y = (sh // 2) - (h // 2)
            win.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    apply_center()
    for delay in (0, 30, 100):
        try:
            win.after(delay, apply_center)
        except Exception:
            pass

_schedule_window_centering = schedule_window_centering
