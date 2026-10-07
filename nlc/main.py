"""
nlc.main - Entry point and runtime initialization for New Launcher (NLC)
Handles single instance lock, global exception logging, splash animation, and window lifecycle.
"""

import os
import sys
import logging
import traceback
import threading
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk

from nlc.storage.paths import resource_path, get_nlc_data_dir
from nlc.storage.lock import SingleInstanceLock
from nlc.ui.components.dialogs import custom_showerror
from nlc.ui.app import MinecraftLauncher

logger = logging.getLogger(__name__)

def setup_global_exception_handling(log_dir: Path):
    """Install global crash handlers for unhandled main-thread and worker-thread exceptions."""
    log_dir.mkdir(parents=True, exist_ok=True)
    crash_log_file = log_dir / "crash.log"

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        formatted = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        logger.critical("Unhandled exception: %s", formatted)

        try:
            with open(crash_log_file, "a", encoding="utf-8") as f:
                f.write(f"\n--- Crash Report [{threading.current_thread().name}] ---\n")
                f.write(formatted)
        except Exception:
            pass

        try:
            custom_showerror(
                "Unexpected Error",
                f"An unexpected error occurred:\n\n{exc_value}\n\nDetails saved to crash.log"
            )
        except Exception:
            pass

    sys.excepthook = handle_exception

    def handle_thread_exception(args):
        handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

    if hasattr(threading, "excepthook"):
        threading.excepthook = handle_thread_exception


def main() -> int:
    """Main application entry point."""
    data_dir = get_nlc_data_dir()
    logs_dir = data_dir / "logs"
    setup_global_exception_handling(logs_dir)

    # 1. Single Instance Lock
    lock = SingleInstanceLock()
    if not lock.acquire():
        logger.warning("Another instance of NLC is already running.")
        try:
            root = tk.Tk()
            root.withdraw()
            custom_showerror(
                "Launcher Already Running",
                "Another instance of New Launcher is already active.\nPlease check your taskbar or tray."
            )
            root.destroy()
        except Exception:
            pass
        return 1

    try:
        root = tk.Tk()
        root.withdraw()

        splash = tk.Toplevel(root)
        splash.overrideredirect(True)

        try:
            splash.attributes("-transparentcolor", "#050505")
        except Exception:
            pass
        splash.configure(bg="#050505")

        splash_width = 300
        splash_height = 300
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = (screen_w // 2) - (splash_width // 2)
        y = (screen_h // 2) - (splash_height // 2)
        splash.geometry(f"{splash_width}x{splash_height}+{x}+{y}")

        try:
            logo_path = resource_path("logo.png")
            if os.path.exists(logo_path):
                img = Image.open(logo_path).resize((256, 256), Image.Resampling.LANCZOS)
                splash_logo = ImageTk.PhotoImage(img)
                logo_lbl = tk.Label(splash, image=splash_logo, bg="#050505")
                logo_lbl.image = splash_logo  # type: ignore
                logo_lbl.pack(expand=True)
            else:
                tk.Label(splash, text="NLC", font=("Segoe UI", 48, "bold"), fg="white", bg="#050505").pack(expand=True)
        except Exception:
            tk.Label(splash, text="NLC", font=("Segoe UI", 48, "bold"), fg="white", bg="#050505").pack(expand=True)

        alpha_state = {"alpha": 0.0, "fading_in": True}
        splash.attributes("-alpha", alpha_state["alpha"])

        def pulsate_splash():
            if not splash.winfo_exists():
                return
            if alpha_state["fading_in"]:
                alpha_state["alpha"] += 0.05
                if alpha_state["alpha"] >= 1.0:
                    alpha_state["alpha"] = 1.0
                    alpha_state["fading_in"] = False
            else:
                alpha_state["alpha"] -= 0.05
                if alpha_state["alpha"] <= 0.3:
                    alpha_state["alpha"] = 0.3
                    alpha_state["fading_in"] = True
            try:
                splash.attributes("-alpha", alpha_state["alpha"])
            except Exception:
                pass
            splash.after(40, pulsate_splash)

        pulsate_splash()

        def finish_loading():
            if splash.winfo_exists():
                splash.destroy()
            root.deiconify()

        def init_app():
            try:
                _app = MinecraftLauncher(root)
                root.after(1000, finish_loading)
            except Exception as e:
                logger.critical("Failed to initialize launcher: %s", traceback.format_exc())
                finish_loading()
                custom_showerror("Startup Error", f"Failed to initialize New Launcher:\n{e}")

        root.after(100, init_app)
        root.mainloop()

    finally:
        lock.release()

    return 0


if __name__ == "__main__":
    sys.exit(main())
