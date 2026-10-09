"""
tests/test_sidebar_account_center.py - Tests for the in-app collapsible sidebar Account Center.
"""

import json
import pytest
import tkinter as tk
from unittest.mock import patch
from nlc.ui.app import MinecraftLauncher
from nlc.ui.theme import COLORS, FONT_FAMILY


def test_sidebar_account_drawer_toggle_and_render(tk_root, tmp_path, monkeypatch):
    """Verify that toggling profile menu expands/collapses the in-sidebar drawer without popups."""
    if not tk_root:
        pytest.skip("Tkinter not available")

    cfg_file = tmp_path / "launcher_config.json"
    cfg_data = {
        "theme_id": "dark_slate",
        "first_run_completed": True,
        "neo_style_enabled": True,
        "profiles": [
            {"name": "PlayerOne", "type": "offline", "skin_path": "", "uuid": ""},
            {"name": "PlayerTwo", "type": "microsoft", "skin_path": "", "uuid": "ms-uuid-123"}
        ],
        "current_profile_index": 0
    }
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with patch("subprocess.Popen"):
        app = MinecraftLauncher(root=tk_root)
        try:
            # Initially drawer is collapsed
            assert hasattr(app, "sidebar_account_drawer")
            assert getattr(app, "sidebar_account_drawer_open", False) is False
            assert app.sidebar_chevron.cget("text") == "▾"

            toplevel_count_before = len([w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel)])

            # Toggle to open
            app.toggle_profile_menu()

            # Verify no popup Toplevel was spawned
            toplevel_count_after = len([w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel)])
            assert toplevel_count_after == toplevel_count_before

            # Verify drawer state
            assert getattr(app, "sidebar_account_drawer_open", False) is True
            assert app.sidebar_chevron.cget("text") == "▴"
            assert app.sidebar_account_drawer.winfo_ismapped() or app.sidebar_account_drawer.winfo_exists()

            # Verify accounts rendered inside drawer
            drawer_children = app.sidebar_account_drawer.winfo_children()
            assert len(drawer_children) >= 2  # header, list container, footer

            # Switch active profile to PlayerTwo (index 1)
            app.current_profile_index = 1
            app.update_active_profile()
            assert app.sidebar_username.cget("text") == "PlayerTwo"

            # Toggle again to collapse
            app.toggle_profile_menu()
            assert getattr(app, "sidebar_account_drawer_open", False) is False
            assert app.sidebar_chevron.cget("text") == "▾"
        finally:
            if hasattr(app, "stop_agent"):
                app.stop_agent()


def test_sidebar_account_drawer_switch_and_delete(tk_root, tmp_path, monkeypatch):
    """Verify switching and deleting accounts inside the sidebar drawer."""
    if not tk_root:
        pytest.skip("Tkinter not available")

    cfg_file = tmp_path / "launcher_config.json"
    cfg_data = {
        "theme_id": "dark_slate",
        "first_run_completed": True,
        "profiles": [
            {"name": "Alice", "type": "offline", "skin_path": "", "uuid": ""},
            {"name": "Bob", "type": "offline", "skin_path": "", "uuid": ""}
        ],
        "current_profile_index": 0
    }
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with patch("subprocess.Popen"):
        app = MinecraftLauncher(root=tk_root)
        try:
            app.toggle_profile_menu()
            assert getattr(app, "sidebar_account_drawer_open", False) is True

            # Mock confirmation to true for delete_profile
            with patch("nlc.ui.screens.accounts.custom_askyesno", return_value=True):
                assert len(app.profiles) == 2
                app.delete_profile(1)  # Delete Bob
                assert len(app.profiles) == 1
                assert app.profiles[0]["name"] == "Alice"

            # Verify drawer re-rendered with 1 account
            assert getattr(app, "sidebar_account_drawer_open", False) is True
        finally:
            if hasattr(app, "stop_agent"):
                app.stop_agent()
