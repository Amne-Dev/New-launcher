import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tkinter as tk

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nlc.ui.screens.mods import ModsScreenMixin


class DummyModsHost(ModsScreenMixin):
    def __init__(self, root):
        self.root = root
        self._mod_search_generation = 1
        self.mod_offset = 0
        self.mod_end_reached = False
        self.mod_loading = False
        self.results = []
        self.errors = []

    def _on_mod_search_result(self, result, reset, generation=None):
        if generation != self._mod_search_generation:
            return
        if not result or result.get("status") != "success":
            self.errors.append(result.get("msg") if result else "No response")
            return
        self.results.append(result)


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_direct_search_mods_worker_success(tk_root):
    host = DummyModsHost(tk_root)
    fake_hits = [{"title": "Sodium", "slug": "sodium"}]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"hits": fake_hits, "total_hits": 1}

    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp

    with patch("nlc.ui.screens.mods.get_http_session", return_value=mock_session):
        host._direct_search_mods_worker(
            {"query": "sodium", "limit": 10, "offset": 0, "facets": ["project_type:mod"]},
            reset=True,
            generation=1,
        )

    # Process events on root
    tk_root.update()

    assert len(host.results) == 1
    assert host.results[0]["status"] == "success"
    assert host.results[0]["data"]["hits"] == fake_hits


def test_direct_search_mods_worker_error(tk_root):
    host = DummyModsHost(tk_root)
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp

    with patch("nlc.ui.screens.mods.get_http_session", return_value=mock_session):
        host._direct_search_mods_worker(
            {"query": "error_test", "limit": 10, "offset": 0},
            reset=True,
            generation=1,
        )

    tk_root.update()

    assert len(host.errors) == 1
    assert "Internal Server Error" in host.errors[0]


def test_mods_progressive_card_rendering(tk_root, tmp_path):
    import time

    class FullModsHost(ModsScreenMixin):
        def __init__(self, root):
            self.root = root
            self.tab_container = tk.Frame(root)
            self.tabs = {}
            self.modpacks = []
            self.config_dir = str(tmp_path)
            self._make_btn = lambda parent, text, **kw: tk.Button(parent, text=text)
            self._bind_wheel_events = lambda *a, **k: None
            self._bind_smooth_scroll = lambda *a, **k: None
            self.create_mods_tab()

    host = FullModsHost(tk_root)
    fake_hits = [{"title": f"Mod {i}", "slug": f"mod-{i}", "author": "dev", "description": "desc"} for i in range(12)]
    
    host.mod_end_reached = True
    host.mod_loading = True
    # Reset and display results
    host._display_mod_results(fake_hits, reset=True, generation=0)
    
    # First batch (5 cards) renders immediately
    cards_batch1 = [w for w in host.mods_scrollable_frame.winfo_children() if isinstance(w, tk.Frame)]
    assert len(cards_batch1) == 5

    # Process pending events for remaining batches
    for _ in range(20):
        tk_root.update()
        time.sleep(0.01)

    cards_all = [w for w in host.mods_scrollable_frame.winfo_children() if isinstance(w, tk.Frame)]
    assert len(cards_all) == 12
    assert not host.mod_loading


def test_mod_icon_disk_caching(tk_root, tmp_path):
    import io
    import hashlib
    from PIL import Image

    class FullModsHost(ModsScreenMixin):
        def __init__(self, root):
            self.root = root
            self.tab_container = tk.Frame(root)
            self.tabs = {}
            self.modpacks = []
            self.config_dir = str(tmp_path)
            self._make_btn = lambda parent, text, **kw: tk.Button(parent, text=text)
            self._bind_wheel_events = lambda *a, **k: None
            self._bind_smooth_scroll = lambda *a, **k: None
            self.create_mods_tab()

    host = FullModsHost(tk_root)
    cache_dir = host._get_mod_icon_cache_dir()
    assert os.path.exists(cache_dir)

    # Create dummy 128x128 image
    test_img = Image.new("RGBA", (128, 128), (255, 0, 0, 255))
    buf = io.BytesIO()
    test_img.save(buf, format="PNG")
    raw_bytes = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = raw_bytes

    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp

    test_url = "https://cdn.modrinth.com/data/test/icon.png"

    with patch("nlc.ui.screens.mods.get_http_session", return_value=mock_session):
        host._fetch_and_cache_mod_icon(test_url)

    # Process Tk queue
    tk_root.update()

    # Verify cached on disk as a 64x64 PNG
    url_hash = hashlib.sha256(test_url.encode("utf-8")).hexdigest()[:24]
    cached_path = os.path.join(cache_dir, f"{url_hash}.png")
    assert os.path.exists(cached_path)

    with Image.open(cached_path) as saved_img:
        assert saved_img.size == (64, 64)

    # Verify second load reads from disk without network
    mock_session.get.reset_mock()
    with patch("nlc.ui.screens.mods.get_http_session", return_value=mock_session):
        host._fetch_and_cache_mod_icon(test_url)
    mock_session.get.assert_not_called()
