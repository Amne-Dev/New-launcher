"""
nlc.ui.components.radial_progress - Smooth circular (radial) progress bar for Tkinter.
Pure Tkinter Canvas arc rendering: ultra lightweight, zero dependencies, < 0.2 MB memory.
"""

import math
import tkinter as tk
from typing import Optional

from nlc.ui.theme import COLORS, FONT_FAMILY


class RadialProgress(tk.Canvas):
    """
    A lightweight, modern circular progress ring rendered via Tkinter Canvas arcs.
    Supports determinate progress (0..100%), smooth success checkmark, error state,
    and indeterminate spinner mode.
    """
    def __init__(
        self,
        parent: tk.Widget,
        size: int = 44,
        line_width: int = 4,
        track_color: Optional[str] = None,
        progress_color: Optional[str] = None,
        bg: Optional[str] = None,
        **kwargs
    ):
        card_bg = bg or COLORS.get("card_bg", "#222630")
        super().__init__(
            parent,
            width=size,
            height=size,
            bg=card_bg,
            highlightthickness=0,
            bd=0,
            **kwargs
        )
        self.size = size
        self.line_width = line_width
        self.track_color = track_color or COLORS.get("card_border", "#2A303F")
        self.progress_color = progress_color or COLORS.get("accent_color", "#2ECC71")
        self._card_bg = card_bg

        self._value = 0.0  # 0.0 to 100.0
        self._status = "normal"  # "normal", "success", "error", "indeterminate"
        self._indeterminate_angle = 0
        self._indeterminate_job = None

        self._draw()

    @property
    def progress(self) -> float:
        return self._value

    @property
    def status(self) -> str:
        return self._status

    def set_progress(self, value: float, text: Optional[str] = None):
        """Update progress value from 0.0 to 100.0."""
        self._value = max(0.0, min(100.0, float(value)))
        self._status = "normal"
        self._draw(custom_text=text)

    def set_success(self):
        """Display 100% completion with a checkmark."""
        self._value = 100.0
        self._status = "success"
        self._stop_indeterminate()
        self._draw()

    def set_error(self):
        """Display error state with a red ring and cross."""
        self._status = "error"
        self._stop_indeterminate()
        self._draw()

    def set_indeterminate(self, active: bool = True):
        """Start or stop an indeterminate rotating spinner arc."""
        if active:
            if self._status != "indeterminate":
                self._status = "indeterminate"
                self._tick_indeterminate()
        else:
            self._stop_indeterminate()
            self._status = "normal"
            self._draw()

    def _stop_indeterminate(self):
        if self._indeterminate_job:
            try:
                self.after_cancel(self._indeterminate_job)
            except Exception:
                pass
            self._indeterminate_job = None

    def _tick_indeterminate(self):
        if self._status != "indeterminate":
            return
        self._indeterminate_angle = (self._indeterminate_angle + 12) % 360
        self._draw_indeterminate(self._indeterminate_angle)
        self._indeterminate_job = self.after(35, self._tick_indeterminate)

    def _draw(self, custom_text: Optional[str] = None):
        self.delete("all")
        pad = self.line_width // 2 + 2
        d = self.size - 2 * pad
        cx = self.size / 2.0
        cy = self.size / 2.0

        # Background track circle
        self.create_oval(
            pad, pad, pad + d, pad + d,
            outline=self.track_color,
            width=self.line_width
        )

        if self._status == "success":
            succ_color = COLORS.get("accent_color", "#2ECC71")
            self.create_oval(
                pad, pad, pad + d, pad + d,
                outline=succ_color,
                width=self.line_width
            )
            # Checkmark
            self.create_line(
                cx - 7, cy,
                cx - 2, cy + 5,
                cx + 7, cy - 5,
                fill=succ_color,
                width=max(2, self.line_width - 1),
                capstyle="round"
            )
            return

        if self._status == "error":
            err_color = COLORS.get("error_red", "#EF4444")
            self.create_oval(
                pad, pad, pad + d, pad + d,
                outline=err_color,
                width=self.line_width
            )
            # Cross
            r = 6
            self.create_line(cx - r, cy - r, cx + r, cy + r, fill=err_color, width=2, capstyle="round")
            self.create_line(cx + r, cy - r, cx - r, cy + r, fill=err_color, width=2, capstyle="round")
            return

        # Determinate arc
        extent = -(self._value / 100.0) * 359.9
        if abs(extent) > 0.5:
            self.create_arc(
                pad, pad, pad + d, pad + d,
                start=90,
                extent=extent,
                style="arc",
                outline=self.progress_color,
                width=self.line_width
            )

        # Center text
        txt = custom_text if custom_text is not None else f"{int(self._value)}%"
        font_sz = 8 if self.size <= 44 else (9 if self.size <= 56 else 10)
        self.create_text(
            cx, cy,
            text=txt,
            font=(FONT_FAMILY, font_sz, "bold"),
            fill=COLORS.get("text_primary", "#FFFFFF")
        )

    def _draw_indeterminate(self, angle: int):
        self.delete("all")
        pad = self.line_width // 2 + 2
        d = self.size - 2 * pad

        self.create_oval(
            pad, pad, pad + d, pad + d,
            outline=self.track_color,
            width=self.line_width
        )
        self.create_arc(
            pad, pad, pad + d, pad + d,
            start=angle,
            extent=90,
            style="arc",
            outline=self.progress_color,
            width=self.line_width
        )
