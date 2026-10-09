import os
import sys
import pytest
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils import resource_path, get_minecraft_dir, is_version_installed

def test_resource_path_finds_existing_asset():
    logo_path = resource_path("logo.png")
    assert os.path.exists(logo_path)
    assert os.path.basename(logo_path) == "logo.png"

def test_resource_path_nonexistent_returns_absolute_path():
    p = resource_path("nonexistent_test_asset.xyz")
    assert os.path.isabs(p)
    assert p.endswith("nonexistent_test_asset.xyz")

def test_get_minecraft_dir():
    mc_dir = get_minecraft_dir()
    assert mc_dir
    assert os.path.isabs(mc_dir)
    assert ".minecraft" in mc_dir

def test_is_version_installed_returns_bool():
    res = is_version_installed("nonexistent_version_12345")
    assert res is False
