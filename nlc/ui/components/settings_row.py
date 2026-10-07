"""
nlc.ui.components.settings_row - Standardized Settings Row and modern tactile controls.
Provides SettingRow layout, animated ToggleSwitch, and SegmentedChips components.
"""

import tkinter as tk
from typing import Callable, Optional, List, Tuple, Any
from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.animation import AnimationManager

class ToggleSwitch(tk.Canvas):
    """
    Tactile modern pill toggle switch.
    Smoothly animates thumb position and background color on toggle.
    """
    def __init__(
        self,
        parent: tk.Widget,
        variable: tk.BooleanVar,
        command: Optional[Callable[[], None]] = None,
        animator: Optional[AnimationManager] = None,
        width: int = 44,
        height: int = 24,
        on_color: Optional[str] = None,
        off_color: Optional[str] = None,
        thumb_color: str = "#FFFFFF",
        cursor: str = "hand2"
    ):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=parent.cget("bg") if hasattr(parent, "cget") else COLORS['card_bg'],
            highlightthickness=0,
            cursor=cursor
        )
        self.var = variable
        self.command = command
        self.animator = animator
        self.w = width
        self.h = height
        self.on_color = on_color
        self.off_color = off_color or "#3A3F4D"
        self.thumb_color = thumb_color

        # State tracking
        self._current_x = float(self.w - self.h // 2 - 2 if self.var.get() else self.h // 2 + 2)
        self._anim_id = f"toggle_{id(self)}"

        self.bind("<Button-1>", self._on_click)
        self.var.trace_add("write", lambda *a: self._sync_state())
        self.render()

    def get_on_color(self) -> str:
        return self.on_color or COLORS.get('accent_color', '#2ECC71')

    def render(self):
        self.delete("all")
        bg_col = self.get_on_color() if self.var.get() else self.off_color
        radius = self.h // 2
        pad = 2

        # Draw rounded pill track
        self.create_arc(pad, pad, self.h - pad, self.h - pad, start=90, extent=180, fill=bg_col, outline="")
        self.create_arc(self.w - self.h + pad, pad, self.w - pad, self.h - pad, start=270, extent=180, fill=bg_col, outline="")
        self.create_rectangle(radius, pad, self.w - radius, self.h - pad, fill=bg_col, outline="")

        # Draw thumb circle
        thumb_r = radius - 3
        cx = self._current_x
        cy = self.h / 2
        self.create_oval(cx - thumb_r, cy - thumb_r, cx + thumb_r, cy + thumb_r, fill=self.thumb_color, outline="")

    def _sync_state(self):
        target_x = float(self.w - self.h // 2 - 2 if self.var.get() else self.h // 2 + 2)
        if self.animator and self.animator.is_enabled:
            def _step(val):
                self._current_x = val
                self.render()
            self.animator.animate_value(
                self._current_x, target_x, duration_ms=90,
                on_step=_step, anim_id=self._anim_id
            )
        else:
            self._current_x = target_x
            self.render()

    def _on_click(self, event=None):
        self.var.set(not self.var.get())
        if self.command:
            try:
                self.command()
            except Exception:
                pass


def create_toggle_switch(
    parent: tk.Widget,
    variable: tk.BooleanVar,
    command: Optional[Callable[[], None]] = None,
    animator: Optional[AnimationManager] = None
) -> ToggleSwitch:
    """Helper factory for modern ToggleSwitch."""
    return ToggleSwitch(parent, variable=variable, command=command, animator=animator)


def create_setting_row(
    parent: tk.Widget,
    title: str,
    description: Optional[str] = None,
    control_widget: Optional[tk.Widget] = None,
    *,
    pady: int = 12,
    padx: int = 0
) -> Tuple[tk.Frame, tk.Frame]:
    """
    Standardized Setting Row with left Title/Subtitle and right Control widget.
    Returns (row_frame, control_container).
    """
    bg = parent.cget("bg") if hasattr(parent, "cget") else COLORS['card_bg']
    row = tk.Frame(parent, bg=bg, pady=pady, padx=padx)
    row.pack(fill="x", expand=True)

    text_frame = tk.Frame(row, bg=bg)
    text_frame.pack(side="left", fill="x", expand=True, padx=(0, 15))

    lbl_title = tk.Label(
        text_frame,
        text=title,
        font=(FONT_FAMILY, 10, "bold"),
        bg=bg,
        fg=COLORS['text_primary'],
        anchor="w"
    )
    lbl_title.pack(anchor="w")

    if description:
        lbl_desc = tk.Label(
            text_frame,
            text=description,
            font=(FONT_FAMILY, 8),
            bg=bg,
            fg=COLORS.get('text_secondary', '#A6ACB8'),
            anchor="w",
            wraplength=480,
            justify="left"
        )
        lbl_desc.pack(anchor="w", pady=(2, 0))

    ctrl_frame = tk.Frame(row, bg=bg)
    ctrl_frame.pack(side="right", anchor="center")

    if control_widget:
        control_widget.pack(in_=ctrl_frame, side="right")

    return row, ctrl_frame


def create_segmented_chips(
    parent: tk.Widget,
    options: List[Tuple[str, Any]],
    variable: Any,
    command: Optional[Callable[[Any], None]] = None
) -> tk.Frame:
    """
    Create a row of quick-selection chip pills (e.g. [2 GB], [4 GB], [6 GB], [8 GB]).
    """
    bg = parent.cget("bg") if hasattr(parent, "cget") else COLORS['card_bg']
    container = tk.Frame(parent, bg=bg)
    container.pack(fill="x", pady=(4, 8))

    chip_buttons: List[Tuple[Any, tk.Button]] = []

    def _update_chip_styles():
        curr_val = variable.get()
        accent = COLORS.get('accent_color', '#2ECC71')
        subtle = COLORS.get('input_bg', '#2E333E')
        for val, btn in chip_buttons:
            if curr_val == val:
                btn.config(bg=accent, fg=COLORS.get('accent_text', 'white'), font=(FONT_FAMILY, 8, "bold"))
            else:
                btn.config(bg=subtle, fg=COLORS.get('text_secondary', '#A6ACB8'), font=(FONT_FAMILY, 8))

    for label, val in options:
        def _make_cmd(v=val):
            return lambda: [variable.set(v), _update_chip_styles(), command(v) if command else None]

        btn = tk.Button(
            container,
            text=label,
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=10,
            pady=4,
            command=_make_cmd(val)
        )
        btn.pack(side="left", padx=(0, 6))
        chip_buttons.append((val, btn))

    _update_chip_styles()
    variable.trace_add("write", lambda *a: _update_chip_styles())
    return container
