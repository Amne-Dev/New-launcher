import pytest
from nlc.net.http import get_http_session, DEFAULT_TIMEOUT

def test_shared_http_session_singleton():
    s1 = get_http_session()
    s2 = get_http_session()
    assert s1 is s2
    assert "User-Agent" in s1.headers
    assert "NLC-Launcher" in s1.headers["User-Agent"]

def test_shared_http_session_has_timeout_adapter():
    session = get_http_session()
    adapter = session.adapters["https://"]
    assert hasattr(adapter, "default_timeout")
    assert adapter.default_timeout == DEFAULT_TIMEOUT
