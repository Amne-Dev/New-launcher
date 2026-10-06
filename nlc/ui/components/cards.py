"""
nlc.ui.components.cards - Themed card and row containers
"""

import tkinter as tk
from typing import Optional
from nlc.ui.theme import COLORS

def create_card(
    parent: tk.Widget,
    *,
    bg: Optional[str] = None,
    hover_bg: Optional[str] = None,
    padx: int = 15,
    pady: int = 10,
    cursor: str = "hand2"
) -> tk.Frame:
    """Create a card frame with optional hover highlight."""
    card_color = bg or COLORS['card_bg']
    hover_color = hover_bg or COLORS['card_hover']

    card = tk.Frame(parent, bg=card_color, padx=padx, pady=pady, cursor=cursor)

    def on_enter(e):
        card.config(bg=hover_color)
        for child in card.winfo_children():
            try:
                if child.cget("bg") == card_color:
                    child.config(bg=hover_color)
            except Exception:
                pass

    def on_leave(e):
        card.config(bg=card_color)
        for child in card.winfo_children():
            try:
                if child.cget("bg") == hover_color:
                    child.config(bg=card_color)
            except Exception:
                pass

    card.bind("<Enter>", on_enter)
    card.bind("<Leave>", on_leave)

    return card
