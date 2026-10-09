"""
nlc.ui.components.modal - Universal in-app modal overlay manager.
Provides centered Neo-styled cards, translucent backdrop scrims,
synchronous dialog blocking via wait_variable, and custom modal layouts.
Replaces detached OS tk.Toplevel windows with native in-window overlays.
"""

import logging
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from nlc.ui.theme import COLORS, FONT_FAMILY, derive_hover_color
from nlc.ui.components.buttons import make_button

logger = logging.getLogger(__name__)

_GLOBAL_MODAL_MANAGER: Optional["InAppModalManager"] = None


def get_modal_manager(root: Optional[tk.Widget] = None) -> Optional["InAppModalManager"]:
    """Retrieve or register the active InAppModalManager for the application."""
    global _GLOBAL_MODAL_MANAGER
    if _GLOBAL_MODAL_MANAGER is not None:
        return _GLOBAL_MODAL_MANAGER
    if root is not None:
        top = root.winfo_toplevel()
        _GLOBAL_MODAL_MANAGER = InAppModalManager(top)
        return _GLOBAL_MODAL_MANAGER
    return None


def set_modal_manager(manager: "InAppModalManager") -> None:
    """Set the global InAppModalManager singleton."""
    global _GLOBAL_MODAL_MANAGER
    _GLOBAL_MODAL_MANAGER = manager


class InAppModalManager:
    """
    Manages in-window modal dialog overlays rendered over the main application root.
    All modals are strictly contained within the application's Tkinter window,
    eliminating Wayland (0,0) placement glitches, window desynchronization,
    and detached OS window chrome.
    """

    def __init__(self, root: tk.Widget):
        self.root = root.winfo_toplevel()
        self._active_modal: Optional[Dict[str, Any]] = None
        self._modal_stack: List[Dict[str, Any]] = []

    def is_modal_active(self) -> bool:
        """Check if any modal overlay is currently visible."""
        return self._active_modal is not None and self._active_modal.get("overlay_frame") is not None

    @property
    def has_open_modals(self) -> bool:
        """Check if any modal overlay is currently open."""
        return self.is_modal_active()

    def close_active_modal(self, result: Any = None) -> None:
        """Close the currently active modal overlay."""
        if self._active_modal and self._active_modal.get("close_func"):
            self._active_modal["close_func"](result)

    def handle_escape(self, event: Optional[Any] = None) -> None:
        """Dismiss the top dismissable modal if Escape is triggered."""
        if self._active_modal and self._active_modal.get("dismissable"):
            close_fn = self._active_modal.get("close_func")
            if close_fn:
                close_fn(None)



    def show_modal(
        self,
        title: str,
        content_builder: Callable[[tk.Widget, Callable[..., None]], None],
        width: int = 540,
        height: int = 380,
        dismissable: bool = True,
        on_close: Optional[Callable[[], None]] = None,
        header_accent: Optional[str] = None
    ) -> tk.Widget:
        """
        Display an in-app modal overlay with a dimmed backdrop scrim and centered Neo card.
        - content_builder: callback(body_frame, close_func) to populate the modal content.
        - dismissable: if True, Escape key and clicking the backdrop scrim close the modal.
        """
        # If another modal is active, push it onto stack
        if self._active_modal is not None:
            prev_card = self._active_modal.get("card_frame")
            if prev_card and prev_card.winfo_exists():
                try:
                    prev_card.grab_release()
                except Exception:
                    pass
                prev_card.place_forget()
            self._modal_stack.append(self._active_modal)

        # Centered Modal Card (no full-screen opaque blackout)
        card_bg = COLORS.get("card_bg", "#222630")
        border_col = header_accent or COLORS.get("accent_color", "#2ECC71")
        header_bg = COLORS.get("sidebar_bg", "#181A20")
        text_primary = COLORS.get("text_primary", "#FFFFFF")

        card = tk.Frame(
            self.root,
            bg=card_bg,
            highlightbackground=border_col,
            highlightthickness=2,
            padx=0,
            pady=0
        )

        modal_state: Dict[str, Any] = {
            "overlay_frame": card,
            "card_frame": card,
            "on_close": on_close,
            "dismissable": dismissable,
            "result": None,
            "closed": False,
        }
        self._active_modal = modal_state

        def close_action(result: Any = None):
            if modal_state.get("closed"):
                return
            modal_state["closed"] = True
            modal_state["result"] = result

            try:
                card.grab_release()
            except Exception:
                pass

            if modal_state.get("outside_bind"):
                try:
                    self.root.unbind("<Button-1>", modal_state["outside_bind"])
                except Exception:
                    pass

            if modal_state.get("configure_bind"):
                try:
                    self.root.unbind("<Configure>", modal_state["configure_bind"])
                except Exception:
                    pass

            try:
                self.root.unbind_all("<Escape>", modal_state.get("esc_bind"))
            except Exception:
                pass

            if modal_state.get("on_close"):
                try:
                    try:
                        modal_state["on_close"](result)
                    except TypeError:
                        modal_state["on_close"]()
                except Exception as ex:
                    logger.warning("Error in modal on_close callback: %s", ex)

            try:
                if card.winfo_exists():
                    card.place_forget()
                    card.destroy()
            except Exception:
                pass

            # Restore previous modal if one was stacked
            if self._modal_stack:
                self._active_modal = self._modal_stack.pop()
                prev_card = self._active_modal.get("card_frame")
                if prev_card and prev_card.winfo_exists():
                    prev_card.place(
                        x=self._active_modal.get("cx", 50),
                        y=self._active_modal.get("cy", 50),
                        width=self._active_modal.get("cw", width),
                        height=self._active_modal.get("ch", height)
                    )
                    prev_card.lift()
                    try:
                        prev_card.grab_set()
                    except Exception:
                        pass
            else:
                self._active_modal = None

        modal_state["close_func"] = close_action

        # Header Bar
        header = tk.Frame(card, bg=header_bg, height=52)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)

        title_lbl = tk.Label(
            header,
            text=title,
            font=(FONT_FAMILY, 13, "bold"),
            bg=header_bg,
            fg=text_primary
        )
        title_lbl.pack(side="left", padx=22, pady=12)

        if dismissable:
            close_btn = tk.Label(
                header,
                text="✕",
                font=(FONT_FAMILY, 12, "bold"),
                bg=header_bg,
                fg=COLORS.get("text_secondary", "#A0AAB0"),
                cursor="hand2",
                padx=10,
                pady=6
            )
            close_btn.pack(side="right", padx=12)

            def on_x_hover(e=None):
                close_btn.config(fg="#FFFFFF", bg=COLORS.get("error_red", "#EF4444"))

            def on_x_leave(e=None):
                close_btn.config(fg=COLORS.get("text_secondary", "#A0AAB0"), bg=header_bg)

            close_btn.bind("<Enter>", on_x_hover)
            close_btn.bind("<Leave>", on_x_leave)
            close_btn.bind("<Button-1>", lambda _e: close_action(None))

            def on_outside_click(event):
                if not card.winfo_exists():
                    return
                try:
                    cx = card.winfo_rootx()
                    cy = card.winfo_rooty()
                    cw = card.winfo_width()
                    ch = card.winfo_height()
                    if not (cx <= event.x_root <= cx + cw and cy <= event.y_root <= cy + ch):
                        close_action(None)
                except Exception:
                    pass

            click_id = self.root.bind("<Button-1>", on_outside_click, add="+")
            modal_state["outside_bind"] = click_id

            try:
                esc_id = self.root.bind_all("<Escape>", lambda _e: self.handle_escape(_e), add="+")
                modal_state["esc_bind"] = esc_id
            except Exception:
                pass

        # Modal Body
        body = tk.Frame(card, bg=card_bg, padx=22, pady=18)
        body.pack(fill="both", expand=True)

        # Populate custom content
        try:
            content_builder(body, close_action)
        except Exception as e:
            logger.exception("Failed to build modal content: %s", e)
            tk.Label(body, text=f"Error rendering dialog: {e}", fg="red", bg=card_bg).pack()

        # Center placement with resize repositioning
        def reposition(event=None):
            if not card.winfo_exists():
                return
            rw = max(300, self.root.winfo_width())
            rh = max(200, self.root.winfo_height())
            cw = min(width, rw - 40)
            ch = min(height, rh - 40)
            cx = (rw - cw) // 2
            cy = (rh - ch) // 2
            modal_state["cx"] = cx
            modal_state["cy"] = cy
            modal_state["cw"] = cw
            modal_state["ch"] = ch
            card.place(x=cx, y=cy, width=cw, height=ch)
            card.lift()

        cfg_id = self.root.bind("<Configure>", reposition, add="+")
        modal_state["configure_bind"] = cfg_id
        self.root.update_idletasks()
        reposition()

        try:
            card.grab_set()
        except Exception:
            pass

        try:
            card.focus_set()
        except Exception:
            pass

        return card

    def show_messagebox(
        self,
        title: str,
        message: str,
        type: str = "info",
        buttons: Optional[List[Tuple[str, Any, str]]] = None,
        width: int = 460,
        height: int = 240
    ) -> Any:
        """
        Synchronous in-app message box replacement for CustomMessagebox / tk.messagebox.
        Uses a localized wait_variable to block execution without locking the Tkinter event loop.
        Returns the clicked button value (True/False/Custom).
        """
        done_var = tk.BooleanVar(master=self.root, value=False)
        result_holder: List[Any] = [None]

        if buttons is None:
            if type == "yesno":
                buttons = [("Yes", True, "primary"), ("No", False, "secondary")]
            elif type == "error":
                buttons = [("Close", False, "secondary")]
            else:
                buttons = [("OK", True, "primary")]

        def build_content(body: tk.Widget, close_func: Callable[..., None]):
            card_bg = body.cget("bg")
            msg_lbl = tk.Label(
                body,
                text=message,
                bg=card_bg,
                fg=COLORS.get("text_primary", "#FFFFFF"),
                font=(FONT_FAMILY, 10),
                wraplength=width - 60,
                justify="center"
            )
            msg_lbl.pack(expand=True, fill="both", pady=(8, 16))

            btn_row = tk.Frame(body, bg=card_bg)
            btn_row.pack(side="bottom", fill="x")
            btn_inner = tk.Frame(btn_row, bg=card_bg)
            btn_inner.pack(anchor="center")

            for text, val, style in (buttons or []):
                def on_click(v=val):
                    result_holder[0] = v
                    close_func(v)
                    done_var.set(True)

                btn = make_button(btn_inner, text, style=style, font_size=10, command=on_click)
                btn.pack(side="left", padx=8)

        def on_modal_closed(res=None):
            if result_holder[0] is None and res is not None:
                result_holder[0] = res
            done_var.set(True)

        self.show_modal(
            title=title,
            content_builder=build_content,
            width=width,
            height=height,
            dismissable=True,
            on_close=on_modal_closed
        )

        # Synchronously wait for user action without freezing the UI event loop
        try:
            self.root.wait_variable(done_var)
        except Exception:
            pass

        return result_holder[0]
