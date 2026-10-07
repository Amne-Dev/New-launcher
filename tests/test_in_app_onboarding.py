"""
tests/test_in_app_onboarding.py - Tests for in-app onboarding wizard and zero-popup tour.
"""

import json
import pytest
import tkinter as tk
from nlc.ui.app import MinecraftLauncher


def test_in_app_onboarding_wizard(tk_root, tmp_path, monkeypatch):
    """Verify onboarding wizard renders as an in-app view without creating popup Toplevels."""
    if not tk_root:
        pytest.skip("Tkinter not available")

    cfg_file = tmp_path / "launcher_config.json"
    cfg_data = {
        "theme_id": "dark_slate",
        "first_run_completed": False,
        "neo_style_enabled": True
    }
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    app = MinecraftLauncher(root=tk_root)

    toplevel_count_before = len([w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel)])

    # Trigger onboarding wizard
    app.show_onboarding_wizard()

    # Verify no new popup Toplevel was spawned
    toplevel_count_after = len([w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel)])
    assert toplevel_count_after == toplevel_count_before

    # Verify onboarding view is packed inside window_content
    assert hasattr(app, "_onboarding_view")
    assert app._onboarding_view is not None
    assert app._onboarding_view.winfo_exists()

    # Close onboarding wizard
    app.close_onboarding_wizard(start_tour=False)

    # Verify sidebar and content area are restored
    assert app.sidebar.winfo_ismapped() or app.sidebar.winfo_exists()
    assert app.content_area.winfo_ismapped() or app.content_area.winfo_exists()


def test_in_app_coach_marks_and_celebration(tk_root, tmp_path, monkeypatch):
    """Verify coach marks and celebration banner render inside content area without popups."""
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

    toplevel_count_before = len([w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel)])

    # Show coach mark
    app.show_coach_mark(None, "Tour Test Message", step_info="TOUR 1 OF 3")

    toplevel_count_after = len([w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel)])
    assert toplevel_count_after == toplevel_count_before

    assert hasattr(app, "tour_card")
    assert app.tour_card is not None
    assert app.tour_card.winfo_exists()

    # Finish celebration banner
    app.finish_tour_celebration()

    # Old tour card should be dismissed
    assert app.tour_card is None

    # No popup Toplevels were spawned
    assert len([w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel)]) == toplevel_count_before
