import pytest
from nlc.core.versions import format_version_display, normalize_version_text, INSTALL_MARK
from nlc.core.launch import _get_lib_name_without_version, safe_inherit_json

def test_normalize_version_text():
    raw = f"{INSTALL_MARK}1.20.4"
    assert normalize_version_text(raw) == "1.20.4"
    assert normalize_version_text("1.19.2") == "1.19.2"
    assert normalize_version_text("") == ""
    assert normalize_version_text(None) == ""

def test_get_lib_name_without_version():
    lib = {"name": "org.lwjgl:lwjgl:3.3.1"}
    assert _get_lib_name_without_version(lib) == "org.lwjgl:lwjgl"

def test_format_version_display():
    res = format_version_display("nonexistent_test_version_xyz")
    assert res == "nonexistent_test_version_xyz"
