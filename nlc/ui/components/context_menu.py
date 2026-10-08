"""
nlc.ui.components.context_menu - Unified Neo-styled right-click context menu system
Provides theme-synchronized, border-bounded, accessible in-window context menus with icon and danger support.
"""

import sys
import tkinter as tk
from typing import Callable, Optional, List, Dict, Any, Union
from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.storage.paths import open_path_in_system

_ACTIVE_CONTEXT_MENU: Optional["NeoContextMenu"] = None


def dismiss_active_context_menu() -> None:
    """Dismiss any active context menu globally."""
    global _ACTIVE_CONTEXT_MENU
    if _ACTIVE_CONTEXT_MENU is not None:
        try:
            _ACTIVE_CONTEXT_MENU.dismiss()
        except Exception:
            pass
        _ACTIVE_CONTEXT_MENU = None


class NeoContextMenu:
    """
    Modern Neo design system context menu replacement for tk.Menu.
    Renders as an in-window overlay frame directly inside the application's root window,
    ensuring 100% immune positioning across Wayland, Hyprland, X11, and tiling WMs.
    """

    def __init__(self, parent_widget: tk.Widget, min_width: int = 160):
        self.parent = parent_widget
        self.min_width = min_width
        self.menu_frame: Optional[tk.Frame] = None
        self.items: List[Dict[str, Any]] = []
        self._global_click_id: Optional[str] = None

    @property
    def menu_win(self) -> Optional[tk.Widget]:
        """Backwards-compatibility property returning the active menu frame widget."""
        return self.menu_frame

    @menu_win.setter
    def menu_win(self, val: Optional[tk.Widget]) -> None:
        if isinstance(val, tk.Frame) or val is None:
            self.menu_frame = val

    def add_item(
        self,
        label: str,
        command: Optional[Callable[[], None]] = None,
        icon: str = "",
        is_danger: bool = False,
        disabled: bool = False,
        accelerator: str = ""
    ) -> "NeoContextMenu":
        """Add an action item to the context menu."""
        self.items.append({
            "type": "item",
            "label": label,
            "command": command,
            "icon": icon,
            "is_danger": is_danger,
            "disabled": disabled,
            "accelerator": accelerator
        })
        return self

    def add_separator(self) -> "NeoContextMenu":
        """Add a subtle separator line."""
        self.items.append({"type": "separator"})
        return self

    def post(self, x_root: int, y_root: int) -> None:
        """Render and display context menu at screen root coordinates (converted to in-window coords)."""
        dismiss_active_context_menu()
        global _ACTIVE_CONTEXT_MENU
        _ACTIVE_CONTEXT_MENU = self

        top_win = self.parent.winfo_toplevel()
        top_win.update_idletasks()
        win_w = top_win.winfo_width()
        win_h = top_win.winfo_height()

        card_bg = COLORS.get("card_bg", "#242830")
        border_col = COLORS.get("border_subtle", "#2D3139")

        frame = tk.Frame(
            top_win,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=border_col,
            padx=4,
            pady=4
        )
        self.menu_frame = frame

        for entry in self.items:
            if entry["type"] == "separator":
                sep = tk.Frame(frame, bg=COLORS.get("separator", "#282C36"), height=1)
                sep.pack(fill="x", padx=6, pady=4)
                continue
            self._create_menu_item_row(frame, entry)

        # Measure size
        frame.update_idletasks()
        req_w = max(self.min_width, frame.winfo_reqwidth())
        req_h = frame.winfo_reqheight()

        rel_x = x_root - top_win.winfo_rootx()
        rel_y = y_root - top_win.winfo_rooty()

        # Clamp within window boundaries
        if rel_x + req_w > win_w - 8:
            rel_x = max(8, win_w - req_w - 8)
        if rel_y + req_h > win_h - 8:
            rel_y = max(8, rel_y - req_h)

        frame.place(x=rel_x, y=rel_y, width=req_w, height=req_h)
        frame.lift()
        try:
            frame.focus_set()
        except Exception:
            pass

        # Global click-outside dismissal
        try:
            self._global_click_id = top_win.bind_all("<Button-1>", self._on_global_click, add="+")
        except Exception:
            pass

    def show_at_widget(self, widget: tk.Widget, direction: str = "below") -> None:
        """Position menu relative to a button or trigger widget in window coordinates."""
        dismiss_active_context_menu()
        global _ACTIVE_CONTEXT_MENU
        _ACTIVE_CONTEXT_MENU = self

        top_win = widget.winfo_toplevel()
        widget.update_idletasks()
        top_win.update_idletasks()

        win_w = top_win.winfo_width()
        win_h = top_win.winfo_height()

        card_bg = COLORS.get("card_bg", "#242830")
        border_col = COLORS.get("border_subtle", "#2D3139")

        frame = tk.Frame(
            top_win,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=border_col,
            padx=4,
            pady=4
        )
        self.menu_frame = frame

        for entry in self.items:
            if entry["type"] == "separator":
                sep = tk.Frame(frame, bg=COLORS.get("separator", "#282C36"), height=1)
                sep.pack(fill="x", padx=6, pady=4)
                continue
            self._create_menu_item_row(frame, entry)

        frame.update_idletasks()
        req_w = max(self.min_width, frame.winfo_reqwidth())
        req_h = frame.winfo_reqheight()

        rx = widget.winfo_rootx() - top_win.winfo_rootx()
        ry = widget.winfo_rooty() - top_win.winfo_rooty()
        rw = widget.winfo_width()
        rh = widget.winfo_height()

        # If trigger is near right edge of the window, align right edge of menu to button
        if rx + req_w > win_w - 20:
            target_x = max(8, rx + rw - req_w)
        else:
            target_x = rx

        if direction == "below":
            target_y = ry + rh + 2
            if target_y + req_h > win_h - 8:
                target_y = max(8, ry - req_h - 2)
        else:
            target_y = max(8, ry - req_h - 2)

        # Final bounds clamp
        if target_x + req_w > win_w - 8:
            target_x = max(8, win_w - req_w - 8)

        frame.place(x=target_x, y=target_y, width=req_w, height=req_h)
        frame.lift()
        try:
            frame.focus_set()
        except Exception:
            pass

        try:
            self._global_click_id = top_win.bind_all("<Button-1>", self._on_global_click, add="+")
        except Exception:
            pass

    def show_at(self, x_root: int, y_root: int) -> None:
        """Display context menu at screen root coordinates (convenience alias for post)."""
        self.post(x_root, y_root)

    def show_below(self, widget: tk.Widget) -> None:
        """Display context menu directly below widget (convenience alias for show_at_widget)."""
        self.show_at_widget(widget, direction="below")

    def focus_set(self) -> None:
        """Delegate focus_set to the underlying menu frame if active."""
        if self.menu_frame and self.menu_frame.winfo_exists():
            try:
                self.menu_frame.focus_set()
            except Exception:
                pass

    def invoke(self, index: int) -> None:
        """Programmatically invoke the menu item at index, dismissing the menu."""
        if 0 <= index < len(self.items):
            item = self.items[index]
            if item.get("type") == "item" and not item.get("disabled"):
                self.dismiss()
                cmd = item.get("command")
                if cmd:
                    cmd()

    def _create_menu_item_row(self, container: tk.Frame, entry: Dict[str, Any]) -> None:
        card_bg = COLORS.get("card_bg", "#242830")
        hover_bg = COLORS.get("hover_bg", "#3A3F4D")
        err_red = COLORS.get("error_red", "#EF4444")
        muted = COLORS.get("text_muted", "#6B7280")
        is_danger = entry["is_danger"]
        disabled = entry["disabled"]

        normal_fg = err_red if is_danger else COLORS.get("text_primary", "#FFFFFF")
        if disabled:
            normal_fg = muted

        row = tk.Frame(container, bg=card_bg, cursor="hand2" if not disabled else "arrow", padx=8, pady=4)
        row.pack(fill="x", pady=1)

        # Icon / Glyph
        icon_str = entry.get("icon", "")
        if icon_str:
            icon_lbl = tk.Label(
                row,
                text=icon_str,
                font=(FONT_FAMILY, 9),
                bg=card_bg,
                fg=normal_fg,
                cursor="hand2" if not disabled else "arrow"
            )
            icon_lbl.pack(side="left", padx=(0, 6))

        # Main Label
        lbl = tk.Label(
            row,
            text=entry["label"],
            font=(FONT_FAMILY, 9),
            bg=card_bg,
            fg=normal_fg,
            anchor="w",
            cursor="hand2" if not disabled else "arrow"
        )
        lbl.pack(side="left", fill="x", expand=True)

        # Accelerator (e.g. "Ctrl+C")
        acc_str = entry.get("accelerator", "")
        if acc_str:
            acc_lbl = tk.Label(
                row,
                text=acc_str,
                font=(FONT_FAMILY, 8),
                bg=card_bg,
                fg=muted,
                anchor="e"
            )
            acc_lbl.pack(side="right", padx=(10, 0))

        if disabled:
            return

        cmd = entry.get("command")

        def on_action(e=None):
            self.dismiss()
            if cmd:
                try:
                    cmd()
                except Exception as ex:
                    print(f"Error executing menu action: {ex}")

        def on_enter(e=None):
            bg = err_red if is_danger else hover_bg
            fg = "#FFFFFF" if is_danger else COLORS.get("text_primary", "#FFFFFF")
            row.config(bg=bg)
            for child in row.winfo_children():
                if isinstance(child, tk.Label):
                    child.config(bg=bg, fg=fg)

        def on_leave(e=None):
            row.config(bg=card_bg)
            for child in row.winfo_children():
                if isinstance(child, tk.Label):
                    child.config(bg=card_bg, fg=normal_fg)

        row.bind("<Enter>", on_enter)
        row.bind("<Leave>", on_leave)
        row.bind("<Button-1>", on_action)
        for child in row.winfo_children():
            child.bind("<Button-1>", on_action)

    def _on_global_click(self, event) -> None:
        if not self.menu_frame or not self.menu_frame.winfo_exists():
            return
        try:
            x, y = event.x_root, event.y_root
            mx = self.menu_frame.winfo_rootx()
            my = self.menu_frame.winfo_rooty()
            mw = self.menu_frame.winfo_width()
            mh = self.menu_frame.winfo_height()
            if not (mx <= x <= mx + mw and my <= y <= my + mh):
                self.dismiss()
        except Exception:
            self.dismiss()

    def dismiss(self) -> None:
        """Close the context menu and clean up bindings."""
        global _ACTIVE_CONTEXT_MENU
        if _ACTIVE_CONTEXT_MENU is self:
            _ACTIVE_CONTEXT_MENU = None

        if self.menu_frame:
            try:
                if self.menu_frame.winfo_exists():
                    self.menu_frame.place_forget()
                    self.menu_frame.destroy()
            except Exception:
                pass
            self.menu_frame = None


def attach_context_menu(
    widget: tk.Widget,
    menu_builder: Any,
    include_children: bool = True
) -> None:
    """
    Bind right-click (<Button-3> on Win/Linux, <Button-2> on Mac) on widget
    and optionally all its child widgets to display the built NeoContextMenu.
    """
    def on_right_click(event):
        try:
            if isinstance(menu_builder, NeoContextMenu):
                menu = menu_builder
            elif callable(menu_builder):
                try:
                    menu = menu_builder(event)
                except TypeError:
                    menu = menu_builder()
            else:
                menu = None

            if isinstance(menu, NeoContextMenu) and menu.items:
                menu.post(event.x_root, event.y_root)
            return "break"
        except Exception as e:
            print(f"Error showing context menu: {e}")

    buttons = ["<Button-3>"]
    if sys.platform == "darwin":
        buttons.extend(["<Button-2>", "<Control-Button-1>"])

    def _bind_tree(w: tk.Widget):
        for btn in buttons:
            w.bind(btn, on_right_click, add="+")
        if include_children:
            for child in w.winfo_children():
                _bind_tree(child)

    _bind_tree(widget)


def attach_entry_context_menu(entry_widget: tk.Widget) -> None:
    """
    Attach standard text manipulation context menu (Cut, Copy, Paste, Select All)
    to a tk.Entry, ttk.Entry, or tk.Text/ScrolledText widget.
    """
    def build_entry_menu():
        menu = NeoContextMenu(entry_widget, min_width=130)

        def cut_action():
            try:
                entry_widget.event_generate("<<Cut>>")
            except Exception:
                pass

        def copy_action():
            try:
                entry_widget.event_generate("<<Copy>>")
            except Exception:
                pass

        def paste_action():
            try:
                entry_widget.event_generate("<<Paste>>")
            except Exception:
                pass

        def select_all_action():
            try:
                if isinstance(entry_widget, (tk.Text,)):
                    entry_widget.tag_add("sel", "1.0", "end")
                elif hasattr(entry_widget, "select_range"):
                    entry_widget.select_range(0, "end")
                    entry_widget.icursor("end")
            except Exception:
                pass

        menu.add_item("Cut", cut_action, icon="✂", accelerator="Ctrl+X")
        menu.add_item("Copy", copy_action, icon="📋", accelerator="Ctrl+C")
        menu.add_item("Paste", paste_action, icon="📥", accelerator="Ctrl+V")
        menu.add_separator()
        menu.add_item("Select All", select_all_action, accelerator="Ctrl+A")
        return menu

    attach_context_menu(entry_widget, build_entry_menu, include_children=False)
