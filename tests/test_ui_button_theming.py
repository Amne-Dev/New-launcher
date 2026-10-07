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


def test_sidebar_account_and_header_live_theming(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    from nlc.ui.app import MinecraftLauncher
    from nlc.ui.animation import AnimationManager

    app = MinecraftLauncher.__new__(MinecraftLauncher)
    app.root = tk_root
    app.animator = AnimationManager(tk_root, enabled_provider=lambda: False)
    app.sidebar_items = []

    # Construct sidebar & account button
    app.sidebar = tk.Frame(tk_root, bg=COLORS['sidebar_bg'])
    app.profile_frame = tk.Frame(app.sidebar, bg=COLORS['sidebar_bg'])
    app.sidebar_head_label = tk.Label(app.profile_frame, bg=COLORS['sidebar_bg'])
    app.sidebar_text_frame = tk.Frame(app.profile_frame, bg=COLORS['sidebar_bg'])
    app.sidebar_username = tk.Label(app.sidebar_text_frame, text="Steve", bg=COLORS['sidebar_bg'], fg=COLORS['text_primary'])
    app.sidebar_acct_type = tk.Label(app.sidebar_text_frame, text="Offline", bg=COLORS['sidebar_bg'], fg=COLORS['text_muted'])
    app.sidebar_chevron = tk.Label(app.profile_frame, text="▾", bg=COLORS['sidebar_bg'], fg=COLORS['text_muted'])
    app._attach_sidebar_hover(app.profile_frame)

    # Category header
    app.sidebar_nav_frame = tk.Frame(app.sidebar, bg=COLORS['sidebar_bg'])
    cat_lbl = tk.Label(app.sidebar_nav_frame, text="SETTINGS", bg=COLORS['sidebar_bg'], fg=COLORS['text_muted'])
    cat_lbl._is_category_header = True

    # Initial state
    THEME_MANAGER.apply("dark_slate")
    app.refresh_sidebar_theme()
    assert app.profile_frame.cget("bg") == THEMES['dark_slate']['sidebar_bg']
    assert app.sidebar_username.cget("bg") == THEMES['dark_slate']['sidebar_bg']

    # Live switch to dracula without restart
    THEME_MANAGER.apply("dracula")
    app.refresh_sidebar_theme()
    drac_bg = THEMES['dracula']['sidebar_bg']
    assert app.profile_frame.cget("bg") == drac_bg
    assert app.sidebar_text_frame.cget("bg") == drac_bg
    assert app.sidebar_username.cget("bg") == drac_bg
    assert app.sidebar_username.cget("fg") == COLORS['text_primary']
    assert app.sidebar_acct_type.cget("bg") == drac_bg
    assert app.sidebar_chevron.cget("bg") == drac_bg
    assert cat_lbl.cget("bg") == drac_bg

    # Test hover on profile frame maintains synchronized background
    app.profile_frame._on_enter()
    assert app.sidebar_username.cget("bg") == COLORS['hover_bg']
    assert app.sidebar_text_frame.cget("bg") == COLORS['hover_bg']
    app.profile_frame._on_leave()
    assert app.sidebar_username.cget("bg") == drac_bg
    assert app.sidebar_username.cget("fg") == COLORS['text_primary']

    # Cleanup
    app.sidebar.destroy()
    THEME_MANAGER.apply("dark_slate")

