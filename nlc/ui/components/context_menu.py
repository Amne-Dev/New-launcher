"""
nlc.ui.components.context_menu - Unified Neo-styled right-click context menu system
Provides theme-synchronized, border-bounded, accessible context menus with icon and danger support.
"""

import sys
import tkinter as tk
from typing import Callable, Optional, List, Dict, Any
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
    Renders with dark card backgrounds, subtle borders, Minecraft typography,
    smart boundary detection, and hover animations.
    """

    def __init__(self, parent_widget: tk.Widget, min_width: int = 160):
        self.parent = parent_widget
        self.min_width = min_width
        self.menu_win: Optional[tk.Toplevel] = None
        self.items: List[Dict[str, Any]] = []
        self._global_bind_id: Optional[str] = None

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
        """Render and display context menu at screen root coordinates."""
        dismiss_active_context_menu()
        global _ACTIVE_CONTEXT_MENU
        _ACTIVE_CONTEXT_MENU = self

        root = self.parent.winfo_toplevel()
        menu = tk.Toplevel(root)
        menu.overrideredirect(True)
        menu.transient(root)
        menu.attributes("-topmost", True)

        card_bg = COLORS.get("card_bg", "#242830")
        border_col = COLORS.get("border_subtle", "#2D3139")
        menu.config(bg=card_bg, highlightthickness=1, highlightbackground=border_col)
        self.menu_win = menu

        # Container frame
        container = tk.Frame(menu, bg=card_bg, padx=4, pady=4)
        container.pack(fill="both", expand=True)

        for entry in self.items:
            if entry["type"] == "separator":
                sep = tk.Frame(container, bg=COLORS.get("separator", "#282C36"), height=1)
                sep.pack(fill="x", padx=6, pady=4)
                continue

            self._create_menu_item_row(container, entry)

        # Measure size and position with boundary checking
        menu.update_idletasks()
        req_w = max(self.min_width, menu.winfo_reqwidth())
        req_h = menu.winfo_reqheight()

        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()

        pos_x = x_root
        pos_y = y_root

        # Flip horizontally if overflowing right edge
        if pos_x + req_w > screen_w - 8:
            pos_x = max(8, pos_x - req_w)

        # Flip vertically if overflowing bottom edge
        if pos_y + req_h > screen_h - 10:
            pos_y = max(10, pos_y - req_h)

        menu.geometry(f"{req_w}x{req_h}+{pos_x}+{pos_y}")
        menu.deiconify()
        menu.lift()
        menu.focus_set()

        # Keyboard and click-outside dismissal
        menu.bind("<Escape>", lambda e: self.dismiss())
        menu.bind("<FocusOut>", lambda e: self._on_focus_out())

        try:
            self._global_bind_id = root.bind_all("<Button-1>", self._on_global_click, add="+")
        except Exception:
            pass

    def show_at_widget(self, widget: tk.Widget, direction: str = "below") -> None:
        """Position menu relative to a button or trigger widget."""
        widget.update_idletasks()
        rx = widget.winfo_rootx()
        ry = widget.winfo_rooty()
        rw = widget.winfo_width()
        rh = widget.winfo_height()

        if direction == "below":
            self.post(rx, ry + rh + 2)
        else:
            self.post(rx, ry - 2)

    def show_at(self, x_root: int, y_root: int) -> None:
        """Display context menu at screen root coordinates (convenience alias for post)."""
        self.post(x_root, y_root)

    def show_below(self, widget: tk.Widget) -> None:
        """Display context menu directly below widget (convenience alias for show_at_widget)."""
        self.show_at_widget(widget, direction="below")

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

        # Hover states
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

    def _on_focus_out(self) -> None:
        if self.menu_win and self.menu_win.winfo_exists():
            self.menu_win.after(120, self._check_focus_close)

    def _check_focus_close(self) -> None:
        if not self.menu_win or not self.menu_win.winfo_exists():
            return
        try:
            focus = self.menu_win.focus_displayof()
            if focus and str(focus).startswith(str(self.menu_win)):
                return
            self.dismiss()
        except Exception:
            self.dismiss()

    def _on_global_click(self, event) -> None:
        if not self.menu_win or not self.menu_win.winfo_exists():
            return
        try:
            x, y = event.x_root, event.y_root
            mx = self.menu_win.winfo_rootx()
            my = self.menu_win.winfo_rooty()
            mw = self.menu_win.winfo_width()
            mh = self.menu_win.winfo_height()
            if not (mx <= x <= mx + mw and my <= y <= my + mh):
                self.dismiss()
        except Exception:
            self.dismiss()

    def dismiss(self) -> None:
        """Close the context menu and clean up bindings."""
        global _ACTIVE_CONTEXT_MENU
        if _ACTIVE_CONTEXT_MENU is self:
            _ACTIVE_CONTEXT_MENU = None

        if self.menu_win:
            try:
                if self.menu_win.winfo_exists():
                    self.menu_win.destroy()
            except Exception:
                pass
            self.menu_win = None


def attach_context_menu(
    widget: tk.Widget,
    menu_builder: Callable[[], NeoContextMenu],
    include_children: bool = True
) -> None:
    """
    Bind right-click (<Button-3> on Win/Linux, <Button-2> on Mac) on widget
    and optionally all its child widgets to display the built NeoContextMenu.
    """
    def on_right_click(event):
        try:
            menu = menu_builder()
            if menu and menu.items:
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


def attach_entry_context_menu(widget: tk.Widget) -> None:
    """Attach standard Cut, Copy, Paste, Select All context menu to an Entry or Text widget."""
    def build_menu() -> NeoContextMenu:
        menu = NeoContextMenu(widget, min_width=130)

        def do_cut():
            widget.event_generate("<<Cut>>")

        def do_copy():
            widget.event_generate("<<Copy>>")

        def do_paste():
            widget.event_generate("<<Paste>>")

        def do_select_all():
            if isinstance(widget, tk.Entry):
                widget.selection_range(0, tk.END)
            elif isinstance(widget, tk.Text):
                widget.tag_add(tk.SEL, "1.0", tk.END)

        menu.add_item("Cut", do_cut, icon="✂", accelerator="Ctrl+X")
        menu.add_item("Copy", do_copy, icon="⧉", accelerator="Ctrl+C")
        menu.add_item("Paste", do_paste, icon="📋", accelerator="Ctrl+V")
        menu.add_separator()
        menu.add_item("Select All", do_select_all, accelerator="Ctrl+A")
        return menu

    attach_context_menu(widget, build_menu, include_children=False)
