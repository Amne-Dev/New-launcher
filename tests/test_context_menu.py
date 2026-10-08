import os
import sys
import tkinter as tk
import pytest
from unittest.mock import MagicMock

from nlc.storage.paths import open_path_in_system
from nlc.ui.components.context_menu import (
    NeoContextMenu,
    attach_context_menu,
    attach_entry_context_menu,
    dismiss_active_context_menu,
)


def test_open_path_in_system_linux(monkeypatch, tmp_path):
    test_dir = tmp_path / "test_folder"
    test_dir.mkdir()

    mock_popen = MagicMock()
    monkeypatch.setattr("subprocess.Popen", mock_popen)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("os.name", "posix")

    assert open_path_in_system(str(test_dir)) is True
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    assert args[0] == ["xdg-open", str(test_dir)]


def test_open_path_in_system_darwin(monkeypatch, tmp_path):
    test_dir = tmp_path / "test_mac_folder"
    test_dir.mkdir()

    mock_popen = MagicMock()
    monkeypatch.setattr("subprocess.Popen", mock_popen)
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("os.name", "posix")

    assert open_path_in_system(str(test_dir)) is True
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    assert args[0] == ["open", str(test_dir)]


def test_open_path_in_system_nonexistent(tmp_path):
    missing_dir = tmp_path / "missing_folder"
    assert open_path_in_system(str(missing_dir)) is False


def test_neo_context_menu_items(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    menu = NeoContextMenu(tk_root)
    called = []

    def action1():
        called.append(1)

    def action2():
        called.append(2)

    menu.add_item("📁 Open Folder", action1)
    menu.add_separator()
    menu.add_item("🗑 Delete", action2, is_danger=True)

    assert len(menu.items) == 3
    assert menu.items[0]["type"] == "item"
    assert menu.items[0]["label"] == "📁 Open Folder"
    assert menu.items[0]["is_danger"] is False

    assert menu.items[1]["type"] == "separator"

    assert menu.items[2]["type"] == "item"
    assert menu.items[2]["label"] == "🗑 Delete"
    assert menu.items[2]["is_danger"] is True

    menu.dismiss()


def test_neo_context_menu_show_and_dismiss(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    menu = NeoContextMenu(tk_root)
    menu.add_item("Action A", lambda: None)
    menu.add_item("Action B", lambda: None)

    # Show menu at specific position
    menu.show_at(100, 200)
    assert menu.menu_win is not None
    assert menu.menu_win.winfo_exists()

    # Verify dismiss
    menu.dismiss()
    assert menu.menu_win is None


def test_dismiss_active_context_menu(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    menu = NeoContextMenu(tk_root)
    menu.add_item("Action", lambda: None)
    menu.show_at(50, 50)

    # Global dismiss
    dismiss_active_context_menu()
    assert menu.menu_win is None


def test_attach_context_menu(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    frame = tk.Frame(tk_root)
    child = tk.Label(frame, text="Hello")
    child.pack()

    callback_called = []

    def on_right_click(event):
        callback_called.append(event)

    attach_context_menu(frame, on_right_click)

    # Check that bindings exist on both parent and child
    assert "<Button-3>" in frame.bind()
    assert "<Button-3>" in child.bind()


def test_attach_entry_context_menu(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    entry = tk.Entry(tk_root)
    entry.insert(0, "Test Value")

    attach_entry_context_menu(entry)
    assert "<Button-3>" in entry.bind()


def test_neo_context_menu_item_invocation(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    called = []
    menu = NeoContextMenu(tk_root)
    menu.add_item("Trigger Action", lambda: called.append("ok"))
    menu.show_at(100, 100)

    # Programmatically invoke item 0
    menu.invoke(0)

    assert called == ["ok"]
    assert menu.menu_win is None
