"""
tests/test_settings_screen.py - Integration tests for SettingsScreenMixin category navigation and components.
"""

import pytest
import tkinter as tk
from unittest.mock import MagicMock
from nlc.ui.screens.settings import SettingsScreenMixin, CATEGORIES
from nlc.storage.config import get_default_config

class DummyLauncher(SettingsScreenMixin):
    def __init__(self, root):
        self.root = root
        self.config = get_default_config()
        self.config_vars = {}
        self.animator = MagicMock()
        self.animator.is_enabled = False
        self.status_var = tk.StringVar()
        self.save_config = MagicMock()
        self.check_for_updates = MagicMock()
        self.reset_to_defaults = MagicMock()
        self.tab_container = tk.Frame(root)
        self.tab_container.pack()
        self.tabs = {}
        self.apply_theme = MagicMock()
        self.user_dir = "/fake/mc"
        self.config_dir = "/fake/config"
        self.config_file = "/fake/config/config.json"
        self.rpc_connected = False
        self.rpc_enabled = True

def test_settings_screen_categories(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    launcher = DummyLauncher(tk_root)
    launcher.create_settings_tab()

    assert "Settings" in launcher.tabs
    assert hasattr(launcher, "settings_scroll_frame")

    # Test switching between all categories (including Modpacks & Instances)
    expected_categories = [cat[0] for cat in CATEGORIES]
    assert len(expected_categories) == 8
    assert "Modpacks & Instances" in expected_categories

    for cat_name in expected_categories:
        launcher.switch_settings_category(cat_name)
        assert launcher.current_settings_category == cat_name
        # Ensure widgets were populated inside right content frame
        assert len(launcher.settings_scroll_frame.winfo_children()) > 0

    launcher.tab_container.destroy()

def test_settings_ram_allocation_handlers(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    launcher = DummyLauncher(tk_root)
    launcher.create_settings_tab()
    launcher.switch_settings_category("Java & Memory")

    # Verify RAM widgets exist
    assert hasattr(launcher, "ram_var")
    assert hasattr(launcher, "ram_entry_var")

    # Test slider handler
    launcher._on_ram_slider_change(6144)
    assert launcher.ram_allocation == 6144
    assert launcher.ram_entry_var.get() == "6144"
    assert launcher.save_config.called

    # Test text entry handler
    launcher.save_config.reset_mock()
    launcher.ram_entry_var.set("8192")
    launcher._on_ram_entry_change()
    assert launcher.ram_allocation == 8192
    assert launcher.ram_var.get() == 8192
    assert launcher.save_config.called

    launcher.tab_container.destroy()

def test_settings_rpc_toggle(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    launcher = DummyLauncher(tk_root)
    launcher.create_settings_tab()
    launcher.switch_settings_category("Integrations")

    assert hasattr(launcher, "rpc_var")
    launcher.rpc_var.set(False)
    launcher._on_rpc_toggle()
    assert launcher.rpc_enabled is False
    assert launcher.save_config.called

    launcher.tab_container.destroy()
