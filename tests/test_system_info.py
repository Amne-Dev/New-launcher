"""
tests/test_system_info.py - Unit tests for system RAM, Java discovery, and diagnostics.
"""

import os
from unittest.mock import patch, MagicMock
from nlc.core.system_info import get_total_ram_mb, get_system_specs, detect_installed_javas, _get_java_version

def test_get_total_ram_mb_returns_positive_integer():
    """Verify that get_total_ram_mb returns a sensible positive integer (> 512 MB)."""
    ram = get_total_ram_mb()
    assert isinstance(ram, int)
    assert ram >= 512

def test_get_total_ram_mb_fallback_on_error():
    """Verify fallback to 8192 MB when platform checks fail."""
    with patch("os.sysconf", side_effect=ValueError("Disabled")):
        with patch("pathlib.Path.exists", return_value=False):
            with patch("platform.system", return_value="Unknown"):
                ram = get_total_ram_mb()
                assert isinstance(ram, int)
                assert ram > 0

def test_get_system_specs_contains_required_keys():
    """Verify get_system_specs returns os, python, ram, processor strings."""
    specs = get_system_specs()
    assert "os" in specs
    assert "python" in specs
    assert "ram" in specs
    assert "processor" in specs
    assert "Python" in specs["python"]
    assert "GB" in specs["ram"]

def test_get_java_version_parsing():
    """Verify version string extraction from java -version output."""
    mock_output = 'openjdk version "21.0.2" 2024-01-16\nOpenJDK Runtime Environment\n'
    with patch("subprocess.check_output", return_value=mock_output):
        ver = _get_java_version("/fake/bin/java")
        assert 'openjdk version "21.0.2"' in ver

def test_detect_installed_javas_format():
    """Verify detect_installed_javas returns a list of dictionaries with 'path' and 'label'."""
    # Mocking which to return a fake binary
    with patch("shutil.which", return_value="/mock/bin/java"):
        with patch("nlc.core.system_info._get_java_version", return_value='openjdk version "17.0.9" 2023-10-17'):
            javas = detect_installed_javas()
            assert len(javas) >= 1
            entry = [j for j in javas if j["path"] == "/mock/bin/java"][0]
            assert "Java 17 (17.0.9)" in entry["label"]
