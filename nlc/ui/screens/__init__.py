"""
nlc.ui.screens - Screen mixins for the Minecraft launcher UI
"""

from nlc.ui.screens.accounts import AccountsScreenMixin
from nlc.ui.screens.settings import SettingsScreenMixin
from nlc.ui.screens.addons import AddonsScreenMixin
from nlc.ui.screens.modpacks import ModpacksScreenMixin
from nlc.ui.screens.mods import ModsScreenMixin
from nlc.ui.screens.locker import LockerScreenMixin
from nlc.ui.screens.installations import InstallationsScreenMixin
from nlc.ui.screens.play import PlayScreenMixin

__all__ = [
    "AccountsScreenMixin",
    "SettingsScreenMixin",
    "AddonsScreenMixin",
    "ModpacksScreenMixin",
    "ModsScreenMixin",
    "LockerScreenMixin",
    "InstallationsScreenMixin",
    "PlayScreenMixin",
]
