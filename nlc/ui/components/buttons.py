"""
nlc.ui.components.buttons - Standardized themed buttons
"""

import os
import tkinter as tk
from typing import Callable, Optional
from nlc.ui.theme import COLORS, FONT_FAMILY

def make_button(
    parent: tk.Widget,
    text: str,
    *,
    style: str = "secondary",
    command: Optional[Callable] = None,
    font_size: int = 9,
    bold: bool = False,
    width: Optional[int] = None,
    cursor: str = "hand2"
) -> tk.Button:
    """
    Creates a consistently styled button adhering to design tokens.
    Styles: 'primary', 'secondary', 'danger', 'text', 'icon'
    """
    weight = "bold" if bold else "normal"
    cfg_map = {
        "primary": {
            "bg": COLORS['play_btn_green'],
            "fg": COLORS['text_primary'],
            "hover": COLORS['play_btn_hover'],
            "active_fg": COLORS['text_primary']
        },
        "secondary": {
            "bg": "#404040",
            "fg": "#E0E0E0",
            "hover": "#525252",
            "active_fg": COLORS['text_primary']
        },
        "danger": {
            "bg": "#C0392B",
            "fg": COLORS['text_primary'],
            "hover": COLORS['error_red'],
            "active_fg": COLORS['text_primary']
        },
        "text": {
            "bg": COLORS['main_bg'],
            "fg": "#909090",
            "hover": COLORS['main_bg'],
            "active_fg": COLORS['text_primary']
        },
        "icon": {
            "bg": "#404040",
            "fg": "#C0C0C0",
            "hover": "#525252",
            "active_fg": COLORS['text_primary']
        }
    }
    cfg = cfg_map.get(style, cfg_map["secondary"])

    btn = tk.Button(
        parent,
        text=text,
        font=(FONT_FAMILY, font_size, weight),
        bg=cfg["bg"],
        fg=cfg["fg"],
        activebackground=cfg["hover"],
        activeforeground=cfg["active_fg"],
        relief="flat",
        bd=0,
        cursor=cursor,
        command=command
    )

    if os.name != "nt":
        btn.config(
            highlightthickness=0,
            takefocus=0,
            highlightbackground=cfg["bg"],
            highlightcolor=cfg["bg"],
            disabledforeground=cfg["fg"],
        )

    if style == "icon":
        btn.config(padx=6, pady=4)
    elif style == "text":
        btn.config(padx=2, pady=2)
    else:
        btn.config(padx=14, pady=6)

    if width is not None:
        btn.config(width=width)

    # Hover bindings
    def on_enter(e):
        btn.config(bg=cfg["hover"])

    def on_leave(e):
        btn.config(bg=cfg["bg"])

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)

    if os.name != "nt":
        def prime_linux_button():
            try:
                if not btn.winfo_exists():
                    return
                btn.config(
                    bg=cfg["bg"],
                    fg=cfg["fg"],
                    activebackground=cfg["hover"],
                    activeforeground=cfg["active_fg"],
                )
                btn.update_idletasks()
            except Exception:
                pass

        btn.after_idle(prime_linux_button)
        btn.after(40, prime_linux_button)

    return btn
