"""
nlc.ui.components.cards - Themed card and row containers with depth borders and micro-animations.
"""

import tkinter as tk
from typing import Optional
from nlc.ui.theme import COLORS
from nlc.ui.animation import AnimationManager

def create_card(
    parent: tk.Widget,
    *,
    bg: Optional[str] = None,
    hover_bg: Optional[str] = None,
    border_color: Optional[str] = None,
    border: bool = True,
    padx: int = 16,
    pady: int = 12,
    cursor: str = "hand2",
    animator: Optional[AnimationManager] = None
) -> tk.Frame:
    """Create a modern card frame with subtle depth border and optional smooth hover highlight."""
    card_color = bg or COLORS['card_bg']
    hover_color = hover_bg or COLORS['card_hover']
    normal_border = border_color or COLORS.get('border_subtle', '#2B303A')
    hover_border = COLORS.get('accent_color', normal_border)

    card = tk.Frame(
        parent,
        bg=card_color,
        padx=padx,
        pady=pady,
        cursor=cursor,
        highlightthickness=1 if border else 0,
        highlightbackground=normal_border,
        highlightcolor=hover_border
    )

    def on_enter(e):
        cur_card_color = bg or COLORS['card_bg']
        cur_hover_color = hover_bg or COLORS['card_hover']
        cur_normal_border = border_color or COLORS.get('border_subtle', '#2B303A')
        cur_hover_border = COLORS.get('accent_color', cur_normal_border)

        if animator and animator.is_enabled:
            animator.animate_color(card, "bg", card.cget("bg"), cur_hover_color, duration_ms=80)
            if border:
                animator.animate_color(card, "highlightbackground", card.cget("highlightbackground"), cur_hover_border, duration_ms=80)
        else:
            card.config(bg=cur_hover_color)
            if border:
                card.config(highlightbackground=cur_hover_border)

        for child in card.winfo_children():
            try:
                if child.cget("bg") in (cur_card_color, card_color):
                    child.config(bg=cur_hover_color)
            except Exception:
                pass

    def on_leave(e):
        cur_card_color = bg or COLORS['card_bg']
        cur_hover_color = hover_bg or COLORS['card_hover']
        cur_normal_border = border_color or COLORS.get('border_subtle', '#2B303A')

        if animator and animator.is_enabled:
            animator.animate_color(card, "bg", card.cget("bg"), cur_card_color, duration_ms=80)
            if border:
                animator.animate_color(card, "highlightbackground", card.cget("highlightbackground"), cur_normal_border, duration_ms=80)
        else:
            card.config(bg=cur_card_color)
            if border:
                card.config(highlightbackground=cur_normal_border)

        for child in card.winfo_children():
            try:
                if child.cget("bg") in (cur_hover_color, hover_color):
                    child.config(bg=cur_card_color)
            except Exception:
                pass

    card.bind("<Enter>", on_enter)
    card.bind("<Leave>", on_leave)

    return card
