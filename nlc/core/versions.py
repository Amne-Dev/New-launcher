"""
nlc.core.versions - Minecraft version querying and formatting
"""

import logging
from typing import Any, Dict, List, Optional
from nlc.storage.paths import is_version_installed
from nlc.net.http import get_http_session

logger = logging.getLogger(__name__)

INSTALL_MARK = "✅ "
VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"

def format_version_display(version_id: str) -> str:
    """Prepends installation mark if version is locally downloaded."""
    return f"{INSTALL_MARK}{version_id}" if is_version_installed(version_id) else version_id

def normalize_version_text(value: Optional[str]) -> str:
    """Strips installation mark and whitespace from version string."""
    if not value:
        return ""
    return value.replace(INSTALL_MARK, "").strip()

def fetch_version_manifest() -> List[Dict[str, Any]]:
    """Fetches official Mojang version manifest."""
    session = get_http_session()
    try:
        resp = session.get(VERSION_MANIFEST_URL, timeout=(5.0, 15.0))
        resp.raise_for_status()
        data = resp.json()
        return data.get("versions", [])
    except Exception as e:
        logger.error("Failed to fetch Minecraft version manifest: %s", e)
        return []
