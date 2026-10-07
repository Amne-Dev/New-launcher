"""
nlc.ui.theme - Unified Design System Tokens & Dynamic Theme Engine for New Launcher (NLC)
Provides cohesive palettes, WCAG AA contrast calculation, live theme switching,
and centralized typography, metrics, and styling.
"""

import os
from typing import Dict, Tuple, List, Callable, Optional, Any
from nlc.ui.animation import hex_to_rgb, rgb_to_hex, color_lerp

# --- Curated Designer Themes ---
THEMES: Dict[str, Dict[str, Any]] = {
    'dark_slate': {
        'name': 'Dark Slate',
        'description': 'Refined modern graphite slate with emerald accent',
        'sidebar_bg': '#181A1E',
        'main_bg': '#1E2025',
        'tab_bar_bg': '#1E2025',
        'bottom_bar_bg': '#181A1E',
        'card_bg': '#242830',
        'card_hover': '#2C313C',
        'hover_bg': '#282C36',
        'input_bg': '#2E333E',
        'input_border': '#3D4452',
        'border_subtle': '#2B303A',
        'separator': '#282C36',
        'default_accent': '#2ECC71',
        'play_btn_hover': '#27AE60',
        'dialog_backdrop': '#0D0E11',
    },
    'obsidian': {
        'name': 'OLED Obsidian',
        'description': 'True pitch black contrast with neon cyan accent',
        'sidebar_bg': '#000000',
        'main_bg': '#0A0A0A',
        'tab_bar_bg': '#0A0A0A',
        'bottom_bar_bg': '#050505',
        'card_bg': '#141414',
        'card_hover': '#1F1F1F',
        'hover_bg': '#1A1A1A',
        'input_bg': '#181818',
        'input_border': '#333333',
        'border_subtle': '#222222',
        'separator': '#1A1A1A',
        'default_accent': '#00E5FF',
        'play_btn_hover': '#00B4D8',
        'dialog_backdrop': '#000000',
    },
    'catppuccin': {
        'name': 'Catppuccin Mocha',
        'description': 'Soothing warm dark aesthetic with soft mauve accent',
        'sidebar_bg': '#181825',
        'main_bg': '#1E1E2E',
        'tab_bar_bg': '#1E1E2E',
        'bottom_bar_bg': '#181825',
        'card_bg': '#28283D',
        'card_hover': '#313244',
        'hover_bg': '#313244',
        'input_bg': '#313244',
        'input_border': '#45475A',
        'border_subtle': '#36374D',
        'separator': '#313244',
        'default_accent': '#CBA6F7',
        'play_btn_hover': '#B4BEFE',
        'dialog_backdrop': '#11111B',
    },
    'nord': {
        'name': 'Nord Frost',
        'description': 'Arctic dusk slate with polar frost blue accent',
        'sidebar_bg': '#242933',
        'main_bg': '#2E3440',
        'tab_bar_bg': '#2E3440',
        'bottom_bar_bg': '#242933',
        'card_bg': '#384152',
        'card_hover': '#434C5E',
        'hover_bg': '#3B4252',
        'input_bg': '#3B4252',
        'input_border': '#4C566A',
        'border_subtle': '#3B4252',
        'separator': '#3B4252',
        'default_accent': '#88C0D0',
        'play_btn_hover': '#81A1C1',
        'dialog_backdrop': '#1E222A',
    },
    'dracula': {
        'name': 'Dracula Midnight',
        'description': 'Deep violet-charcoal with electric purple accent',
        'sidebar_bg': '#1E1F29',
        'main_bg': '#282A36',
        'tab_bar_bg': '#282A36',
        'bottom_bar_bg': '#1E1F29',
        'card_bg': '#343746',
        'card_hover': '#44475A',
        'hover_bg': '#44475A',
        'input_bg': '#44475A',
        'input_border': '#6272A4',
        'border_subtle': '#3A3D4E',
        'separator': '#3A3D4E',
        'default_accent': '#BD93F9',
        'play_btn_hover': '#FF79C6',
        'dialog_backdrop': '#14151C',
    },
    'emerald': {
        'name': 'Emerald Pine',
        'description': 'Deep evergreen foliage with vibrant pine green accent',
        'sidebar_bg': '#101712',
        'main_bg': '#162119',
        'tab_bar_bg': '#162119',
        'bottom_bar_bg': '#101712',
        'card_bg': '#1F2E23',
        'card_hover': '#2A3C2F',
        'hover_bg': '#253629',
        'input_bg': '#223326',
        'input_border': '#334A38',
        'border_subtle': '#253629',
        'separator': '#223326',
        'default_accent': '#27AE60',
        'play_btn_hover': '#2ECC71',
        'dialog_backdrop': '#0B100C',
    }
}

def get_relative_luminance(hex_color: str) -> float:
    """Calculate relative luminance according to WCAG 2.1 specifications."""
    r, g, b = hex_to_rgb(hex_color)
    def _srgb_to_lin(c_int: int) -> float:
        c = c_int / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * _srgb_to_lin(r) + 0.7152 * _srgb_to_lin(g) + 0.0722 * _srgb_to_lin(b)

def get_contrast_text_color(bg_hex: str) -> str:
    """Return #FFFFFF or #121316 to maximize WCAG contrast against bg_hex."""
    lum = get_relative_luminance(bg_hex)
    return "#121316" if lum > 0.42 else "#FFFFFF"

def derive_hover_color(hex_color: str) -> str:
    """Derive an appropriate hover state (slightly brighter or deeper)."""
    lum = get_relative_luminance(hex_color)
    target = "#000000" if lum > 0.5 else "#FFFFFF"
    return color_lerp(hex_color, target, 0.16)

def build_theme_tokens(theme_key: str = "dark_slate", custom_accent: Optional[str] = None) -> Dict[str, str]:
    """Build full dictionary of design tokens for the specified theme and accent."""
    base = THEMES.get(theme_key, THEMES['dark_slate'])
    accent = custom_accent or base['default_accent']
    accent_hover = derive_hover_color(accent)
    accent_text = get_contrast_text_color(accent)

    return {
        'theme_id': theme_key,
        'sidebar_bg': base['sidebar_bg'],
        'main_bg': base['main_bg'],
        'tab_bar_bg': base['tab_bar_bg'],
        'bottom_bar_bg': base['bottom_bar_bg'],
        'card_bg': base['card_bg'],
        'card_hover': base['card_hover'],
        'hover_bg': base['hover_bg'],
        'play_btn_green': accent,
        'play_btn_hover': accent_hover,
        'play_btn_text': accent_text,
        'active_tab_border': accent,
        'accent_color': accent,
        'accent_hover': accent_hover,
        'accent_text': accent_text,
        'accent_subtle': color_lerp(base['card_bg'], accent, 0.18),
        'border_subtle': base.get('border_subtle', '#2D3139'),
        'text_primary': '#FFFFFF',
        'text_secondary': '#A6ACB8',
        'text_muted': '#6B7280',
        'input_bg': base['input_bg'],
        'input_border': base['input_border'],
        'separator': base['separator'],
        'accent_blue': '#3498DB',
        'button_hover': base['card_hover'],
        'error_red': '#EF4444',
        'success_green': '#10B981',
        'warning_orange': '#F59E0B',
        'dialog_backdrop': base['dialog_backdrop'],
    }

# Active Global Tokens (mutated in-place on theme switch for seamless legacy compatibility)
COLORS: Dict[str, str] = build_theme_tokens("dark_slate")

# --- Typography Tokens ---
FONT_FAMILY = "Segoe UI" if os.name == "nt" else "DejaVu Sans"

FONTS = {
    'hero_title': (FONT_FAMILY, 24, "bold"),
    'dialog_title': (FONT_FAMILY, 14, "bold"),
    'heading_large': (FONT_FAMILY, 12, "bold"),
    'heading_medium': (FONT_FAMILY, 10, "bold"),
    'sidebar_category': (FONT_FAMILY, 8, "bold"),
    'body': (FONT_FAMILY, 10),
    'body_bold': (FONT_FAMILY, 10, "bold"),
    'small': (FONT_FAMILY, 9),
    'small_bold': (FONT_FAMILY, 9, "bold"),
    'caption': (FONT_FAMILY, 8),
    'btn_large': (FONT_FAMILY, 14, "bold"),
    'btn_medium': (FONT_FAMILY, 10, "bold"),
    'code': ("Consolas" if os.name == "nt" else "Monospace", 9)
}

# --- Layout Metrics ---
METRICS = {
    'window_default_width': 1080,
    'window_default_height': 720,
    'sidebar_width': 240,
    'sidebar_width_neo': 240,  # alias for backward compatibility
    'bottom_bar_height': 80,
    'card_padding_x': 16,
    'card_padding_y': 12,
    'btn_padding_x': 16,
    'btn_padding_y': 8,
    'input_padding_x': 10,
    'input_padding_y': 6,
    'corner_radius_sm': 4,
    'corner_radius_md': 8,
    'corner_radius_lg': 12,
}


class ThemeManager:
    """Manages active theme state and dispatches live update events to subscribers."""
    def __init__(self, current_theme: str = "dark_slate", custom_accent: Optional[str] = None):
        self.theme_id = current_theme if current_theme in THEMES else "dark_slate"
        self.custom_accent = custom_accent
        self._listeners: List[Callable[[Dict[str, str]], None]] = []
        self.apply(self.theme_id, self.custom_accent, notify=False)

    def subscribe(self, callback: Callable[[Dict[str, str]], None]) -> Callable[[], None]:
        """Subscribe to live theme change events. Returns an unsubscribe callable."""
        self._listeners.append(callback)
        def _unsub():
            if callback in self._listeners:
                self._listeners.remove(callback)
        return _unsub

    # Alias for convenience
    add_listener = subscribe

    def apply(self, theme_key: str, custom_accent: Optional[str] = None, notify: bool = True) -> Dict[str, str]:
        """Apply theme and update global COLORS dictionary in place."""
        if theme_key in THEMES:
            self.theme_id = theme_key
        self.custom_accent = custom_accent

        new_tokens = build_theme_tokens(self.theme_id, self.custom_accent)
        COLORS.clear()
        COLORS.update(new_tokens)

        if notify:
            for listener in list(self._listeners):
                try:
                    listener(new_tokens)
                except Exception:
                    pass

        return new_tokens

# Singleton Theme Manager
THEME_MANAGER = ThemeManager("dark_slate")
