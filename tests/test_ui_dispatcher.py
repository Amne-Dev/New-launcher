import tkinter as tk
import pytest
from nlc.ui.dispatcher import EventDispatcher
from nlc.ui.theme import COLORS, FONTS

def test_theme_tokens_exist():
    assert "main_bg" in COLORS
    assert "play_btn_green" in COLORS
    assert "sidebar_bg" in COLORS
    assert "hero_title" in FONTS

def test_event_dispatcher_runs_callbacks():
    root = tk.Tk()
    root.withdraw()
    dispatcher = EventDispatcher(root)
    dispatcher.start()

    results = []

    def callback(val):
        results.append(val)

    dispatcher.post(callback, 42)
    dispatcher.post(callback, "hello")

    # Manually trigger process events
    dispatcher._process_events()

    assert results == [42, "hello"]
    dispatcher.stop()
    root.destroy()
