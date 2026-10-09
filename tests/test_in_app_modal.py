"""
tests/test_in_app_modal.py - Tests for InAppModalManager and in-window modal dialogs.
"""

import tkinter as tk
import pytest
from nlc.ui.components.modal import (
    InAppModalManager,
    set_modal_manager,
    get_modal_manager,
)
from nlc.ui.components.dialogs import (
    custom_showinfo,
    custom_showwarning,
    custom_showerror,
    custom_askyesno,
)


def test_in_app_modal_manager_lifecycle(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    manager = InAppModalManager(tk_root)
    assert not manager.has_open_modals
    assert not manager.is_modal_active()

    close_fn_holder = []

    def builder(body, close):
        close_fn_holder.append(close)
        lbl = tk.Label(body, text="Hello Modal")
        lbl.pack()

    card = manager.show_modal("Test Modal", builder, width=300, height=200)
    assert manager.has_open_modals
    assert manager.is_modal_active()
    assert card.winfo_exists()

    close_fn_holder[0]()
    tk_root.update_idletasks()
    assert not manager.has_open_modals
    assert not manager.is_modal_active()


def test_modal_close_active_modal(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    manager = InAppModalManager(tk_root)

    def builder(body, close):
        tk.Label(body, text="Modal Content").pack()

    manager.show_modal("Dismiss Me", builder)
    assert manager.has_open_modals

    manager.close_active_modal("done")
    tk_root.update_idletasks()
    assert not manager.has_open_modals


def test_modal_escape_dismiss(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    manager = InAppModalManager(tk_root)

    def builder(body, close):
        tk.Label(body, text="Modal Content").pack()

    manager.show_modal("Dismiss Me", builder)
    assert manager.has_open_modals

    manager.handle_escape()
    tk_root.update_idletasks()
    assert not manager.has_open_modals


def test_modal_messagebox_info(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    manager = InAppModalManager(tk_root)

    # Schedule closing the modal via manager
    tk_root.after(30, lambda: manager.close_active_modal(True))
    res = manager.show_messagebox("Info Title", "Operation completed successfully.", type="info")
    assert res is True
    assert not manager.has_open_modals


def test_modal_messagebox_yesno(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    manager = InAppModalManager(tk_root)

    tk_root.after(30, lambda: manager.close_active_modal(True))
    res_yes = manager.show_messagebox("Confirm", "Do you want to continue?", type="yesno")
    assert res_yes is True

    tk_root.after(30, lambda: manager.close_active_modal(False))
    res_no = manager.show_messagebox("Confirm", "Do you want to continue?", type="yesno")
    assert res_no is False


def test_custom_dialog_helpers_use_modal_manager(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    manager = InAppModalManager(tk_root)
    set_modal_manager(manager)
    assert get_modal_manager(tk_root) is manager

    tk_root.after(30, lambda: manager.close_active_modal(True))
    info_res = custom_showinfo("Title", "Message", parent=tk_root)
    assert info_res is True

    tk_root.after(30, lambda: manager.close_active_modal(True))
    warn_res = custom_showwarning("Warning", "Caution advised", parent=tk_root)
    assert warn_res is True

    tk_root.after(30, lambda: manager.close_active_modal(False))
    err_res = custom_showerror("Error", "Something went wrong", parent=tk_root)
    assert err_res is False

    tk_root.after(30, lambda: manager.close_active_modal(True))
    yes_res = custom_askyesno("Confirm", "Are you sure?", parent=tk_root)
    assert yes_res is True


def test_stacked_modals(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    manager = InAppModalManager(tk_root)

    c1 = manager.show_modal("Modal 1", lambda b, c: tk.Label(b, text="1").pack())
    assert manager.has_open_modals
    assert len(manager._modal_stack) == 0

    c2 = manager.show_modal("Modal 2", lambda b, c: tk.Label(b, text="2").pack())
    assert manager.has_open_modals
    assert len(manager._modal_stack) == 1

    # Close top modal
    manager.close_active_modal()
    tk_root.update_idletasks()
    assert manager.has_open_modals
    assert len(manager._modal_stack) == 0

    # Close first modal
    manager.close_active_modal()
    tk_root.update_idletasks()
    assert not manager.has_open_modals
