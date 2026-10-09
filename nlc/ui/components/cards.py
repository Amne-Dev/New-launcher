"""
nlc.ui.components.cards - Themed card and row containers with depth borders and micro-animations.
"""

import tkinter as tk
from typing import Optional
from nlc.ui.theme import COLORS
from nlc.ui.animation import AnimationManager


def _get_card_descendants(widget):
    """Recursively retrieve all descendant widgets."""
    descendants = []
    try:
        if not widget or not widget.winfo_exists():
            return descendants
        for child in widget.winfo_children():
            descendants.append(child)
            descendants.extend(_get_card_descendants(child))
    except Exception:
        pass
    return descendants


def _is_card_pointer_inside(widget):
    """Return True if pointer is within widget or any descendant."""
    try:
        if not widget or not widget.winfo_exists():
            return False
        x, y = widget.winfo_pointerxy()
        under = widget.winfo_containing(x, y)
        if under is None:
            return False
        curr = under
        while curr is not None:
            if curr == widget:
                return True
            curr = getattr(curr, "master", None)
        return False
    except Exception:
        return False


def create_card(
    parent: tk.Widget,
    *,
    bg: Optional[str] = None,
    hover_bg: Optional[str] = None,
    border_color: Optional[str] = None,
    border: bool = True,
    padx: int = 16,
    pady: int = 12,
    cursor: str = "",
    hoverable: bool = False,
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
        cursor=cursor if cursor else ("hand2" if hoverable else ""),
        highlightthickness=1 if border else 0,
        highlightbackground=normal_border,
        highlightcolor=hover_border
    )

    if not hoverable:
        return card

    hover_state = {"is_hovered": False}

    def _update_descendants_bg(bg_col):
        for child in _get_card_descendants(card):
            try:
                child.config(bg=bg_col)
            except Exception:
                pass

    def on_enter(e=None):
        if hover_state["is_hovered"]:
            return
        hover_state["is_hovered"] = True
        cur_hover_color = hover_bg or COLORS['card_hover']
        cur_hover_border = COLORS.get('accent_color', normal_border)

        if animator and animator.is_enabled:
            animator.animate_color(
                card, "bg", card.cget("bg"), cur_hover_color,
                duration_ms=80,
                on_step=_update_descendants_bg
            )
            if border:
                animator.animate_color(card, "highlightbackground", card.cget("highlightbackground"), cur_hover_border, duration_ms=80)
        else:
            card.config(bg=cur_hover_color)
            if border:
                card.config(highlightbackground=cur_hover_border)
            _update_descendants_bg(cur_hover_color)

    def on_leave(e=None):
        if _is_card_pointer_inside(card):
            return
        hover_state["is_hovered"] = False
        cur_card_color = bg or COLORS['card_bg']
        cur_normal_border = border_color or COLORS.get('border_subtle', '#2B303A')

        if animator and animator.is_enabled:
            animator.animate_color(
                card, "bg", card.cget("bg"), cur_card_color,
                duration_ms=80,
                on_step=_update_descendants_bg
            )
            if border:
                animator.animate_color(card, "highlightbackground", card.cget("highlightbackground"), cur_normal_border, duration_ms=80)
        else:
            card.config(bg=cur_card_color)
            if border:
                card.config(highlightbackground=cur_normal_border)
            _update_descendants_bg(cur_card_color)

    card.bind("<Enter>", on_enter)
    card.bind("<Leave>", on_leave)

    def _bind_all():
        for child in _get_card_descendants(card):
            child.bind("<Enter>", on_enter, add="+")
            child.bind("<Leave>", on_leave, add="+")

    card.after_idle(_bind_all)

    return card
