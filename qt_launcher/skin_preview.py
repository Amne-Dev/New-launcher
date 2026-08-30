"""Rendered skin previews for the QML Locker, using the existing skinpy stack."""

from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Lock, Thread
from typing import Callable

from PIL import Image

try:
    from skinpy import BodyPart, Perspective, Skin
except ImportError:  # The caller reports a useful state if optional rendering is unavailable.
    BodyPart = Perspective = Skin = None  # type: ignore[assignment,misc]


PreviewCallback = Callable[[str, str], None]


def _render(path: Path, model: str, destination: Path) -> None:
    if Skin is None or Perspective is None:
        raise RuntimeError("skinpy is not installed")
    with Image.open(path) as source:
        image = source.convert("RGBA")
    if image.width != 64 or image.height not in {32, 64}:
        raise ValueError("A Minecraft skin must be 64 × 32 or 64 × 64 pixels")
    skin = Skin.from_image(image)
    if model == "slim" and BodyPart is not None:
        left_arm = BodyPart.new(
            id_="left_arm",
            skin_image_color=skin.image_color,
            part_shape=(3, 4, 12),
            part_model_origin=(1, 2, 12),
            part_image_origin=(40, 16),
        )
        right_arm = BodyPart.new(
            id_="right_arm",
            skin_image_color=skin.image_color,
            part_shape=(3, 4, 12),
            part_model_origin=(12, 2, 12),
            part_image_origin=(32, 48),
        )
        skin = Skin(
            image_color=skin.image_color,
            head=skin.head,
            torso=skin.torso,
            left_arm=left_arm,
            right_arm=right_arm,
            left_leg=skin.left_leg,
            right_leg=skin.right_leg,
        )
    rendered = skin.to_isometric_image(Perspective(x="right", y="front", z="up", scaling_factor=10))
    height = 330
    width = max(1, int(rendered.width * (height / rendered.height)))
    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:
        resample = Image.LANCZOS
    preview = rendered.resize((width, height), resample)
    destination.parent.mkdir(parents=True, exist_ok=True)
    preview.save(destination, "PNG")


class SkinPreviewer:
    """Serialises rendering off the QML thread to keep Locker responsive."""

    def __init__(self, cache_directory: Path, callback: PreviewCallback) -> None:
        self._cache_directory = cache_directory
        self._callback = callback
        self._lock = Lock()
        self._running = False

    def start(self, path: str, model: str) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
        Thread(target=self._run, args=(path, model), daemon=True).start()
        return True

    def _run(self, raw_path: str, model: str) -> None:
        try:
            path = Path(raw_path).expanduser().resolve()
            if not path.is_file():
                self._callback("", "Choose a skin PNG to see a 3D preview")
                return
            fingerprint = hashlib.sha256(f"{path}|{path.stat().st_mtime_ns}|{model}".encode()).hexdigest()[:20]
            destination = self._cache_directory / f"{fingerprint}.png"
            if not destination.is_file():
                _render(path, model, destination)
            self._callback(str(destination), "Offline skin preview ready")
        except (OSError, ValueError, RuntimeError) as error:
            self._callback("", f"Skin preview unavailable: {error}")
        finally:
            with self._lock:
                self._running = False
