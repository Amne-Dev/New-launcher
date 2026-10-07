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
