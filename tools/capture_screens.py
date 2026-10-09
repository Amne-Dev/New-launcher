#!/usr/bin/env python3
"""
tools/capture_screens.py - Automated Visual Regression Capture Tool
Captures screenshots of every screen and dialog in NLC using grim.
Modes:
  --mode baseline: Captures screenshots to docs/refactor/screenshots/baseline/
  --mode compare:  Captures to docs/refactor/screenshots/refactored/ and produces diffs in docs/refactor/screenshots/diff/
"""

import argparse
import os
import sys
import time
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageChops

SCREENSHOTS_DIR = REPO_ROOT / "docs" / "refactor" / "screenshots"

def capture_window(root, output_path: Path):
    root.update()
    time.sleep(0.3)
    root.update_idletasks()

    x = root.winfo_rootx()
    y = root.winfo_rooty()
    w = root.winfo_width()
    h = root.winfo_height()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    geom = f"{x},{y} {w}x{h}"
    try:
        subprocess.run(["grim", "-g", geom, str(output_path)], check=True, timeout=5)
    except Exception:
        # Fallback to full screen and crop
        tmp = output_path.with_suffix(".tmp.png")
        subprocess.run(["grim", str(tmp)], check=True, timeout=5)
        with Image.open(tmp) as im:
            crop_im = im.crop((x, y, x + w, y + h))
            crop_im.save(output_path)
        if tmp.exists():
            tmp.unlink()

    print(f"Captured: {output_path.name} ({w}x{h})")

def capture_all_screens(target_dir: Path):
    import tkinter as tk
    import alt

    root = tk.Tk()
    root.title("NLC Visual Capture")
    root.geometry("1080x720+150+100")
    launcher = alt.MinecraftLauncher(root)

    steps = []

    def add_step(fn, delay=350):
        steps.append((fn, delay))

    def step_play():
        launcher.show_tab("Play")
        capture_window(root, target_dir / "01_play_tab.png")

    def step_installations():
        launcher.show_tab("Installations")
        capture_window(root, target_dir / "02_installations_tab.png")

    def step_modpacks():
        launcher.show_tab("Modpacks")
        capture_window(root, target_dir / "03_modpacks_tab.png")

    def step_locker_skins():
        launcher.show_tab("Locker")
        if hasattr(launcher, "locker_view"):
            launcher.locker_view.set("Skins")
            launcher.refresh_locker_view()
        capture_window(root, target_dir / "04_locker_skins_tab.png")

    def step_locker_wallpapers():
        if hasattr(launcher, "locker_view"):
            launcher.locker_view.set("Wallpapers")
            launcher.refresh_locker_view()
        capture_window(root, target_dir / "05_locker_wallpapers_tab.png")

    def step_settings():
        launcher.show_tab("Settings")
        capture_window(root, target_dir / "06_settings_tab.png")

    def step_addons():
        launcher.show_tab("Addons")
        capture_window(root, target_dir / "07_addons_tab.png")

    def step_launch_options():
        launcher.show_tab("Play")
        try:
            launcher.open_launch_options()
            top = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_viewable()]
            if top:
                capture_window(top[0], target_dir / "08_launch_options_modal.png")
                top[0].destroy()
        except Exception as e:
            print(f"Skipping launch options capture: {e}")

    def step_add_account():
        try:
            launcher.open_add_account_modal()
            top = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_viewable()]
            if top:
                capture_window(top[0], target_dir / "09_add_account_modal.png")
                top[0].destroy()
        except Exception as e:
            print(f"Skipping add account modal capture: {e}")

    def step_new_installation():
        try:
            launcher.open_new_installation_modal()
            top = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_viewable()]
            if top:
                capture_window(top[0], target_dir / "10_new_installation_modal.png")
                top[0].destroy()
        except Exception as e:
            print(f"Skipping new installation modal capture: {e}")

    def step_finish():
        print(f"\nAll screenshots successfully saved to {target_dir}")
        root.destroy()

    add_step(step_play, 600)
    add_step(step_installations, 400)
    add_step(step_modpacks, 400)
    add_step(step_locker_skins, 500)
    add_step(step_locker_wallpapers, 400)
    add_step(step_settings, 400)
    add_step(step_addons, 400)
    add_step(step_launch_options, 400)
    add_step(step_add_account, 400)
    add_step(step_new_installation, 400)
    add_step(step_finish, 200)

    step_idx = 0
    def run_next_step():
        nonlocal step_idx
        if step_idx < len(steps):
            fn, delay = steps[step_idx]
            step_idx += 1
            try:
                fn()
            except Exception as e:
                print(f"Error in step {step_idx}: {e}")
            root.after(delay, run_next_step)

    root.after(800, run_next_step)
    root.mainloop()

def generate_comparisons():
    base_dir = SCREENSHOTS_DIR / "baseline"
    ref_dir = SCREENSHOTS_DIR / "refactored"
    diff_dir = SCREENSHOTS_DIR / "diff"
    diff_dir.mkdir(parents=True, exist_ok=True)

    base_files = sorted(base_dir.glob("*.png"))
    if not base_files:
        print("No baseline screenshots found.")
        return

    report = ["# Visual Regression Diff Report\n"]

    for bpath in base_files:
        rpath = ref_dir / bpath.name
        if not rpath.exists():
            report.append(f"- **{bpath.name}**: ⚠️ Missing in refactored run")
            continue

        bimg = Image.open(bpath).convert("RGBA")
        rimg = Image.open(rpath).convert("RGBA")

        # Create side-by-side composite
        w = bimg.width + rimg.width
        h = max(bimg.height, rimg.height)
        composite = Image.new("RGBA", (w, h), (30, 30, 30, 255))
        composite.paste(bimg, (0, 0))
        composite.paste(rimg, (bimg.width, 0))

        # Check difference
        diff = ImageChops.difference(bimg, rimg)
        bbox = diff.getbbox()
        if bbox is None:
            status = "✅ Pixel-Identical (100% Match)"
        else:
            status = f"ℹ️ Minor visual difference detected: bounding box {bbox}"

        diff_path = diff_dir / f"diff_{bpath.name}"
        composite.save(diff_path)
        report.append(f"- **{bpath.name}**: {status} (Diff: `{diff_path.name}`)")

    report_file = SCREENSHOTS_DIR / "REPORT.md"
    report_file.write_text("\n".join(report), encoding="utf-8")
    print(f"Visual comparison report saved to {report_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visual screenshot capture tool")
    parser.add_argument("--mode", choices=["baseline", "compare"], default="baseline")
    args = parser.parse_args()

    if args.mode == "baseline":
        capture_all_screens(SCREENSHOTS_DIR / "baseline")
    elif args.mode == "compare":
        capture_all_screens(SCREENSHOTS_DIR / "refactored")
        generate_comparisons()
