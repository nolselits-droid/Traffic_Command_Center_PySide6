from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from .camera_store import CameraRepository
from .mock_data import build_mock_controllers, make_cameras
from .models import (
    ControllerMode,
    ControllerSnapshot,
    NetworkInterface,
    SignalGroupState,
)


REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent
    / "command_center_data"
    / "controllers.json"
)


def _default_entries() -> list[dict[str, Any]]:
    return [
        {
            "controllerId": f"TLC-{index:03d}",
            "displayName": f"Controller {index}",
            "enabled": index == 1,
            "baseUrl": f"http://192.168.10.{20 + index}",
        }
        for index in range(1, 6)
    ]


def _normalise_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if base_url and not base_url.lower().startswith(("http://", "https://")):
        base_url = f"http://{base_url}"
    return base_url


class ControllerService(QObject):
    """Provides mock data or read-only HTTP monitoring for up to five TLCs."""

    snapshot_updated = Signal(str)
    controllers_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.controllers: list[ControllerSnapshot] = []
        self.mode = "mock"
        self.poll_interval_ms = 1000
        self._entries = _default_entries()
        self._endpoints: dict[str, str] = {}
        self._pending: dict[str, QNetworkReply] = {}
        self._request_started: dict[str, float] = {}
        self._next_request_at: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self.camera_repository = CameraRepository()

        self._network = QNetworkAccessManager(self)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        settings = self._load_registry()
        self.apply_settings(
            settings["mode"],
            settings["controllers"],
            persist=False,
            notify=False,
        )
        self._timer.setInterval(self.poll_interval_ms)
        self._timer.start()
        QTimer.singleShot(100, self._tick)

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    def get_controller(self, controller_id: str) -> ControllerSnapshot | None:
        return next(
            (item for item in self.controllers if item.controller_id == controller_id),
            None,
        )

    def registry_entries(self) -> list[dict[str, Any]]:
        return deepcopy(self._entries)

    def base_url(self, controller_id: str) -> str:
        """Return the configured controller URL without exposing registry internals."""
        return self._endpoints.get(controller_id, "")

    def apply_settings(
        self,
        mode: str,
        entries: list[dict[str, Any]],
        *,
        persist: bool = True,
        notify: bool = True,
    ) -> None:
        selected_mode = "live" if mode == "live" else "mock"
        normalised_entries = self._normalise_entries(entries)

        for reply in self._pending.values():
            reply.abort()
        self._pending.clear()
        self._request_started.clear()
        self._next_request_at.clear()
        self._failures.clear()

        self.mode = selected_mode
        self._entries = normalised_entries
        self._endpoints.clear()

        if self.mode == "mock":
            self.controllers = build_mock_controllers()
        else:
            self.controllers = self._build_live_placeholders(normalised_entries)
        for controller in self.controllers:
            self.camera_repository.apply_to_cameras(controller.cameras)

        if persist:
            self._save_registry()
        if notify:
            self.controllers_changed.emit()
            for controller in self.controllers:
                self.snapshot_updated.emit(controller.controller_id)
            if self.is_live:
                QTimer.singleShot(0, self.poll_now)

    def poll_now(self) -> None:
        if not self.is_live:
            return
        for controller in self.controllers:
            self._request_status(controller)

    def _tick(self) -> None:
        if self.is_live:
            self.poll_now()
        else:
            self._tick_mock()

    def _tick_mock(self) -> None:
        for controller in self.controllers:
            if not controller.online or controller.mode in {
                ControllerMode.HOLD,
                ControllerMode.OFFLINE,
            }:
                continue

            controller.remaining_seconds -= 1
            if controller.remaining_seconds <= 0:
                controller.current_stage = (
                    controller.current_stage % controller.total_stages
                ) + 1
                controller.remaining_seconds = 30
                for signal_group in controller.signal_groups:
                    signal_group.aspect = (
                        "GREEN"
                        if signal_group.number
                        == (
                            (controller.current_stage - 1)
                            % controller.active_signal_groups
                        )
                        + 1
                        else "RED"
                    )

            self.snapshot_updated.emit(controller.controller_id)

    def _request_status(self, controller: ControllerSnapshot) -> None:
        controller_id = controller.controller_id
        if controller_id in self._pending:
            return
        if monotonic() < self._next_request_at.get(controller_id, 0.0):
            return
        base_url = self._endpoints.get(controller_id, "")
        if not base_url:
            return

        request = QNetworkRequest(QUrl(f"{base_url}/api/status"))
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"Traffic-Command-Center/0.5.02")
        request.setTransferTimeout(1800)
        reply = self._network.get(request)
        self._pending[controller_id] = reply
        self._request_started[controller_id] = monotonic()
        reply.finished.connect(
            lambda current=reply, key=controller_id: self._status_finished(
                key,
                current,
            )
        )

    def _status_finished(
        self,
        controller_id: str,
        reply: QNetworkReply,
    ) -> None:
        if self._pending.get(controller_id) is not reply:
            reply.deleteLater()
            return
        self._pending.pop(controller_id, None)
        started = self._request_started.pop(controller_id, None)
        response_time_ms = (
            max(0, round((monotonic() - started) * 1000))
            if started is not None
            else None
        )

        error = reply.error()
        payload: dict[str, Any] | None = None
        if error == QNetworkReply.NetworkError.NoError:
            try:
                decoded = json.loads(bytes(reply.readAll()).decode("utf-8"))
                if isinstance(decoded, dict):
                    payload = decoded
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
        reply.deleteLater()

        snapshot = self.get_controller(controller_id)
        if not snapshot:
            return

        if payload is None:
            self._mark_request_failed(snapshot)
            return

        self._failures[controller_id] = 0
        self._next_request_at[controller_id] = 0.0
        snapshot.consecutive_failures = 0
        snapshot.response_time_ms = response_time_ms
        snapshot.last_update_at = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        self._apply_status_payload(snapshot, payload)
        self.snapshot_updated.emit(controller_id)

    def _mark_request_failed(self, snapshot: ControllerSnapshot) -> None:
        controller_id = snapshot.controller_id
        failures = self._failures.get(controller_id, 0) + 1
        self._failures[controller_id] = failures
        retry_delays = (1, 2, 5, 10, 15)
        retry_delay = retry_delays[min(failures - 1, len(retry_delays) - 1)]
        self._next_request_at[controller_id] = monotonic() + retry_delay
        snapshot.consecutive_failures = failures
        snapshot.response_time_ms = None
        if failures >= 2:
            snapshot.online = False
            snapshot.mode = ControllerMode.OFFLINE
            snapshot.safety_status = "NO COMMUNICATION"
            for signal_group in snapshot.signal_groups:
                signal_group.aspect = "OFF"
        self.snapshot_updated.emit(controller_id)

    def _apply_status_payload(
        self,
        snapshot: ControllerSnapshot,
        payload: dict[str, Any],
    ) -> None:
        snapshot.online = True
        reported_id = self._safe_int(payload.get("controllerId"), -1)
        snapshot.reported_controller_id = (
            reported_id if reported_id >= 0 else None
        )
        snapshot.name = str(payload.get("controllerName") or snapshot.name)
        snapshot.firmware_version = str(
            payload.get("version") or snapshot.firmware_version
        )

        network = payload.get("ethernet")
        if isinstance(network, dict):
            ip_address = network.get("ip")
            if ip_address:
                snapshot.ip_address = str(ip_address)
            interface_name = str(network.get("interface", "")).upper()
            snapshot.network_interface = (
                NetworkInterface.WIFI
                if "WI" in interface_name
                else NetworkInterface.ETHERNET
            )

        snapshot.mode = self._map_mode(str(payload.get("mode", "NORMAL")))
        snapshot.safety_status = str(payload.get("safety") or "UNKNOWN")
        snapshot.current_plan = self._safe_int(payload.get("plan"), 0)
        snapshot.scheduled_plan = self._safe_int(
            payload.get("desiredPlan"),
            snapshot.current_plan,
        )
        snapshot.current_stage = self._safe_int(payload.get("stage"), 0)
        snapshot.total_stages = self._safe_int(payload.get("stageCount"), 0)
        snapshot.remaining_seconds = max(
            0,
            self._safe_int(payload.get("remaining"), 0),
        )

        raw_states = payload.get("sg")
        if not isinstance(raw_states, list):
            raw_states = []
        raw_names = payload.get("sgNames")
        if not isinstance(raw_names, list):
            raw_names = []
        active_count = self._safe_int(payload.get("activeSg"), len(raw_states))
        active_count = max(0, min(12, active_count))
        snapshot.active_signal_groups = active_count
        snapshot.signal_groups = [
            SignalGroupState(
                number=index + 1,
                name=(
                    str(raw_names[index])
                    if index < len(raw_names) and raw_names[index]
                    else f"Signal Group {index + 1}"
                ),
                aspect=self._map_signal_state(
                    self._safe_int(
                        raw_states[index] if index < len(raw_states) else 0,
                        0,
                    )
                ),
            )
            for index in range(active_count)
        ]
        signal_camera_count = sum(
            camera.signal_group is not None for camera in snapshot.cameras
        )
        if signal_camera_count != active_count:
            try:
                controller_number = int(snapshot.controller_id.rsplit("-", 1)[1])
            except (IndexError, ValueError):
                controller_number = 1
            snapshot.cameras = make_cameras(controller_number, active_count)
            self.camera_repository.apply_to_cameras(snapshot.cameras)
            for camera in snapshot.cameras:
                camera.online = False

    def _build_live_placeholders(
        self,
        entries: list[dict[str, Any]],
    ) -> list[ControllerSnapshot]:
        templates = build_mock_controllers()
        controllers: list[ControllerSnapshot] = []
        for index, entry in enumerate(entries):
            if not entry["enabled"]:
                continue
            snapshot = templates[index]
            snapshot.controller_id = entry["controllerId"]
            snapshot.name = entry["displayName"]
            snapshot.ip_address = QUrl(entry["baseUrl"]).host() or entry["baseUrl"]
            snapshot.online = False
            snapshot.mode = ControllerMode.OFFLINE
            snapshot.safety_status = "WAITING FOR DATA"
            snapshot.current_plan = 0
            snapshot.scheduled_plan = 0
            snapshot.current_stage = 0
            snapshot.total_stages = 0
            snapshot.remaining_seconds = 0
            snapshot.last_update_at = ""
            snapshot.response_time_ms = None
            snapshot.consecutive_failures = 0
            for signal_group in snapshot.signal_groups:
                signal_group.aspect = "OFF"
            for camera in snapshot.cameras:
                camera.online = False
            controllers.append(snapshot)
            self._endpoints[snapshot.controller_id] = entry["baseUrl"]
        return controllers

    def _load_registry(self) -> dict[str, Any]:
        try:
            data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Registry root must be an object")
            return {
                "mode": "live" if data.get("mode") == "live" else "mock",
                "controllers": self._normalise_entries(
                    data.get("controllers", [])
                ),
            }
        except (OSError, ValueError, json.JSONDecodeError):
            return {
                "mode": "mock",
                "controllers": _default_entries(),
            }

    def _save_registry(self) -> None:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "mode": self.mode,
            "pollIntervalMs": self.poll_interval_ms,
            "controllers": self._entries,
        }
        temporary = REGISTRY_PATH.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(REGISTRY_PATH)

    @staticmethod
    def _normalise_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        defaults = _default_entries()
        if not isinstance(entries, list):
            entries = []
        normalised: list[dict[str, Any]] = []
        for index in range(5):
            source = entries[index] if index < len(entries) else defaults[index]
            if not isinstance(source, dict):
                source = defaults[index]
            fallback = defaults[index]
            base_url = _normalise_base_url(
                str(source.get("baseUrl", fallback["baseUrl"]))
            )
            normalised.append(
                {
                    "controllerId": fallback["controllerId"],
                    "displayName": str(
                        source.get("displayName") or fallback["displayName"]
                    ),
                    "enabled": bool(source.get("enabled", False)),
                    "baseUrl": base_url,
                }
            )
        return normalised

    @staticmethod
    def _safe_int(value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _map_mode(value: str) -> ControllerMode:
        mode = value.upper()
        if "FAULT" in mode or "SAFETY" in mode:
            return ControllerMode.SAFETY
        if "HOLD" in mode:
            return ControllerMode.HOLD
        if "FLASH" in mode:
            return ControllerMode.FLASHING
        return ControllerMode.NORMAL

    @staticmethod
    def _map_signal_state(value: int) -> str:
        return {
            0: "OFF",
            1: "RED",
            2: "YELLOW",
            3: "GREEN",
            4: "YELLOW",
            5: "YELLOW",
            6: "YELLOW",
        }.get(value, "OFF")
