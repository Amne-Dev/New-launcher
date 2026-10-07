"""
nlc.ui.animation - Lightweight micro-animation and transition engine.
Zero external dependencies; uses native Tkinter after() scheduling with delta-time
and easing curves. Fully bypassable via settings toggle for 0% CPU overhead.
"""

import time
import math
import tkinter as tk
from typing import Callable, Optional, Tuple, Dict, Any

def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    """Convert hex string (e.g. '#2ECC71' or '2ECC71') to RGB tuple."""
    hex_clean = hex_str.lstrip("#")
    if len(hex_clean) == 3:
        hex_clean = "".join(c * 2 for c in hex_clean)
    if len(hex_clean) != 6:
        return (255, 255, 255)
    try:
        return (
            int(hex_clean[0:2], 16),
            int(hex_clean[2:4], 16),
            int(hex_clean[4:6], 16)
        )
    except ValueError:
        return (255, 255, 255)

def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB integers (0-255) to hex string."""
    r_clamped = max(0, min(255, int(r)))
    g_clamped = max(0, min(255, int(g)))
    b_clamped = max(0, min(255, int(b)))
    return f"#{r_clamped:02x}{g_clamped:02x}{b_clamped:02x}"

def color_lerp(hex_a: str, hex_b: str, t: float) -> str:
    """Linearly interpolate between two hex colors by factor t (0.0 to 1.0)."""
    t_clamped = max(0.0, min(1.0, float(t)))
    r1, g1, b1 = hex_to_rgb(hex_a)
    r2, g2, b2 = hex_to_rgb(hex_b)
    r = r1 + (r2 - r1) * t_clamped
    g = g1 + (g2 - g1) * t_clamped
    b = b1 + (b2 - b1) * t_clamped
    return rgb_to_hex(int(r), int(g), int(b))

def ease_out_cubic(t: float) -> float:
    """Cubic ease-out: starts fast, smoothly decelerates."""
    t_clamped = max(0.0, min(1.0, float(t)))
    return 1.0 - math.pow(1.0 - t_clamped, 3)

def ease_in_out_quad(t: float) -> float:
    """Quadratic ease-in-out: smooth acceleration and deceleration."""
    t_clamped = max(0.0, min(1.0, float(t)))
    if t_clamped < 0.5:
        return 2.0 * t_clamped * t_clamped
    return 1.0 - math.pow(-2.0 * t_clamped + 2.0, 2) / 2.0


class AnimationManager:
    """
    Coordinates smooth 60fps micro-animations across Tkinter widgets.
    Respects global animation enable/disable state for accessibility & performance.
    """
    def __init__(self, root: Optional[tk.Misc] = None, enabled_provider: Optional[Callable[[], bool]] = None):
        self.root = root
        self.enabled_provider = enabled_provider or (lambda: True)
        self._active_anims: Dict[str, str] = {}  # anim_id -> after_id

    @property
    def is_enabled(self) -> bool:
        try:
            return bool(self.enabled_provider())
        except Exception:
            return True

    def cancel(self, anim_id: str) -> None:
        """Cancel an in-flight animation by id."""
        if anim_id in self._active_anims:
            after_id = self._active_anims.pop(anim_id)
            if self.root:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass

    def animate_color(
        self,
        widget: Any,
        prop_name: str,
        start_hex: str,
        end_hex: str,
        duration_ms: int = 80,
        anim_id: Optional[str] = None,
        on_done: Optional[Callable[[], None]] = None,
        on_step: Optional[Callable[[str], None]] = None
    ) -> None:
        """
        Smoothly interpolate widget color property (e.g. 'bg', 'fg', 'highlightbackground').
        If animations are disabled, immediately sets end_hex.
        """
        if not widget:
            return
        exists_fn = getattr(widget, "winfo_exists", None)
        if exists_fn is not None and not exists_fn():
            return

        key = anim_id or f"{id(widget)}_{prop_name}"
        self.cancel(key)

        if not self.is_enabled or duration_ms <= 0 or not self.root:
            try:
                widget[prop_name] = end_hex
            except Exception:
                pass
            if on_step:
                try:
                    on_step(end_hex)
                except Exception:
                    pass
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass
            return

        start_time = time.monotonic()
        duration_sec = max(0.01, duration_ms / 1000.0)

        def _step():
            exists_fn = getattr(widget, "winfo_exists", None)
            if exists_fn is not None and not exists_fn():
                self._active_anims.pop(key, None)
                return

            now = time.monotonic()
            elapsed = now - start_time
            t = min(1.0, elapsed / duration_sec)
            eased_t = ease_out_cubic(t)
            current_color = color_lerp(start_hex, end_hex, eased_t)

            try:
                widget[prop_name] = current_color
            except Exception:
                self._active_anims.pop(key, None)
                return

            if on_step:
                try:
                    on_step(current_color)
                except Exception:
                    pass

            if t < 1.0:
                self._active_anims[key] = self.root.after(16, _step)  # ~60 FPS
            else:
                self._active_anims.pop(key, None)
                try:
                    widget[prop_name] = end_hex
                except Exception:
                    pass
                if on_step:
                    try:
                        on_step(end_hex)
                    except Exception:
                        pass
                if on_done:
                    try:
                        on_done()
                    except Exception:
                        pass

        self._active_anims[key] = self.root.after(1, _step)

    def animate_value(
        self,
        start_val: float,
        end_val: float,
        duration_ms: int = 120,
        on_step: Optional[Callable[[float], None]] = None,
        on_done: Optional[Callable[[], None]] = None,
        anim_id: Optional[str] = None
    ) -> None:
        """Smoothly interpolate a numeric value (e.g. progress bar fraction or pixel coordinate)."""
        key = anim_id or f"val_{id(on_step)}"
        self.cancel(key)

        if not self.is_enabled or duration_ms <= 0 or not self.root:
            if on_step:
                try:
                    on_step(end_val)
                except Exception:
                    pass
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass
            return

        start_time = time.monotonic()
        duration_sec = max(0.01, duration_ms / 1000.0)

        def _step():
            now = time.monotonic()
            elapsed = now - start_time
            t = min(1.0, elapsed / duration_sec)
            eased_t = ease_out_cubic(t)
            current_val = start_val + (end_val - start_val) * eased_t

            if on_step:
                try:
                    on_step(current_val)
                except Exception:
                    self._active_anims.pop(key, None)
                    return

            if t < 1.0:
                self._active_anims[key] = self.root.after(16, _step)
            else:
                self._active_anims.pop(key, None)
                if on_step:
                    try:
                        on_step(end_val)
                    except Exception:
                        pass
                if on_done:
                    try:
                        on_done()
                    except Exception:
                        pass

        self._active_anims[key] = self.root.after(1, _step)
