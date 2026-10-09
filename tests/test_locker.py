"""
tests/test_locker.py - Tests for the redesigned Locker screen, 2.5D showcase stage, wardrobe presets, and wallpaper studio.
"""

import os
import json
import tkinter as tk
import pytest
from PIL import Image

from nlc.ui.app import MinecraftLauncher
from nlc.ui.theme import COLORS, THEMES, THEME_MANAGER


def test_locker_tab_creation_and_subview_switch(tk_root, tmp_path, monkeypatch):
    if not tk_root:
        pytest.skip("Tkinter not available")

    cfg_file = tmp_path / "launcher_config.json"
    cfg_data = {
        "theme_id": "dark_slate",
        "first_run_completed": True,
        "neo_style_enabled": True
    }
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    app = MinecraftLauncher(root=tk_root)
    app.show_tab("Locker")

    # Initial state: Skins view
    assert app.locker_view.get() == "Skins"
    assert hasattr(app, "preview_canvas")
    assert app.preview_canvas.winfo_exists()
    assert hasattr(app, "chip_classic")
    assert hasattr(app, "chip_slim")

    # Switch to Wallpapers view
    app.switch_locker_view("Wallpapers")
    assert app.locker_view.get() == "Wallpapers"
    assert hasattr(app, "wp_grid_frame")
    assert app.wp_grid_frame.winfo_exists()

    # Switch back to Skins view
    app.switch_locker_view("Skins")
    assert app.locker_view.get() == "Skins"
    assert hasattr(app, "preview_canvas")
    assert app.preview_canvas.winfo_exists()


def test_locker_model_chips_toggle(tk_root, tmp_path, monkeypatch):
    if not tk_root:
        pytest.skip("Tkinter not available")

    cfg_file = tmp_path / "launcher_config.json"
    cfg_data = {
        "theme_id": "dark_slate",
        "first_run_completed": True,
        "neo_style_enabled": True
    }
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    app = MinecraftLauncher(root=tk_root)
    app.show_tab("Locker")

    # Toggle to slim (Alex)
    app._select_skin_model("slim")
    assert app.skin_model_var.get() == "slim"
    if app.profiles:
        assert app.profiles[app.current_profile_index].get("skin_model") == "slim"

    # Toggle back to classic (Steve)
    app._select_skin_model("classic")
    assert app.skin_model_var.get() == "classic"
    if app.profiles:
        assert app.profiles[app.current_profile_index].get("skin_model") == "classic"


def test_locker_wardrobe_presets_and_filtering(tk_root, tmp_path, monkeypatch):
    if not tk_root:
        pytest.skip("Tkinter not available")

    cfg_file = tmp_path / "launcher_config.json"
    cfg_data = {
        "theme_id": "dark_slate",
        "first_run_completed": True,
        "neo_style_enabled": True
    }
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    app = MinecraftLauncher(root=tk_root)

    # Create dummy skin files
    skins_dir = tmp_path / "test_skins"
    skins_dir.mkdir()
    skin_a = skins_dir / "knight_skin.png"
    skin_b = skins_dir / "archer_alex.png"

    img_dummy = Image.new("RGBA", (64, 64), color=(100, 150, 200, 255))
    img_dummy.save(skin_a)
    img_dummy.save(skin_b)

    if not app.profiles:
        app.profiles = [{"name": "Tester", "type": "offline", "skin_history": []}]
        app.current_profile_index = 0

    p = app.profiles[app.current_profile_index]
    p["skin_history"] = [
        {"path": str(skin_a), "model": "classic", "name": "Knight"},
        {"path": str(skin_b), "model": "slim", "name": "Archer"},
    ]

    app.show_tab("Locker")
    tk_root.update_idletasks()

    # Verify both cards exist in history frame
    cards = app.history_frame.winfo_children()
    assert len(cards) == 2

    # Filter by 'Knight'
    app.wardrobe_search_var.set("Knight")
    tk_root.update_idletasks()
    filtered_cards = app.history_frame.winfo_children()
    assert len(filtered_cards) == 1

    # Reset filter
    app.wardrobe_search_var.set("")
    tk_root.update_idletasks()
    assert len(app.history_frame.winfo_children()) == 2


def test_locker_dual_layer_head_avatar(tk_root, tmp_path):
    if not tk_root:
        pytest.skip("Tkinter not available")

    # Create 64x64 test image with base head (green) and outer hat (red with alpha)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    # Fill base head at (8, 8, 16, 16) with Green
    for x in range(8, 16):
        for y in range(8, 16):
            img.putpixel((x, y), (0, 255, 0, 255))

    # Fill outer hat at (40, 8, 48, 16) with Red overlay
    for x in range(40, 48):
        for y in range(8, 16):
            img.putpixel((x, y), (255, 0, 0, 180))

    skin_file = tmp_path / "dual_layer_skin.png"
    img.save(skin_file)

    app = MinecraftLauncher(root=tk_root)
    head_photo = app.get_head_from_skin(str(skin_file), size=44)
    assert head_photo is not None
    assert head_photo.width() == 44
    assert head_photo.height() == 44


def test_locker_wallpapers_filtering(tk_root, tmp_path, monkeypatch):
    if not tk_root:
        pytest.skip("Tkinter not available")

    cfg_file = tmp_path / "launcher_config.json"
    cfg_data = {
        "theme_id": "dark_slate",
        "first_run_completed": True,
        "neo_style_enabled": True
    }
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    app = MinecraftLauncher(root=tk_root)
    app.show_tab("Locker")
    app.switch_locker_view("Wallpapers")

    # Test filter switches
    app._set_wallpaper_filter("default")
    assert app.wallpaper_filter_var.get() == "default"

    app._set_wallpaper_filter("custom")
    assert app.wallpaper_filter_var.get() == "custom"

    app._set_wallpaper_filter("all")
    assert app.wallpaper_filter_var.get() == "all"
