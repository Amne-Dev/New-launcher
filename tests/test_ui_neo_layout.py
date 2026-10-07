"""
tests/test_ui_neo_layout.py - Tests for unified Neo layout and sidebar navigation.
"""

import pytest
import tkinter as tk
from unittest.mock import MagicMock
from nlc.ui.theme import METRICS, COLORS
from nlc.ui.app import MinecraftLauncher

def test_theme_neo_metrics():
    """Verify that sidebar width is standardized to 240px and classic nav height is removed."""
    assert METRICS["sidebar_width"] == 240
    assert METRICS.get("sidebar_width_neo") == 240
    assert "nav_bar_height" not in METRICS

def test_neo_layout_no_top_navbar(tk_root):
    """Verify that MinecraftLauncher initializes only the Neo sidebar and no classic nav bar."""
    if not tk_root:
        pytest.skip("Tkinter not available")

    # Mock external network/filesystem calls
    try:
        app = MinecraftLauncher(root=tk_root)
    except Exception as e:
        # If initialization requires assets or mocks, handle gracefully
        pytest.fail(f"MinecraftLauncher initialization failed: {e}")

    # Key assertions for Neo unification
    assert app.nav_bar is None, "Classic top nav_bar should be None in unified Neo layout"
    assert hasattr(app, "sidebar"), "Neo sidebar should exist"
    assert app.sidebar is not None, "Neo sidebar must be instantiated"
    assert hasattr(app, "sidebar_nav_frame"), "Neo sidebar navigation container must exist"

    # Verify active bar tracking on items
    assert len(app.sidebar_items) > 0
    first_item = app.sidebar_items[0]
    assert hasattr(first_item, "_active_bar"), "Sidebar items must have active indicator bar"
    app.set_active_sidebar(first_item)
    assert getattr(first_item, "is_active", False) is True

    # Test drill-down to Modrinth sidebar
    assert hasattr(app, "build_modrinth_sidebar")
    app.build_modrinth_sidebar()
    assert len(app.sidebar_nav_frame.winfo_children()) > 0

    # Test drill-down to dynamic Settings sidebar
    assert hasattr(app, "build_settings_sidebar")
    app.build_settings_sidebar()
    assert len(app.sidebar_nav_frame.winfo_children()) > 0
    assert hasattr(app, "settings_nav_items")
    assert "General" in app.settings_nav_items
    assert "Appearance" in app.settings_nav_items

    # Test exiting settings returns to main sidebar
    assert hasattr(app, "exit_settings")
    app.exit_settings()
    assert getattr(app, "_in_settings_sidebar", True) is False

    # Test returning to main sidebar
    assert hasattr(app, "build_main_sidebar")
    app.build_main_sidebar()
    assert len(app.sidebar_nav_frame.winfo_children()) > 0

    # Test theme refresh on sidebar
    assert hasattr(app, "refresh_sidebar_theme")
    app.refresh_sidebar_theme()
    assert app.sidebar.cget("bg") == COLORS["sidebar_bg"]

    # Test _make_btn creates standard widget
    test_btn = app._make_btn(app.sidebar, "Test", style="primary")
    # Cleanup background services started during init
    if hasattr(app, "close_rpc"):
        try:
            app.close_rpc()
        except Exception:
            pass
    if hasattr(app, "tray_icon") and app.tray_icon:
        try:
            app.tray_icon.stop()
        except Exception:
            pass
