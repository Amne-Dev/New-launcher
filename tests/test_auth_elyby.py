import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from auth import ElyByAuth

def test_elyby_missing_credentials():
    res = ElyByAuth.authenticate("", "")
    assert "error" in res
    assert "Username and password are required" in res["error"]

def test_elyby_invalid_credentials_returns_error(monkeypatch):
    # Mock urllib response with 401 error
    import urllib.error
    import io

    def fake_urlopen(*args, **kwargs):
        fp = io.BytesIO(b'{"error": "ForbiddenOperationException", "errorMessage": "Invalid credentials."}')
        raise urllib.error.HTTPError("http://example.com", 401, "Unauthorized", {}, fp)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    res = ElyByAuth.authenticate("bad_user", "bad_pass")
    assert "error" in res
    assert "Invalid credentials" in res["error"]
