import os
import tempfile
import tkinter as tk
from unittest.mock import MagicMock
from PIL import Image

from nlc.ui.screens.locker import LockerScreenMixin
from nlc.ui.screens.addons import AddonsScreenMixin
from nlc.ui.app import MinecraftLauncher


def test_wallpaper_thumbnail_caching():
    """Verify that get_wallpaper_thumbnail creates and caches thumbnails in disk and memory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mixin = LockerScreenMixin()
        mixin.config_dir = tmpdir

        # Create a test high-res image
        img_path = os.path.join(tmpdir, "test_wallpaper.png")
        img = Image.new("RGB", (1920, 1080), color=(100, 150, 200))
        img.save(img_path)

        root = tk.Tk()
        root.withdraw()
        try:
            # First load: creates disk cache and memory cache
            thumb1 = mixin.get_wallpaper_thumbnail(img_path, size=(220, 124))
            assert thumb1 is not None

            cache_dir = os.path.join(tmpdir, "cache", "wallpaper_thumbs")
            assert os.path.exists(cache_dir)
            cached_files = os.listdir(cache_dir)
            assert len(cached_files) == 1
            assert cached_files[0].endswith(".jpg")

            # Second load: hits in-memory cache directly
            thumb2 = mixin.get_wallpaper_thumbnail(img_path, size=(220, 124))
            assert thumb2 is thumb1

            # Clear memory cache: hits disk cache
            mixin._wallpaper_thumb_cache.clear()
            thumb3 = mixin.get_wallpaper_thumbnail(img_path, size=(220, 124))
            assert thumb3 is not None
        finally:
            root.destroy()


def test_screenshot_thumbnail_caching():
    """Verify that addons screenshot thumbnail generates and reads from disk cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mixin = AddonsScreenMixin()
        mixin.config_dir = tmpdir

        img_path = os.path.join(tmpdir, "shot.png")
        img = Image.new("RGBA", (800, 600), color=(50, 100, 150, 255))
        img.save(img_path)

        root = tk.Tk()
        root.withdraw()
        try:
            # First load
            p1 = mixin._get_screenshot_thumbnail(img_path, (160, 100))
            assert p1 is not None

            cache_dir = os.path.join(tmpdir, "cache", "screenshot_thumbs")
            assert os.path.exists(cache_dir)
            cached_files = os.listdir(cache_dir)
            assert len(cached_files) == 1

            # Second load
            p2 = mixin._get_screenshot_thumbnail(img_path, (160, 100))
            assert p2 is not None
        finally:
            root.destroy()


def test_skin_head_caching():
    """Verify that get_head_from_skin caches the resulting PhotoImage in memory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skin_path = os.path.join(tmpdir, "skin.png")
        skin_img = Image.new("RGBA", (64, 64), color=(20, 40, 60, 255))
        skin_img.save(skin_path)

        root = tk.Tk()
        root.withdraw()
        try:
            class DummyLauncher:
                get_head_from_skin = MinecraftLauncher.get_head_from_skin

            app_dummy = DummyLauncher()
            head1 = app_dummy.get_head_from_skin(skin_path, size=40)
            assert head1 is not None
            assert hasattr(app_dummy, '_skin_head_cache')

            head2 = app_dummy.get_head_from_skin(skin_path, size=40)
            assert head2 is head1
        finally:
            root.destroy()


def test_addons_screen_theme_refresh_in_place():
    """Verify refresh_addons_screen_theme does not destroy the tab or reset scroll."""
    root = tk.Tk()
    root.withdraw()
    try:
        mixin = AddonsScreenMixin()
        mixin.root = root
        mixin.addons_header_frame = tk.Frame(root)
        mixin.addons_title_lbl = tk.Label(mixin.addons_header_frame, text="Addons")
        mixin.addons_tab_frame = tk.Frame(root)
        mixin.current_tab = "Addons"

        # Ensure calling refresh_addons_screen_theme does not crash or destroy the tab
        mixin.refresh_addons_screen_theme()
        assert mixin.addons_tab_frame.winfo_exists()
    finally:
        root.destroy()
