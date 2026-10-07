"""
tests/test_ui_button_theming.py - Tests for real-time live button theme hot-reloading.
"""

import pytest
import tkinter as tk
from nlc.ui.theme import COLORS, THEME_MANAGER, THEMES
from nlc.ui.components.buttons import make_button, refresh_all_buttons, get_button_style_cfg

def test_live_button_theme_switch(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    # Start with dark_slate
    THEME_MANAGER.apply("dark_slate")
    initial_primary_bg = COLORS['play_btn_green']
    initial_secondary_bg = COLORS.get('input_bg', '#2E333E')

    btn_primary = make_button(tk_root, "Primary Action", style="primary")
    btn_secondary = make_button(tk_root, "Secondary Action", style="secondary")

    assert btn_primary.cget("bg") == initial_primary_bg
    assert btn_secondary.cget("bg") == initial_secondary_bg

    # Switch to Catppuccin theme
    catppuccin_tokens = THEME_MANAGER.apply("catppuccin")
    assert btn_primary.cget("bg") == catppuccin_tokens['play_btn_green']
    assert btn_secondary.cget("bg") == catppuccin_tokens['input_bg']

    # Switch to Nord theme
    nord_tokens = THEME_MANAGER.apply("nord")
    assert btn_primary.cget("bg") == nord_tokens['play_btn_green']
    assert btn_secondary.cget("bg") == nord_tokens['input_bg']

    # Test dynamic hover restoration
    btn_secondary._on_enter(None)
    assert btn_secondary.cget("bg") == nord_tokens['card_hover']
    btn_secondary._on_leave(None)
    assert btn_secondary.cget("bg") == nord_tokens['input_bg']

    # Cleanup
    btn_primary.destroy()
    btn_secondary.destroy()
    THEME_MANAGER.apply("dark_slate")
