from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CameraConfiguration

try:
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError
except ImportError:  # Optional fallback; password remains in memory only.
    keyring = None

    class KeyringError(Exception):
        pass

    class PasswordDeleteError(KeyringError):
        pass


CAMERA_STORE_PATH = (
    Path(__file__).resolve().parent.parent
    / "command_center_data"
    / "cameras.json"
)
KEYRING_SERVICE = "TrafficCommandCenter.Camera"


class CameraRepository:
    """Persists non-secret camera settings and stores passwords in keyring."""

    def __init__(self) -> None:
        self._records = self._load_records()
        self.password_storage_message = (
            "Windows Credential Manager ready"
            if keyring is not None
            else "Keyring unavailable; password is memory-only"
        )

    def apply_to_camera(self, camera: CameraConfiguration) -> None:
        record = self._records.get(camera.camera_id)
        if isinstance(record, dict):
            camera.name = str(record.get("name") or camera.name)
            camera.enabled = bool(record.get("enabled", camera.enabled))
            camera.profile = str(record.get("profile") or camera.profile)
            camera.host = str(record.get("host") or camera.host)
            camera.port = self._safe_port(record.get("port"), camera.port)
            camera.username = str(record.get("username") or camera.username)
            camera.main_path = str(record.get("mainPath") or camera.main_path)
            camera.sub_path = str(record.get("subPath") or camera.sub_path)

        if keyring is not None:
            try:
                stored_password = keyring.get_password(
                    KEYRING_SERVICE,
                    camera.camera_id,
                )
                if stored_password is not None:
                    camera.password = stored_password
            except KeyringError as exc:
                self.password_storage_message = (
                    f"Credential Manager unavailable: {exc}"
                )

    def apply_to_cameras(self, cameras: list[CameraConfiguration]) -> None:
        for camera in cameras:
            self.apply_to_camera(camera)

    def save_camera(self, camera: CameraConfiguration) -> str:
        self._records[camera.camera_id] = {
            "name": camera.name,
            "enabled": camera.enabled,
            "profile": camera.profile,
            "host": camera.host,
            "port": camera.port,
            "username": camera.username,
            "mainPath": camera.main_path,
            "subPath": camera.sub_path,
        }
        self._save_records()

        if keyring is None:
            self.password_storage_message = (
                "Konfigurasi tersimpan; password hanya berada di memori sesi ini."
            )
            return self.password_storage_message

        try:
            if camera.password:
                keyring.set_password(
                    KEYRING_SERVICE,
                    camera.camera_id,
                    camera.password,
                )
            else:
                try:
                    keyring.delete_password(
                        KEYRING_SERVICE,
                        camera.camera_id,
                    )
                except PasswordDeleteError:
                    pass
            self.password_storage_message = (
                "Konfigurasi tersimpan; password diamankan oleh Credential Manager."
            )
        except KeyringError as exc:
            self.password_storage_message = (
                "Konfigurasi tersimpan; password gagal disimpan permanen "
                f"({exc})."
            )
        return self.password_storage_message

    def _load_records(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(CAMERA_STORE_PATH.read_text(encoding="utf-8"))
            cameras = data.get("cameras", {}) if isinstance(data, dict) else {}
            return cameras if isinstance(cameras, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _save_records(self) -> None:
        CAMERA_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = CAMERA_STORE_PATH.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"schemaVersion": 1, "cameras": self._records},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(CAMERA_STORE_PATH)

    @staticmethod
    def _safe_port(value: Any, fallback: int) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            return fallback
        return port if 1 <= port <= 65535 else fallback
