"""
tests/test_skin_renderer_3d.py - Comprehensive tests for 3D skin & cape renderer,
drag rotation, walk cycle harmonics, and Mojang cape studio integration.
"""

import os
import json
import math
import pytest
from PIL import Image
from unittest.mock import MagicMock, patch

from nlc.ui.components.skin_renderer import SkinRenderer3D, Model3DRenderer
from nlc.net.capes import fetch_account_capes, download_and_cache_cape, set_active_mojang_cape, clear_active_mojang_cape
from nlc.ui.app import MinecraftLauncher


@pytest.fixture
def dummy_skin_path(tmp_path):
    skin_path = tmp_path / "test_skin_64x64.png"
    img = Image.new("RGBA", (64, 64), color=(50, 100, 150, 255))
    img.save(skin_path)
    return str(skin_path)


@pytest.fixture
def dummy_cape_path(tmp_path):
    cape_path = tmp_path / "test_cape_64x32.png"
    img = Image.new("RGBA", (64, 32), color=(200, 50, 50, 255))
    img.save(cape_path)
    return str(cape_path)


def test_skin_renderer_3d_rotations(dummy_skin_path):
    """Test 3D rendering produces valid RGBA images across full 360 yaw rotation."""
    for yaw in [0.0, 45.0, 90.0, 180.0, 270.0, 360.0]:
        img = SkinRenderer3D.render_frame(
            skin_path=dummy_skin_path,
            yaw_deg=yaw,
            pitch_deg=10.0,
            walk_phase=0.0,
            width=280,
            height=340,
            model="classic"
        )
        assert img is not None
        assert isinstance(img, Image.Image)
        assert img.size == (280, 340)
        assert img.mode == "RGBA"


def test_skin_renderer_3d_walk_cycle(dummy_skin_path):
    """Test walk cycle renders frames at different phases without crash."""
    for phase in [0.0, math.pi / 2, math.pi, math.pi * 1.5, math.pi * 2]:
        img = SkinRenderer3D.render_frame(
            skin_path=dummy_skin_path,
            yaw_deg=30.0,
            pitch_deg=10.0,
            walk_phase=phase,
            width=280,
            height=340,
            model="classic"
        )
        assert img is not None
        assert img.size == (280, 340)


def test_skin_renderer_3d_with_cape(dummy_skin_path, dummy_cape_path):
    """Test rendering model with an attached cape fluttering in stride."""
    img_without_cape = SkinRenderer3D.render_frame(
        skin_path=dummy_skin_path,
        cape_path=None,
        yaw_deg=180.0,  # Look at player's back
        pitch_deg=10.0,
        walk_phase=1.0,
        width=280,
        height=340,
        model="classic"
    )
    img_with_cape = SkinRenderer3D.render_frame(
        skin_path=dummy_skin_path,
        cape_path=dummy_cape_path,
        yaw_deg=180.0,
        pitch_deg=10.0,
        walk_phase=1.0,
        width=280,
        height=340,
        model="classic"
    )
    assert img_without_cape is not None
    assert img_with_cape is not None
    # Cape rendering should produce different pixel values on the back
    assert img_without_cape.tobytes() != img_with_cape.tobytes()


def test_skin_renderer_slim_alex_model(dummy_skin_path):
    """Test slim 3-pixel arm geometry renders cleanly."""
    img = SkinRenderer3D.render_frame(
        skin_path=dummy_skin_path,
        yaw_deg=30.0,
        pitch_deg=10.0,
        walk_phase=0.0,
        width=280,
        height=340,
        model="slim"
    )
    assert img is not None
    assert img.size == (280, 340)


def test_capes_api_fetch_and_cache(tmp_path):
    """Test Mojang capes retrieval parsing and local caching."""
    mock_profile_resp = MagicMock()
    mock_profile_resp.status_code = 200
    mock_profile_resp.json.return_value = {
        "id": "12345678-abcd-ef01-2345-6789abcdef01",
        "name": "ev_s",
        "capes": [
            {
                "id": "cape-aurora-id",
                "state": "ACTIVE",
                "url": "http://example.com/aurora.png",
                "alias": "Aurora"
            },
            {
                "id": "cape-pan-id",
                "state": "INACTIVE",
                "url": "http://example.com/pan.png",
                "alias": "Pan"
            }
        ]
    }

    with patch("requests.get", return_value=mock_profile_resp):
        capes = fetch_account_capes("mock_token")
        assert len(capes) == 2
        assert capes[0]["alias"] == "Aurora"
        assert capes[0]["state"] == "ACTIVE"
        assert capes[1]["alias"] == "Pan"
        assert capes[1]["state"] == "INACTIVE"

    # Test downloading cape
    mock_img_resp = MagicMock()
    mock_img_resp.status_code = 200
    dummy_img = Image.new("RGBA", (64, 32), color=(10, 20, 30, 255))
    import io
    buf = io.BytesIO()
    dummy_img.save(buf, format="PNG")
    mock_img_resp.content = buf.getvalue()

    with patch("requests.get", return_value=mock_img_resp):
        with patch("nlc.net.capes.get_launcher_data_dir", return_value=str(tmp_path)):
            cached_path = download_and_cache_cape("http://example.com/aurora.png", "Aurora")
            assert os.path.exists(cached_path)
            assert os.path.basename(cached_path) == "aurora.png"


def test_capes_equip_and_unequip():
    """Test Mojang cape PUT and DELETE endpoints."""
    mock_put_resp = MagicMock()
    mock_put_resp.status_code = 200

    with patch("requests.put", return_value=mock_put_resp) as mock_put:
        success = set_active_mojang_cape("mock_token", "cape-aurora-id")
        assert success is True
        mock_put.assert_called_once()
        assert "cape-aurora-id" in mock_put.call_args[1]["json"]["capeId"]

    mock_del_resp = MagicMock()
    mock_del_resp.status_code = 200

    with patch("requests.delete", return_value=mock_del_resp) as mock_del:
        success = clear_active_mojang_cape("mock_token")
        assert success is True
        mock_del.assert_called_once()


def test_has_owned_capes_filtering(tk_root, tmp_path, monkeypatch):
    """Test capes sub-tab is shown ONLY for Microsoft accounts with >= 1 capes."""
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

    # 1. Offline account -> has_owned_capes must be False
    app.profiles = [{"name": "OfflineUser", "type": "offline"}]
    app.current_profile_index = 0
    app.account_capes = [{"alias": "Aurora"}]  # even if capes list has items
    assert app.has_owned_capes() is False

    # 2. Ely.by account -> has_owned_capes must be False
    app.profiles = [{"name": "ElybyUser", "type": "ely.by"}]
    app.current_profile_index = 0
    app.account_capes = [{"alias": "Aurora"}]
    assert app.has_owned_capes() is False

    # 3. Microsoft account with 0 capes -> has_owned_capes must be False
    app.profiles = [{"name": "MSUserNoCapes", "type": "microsoft", "access_token": "tok"}]
    app.current_profile_index = 0
    app.account_capes = []
    assert app.has_owned_capes() is False

    # 4. Microsoft account with >= 1 capes -> has_owned_capes must be True
    app.profiles = [{"name": "MSUserWithCapes", "type": "microsoft", "access_token": "tok"}]
    app.current_profile_index = 0
    app.account_capes = [{"alias": "Aurora", "id": "1", "state": "ACTIVE"}]
    assert app.has_owned_capes() is True

    # Check update_locker_subtabs
    app.show_tab("Locker")
    assert "Capes" in app.locker_btns

    # Switch to offline account -> Capes button should vanish
    app.profiles = [{"name": "OfflineUser", "type": "offline"}]
    app.update_locker_subtabs()
    assert "Capes" not in app.locker_btns
