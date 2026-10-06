import hashlib
import http.server
import os
import socketserver
import sys
import threading
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from alt import _atomic_download

@pytest.fixture
def fake_http_server(tmp_path):
    # Setup test file
    payload = b"MinecraftLauncherDownloadTestData12345"
    sha1 = hashlib.sha1(payload).hexdigest()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            if self.path == "/testfile.bin":
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_error(404)

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}", payload, sha1

    server.shutdown()
    server.server_close()

def test_atomic_download_success(fake_http_server, tmp_path):
    base_url, payload, sha1 = fake_http_server
    dest = tmp_path / "downloaded.bin"

    result = _atomic_download(f"{base_url}/testfile.bin", str(dest), expected_sha1=sha1)
    assert os.path.exists(result)
    assert dest.read_bytes() == payload

def test_atomic_download_checksum_failure(fake_http_server, tmp_path):
    base_url, payload, _ = fake_http_server
    dest = tmp_path / "corrupt.bin"

    with pytest.raises(ValueError, match="checksum verification"):
        _atomic_download(f"{base_url}/testfile.bin", str(dest), expected_sha1="0000000000000000000000000000000000000000")

    # Ensure corrupt file was removed
    assert not dest.exists()
