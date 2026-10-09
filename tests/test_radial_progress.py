"""
tests/test_radial_progress.py - Tests for pure Tkinter radial progress ring widget.
"""

import pytest
import tkinter as tk
from nlc.ui.components.radial_progress import RadialProgress


def test_radial_progress_init(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    rp = RadialProgress(tk_root, size=44, line_width=3)
    assert rp.winfo_exists()
    assert rp.progress == 0.0
    assert rp.status == "normal"


def test_radial_progress_set_progress(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    rp = RadialProgress(tk_root, size=44, line_width=3)
    rp.set_progress(50.0)
    assert rp.progress == 50.0

    rp.set_progress(120.0)  # should clamp to 100.0
    assert rp.progress == 100.0

    rp.set_progress(-10.0)  # should clamp to 0.0
    assert rp.progress == 0.0


def test_radial_progress_states(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    rp = RadialProgress(tk_root, size=44, line_width=3)

    # Success state
    rp.set_success()
    assert rp.status == "success"
    assert rp.progress == 100.0

    # Error state
    rp.set_error()
    assert rp.status == "error"

    # Indeterminate state
    rp.set_indeterminate(True)
    assert rp.status == "indeterminate"
    rp.set_indeterminate(False)
    assert rp.status != "indeterminate"
