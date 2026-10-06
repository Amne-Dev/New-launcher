"""
nlc.core.discord_rpc - Discord Rich Presence integration with safe failure handling
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

DISCORD_CLIENT_ID = "1214227702581694474"

class DiscordRPCManager:
    """Manages Discord Rich Presence client safely in a worker thread."""
    def __init__(self, client_id: str = DISCORD_CLIENT_ID):
        self.client_id = client_id
        self.rpc = None
        self.connected = False
        self._lock = threading.Lock()

    def connect(self):
        """Connect to local Discord client."""
        def _connect():
            with self._lock:
                if self.connected:
                    return
                try:
                    from pypresence import Presence
                    self.rpc = Presence(self.client_id)
                    self.rpc.connect()
                    self.connected = True
                    logger.info("Discord Rich Presence connected.")
                except Exception as e:
                    logger.debug("Discord RPC unavailable: %s", e)
                    self.connected = False
                    self.rpc = None

        threading.Thread(target=_connect, daemon=True, name="nlc-rpc-connect").start()

    def update(self, state: str, details: str, start_time: Optional[float] = None):
        """Update presence details safely."""
        with self._lock:
            if not self.connected or not self.rpc:
                return

        def _update():
            with self._lock:
                if not self.connected or not self.rpc:
                    return
                try:
                    kwargs = {
                        "state": state,
                        "details": details,
                        "large_image": "logo",
                        "large_text": "New Launcher",
                    }
                    if start_time:
                        kwargs["start"] = int(start_time)
                    self.rpc.update(**kwargs)
                except Exception as e:
                    logger.debug("Failed to update Discord presence: %s", e)

        threading.Thread(target=_update, daemon=True, name="nlc-rpc-update").start()

    def close(self):
        """Disconnect and clean up."""
        with self._lock:
            if not self.connected or not self.rpc:
                return
            try:
                self.rpc.close()
            except Exception:
                pass
            finally:
                self.rpc = None
                self.connected = False
                logger.info("Discord Rich Presence closed.")
