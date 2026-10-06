"""
nlc.ui.theme - Unified Design System Tokens for New Launcher (NLC)
Contains all colors, typography, paddings, metrics, and ttk style initializers.
"""

import os
from typing import Dict, Tuple

# --- Color Tokens ---
COLORS: Dict[str, str] = {
    'sidebar_bg': '#212121',
    'main_bg': '#313233',
    'tab_bar_bg': '#313233',
    'bottom_bar_bg': '#313233',
    'card_bg': '#3A3B3C',
    'card_hover': '#454647',
    'hover_bg': '#3A3B3C',
    'play_btn_green': '#2D8F36',
    'play_btn_hover': '#1E6624',
    'text_primary': '#FFFFFF',
    'text_secondary': '#B0B0B0',
    'text_muted': '#777777',
    'input_bg': '#48494A',
    'input_border': '#5A5B5C',
    'active_tab_border': '#2D8F36',
    'separator': '#454545',
    'accent_blue': '#3498DB',
    'button_hover': '#2980B9',
    'error_red': '#E74C3C',
    'success_green': '#2ECC71',
    'warning_orange': '#F39C12',
    'dialog_backdrop': '#141414'
}

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
    'sidebar_width_neo': 240,
    'sidebar_width_classic': 200,
    'bottom_bar_height': 80,
    'nav_bar_height': 60,
    'card_padding_x': 15,
    'card_padding_y': 10,
    'btn_padding_x': 15,
    'btn_padding_y': 6,
    'input_padding_x': 8,
    'input_padding_y': 4
}
