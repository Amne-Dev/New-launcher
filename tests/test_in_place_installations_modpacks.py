"""
tests/test_in_place_installations_modpacks.py - Tests for in-place views in Installations and Modpacks tabs.
"""

import json
import pytest
import tkinter as tk
from nlc.ui.app import MinecraftLauncher


def test_installations_in_place_editor(tk_root, tmp_path, monkeypatch):
    """Verify that opening/closing installation editor swaps views in-place without popup Toplevels."""
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
    app.show_tab("Installations")

    # Initially, browse view is visible and editor view is not active
    assert hasattr(app, "inst_browse_view")
    assert app.inst_browse_view.winfo_ismapped() or app.inst_browse_view.winfo_exists()
    assert getattr(app, "_in_inst_editor", False) is False

    toplevel_count_before = len([w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel)])

    # Open in-place editor
    app.show_installation_editor()
    assert getattr(app, "_in_inst_editor", False) is True
    assert hasattr(app, "inst_editor_view")
    assert app.inst_editor_view.winfo_exists()

    # Verify no new popup Toplevel was spawned
    toplevel_count_after = len([w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel)])
    assert toplevel_count_after == toplevel_count_before

    # Verify fields frame and input entries use active theme tokens (not hardcoded #1e1e1e)
    from nlc.ui.theme import COLORS
    assert app.inst_editor_fields_frame.cget("bg") == COLORS['card_bg']
    assert app.inst_editor_entries[0].cget("bg") == COLORS['input_bg']
    assert app.inst_editor_card.cget("bg") == COLORS['card_bg']

    # Close editor
    app.close_installation_editor()
    assert getattr(app, "_in_inst_editor", False) is False
    assert app.inst_browse_view.winfo_exists()


def test_modpacks_in_place_create_page(tk_root, tmp_path, monkeypatch):
    """Verify that opening/closing modpack create page swaps views in-place without popup Toplevels."""
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
    app.show_tab("Modpacks")

    # Initially, browse view is visible
    assert hasattr(app, "modpacks_browse_view")
    assert app.modpacks_browse_view.winfo_exists()
    assert getattr(app, "_in_modpack_create_view", False) is False

    toplevel_count_before = len([w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel)])

    # Open in-place modpack creation
    app.show_create_modpack_page()
    assert getattr(app, "_in_modpack_create_view", False) is True
    assert hasattr(app, "modpack_create_view")
    assert app.modpack_create_view.winfo_exists()

    # Verify no new popup Toplevel was spawned
    toplevel_count_after = len([w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel)])
    assert toplevel_count_after == toplevel_count_before

    # Close create page
    app.close_create_modpack_page()
    assert getattr(app, "_in_modpack_create_view", False) is False
    assert app.modpacks_browse_view.winfo_exists()
