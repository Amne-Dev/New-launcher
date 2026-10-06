import json
import pytest
from pathlib import Path
from nlc.storage.config import ConfigManager, get_default_config

def test_config_manager_creates_default_on_missing_file(tmp_path):
    cfg_file = tmp_path / "launcher_config.json"
    mgr = ConfigManager(cfg_file)
    data = mgr.load()

    assert cfg_file.exists()
    assert "profiles" in data
    assert "installations" in data
    assert len(data["profiles"]) > 0

def test_config_manager_atomic_save_and_backup(tmp_path):
    cfg_file = tmp_path / "launcher_config.json"
    mgr = ConfigManager(cfg_file)
    data = mgr.load()

    data["ram"] = 8192
    success = mgr.save(data)
    assert success is True

    # Reload and verify
    reloaded = mgr.load()
    assert reloaded["ram"] == 8192

    # Save again to verify .bak creation
    data["ram"] = 12288
    mgr.save(data)
    bak_file = tmp_path / "launcher_config.json.bak"
    assert bak_file.exists()

    with open(bak_file, "r") as f:
        bak_data = json.load(f)
    assert bak_data["ram"] == 8192

def test_config_manager_recovers_from_corrupt_file_using_backup(tmp_path):
    cfg_file = tmp_path / "launcher_config.json"
    mgr = ConfigManager(cfg_file)
    data = mgr.load()

    # Modify and save twice to establish backup
    data["profiles"][0]["name"] = "SavedProfile"
    mgr.save(data)
    data["ram"] = 6144
    mgr.save(data)

    # Now corrupt main config file
    cfg_file.write_text("{corrupt: json truncated...", encoding="utf-8")

    # Load should fallback to .bak
    recovered = mgr.load()
    assert recovered is not None
    assert recovered["profiles"][0]["name"] == "SavedProfile"
    assert (tmp_path / "launcher_config.json.corrupt").exists()
