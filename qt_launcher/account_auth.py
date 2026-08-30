"""Non-blocking Microsoft and Ely.by sign-in flows for the QML account manager."""

from __future__ import annotations

import base64
import io
import json
import time
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable

import minecraft_launcher_lib
import requests
from PIL import Image

from auth import ElyByAuth
from config import MSA_CLIENT_ID, MSA_REDIRECT_URI


StateCallback = Callable[[dict[str, Any]], None]
FinishCallback = Callable[[dict[str, Any] | None, str], None]


class AccountAuthenticator:
    """Runs credential work away from the Qt thread and never persists passwords."""

    def __init__(self, config_directory: Path, on_state: StateCallback, on_finished: FinishCallback) -> None:
        self._skins_directory = config_directory / "skins"
        self._on_state = on_state
        self._on_finished = on_finished
        self._lock = Lock()
        self._busy = False
        self._cancel = Event()

    def _start(self, target: Callable[..., None], *args: str) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            self._cancel = Event()
        Thread(target=target, args=args, daemon=True).start()
        return True

    def _state(self, provider: str, status: str, **values: Any) -> None:
        self._on_state({"provider": provider, "status": status, "busy": True, **values})

    def _finish(self, profile: dict[str, Any] | None, status: str, provider: str) -> None:
        with self._lock:
            self._busy = False
        self._on_state({"provider": provider, "status": status, "busy": False, "deviceCode": "", "verificationUrl": ""})
        self._on_finished(profile, status)

    @staticmethod
    def _texture_details(properties: Any) -> tuple[str, str]:
        if not isinstance(properties, list):
            return "", "classic"
        for property_ in properties:
            if not isinstance(property_, dict) or property_.get("name") != "textures":
                continue
            try:
                payload = base64.b64decode(str(property_.get("value") or "")).decode("utf-8")
                texture = json.loads(payload).get("textures", {}).get("SKIN", {})
                url = str(texture.get("url") or "")
                model = str(texture.get("metadata", {}).get("model") or "classic").lower()
                return url, "slim" if model == "slim" else "classic"
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                continue
        return "", "classic"

    def _cache_skin(self, name: str, identifier: str, url: str) -> str:
        if not url:
            return ""
        response = requests.get(url, timeout=(8, 20))
        response.raise_for_status()
        image_bytes = response.content
        with Image.open(io.BytesIO(image_bytes)) as image:
            if image.width != 64 or image.height not in {32, 64}:
                return ""
        safe_identifier = "".join(character for character in (identifier or name) if character.isalnum() or character in "-_")
        destination = self._skins_directory / f"{safe_identifier or 'account'}.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".download")
        temporary.write_bytes(image_bytes)
        temporary.replace(destination)
        return str(destination)

    def start_microsoft(self) -> bool:
        return self._start(self._microsoft_worker)

    def cancel_microsoft(self) -> None:
        self._cancel.set()

    def _microsoft_worker(self) -> None:
        provider = "microsoft"
        try:
            self._state(provider, "Contacting Microsoft…")
            device = requests.post(
                "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode",
                data={"client_id": MSA_CLIENT_ID, "scope": "XboxLive.signin offline_access"},
                timeout=(8, 20),
            )
            device.raise_for_status()
            data = device.json()
            device_code = str(data.get("device_code") or "")
            user_code = str(data.get("user_code") or "")
            verification_url = str(data.get("verification_uri") or data.get("verification_uri_complete") or "")
            if not device_code or not user_code or not verification_url:
                raise RuntimeError("Microsoft did not return a usable device code.")
            interval = max(2, int(data.get("interval") or 5))
            expires_at = time.monotonic() + max(1, int(data.get("expires_in") or 900))
            self._state(
                provider,
                "Open the Microsoft page and enter the one-time code.",
                deviceCode=user_code,
                verificationUrl=verification_url,
            )
            while time.monotonic() < expires_at:
                if self._cancel.wait(interval):
                    self._finish(None, "Microsoft sign-in cancelled", provider)
                    return
                poll = requests.post(
                    "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
                    data={"grant_type": "device_code", "client_id": MSA_CLIENT_ID, "device_code": device_code},
                    timeout=(8, 20),
                )
                token_data = poll.json()
                if poll.status_code == 200:
                    self._complete_microsoft(token_data, provider)
                    return
                error = str(token_data.get("error") or "")
                if error == "authorization_pending":
                    continue
                if error == "slow_down":
                    interval += 2
                    continue
                if error == "expired_token":
                    break
                raise RuntimeError(str(token_data.get("error_description") or "Microsoft sign-in was rejected."))
            self._finish(None, "Microsoft sign-in code expired. Start again to get a new code.", provider)
        except (requests.RequestException, ValueError, RuntimeError, KeyError) as error:
            self._finish(None, f"Microsoft sign-in failed: {error}", provider)

    def _complete_microsoft(self, token_data: dict[str, Any], provider: str) -> None:
        self._state(provider, "Connecting your Minecraft account…")
        access_token = str(token_data["access_token"])
        refresh_token = str(token_data["refresh_token"])
        xbl = minecraft_launcher_lib.microsoft_account.authenticate_with_xbl(access_token)
        xsts = minecraft_launcher_lib.microsoft_account.authenticate_with_xsts(xbl["Token"])
        user_hash = xbl["DisplayClaims"]["xui"][0]["uhs"]
        minecraft = minecraft_launcher_lib.microsoft_account.authenticate_with_minecraft(user_hash, xsts["Token"])
        profile = minecraft_launcher_lib.microsoft_account.get_profile(minecraft["access_token"])
        name, identifier = str(profile["name"]), str(profile["id"])
        skin_path, skin_model = "", "classic"
        try:
            skin_response = requests.get(
                "https://api.minecraftservices.com/minecraft/profile",
                headers={"Authorization": f"Bearer {minecraft['access_token']}"},
                timeout=(8, 20),
            )
            skin_response.raise_for_status()
            active_skin = next((item for item in skin_response.json().get("skins", []) if item.get("state") == "ACTIVE"), {})
            skin_path = self._cache_skin(name, f"{identifier}_ms", str(active_skin.get("url") or ""))
            skin_model = "slim" if str(active_skin.get("variant") or "").lower() == "slim" else "classic"
        except (requests.RequestException, ValueError, OSError):
            pass  # Skin retrieval is optional; the authenticated account remains usable.
        self._finish(
            {
                "name": name,
                "uuid": identifier,
                "type": "microsoft",
                "skin_path": skin_path,
                "skin_model": skin_model,
                "access_token": str(minecraft["access_token"]),
                "refresh_token": refresh_token,
                "created": datetime.now().strftime("%Y-%m-%d"),
            },
            f"Signed in to Microsoft as {name}",
            provider,
        )

    def login_elyby(self, username: str, password: str) -> bool:
        return self._start(self._elyby_worker, username.strip(), password)

    def _elyby_worker(self, username: str, password: str) -> None:
        provider = "ely.by"
        try:
            if not username or not password:
                raise RuntimeError("Enter your Ely.by username/email and password.")
            self._state(provider, "Signing in to Ely.by…")
            response = ElyByAuth.authenticate(username, password)
            if not isinstance(response, dict) or response.get("error"):
                raise RuntimeError(str(response.get("error") if isinstance(response, dict) else "Ely.by did not return an account."))
            selected = response.get("selectedProfile")
            if not isinstance(selected, dict):
                raise RuntimeError("Ely.by did not return a selected Minecraft profile.")
            name = str(selected.get("name") or username)
            identifier = str(selected.get("id") or "")
            texture_url, skin_model = self._texture_details(selected.get("properties"))
            if not texture_url:
                texture_url = f"https://skinsystem.ely.by/skins/{name}.png"
            skin_path = ""
            try:
                skin_path = self._cache_skin(name, f"{identifier}_elyby", texture_url)
            except (requests.RequestException, OSError, ValueError):
                pass
            self._finish(
                {
                    "name": name,
                    "uuid": identifier,
                    "type": "ely.by",
                    "skin_path": skin_path,
                    "skin_model": skin_model,
                    "token": str(response.get("accessToken") or ""),
                },
                f"Signed in to Ely.by as {name}",
                provider,
            )
        except (RuntimeError, OSError, ValueError) as error:
            self._finish(None, f"Ely.by sign-in failed: {error}", provider)
