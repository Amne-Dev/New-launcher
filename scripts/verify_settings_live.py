"""
scripts/verify_settings_live.py - Test running the full MinecraftLauncher, opening Settings,
and switching through all 7 categories live.
"""

import os
import sys
import tkinter as tk

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from nlc.ui.app import MinecraftLauncher

def verify_live_settings():
    print("Initializing Tk root...")
    root = tk.Tk()
    root.withdraw()

    print("Instantiating MinecraftLauncher...")
    launcher = MinecraftLauncher(root)

    print("Showing Settings tab...")
    launcher.show_tab("Settings")
    root.update()

    categories = [
        "General",
        "Appearance",
        "Java & Memory",
        "Downloads",
        "Integrations",
        "Logs & Diagnostics",
        "About & Reset"
    ]

    for cat in categories:
        print(f"Switching to category: {cat}...")
        launcher.switch_settings_category(cat)
        root.update()
        assert launcher.current_settings_category == cat
        print(f"  -> Successfully rendered {cat} with {len(launcher.settings_scroll_frame.winfo_children())} child widgets.")

    print("Testing theme switch inside Settings...")
    launcher.apply_theme("catppuccin")
    root.update()
    print("  -> Applied Catppuccin theme successfully.")

    launcher.apply_theme("dark_slate")
    root.update()
    print("  -> Restored Dark Slate theme successfully.")

    print("All live verifications passed cleanly!")
    root.destroy()

if __name__ == "__main__":
    verify_live_settings()
