import json
import os
import sys
import subprocess
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nlc.storage.paths import resource_path


def test_agent_script_exists_and_runs():
    script = resource_path("agent.py")
    assert os.path.exists(script), f"agent.py not found at {script}"

    # Launch agent process
    proc = subprocess.Popen(
        [sys.executable, script, "/tmp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # Send a normalize addons request
        req = {
            "id": "test_req_1",
            "action": "addons_normalize",
            "payload": {"addons": {"streamer_mode_enabled": True}}
        }
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()

        assert proc.stdout is not None
        res = None
        for _ in range(5):
            line = proc.stdout.readline()
            if not line:
                break
            try:
                data = json.loads(line)
                if data.get("id") == "test_req_1":
                    res = data
                    break
            except json.JSONDecodeError:
                continue

        assert res is not None, "Expected JSON response from agent"
        assert res.get("id") == "test_req_1"
        result_data = res.get("result", {})
        assert result_data.get("status") == "success"
        assert result_data.get("data", {}).get("streamer_mode_enabled") is True
    finally:
        proc.terminate()
        proc.wait(timeout=2)
