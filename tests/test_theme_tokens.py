"""
tests/test_theme_tokens.py - Verification tests for design tokens, curated themes,
WCAG AA contrast calculation, and ThemeManager live updates.
"""

import pytest
from nlc.ui.theme import (
    THEMES, COLORS, THEME_MANAGER, ThemeManager,
    build_theme_tokens, get_relative_luminance, get_contrast_text_color,
    derive_hover_color
)

REQUIRED_TOKENS = [
    'sidebar_bg', 'main_bg', 'tab_bar_bg', 'bottom_bar_bg',
    'card_bg', 'card_hover', 'hover_bg', 'play_btn_green',
    'play_btn_hover', 'play_btn_text', 'accent_color', 'accent_text',
    'border_subtle', 'text_primary', 'text_secondary', 'input_bg',
    'input_border', 'separator', 'error_red', 'success_green'
]

def test_curated_themes_completeness():
    """Verify all 6 curated themes are defined and contain required base tokens."""
    expected_themes = ['dark_slate', 'obsidian', 'catppuccin', 'nord', 'dracula', 'emerald']
    for theme_id in expected_themes:
        assert theme_id in THEMES, f"Missing expected theme: {theme_id}"
        t = THEMES[theme_id]
        assert 'name' in t
        assert 'description' in t
        assert 'card_bg' in t
        assert 'main_bg' in t
        assert 'default_accent' in t

def test_build_theme_tokens_contains_all_tokens():
    """Verify built token dictionary contains all required UI design tokens."""
    for theme_id in THEMES:
        tokens = build_theme_tokens(theme_id)
        for req in REQUIRED_TOKENS:
            assert req in tokens, f"Theme {theme_id} missing token {req}"
            assert tokens[req].startswith("#"), f"Token {req} must be hex color, got {tokens[req]}"

def test_wcag_contrast_text_color():
    """Verify relative luminance & WCAG contrast calculation for light vs dark accents."""
    # Dark backgrounds must yield white text
    assert get_contrast_text_color("#181A1E") == "#FFFFFF"
    assert get_contrast_text_color("#000000") == "#FFFFFF"
    assert get_contrast_text_color("#2D8F36") == "#FFFFFF"
    assert get_contrast_text_color("#B91C1C") == "#FFFFFF"

    # Very bright / neon backgrounds must yield dark text for WCAG AA readability
    assert get_contrast_text_color("#FFFFFF") == "#121316"
    assert get_contrast_text_color("#00E5FF") == "#121316"
    assert get_contrast_text_color("#F1FA8C") == "#121316"

def test_custom_accent_token_derivation():
    """Verify passing a custom accent color overrides accent tokens properly."""
    tokens = build_theme_tokens("obsidian", custom_accent="#FF007F")
    assert tokens['accent_color'] == "#FF007F"
    assert tokens['play_btn_green'] == "#FF007F"
    assert tokens['accent_hover'].startswith("#")
    assert tokens['accent_text'] in ("#FFFFFF", "#121316")

def test_theme_manager_subscription_and_apply():
    """Verify ThemeManager applies tokens and dispatches events to subscribers."""
    manager = ThemeManager("dark_slate")
    received_tokens = []

    def on_theme_change(tokens):
        received_tokens.append(tokens)

    unsub = manager.subscribe(on_theme_change)

    # Apply Nord theme
    new_tokens = manager.apply("nord", custom_accent="#88C0D0")
    assert len(received_tokens) == 1
    assert received_tokens[0]['theme_id'] == "nord"
    assert received_tokens[0]['accent_color'] == "#88C0D0"

    # Unsubscribe and verify no further notifications
    unsub()
    manager.apply("dracula")
    assert len(received_tokens) == 1
