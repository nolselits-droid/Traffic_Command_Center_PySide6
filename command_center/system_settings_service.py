from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .controller_service import ControllerService


@dataclass(slots=True)
class ControllerSystemSettings:
    controller_id: int = 1
    controller_name: str = "Controller"
    all_red_seconds: int = 3
    hold_duration: int = 30
    min_green_before_skip: int = 15
    startup_flashing: int = 5
    startup_all_red: int = 3
    sg_names: list[str] = field(default_factory=lambda: [""] * 12)
    sg_names_dirty: bool = False
    network_mode: int = 0
    selected_interface: str = "ETHERNET"
    static_ip: str = "0.0.0.0"
    static_subnet: str = "0.0.0.0"
    static_gateway: str = "0.0.0.0"
    static_dns: str = "0.0.0.0"
    current_ip: str = "0.0.0.0"
    system_dirty: bool = False
    restart_required: bool = False
    apply_state: str = "UNKNOWN"
    rtc_date: str = "--/--/----"
    rtc_time: str = "--:--:--"


@dataclass(slots=True)
class ControllerTimeStatus:
    rtc_available: bool = False
    rtc_valid: bool = False
    apply_busy: bool = False
    year: int = 2000
    month: int = 1
    day: int = 1
    hour: int = 0
    minute: int = 0
    second: int = 0
    date_text: str = "--/--/----"
    time_text: str = "--:--:--"

    def as_datetime(self) -> datetime | None:
        try:
            return datetime(
                self.year,
                self.month,
                self.day,
                self.hour,
                self.minute,
                self.second,
            )
        except ValueError:
            return None


@dataclass(slots=True)
class SystemActionResult:
    ok: bool
    action: str
    message: str


@dataclass(slots=True)
class _RequestJob:
    controller_id: str
    resource: str
    endpoint: str
    method: str = "GET"
    generation: int = 0


class SystemSettingsService(QObject):
    system_loaded = Signal(str, object)
    time_loaded = Signal(str, object)
    action_completed = Signal(str, str, object)
    request_failed = Signal(str, str, str)
    busy_changed = Signal(bool)

    def __init__(
        self,
        controller_service: ControllerService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller_service = controller_service
        self._network = QNetworkAccessManager(self)
        self._queue: deque[_RequestJob] = deque()
        self._reply: QNetworkReply | None = None
        self._current_job: _RequestJob | None = None
        self._generation = 0
        self._suspended_controller_id = ""

    def cancel(self) -> None:
        self._generation += 1
        self._queue.clear()
        if self._reply is not None:
            self._reply.abort()
            self._reply.deleteLater()
        self._reply = None
        self._current_job = None
        self._resume_polling()
        self.busy_changed.emit(False)

    def load_all(self, controller_id: str) -> None:
        self.cancel()
        self._enqueue(controller_id, "system", "/api/system/status")
        self._enqueue(controller_id, "time", "/api/time/status")
        self._start_next()

    def save_general(
        self,
        controller_id: str,
        reported_id: int,
        name: str,
        all_red_seconds: int,
        hold_duration: int,
        min_green: int,
    ) -> None:
        query = urlencode(
            {
                "id": reported_id,
                "name": name,
                "allred": all_red_seconds,
                "hold": hold_duration,
                "minGreen": min_green,
            }
        )
        self._enqueue_action(
            controller_id,
            "general",
            f"/api/system/save?{query}",
        )

    def save_startup(
        self,
        controller_id: str,
        flashing_seconds: int,
        all_red_seconds: int,
    ) -> None:
        query = urlencode(
            {"flashing": flashing_seconds, "allred": all_red_seconds}
        )
        self._enqueue_action(
            controller_id,
            "startup",
            f"/api/system/startup-pattern/save?{query}",
        )

    def save_signal_group_names(
        self,
        controller_id: str,
        changes: list[tuple[int, str]],
    ) -> None:
        if not self._can_write(controller_id, "sg-names"):
            return
        for number, name in changes:
            query = urlencode({"sg": number, "name": name})
            self._enqueue(
                controller_id,
                f"sg-step-{number}",
                f"/api/system/sg-name?{query}",
                method="POST",
            )
        self._enqueue(
            controller_id,
            "action:sg-names",
            "/api/system/sg-names/save",
            method="POST",
        )
        self._start_next()

    def set_time(self, controller_id: str, value: datetime) -> None:
        query = urlencode(
            {
                "year": value.year,
                "month": value.month,
                "day": value.day,
                "hour": value.hour,
                "minute": value.minute,
                "second": value.second,
            }
        )
        self._enqueue_action(
            controller_id,
            "rtc",
            f"/api/time/set?{query}",
        )

    def _enqueue_action(
        self,
        controller_id: str,
        action: str,
        endpoint: str,
    ) -> None:
        if not self._can_write(controller_id, action):
            return
        self._enqueue(
            controller_id,
            f"action:{action}",
            endpoint,
            method="POST",
        )
        self._start_next()

    def _can_write(self, controller_id: str, action: str) -> bool:
        if self._reply is not None or self._queue:
            QTimer.singleShot(
                0,
                lambda: self.request_failed.emit(
                    controller_id,
                    action,
                    "Request System Settings lain masih berjalan.",
                ),
            )
            return False
        return True

    def _enqueue(
        self,
        controller_id: str,
        resource: str,
        endpoint: str,
        *,
        method: str = "GET",
    ) -> None:
        self._queue.append(
            _RequestJob(
                controller_id=controller_id,
                resource=resource,
                endpoint=endpoint,
                method=method,
                generation=self._generation,
            )
        )

    def _start_next(self) -> None:
        if self._reply is not None:
            return
        if not self._queue:
            self._resume_polling()
            self.busy_changed.emit(False)
            return
        job = self._queue.popleft()
        if job.generation != self._generation:
            return self._start_next()
        base_url = self.controller_service.base_url(job.controller_id)
        if not base_url:
            self._fail_batch(
                job,
                "Base URL controller tidak tersedia.",
            )
            return

        if not self._suspended_controller_id:
            self._suspended_controller_id = job.controller_id
            self.controller_service.suspend_polling(
                job.controller_id,
                owner="system-settings",
            )
        self.busy_changed.emit(True)
        request = QNetworkRequest(QUrl(f"{base_url}{job.endpoint}"))
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(
            b"User-Agent",
            b"Traffic-Command-Center/0.6.00-FIX1-TEST",
        )
        request.setRawHeader(b"Connection", b"close")
        request.setTransferTimeout(5000)
        reply = (
            self._network.post(request, QByteArray())
            if job.method == "POST"
            else self._network.get(request)
        )
        self._reply = reply
        self._current_job = job
        reply.finished.connect(
            lambda current=reply, current_job=job: self._request_finished(
                current,
                current_job,
            )
        )

    def _request_finished(
        self,
        reply: QNetworkReply,
        job: _RequestJob,
    ) -> None:
        if self._reply is not reply:
            reply.deleteLater()
            return
        self._reply = None
        self._current_job = None
        if job.generation != self._generation:
            reply.deleteLater()
            return self._start_next()

        network_error = reply.error()
        raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
        reply.deleteLater()
        payload: dict[str, Any] | None = None
        if raw:
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    payload = decoded
            except json.JSONDecodeError:
                payload = None

        if payload is not None and payload.get("ok") is False:
            self._fail_batch(
                job,
                str(payload.get("message") or "Controller menolak request."),
            )
            return
        if network_error != QNetworkReply.NetworkError.NoError:
            error_name = getattr(network_error, "name", str(network_error))
            self._fail_batch(job, f"HTTP request gagal: {error_name}")
            return
        if payload is None:
            self._fail_batch(job, "Respons controller bukan JSON object yang valid.")
            return

        try:
            if job.resource == "system":
                self.system_loaded.emit(
                    job.controller_id,
                    _parse_system_settings(payload),
                )
            elif job.resource == "time":
                self.time_loaded.emit(
                    job.controller_id,
                    _parse_time_status(payload),
                )
            elif job.resource.startswith("action:"):
                action = job.resource.split(":", 1)[1]
                result = SystemActionResult(
                    ok=bool(payload.get("ok", True)),
                    action=str(payload.get("action") or action.upper()),
                    message=str(
                        payload.get("message") or "Pengaturan berhasil diperbarui."
                    ),
                )
                self.action_completed.emit(job.controller_id, action, result)
            # sg-step responses are intentionally silent; the final SAVE SG
            # NAMES response is the transaction result shown to the operator.
        except (TypeError, ValueError) as exc:
            self._fail_batch(job, str(exc))
            return
        self._start_next()

    def _fail_batch(self, job: _RequestJob, message: str) -> None:
        self._queue.clear()
        if job.resource.startswith("sg-step-") or job.resource == "action:sg-names":
            message += (
                " Beberapa nama SG mungkin sudah berada di RAM controller tetapi "
                "belum tersimpan; tekan REFRESH lalu ulangi SAVE SG NAMES."
            )
        action = job.resource.split(":", 1)[-1]
        self.request_failed.emit(job.controller_id, action, message)
        self._resume_polling()
        self.busy_changed.emit(False)

    def _resume_polling(self) -> None:
        if not self._suspended_controller_id:
            return
        controller_id = self._suspended_controller_id
        self._suspended_controller_id = ""
        self.controller_service.resume_polling(
            controller_id,
            owner="system-settings",
            refresh=True,
        )

def _parse_system_settings(payload: dict[str, Any]) -> ControllerSystemSettings:
    raw_names = payload.get("sgNames")
    names = [str(value) for value in raw_names] if isinstance(raw_names, list) else []
    names = names[:12] + [""] * max(0, 12 - len(names))
    return ControllerSystemSettings(
        controller_id=_safe_int(payload.get("controllerId"), 1),
        controller_name=str(payload.get("controllerName") or "Controller"),
        all_red_seconds=_safe_int(payload.get("allRedSeconds"), 3),
        hold_duration=_safe_int(payload.get("holdDuration"), 30),
        min_green_before_skip=_safe_int(
            payload.get("minGreenBeforeSkip"),
            15,
        ),
        startup_flashing=_safe_int(payload.get("startupFlashing"), 0),
        startup_all_red=_safe_int(payload.get("startupAllRed"), 0),
        sg_names=names,
        sg_names_dirty=bool(payload.get("sgNamesDirty", False)),
        network_mode=_safe_int(payload.get("networkMode"), 0),
        selected_interface=str(payload.get("selectedInterface") or "UNKNOWN"),
        static_ip=str(payload.get("staticIp") or "0.0.0.0"),
        static_subnet=str(payload.get("staticSubnet") or "0.0.0.0"),
        static_gateway=str(payload.get("staticGateway") or "0.0.0.0"),
        static_dns=str(payload.get("staticDns") or "0.0.0.0"),
        current_ip=str(payload.get("currentIp") or "0.0.0.0"),
        system_dirty=bool(payload.get("systemDirty", False)),
        restart_required=bool(payload.get("restartRequired", False)),
        apply_state=str(payload.get("apply") or "UNKNOWN"),
        rtc_date=str(payload.get("rtcDate") or "--/--/----"),
        rtc_time=str(payload.get("rtcTime") or "--:--:--"),
    )


def _parse_time_status(payload: dict[str, Any]) -> ControllerTimeStatus:
    return ControllerTimeStatus(
        rtc_available=bool(payload.get("rtcAvailable", False)),
        rtc_valid=bool(payload.get("rtcValid", False)),
        apply_busy=bool(payload.get("applyBusy", False)),
        year=_safe_int(payload.get("year"), 2000),
        month=_safe_int(payload.get("month"), 1),
        day=_safe_int(payload.get("day"), 1),
        hour=_safe_int(payload.get("hour"), 0),
        minute=_safe_int(payload.get("minute"), 0),
        second=_safe_int(payload.get("second"), 0),
        date_text=str(payload.get("date") or "--/--/----"),
        time_text=str(payload.get("time") or "--:--:--"),
    )


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
