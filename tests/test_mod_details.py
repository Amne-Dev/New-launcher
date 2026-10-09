import io
import os
import sys
import json
import zipfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tkinter as tk

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nlc.ui.screens.mods import ModsScreenMixin
from nlc.ui.theme import COLORS, THEMES


class DummyModsHost(ModsScreenMixin):
    def __init__(self, root, tmp_path):
        self.root = root
        self.tab_container = tk.Frame(root)
        self.tabs = {}
        self.modpacks = [{'name': 'TestPack', 'loader': 'fabric', 'mc_version': '1.20.1', 'mods': []}]
        self.config_dir = str(tmp_path)
        self._make_btn = lambda parent, text, **kw: tk.Button(parent, text=text, command=kw.get('command'))
        self._bind_wheel_events = lambda *a, **k: None
        self._bind_smooth_scroll = lambda *a, **k: None
        self.create_mods_tab()


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_card_click_opens_details_and_back_returns(tk_root, tmp_path):
    host = DummyModsHost(tk_root, tmp_path)
    fake_mod = {
        "title": "Sodium",
        "slug": "sodium",
        "author": "jellysquid",
        "description": "Fast rendering engine",
        "project_type": "mod",
        "downloads": 1250000,
        "follows": 45000,
        "icon_url": None,
    }

    host.mod_end_reached = True
    host._display_mod_results([fake_mod], reset=True, generation=0)
    tk_root.update()

    # Cards rendered in mods_scrollable_frame
    cards = [w for w in host.mods_scrollable_frame.winfo_children() if isinstance(w, tk.Frame)]
    assert len(cards) == 1
    card = cards[0]

    # Verify not in details yet
    assert not getattr(host, '_in_mod_details', False)

    # Trigger click on card
    card.event_generate("<Button-1>")
    tk_root.update()

    # Now in details view
    assert host._in_mod_details is True
    assert host.mods_detail_view.winfo_manager() == "pack"
    assert host.mods_browse_view.winfo_manager() == ""
    assert hasattr(host, 'detail_hero_card') and host.detail_hero_card.winfo_exists()

    # Click back to results
    host.close_project_details()
    tk_root.update()

    assert host._in_mod_details is False
    assert host.mods_browse_view.winfo_manager() == "pack"
    assert host.mods_detail_view.winfo_manager() == ""


def test_extract_modpack_mods_from_mrpack(tk_root, tmp_path):
    host = DummyModsHost(tk_root, tmp_path)

    # Create dummy .mrpack zip in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        idx_content = {
            "name": "SuperPack",
            "files": [
                {"path": "mods/sodium-fabric-0.5.8.jar", "fileSize": 1048576},
                {"path": "mods/iris-1.6.17.jar", "fileSize": 2097152},
                {"path": "config/sodium-options.json", "fileSize": 500},
            ]
        }
        z.writestr("modrinth.index.json", json.dumps(idx_content))
    mrpack_bytes = buf.getvalue()

    mock_resp_versions = MagicMock()
    mock_resp_versions.status_code = 200
    mock_resp_versions.json.return_value = [
        {"files": [{"filename": "superpack.mrpack", "url": "https://example.com/pack.mrpack"}]}
    ]

    mock_resp_mrpack = MagicMock()
    mock_resp_mrpack.status_code = 200
    mock_resp_mrpack.content = mrpack_bytes

    mock_session = MagicMock()
    mock_session.get.side_effect = [mock_resp_versions, mock_resp_mrpack]

    with patch("nlc.ui.screens.mods.get_http_session", return_value=mock_session):
        mods = host._extract_modpack_mods("superpack")

    assert len(mods) == 2
    assert mods[0]["name"] == "sodium-fabric-0.5.8"
    assert mods[1]["name"] == "iris-1.6.17"

    # Verify second call is served from disk cache without network
    mock_session.get.reset_mock()
    with patch("nlc.ui.screens.mods.get_http_session", return_value=mock_session):
        cached_mods = host._extract_modpack_mods("superpack")
    mock_session.get.assert_not_called()
    assert len(cached_mods) == 2


def test_render_markdown_to_text(tk_root, tmp_path):
    host = DummyModsHost(tk_root, tmp_path)
    txt = tk.Text(tk_root)

    md = """# Title Header
A paragraph with **bold** text, *italic* notes, and `code_snippet`.

## Features
- First feature
- Second feature with [Modrinth Link](https://modrinth.com)
"""
    host._render_markdown_to_text(txt, md)
    content = txt.get("1.0", tk.END)

    assert "Title Header" in content
    assert "Features" in content
    assert "First feature" in content
    assert "Modrinth Link" in content
    txt.destroy()


def test_details_view_theme_synchronization(tk_root, tmp_path):
    host = DummyModsHost(tk_root, tmp_path)
    fake_mod = {
        "title": "Iris Shaders",
        "slug": "iris",
        "author": "coderbot",
        "description": "Shaders mod for Minecraft",
        "project_type": "shader",
        "downloads": 8900000,
        "follows": 32000,
    }
    host.show_project_details(fake_mod)
    tk_root.update()

    assert host._in_mod_details is True

    # Populate dummy details
    host._populate_project_details(
        project_data={"title": "Iris Shaders", "gallery": [], "body": "Shader description"},
        included_mods=[],
        mod_summary=fake_mod,
        loading_lbl=None
    )
    tk_root.update()

    # Apply Obsidian theme
    COLORS.update(THEMES['obsidian'])
    host.refresh_mods_screen_theme()
    tk_root.update()

    obs_main = THEMES['obsidian']['main_bg']
    obs_card = THEMES['obsidian']['card_bg']

    assert host.mods_detail_view.cget("bg") == obs_main
    assert host.detail_canvas.cget("bg") == obs_main
    assert host.detail_hero_card.cget("bg") == obs_card
    assert host.detail_desc_section.cget("bg") == obs_card
    assert host.detail_text_widget.cget("bg") == obs_card
