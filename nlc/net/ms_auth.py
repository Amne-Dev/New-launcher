"""
nlc.net.ms_auth - Microsoft OAuth Device Code Flow with timeout policies
"""

import logging
import time
from typing import Any, Callable, Dict, Optional
from nlc.net.http import get_http_session, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

MSA_CLIENT_ID = "c36a9fb6-4f2a-41ff-90bd-ae7cc92031eb"
DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"

class MicrosoftDeviceAuth:
    """Manages Microsoft Device Code authentication flow with safe timeouts."""
    def __init__(self, client_id: str = MSA_CLIENT_ID):
        self.client_id = client_id

    def request_device_code(self, timeout=DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """Request user code and verification URI."""
        session = get_http_session()
        payload = {
            "client_id": self.client_id,
            "scope": "XboxLive.signin offline_access"
        }
        resp = session.post(DEVICE_CODE_URL, data=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def poll_token(
        self,
        device_code: str,
        interval: int = 5,
        expires_in: int = 900,
        cancel_event=None,
        on_status: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """Polls Microsoft token endpoint with exponential backoff on slow_down."""
        session = get_http_session()
        payload = {
            "grant_type": "device_code",
            "client_id": self.client_id,
            "device_code": device_code
        }

        deadline = time.monotonic() + expires_in

        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return {"error": "cancelled", "message": "Login was cancelled."}

            time.sleep(interval)

            if cancel_event is not None and cancel_event.is_set():
                return {"error": "cancelled", "message": "Login was cancelled."}

            try:
                resp = session.post(TOKEN_URL, data=payload, timeout=(5.0, 15.0))
                if resp.status_code == 200:
                    return resp.json()

                err_json = resp.json()
                err_code = err_json.get("error")

                if err_code == "authorization_pending":
                    continue
                elif err_code == "slow_down":
                    interval += 2
                elif err_code == "expired_token":
                    return {"error": "expired", "message": "The login code expired. Please try again."}
                else:
                    return {"error": err_code, "message": err_json.get("error_description", "Unknown error")}
            except Exception as e:
                logger.warning("Transient error during token polling: %s", e)

        return {"error": "timeout", "message": "Login timed out."}
