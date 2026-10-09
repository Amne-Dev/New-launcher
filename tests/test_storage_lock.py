import pytest
from pathlib import Path
from nlc.storage.lock import SingleInstanceLock

def test_single_instance_lock_lifecycle(tmp_path):
    lock_file = tmp_path / "test.lock"
    lock1 = SingleInstanceLock(lock_file)
    assert lock1.acquire() is True

    # Attempting to acquire again from another instance should fail
    lock2 = SingleInstanceLock(lock_file)
    assert lock2.acquire() is False

    # After lock1 releases, lock2 should succeed
    lock1.release()
    assert lock2.acquire() is True
    lock2.release()

def test_single_instance_context_manager(tmp_path):
    lock_file = tmp_path / "test_ctx.lock"
    with SingleInstanceLock(lock_file):
        assert lock_file.exists()
        # Second acquire in context fails
        lock2 = SingleInstanceLock(lock_file)
        assert lock2.acquire() is False

    # Out of context, acquire succeeds
    lock3 = SingleInstanceLock(lock_file)
    assert lock3.acquire() is True
    lock3.release()
