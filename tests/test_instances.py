"""
tests.test_instances - Comprehensive tests for instance directory linking,
asset synchronization, and modpack exporting (.mrpack and .zip).
"""

import json
import os
import shutil
import tempfile
import zipfile
import pytest

from nlc.core.instances import (
    is_directory_link,
    create_directory_link,
    remove_directory_link,
    link_shared_folder,
    sync_instance_assets,
    export_modpack_to_zip,
    export_modpack_to_mrpack,
)


@pytest.fixture
def temp_workspace():
    """Create temporary directories for instance and shared root."""
    with tempfile.TemporaryDirectory() as base:
        inst_dir = os.path.join(base, "instance")
        shared_root = os.path.join(base, ".minecraft")
        os.makedirs(inst_dir)
        os.makedirs(shared_root)
        yield inst_dir, shared_root


def test_directory_link_lifecycle(temp_workspace):
    """Test creating, detecting, and removing directory links."""
    inst_dir, shared_root = temp_workspace
    target_shared = os.path.join(shared_root, "resourcepacks")
    os.makedirs(target_shared, exist_ok=True)
    with open(os.path.join(target_shared, "pack.txt"), "w") as f:
        f.write("shared pack")

    link_path = os.path.join(inst_dir, "resourcepacks")
    assert not is_directory_link(link_path)

    # Create link
    created = create_directory_link(link_path, target_shared)
    assert created is True
    assert is_directory_link(link_path)
    assert os.path.exists(os.path.join(link_path, "pack.txt"))
    with open(os.path.join(link_path, "pack.txt")) as f:
        assert f.read() == "shared pack"

    # Remove link
    removed = remove_directory_link(link_path)
    assert removed is True
    assert not os.path.exists(link_path)
    # Shared source should still exist!
    assert os.path.exists(target_shared)
    assert os.path.exists(os.path.join(target_shared, "pack.txt"))


def test_link_shared_folder_migration(temp_workspace):
    """Test link_shared_folder migrates pre-existing local files into shared directory on link."""
    inst_dir, shared_root = temp_workspace
    inst_rp = os.path.join(inst_dir, "resourcepacks")
    os.makedirs(inst_rp, exist_ok=True)
    with open(os.path.join(inst_rp, "unique_pack.zip"), "w") as f:
        f.write("local content")

    shared_rp = os.path.join(shared_root, "resourcepacks")
    os.makedirs(shared_rp, exist_ok=True)

    # Enable linking: local file should be copied into shared, and inst_rp becomes link
    success = link_shared_folder(inst_dir, shared_root, "resourcepacks", enabled=True)
    assert success is True
    assert is_directory_link(inst_rp)
    assert os.path.exists(os.path.join(shared_rp, "unique_pack.zip"))

    # Disable linking: inst_rp link should be unlinked, converting to empty directory
    success = link_shared_folder(inst_dir, shared_root, "resourcepacks", enabled=False)
    assert success is True
    assert not is_directory_link(inst_rp)
    assert os.path.isdir(inst_rp)


def test_sync_instance_assets(temp_workspace):
    """Test sync_instance_assets honors setting toggles for resourcepacks, shaders, saves, configs."""
    inst_dir, shared_root = temp_workspace
    for folder in ("resourcepacks", "shaderpacks", "saves", "config"):
        os.makedirs(os.path.join(shared_root, folder), exist_ok=True)

    settings = {
        "share_resourcepacks": True,
        "share_shaderpacks": True,
        "share_worlds": False,
        "share_configs": False,
    }

    sync_instance_assets(inst_dir, shared_root, settings)

    assert is_directory_link(os.path.join(inst_dir, "resourcepacks"))
    assert is_directory_link(os.path.join(inst_dir, "shaderpacks"))
    assert not is_directory_link(os.path.join(inst_dir, "saves"))
    assert not is_directory_link(os.path.join(inst_dir, "config"))

    # Now enable worlds and configs
    settings["share_worlds"] = True
    settings["share_configs"] = True
    sync_instance_assets(inst_dir, shared_root, settings)

    assert is_directory_link(os.path.join(inst_dir, "saves"))
    assert is_directory_link(os.path.join(inst_dir, "config"))


def test_export_modpack_to_zip(temp_workspace):
    """Test exporting instance to a standard zip file."""
    inst_dir, _ = temp_workspace
    mods_dir = os.path.join(inst_dir, "mods")
    config_dir = os.path.join(inst_dir, "config")
    os.makedirs(mods_dir)
    os.makedirs(config_dir)

    with open(os.path.join(mods_dir, "testmod.jar"), "w") as f:
        f.write("jar binary mock")
    with open(os.path.join(config_dir, "mod.cfg"), "w") as f:
        f.write("option=true")

    out_zip = os.path.join(tempfile.gettempdir(), "test_export.zip")
    try:
        export_modpack_to_zip(inst_dir, out_zip)
        assert os.path.exists(out_zip)

        with zipfile.ZipFile(out_zip, "r") as z:
            names = z.namelist()
            assert "mods/testmod.jar" in names
            assert "config/mod.cfg" in names
            assert z.read("config/mod.cfg").decode("utf-8") == "option=true"
    finally:
        if os.path.exists(out_zip):
            os.remove(out_zip)


def test_export_modpack_to_mrpack(temp_workspace):
    """Test exporting instance to standard Modrinth .mrpack with index and overrides."""
    inst_dir, _ = temp_workspace
    mods_dir = os.path.join(inst_dir, "mods")
    config_dir = os.path.join(inst_dir, "config")
    os.makedirs(mods_dir)
    os.makedirs(config_dir)

    with open(os.path.join(mods_dir, "sodium.jar"), "w") as f:
        f.write("fake sodium jar")
    with open(os.path.join(config_dir, "sodium-options.json"), "w") as f:
        f.write('{"graphics": "fast"}')

    out_mrpack = os.path.join(tempfile.gettempdir(), "test_pack.mrpack")
    try:
        export_modpack_to_mrpack(
            modpack_dir=inst_dir,
            output_path=out_mrpack,
            modpack_name="Performance Pack",
            version_id="1.0.0",
            game_version="1.20.1",
            loader="Fabric"
        )
        assert os.path.exists(out_mrpack)

        with zipfile.ZipFile(out_mrpack, "r") as z:
            names = z.namelist()
            assert "modrinth.index.json" in names
            # Overrides bundling check
            assert "overrides/config/sodium-options.json" in names
            assert "overrides/mods/sodium.jar" in names

            index_content = json.loads(z.read("modrinth.index.json").decode("utf-8"))
            assert index_content["formatVersion"] == 1
            assert index_content["game"] == "minecraft"
            assert index_content["name"] == "Performance Pack"
            assert index_content["versionId"] == "1.0.0"
            assert index_content["dependencies"]["minecraft"] == "1.20.1"
            assert index_content["dependencies"]["fabric-loader"] == "latest"
    finally:
        if os.path.exists(out_mrpack):
            os.remove(out_mrpack)
