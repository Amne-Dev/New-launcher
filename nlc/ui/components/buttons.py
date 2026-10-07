"""
nlc.ui.components.buttons - Standardized themed buttons and badge chips.
Supports micro-animation color transitions, badge pills, and responsive states.
"""

import os
import weakref
import tkinter as tk
from typing import Callable, Optional, Dict, Any
from nlc.ui.theme import COLORS, FONT_FAMILY, THEME_MANAGER
from nlc.ui.animation import AnimationManager

_ACTIVE_BUTTONS: weakref.WeakSet = weakref.WeakSet()

def get_button_style_cfg(style: str) -> Dict[str, str]:
    """Return styling tokens for the requested button style based on current theme tokens."""
    cfg_map: Dict[str, Dict[str, str]] = {
        "primary": {
            "bg": COLORS['play_btn_green'],
            "fg": COLORS.get('play_btn_text', COLORS['text_primary']),
            "hover": COLORS['play_btn_hover'],
            "active_fg": COLORS.get('play_btn_text', COLORS['text_primary'])
        },
        "accent": {
            "bg": COLORS.get('accent_color', COLORS['play_btn_green']),
            "fg": COLORS.get('accent_text', COLORS['text_primary']),
            "hover": COLORS.get('accent_hover', COLORS['play_btn_hover']),
            "active_fg": COLORS.get('accent_text', COLORS['text_primary'])
        },
        "secondary": {
            "bg": COLORS.get('input_bg', "#2E333E"),
            "fg": COLORS['text_primary'],
            "hover": COLORS.get('card_hover', "#3A3F4D"),
            "active_fg": COLORS['text_primary']
        },
        "danger": {
            "bg": "#B91C1C",
            "fg": "#FFFFFF",
            "hover": COLORS.get('error_red', "#EF4444"),
            "active_fg": "#FFFFFF"
        },
        "text": {
            "bg": COLORS['main_bg'],
            "fg": COLORS.get('text_secondary', "#A6ACB8"),
            "hover": COLORS.get('card_bg', "#242830"),
            "active_fg": COLORS['text_primary']
        },
        "icon": {
            "bg": COLORS.get('card_bg', "#242830"),
            "fg": COLORS.get('text_secondary', "#A6ACB8"),
            "hover": COLORS.get('card_hover', "#2C313C"),
            "active_fg": COLORS['text_primary']
        }
    }
    return cfg_map.get(style, cfg_map["secondary"])

def update_button_style(btn: tk.Button) -> None:
    """Synchronize a button widget with latest theme tokens."""
    style = getattr(btn, "_btn_style", "secondary")
    cfg = get_button_style_cfg(style)
    try:
        btn.config(
            bg=cfg["bg"],
            fg=cfg["fg"],
            activebackground=cfg["hover"],
            activeforeground=cfg["active_fg"],
        )
        if os.name != "nt":
            btn.config(
                highlightbackground=cfg["bg"],
                highlightcolor=cfg["bg"],
                disabledforeground=cfg["fg"],
            )
    except Exception:
        pass

def refresh_all_buttons() -> None:
    """Synchronize all living buttons created by make_button with updated theme tokens."""
    for btn in list(_ACTIVE_BUTTONS):
        try:
            if btn.winfo_exists():
                update_button_style(btn)
        except Exception:
            pass

# Listen for theme changes from ThemeManager
THEME_MANAGER.add_listener(lambda tokens: refresh_all_buttons())

def make_button(
    parent: tk.Widget,
    text: str,
    *,
    style: str = "secondary",
    command: Optional[Callable] = None,
    font_size: int = 9,
    bold: bool = False,
    width: Optional[int] = None,
    cursor: str = "hand2",
    animator: Optional[AnimationManager] = None
) -> tk.Button:
    """
    Creates a consistently styled button adhering to design tokens.
    Styles: 'primary', 'secondary', 'danger', 'text', 'icon', 'accent'
    """
    weight = "bold" if bold else "normal"
    cfg = get_button_style_cfg(style)

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

    btn._btn_style = style  # type: ignore[attr-defined]
    btn._btn_animator = animator  # type: ignore[attr-defined]
    _ACTIVE_BUTTONS.add(btn)

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
        btn.config(padx=4, pady=2)
    elif style in ("primary", "accent"):
        btn.config(padx=16, pady=8)
    else:
        btn.config(padx=14, pady=6)

    if width is not None:
        btn.config(width=width)

    # Hover animations (dynamically reads latest style tokens)
    def on_enter(e):
        btn_style = getattr(btn, "_btn_style", "secondary")
        cur_cfg = get_button_style_cfg(btn_style)
        cur_animator = getattr(btn, "_btn_animator", animator)
        if cur_animator and cur_animator.is_enabled:
            cur_animator.animate_color(btn, "bg", cur_cfg["bg"], cur_cfg["hover"], duration_ms=80)
        else:
            btn.config(bg=cur_cfg["hover"])

    def on_leave(e):
        btn_style = getattr(btn, "_btn_style", "secondary")
        cur_cfg = get_button_style_cfg(btn_style)
        cur_animator = getattr(btn, "_btn_animator", animator)
        if cur_animator and cur_animator.is_enabled:
            cur_animator.animate_color(btn, "bg", cur_cfg["hover"], cur_cfg["bg"], duration_ms=80)
        else:
            btn.config(bg=cur_cfg["bg"])

    btn._on_enter = on_enter  # type: ignore[attr-defined]
    btn._on_leave = on_leave  # type: ignore[attr-defined]
    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)

    if os.name != "nt":
        def prime_linux_button():
            try:
                if not btn.winfo_exists():
                    return
                update_button_style(btn)
            except Exception:
                pass

        btn.after_idle(prime_linux_button)
        btn.after(40, prime_linux_button)

    return btn


def make_badge(
    parent: tk.Widget,
    text: str,
    *,
    style: str = "subtle",
    font_size: int = 8,
    padx: int = 8,
    pady: int = 2
) -> tk.Label:
    """
    Creates an impeccable, modern tag badge / pill chip (e.g. [Fabric], [Forge], [1.21.1]).
    Styles: 'subtle', 'accent', 'success', 'warning', 'danger'
    """
    style_map = {
        "accent": {
            "bg": COLORS.get('accent_subtle', '#23382D'),
            "fg": COLORS.get('accent_color', '#2ECC71')
        },
        "success": {
            "bg": "#132D1F",
            "fg": COLORS.get('success_green', '#10B981')
        },
        "warning": {
            "bg": "#332208",
            "fg": COLORS.get('warning_orange', '#F59E0B')
        },
        "danger": {
            "bg": "#361214",
            "fg": COLORS.get('error_red', '#EF4444')
        },
        "subtle": {
            "bg": COLORS.get('input_bg', '#2E333E'),
            "fg": COLORS.get('text_secondary', '#A6ACB8')
        }
    }
    cfg = style_map.get(style, style_map["subtle"])

    badge = tk.Label(
        parent,
        text=text,
        font=(FONT_FAMILY, font_size, "bold"),
        bg=cfg["bg"],
        fg=cfg["fg"],
        padx=padx,
        pady=pady
    )
    return badge
