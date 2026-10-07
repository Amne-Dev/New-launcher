import os
import sys
import pytest
from pathlib import Path
import tkinter as tk

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nlc.ui.screens.installations import InstallationsScreenMixin


class DummyHost(InstallationsScreenMixin):
    def __init__(self):
        self.icon_cache = {}


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_get_icon_image_with_prefix(tk_root):
    host = DummyHost()
    img = host.get_icon_image("icons/grass_block_side.png", (32, 32))
    assert img is not None
    assert img.width() == 32
    assert img.height() == 32


def test_get_icon_image_without_prefix(tk_root):
    host = DummyHost()
    img = host.get_icon_image("crafting_table_front.png", (40, 40))
    assert img is not None
    assert img.width() == 40
    assert img.height() == 40


def test_get_icon_image_without_extension(tk_root):
    host = DummyHost()
    img = host.get_icon_image("shulker_box", (20, 20))
    assert img is not None
    assert img.width() == 20
    assert img.height() == 20


def test_get_icon_image_caching(tk_root):
    host = DummyHost()
    key = ("icons/grass_block_side.png", (40, 40))
    assert key not in host.icon_cache
    img1 = host.get_icon_image("icons/grass_block_side.png", (40, 40))
    assert key in host.icon_cache
    img2 = host.get_icon_image("icons/grass_block_side.png", (40, 40))
    assert img1 is img2


def test_get_icon_image_nonexistent_returns_none(tk_root):
    host = DummyHost()
    img = host.get_icon_image("totally_nonexistent_block_12345.png")
    assert img is None
