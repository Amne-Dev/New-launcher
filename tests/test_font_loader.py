"""
tests/test_font_loader.py - Test suite for font registration and Minecraft font bundling.
"""

from pathlib import Path
from nlc.ui.font_loader import register_application_fonts, get_minecraft_font_family
from nlc.ui.theme import FONT_FAMILY


def test_bundled_minecraft_font_files_exist():
    """Verify that Minecraft OFL font files and license exist in the repo."""
    font_dir = Path(__file__).resolve().parent.parent / "nlc" / "assets" / "fonts"
    assert (font_dir / "Minecraft.otf").exists(), "Minecraft.otf missing"
    assert (font_dir / "Minecraft-Bold.otf").exists(), "Minecraft-Bold.otf missing"
    assert (font_dir / "OFL.txt").exists(), "OFL.txt license missing"

    # Verify license mentions SIL Open Font License
    license_text = (font_dir / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in license_text


def test_font_registration():
    """Verify register_application_fonts returns successful registration and family name."""
    success, family = register_application_fonts()
    assert family == "Minecraft"
    assert FONT_FAMILY == "Minecraft"
    assert get_minecraft_font_family() == "Minecraft"
