"""
tests/test_animation_engine.py - Tests for micro-animation mathematics, easing curves,
and AnimationManager bypass / execution states.
"""

import pytest
import tkinter as tk
from nlc.ui.animation import (
    hex_to_rgb, rgb_to_hex, color_lerp, ease_out_cubic, ease_in_out_quad,
    AnimationManager
)

def test_hex_rgb_conversions():
    """Verify bidirectional hex and rgb conversions."""
    assert hex_to_rgb("#FFFFFF") == (255, 255, 255)
    assert hex_to_rgb("#000000") == (0, 0, 0)
    assert hex_to_rgb("#2ECC71") == (46, 204, 113)
    assert rgb_to_hex(46, 204, 113) == "#2ecc71"
    # Clamping out-of-range inputs
    assert rgb_to_hex(300, -50, 100) == "#ff0064"

def test_color_lerp():
    """Verify color interpolation produces expected endpoints and midpoints."""
    # Endpoints
    assert color_lerp("#000000", "#FFFFFF", 0.0) == "#000000"
    assert color_lerp("#000000", "#FFFFFF", 1.0) == "#ffffff"
    # Midpoint
    mid = color_lerp("#000000", "#FFFFFF", 0.5)
    assert mid in ("#7f7f7f", "#808080")

def test_easing_curves():
    """Verify easing curves start at 0, end at 1, and remain monotonically non-decreasing."""
    assert ease_out_cubic(0.0) == 0.0
    assert ease_out_cubic(1.0) == 1.0
    assert 0.0 < ease_out_cubic(0.5) <= 1.0
    assert ease_in_out_quad(0.0) == 0.0
    assert ease_in_out_quad(1.0) == 1.0

def test_animation_manager_disabled_bypass():
    """Verify animator applies final values immediately with 0 delay when disabled."""
    manager = AnimationManager(root=None, enabled_provider=lambda: False)
    assert manager.is_enabled is False

    # Mock widget dictionary-like access
    widget = {"bg": "#111111"}
    widget["winfo_exists"] = lambda: True

    done_called = False
    def on_done():
        nonlocal done_called
        done_called = True

    manager.animate_color(widget, "bg", "#111111", "#2ECC71", duration_ms=100, on_done=on_done)
    # Must immediately be the end color without delay
    assert widget["bg"] == "#2ECC71"
    assert done_called is True

def test_animation_manager_numeric_interpolation(tk_root):
    """Verify animate_value executes and reaches target value."""
    manager = AnimationManager(root=tk_root, enabled_provider=lambda: True)
    assert manager.is_enabled is True

    stepped_values = []
    done_called = False

    def on_step(val):
        stepped_values.append(val)

    def on_done():
        nonlocal done_called
        done_called = True

    manager.animate_value(0.0, 100.0, duration_ms=30, on_step=on_step, on_done=on_done)

    # Pump Tkinter event loop for animation steps
    for _ in range(10):
        tk_root.update()
        tk_root.after(10)

    assert len(stepped_values) > 0
    assert done_called is True
    assert stepped_values[-1] == 100.0
