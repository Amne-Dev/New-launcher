"""
tests/test_settings_rows.py - Tests for SettingRow, ToggleSwitch, and SegmentedChips.
"""

import pytest
import tkinter as tk
from nlc.ui.components.settings_row import ToggleSwitch, create_setting_row, create_segmented_chips
from nlc.ui.animation import AnimationManager

def test_toggle_switch_state_and_command(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    var = tk.BooleanVar(value=False)
    command_called = False

    def on_cmd():
        nonlocal command_called
        command_called = True

    animator = AnimationManager(root=tk_root, enabled_provider=lambda: False)
    toggle = ToggleSwitch(tk_root, variable=var, command=on_cmd, animator=animator)

    assert var.get() is False

    # Simulate click
    toggle._on_click()
    assert var.get() is True
    assert command_called is True

    # Click again to turn off
    toggle._on_click()
    assert var.get() is False

    toggle.destroy()

def test_create_setting_row(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    parent = tk.Frame(tk_root)
    ctrl = tk.Button(parent, text="Click")
    row, ctrl_container = create_setting_row(
        parent,
        title="Test Setting",
        description="A helpful description of the test setting.",
        control_widget=ctrl
    )

    assert row is not None
    assert ctrl_container is not None
    # Verify children
    children = row.winfo_children()
    assert len(children) >= 2  # text frame and ctrl container

    parent.destroy()

def test_create_segmented_chips(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    parent = tk.Frame(tk_root)
    var = tk.IntVar(value=4096)
    last_val = None

    def on_change(v):
        nonlocal last_val
        last_val = v

    options = [("2 GB", 2048), ("4 GB", 4096), ("8 GB", 8192)]
    chips = create_segmented_chips(parent, options=options, variable=var, command=on_change)

    assert chips is not None
    assert var.get() == 4096

    # Select 8 GB (third button)
    buttons = [w for w in chips.winfo_children() if isinstance(w, tk.Button)]
    assert len(buttons) == 3

    # Invoke 8 GB button
    buttons[2].invoke()
    assert var.get() == 8192
    assert last_val == 8192

    parent.destroy()


def test_create_setting_row_toggle_switch_visibility(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    parent = tk.Frame(tk_root, bg="#242830")
    parent.pack(fill="x")
    var = tk.BooleanVar(value=True)
    toggle = ToggleSwitch(parent, variable=var)
    row, ctrl_container = create_setting_row(
        parent,
        title="Enable Micro-Animations (60 FPS)",
        description="Enables smooth transitions and micro-animations throughout the UI.",
        control_widget=toggle
    )
    tk_root.update()

    assert toggle.winfo_manager() == "pack"
    assert toggle.winfo_reqwidth() == 44
    assert toggle.winfo_reqheight() == 24
    assert ctrl_container.winfo_manager() == "pack"

    parent.destroy()

