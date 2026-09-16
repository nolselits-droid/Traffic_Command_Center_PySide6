from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from .controller_service import ControllerService


SIGNAL_STATE_NAMES = {
    0: "OFF",
    1: "RED",
    2: "YELLOW",
    3: "GREEN",
    4: "FLASH YELLOW 500",
    5: "FLASH YELLOW 1000",
    6: "RED + YELLOW",
}


@dataclass(slots=True)
class TrafficEditorStatus:
    editing: bool
    modified: bool
    config_dirty: bool
    config_revision: int
    runtime_revision: int
    apply_state: str
    apply_busy: bool
    safety: str
    active_sg: int
    plan_count: int
    schedule_count: int
    holiday_count: int
    conflict_count: int
    loaded_at: str = field(default_factory=lambda: _timestamp())


@dataclass(slots=True)
class TrafficSystemConfig:
    editing: bool
    source: str
    active_sg: int
    sg_names: list[str]


@dataclass(slots=True)
class PlanSummary:
    number: int
    stage_count: int


@dataclass(slots=True)
class PlansIndex:
    editing: bool
    source: str
    plans: list[PlanSummary]


@dataclass(slots=True)
class StageConfig:
    number: int
    duration_seconds: int
    signal_states: list[int]


@dataclass(slots=True)
class PlanConfig:
    editing: bool
    source: str
    number: int
    stages: list[StageConfig]


@dataclass(slots=True)
class ScheduleEntryConfig:
    slot: int
    plan: int
    hour: int
    minute: int


@dataclass(slots=True)
class ScheduleDayConfig:
    editing: bool
    source: str
    day: int
    day_name: str
    entries: list[ScheduleEntryConfig]


@dataclass(slots=True)
class HolidayConfig:
    slot: int
    day: int
    month: int
    year: int

    @property
    def defined(self) -> bool:
        return self.year > 0


@dataclass(slots=True)
class HolidaysConfig:
    editing: bool
    source: str
    entries: list[HolidayConfig]


def parse_editor_status(payload: dict[str, Any]) -> TrafficEditorStatus:
    _require_ok(payload)
    return TrafficEditorStatus(
        editing=bool(payload.get("editing", False)),
        modified=bool(payload.get("modified", False)),
        config_dirty=bool(payload.get("configDirty", False)),
        config_revision=_safe_int(payload.get("configRevision"), 0),
        runtime_revision=_safe_int(payload.get("runtimeRevision"), 0),
        apply_state=str(payload.get("applyState") or "UNKNOWN"),
        apply_busy=bool(payload.get("applyBusy", False)),
        safety=str(payload.get("safety") or "UNKNOWN"),
        active_sg=max(0, min(12, _safe_int(payload.get("activeSg"), 0))),
        plan_count=max(0, _safe_int(payload.get("planCount"), 0)),
        schedule_count=max(0, _safe_int(payload.get("scheduleCount"), 0)),
        holiday_count=max(0, _safe_int(payload.get("holidayCount"), 0)),
        conflict_count=max(0, _safe_int(payload.get("conflictCount"), 0)),
    )


def parse_system_config(payload: dict[str, Any]) -> TrafficSystemConfig:
    _require_ok(payload)
    names = payload.get("sgNames")
    if not isinstance(names, list):
        names = []
    return TrafficSystemConfig(
        editing=bool(payload.get("editing", False)),
        source=str(payload.get("source") or "UNKNOWN"),
        active_sg=max(0, min(12, _safe_int(payload.get("activeSg"), 0))),
        sg_names=[str(value or "") for value in names[:12]],
    )


def parse_plans_index(payload: dict[str, Any]) -> PlansIndex:
    _require_ok(payload)
    raw_plans = payload.get("plans")
    if not isinstance(raw_plans, list):
        raise ValueError("Field plans tidak ditemukan.")
    plans: list[PlanSummary] = []
    for raw in raw_plans:
        if not isinstance(raw, dict):
            continue
        number = _safe_int(raw.get("plan"), 0)
        if 1 <= number <= 24:
            plans.append(
                PlanSummary(
                    number=number,
                    stage_count=max(0, min(24, _safe_int(raw.get("stages"), 0))),
                )
            )
    return PlansIndex(
        editing=bool(payload.get("editing", False)),
        source=str(payload.get("source") or "UNKNOWN"),
        plans=plans,
    )


def parse_plan(payload: dict[str, Any]) -> PlanConfig:
    _require_ok(payload)
    raw_stages = payload.get("stageList")
    if not isinstance(raw_stages, list):
        raise ValueError("Field stageList tidak ditemukan.")
    stages: list[StageConfig] = []
    for raw in raw_stages:
        if not isinstance(raw, dict):
            continue
        states = raw.get("sg")
        if not isinstance(states, list):
            states = []
        stages.append(
            StageConfig(
                number=_safe_int(raw.get("stage"), len(stages) + 1),
                duration_seconds=max(0, _safe_int(raw.get("duration"), 0)),
                signal_states=[_safe_int(value, 0) for value in states[:12]],
            )
        )
    return PlanConfig(
        editing=bool(payload.get("editing", False)),
        source=str(payload.get("source") or "UNKNOWN"),
        number=_safe_int(payload.get("plan"), 0),
        stages=stages,
    )


def parse_schedule(payload: dict[str, Any]) -> ScheduleDayConfig:
    _require_ok(payload)
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("Field entries schedule tidak ditemukan.")
    entries: list[ScheduleEntryConfig] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        entries.append(
            ScheduleEntryConfig(
                slot=_safe_int(raw.get("slot"), len(entries) + 1),
                plan=max(0, _safe_int(raw.get("plan"), 0)),
                hour=max(0, min(23, _safe_int(raw.get("hour"), 0))),
                minute=max(0, min(59, _safe_int(raw.get("minute"), 0))),
            )
        )
    return ScheduleDayConfig(
        editing=bool(payload.get("editing", False)),
        source=str(payload.get("source") or "UNKNOWN"),
        day=_safe_int(payload.get("day"), 0),
        day_name=str(payload.get("dayName") or "UNKNOWN"),
        entries=entries,
    )


def parse_holidays(payload: dict[str, Any]) -> HolidaysConfig:
    _require_ok(payload)
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("Field entries holiday tidak ditemukan.")
    entries: list[HolidayConfig] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        entries.append(
            HolidayConfig(
                slot=_safe_int(raw.get("slot"), len(entries) + 1),
                day=max(0, _safe_int(raw.get("day"), 0)),
                month=max(0, _safe_int(raw.get("month"), 0)),
                year=max(0, _safe_int(raw.get("year"), 0)),
            )
        )
    return HolidaysConfig(
        editing=bool(payload.get("editing", False)),
        source=str(payload.get("source") or "UNKNOWN"),
        entries=entries,
    )


class TrafficConfigService(QObject):
    status_loaded = Signal(str, object)
    system_loaded = Signal(str, object)
    plans_loaded = Signal(str, object)
    plan_loaded = Signal(str, int, object)
    schedule_loaded = Signal(str, int, object)
    holidays_loaded = Signal(str, object)
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
        self._queue: deque[
            tuple[str, str, str, Callable[[dict[str, Any]], Any], int]
        ] = deque()
        self._reply: QNetworkReply | None = None
        self._current_key: tuple[str, str] | None = None
        self._generation = 0

    def cancel(self) -> None:
        self._generation += 1
        self._queue.clear()
        if self._reply:
            self._reply.abort()
            self._reply = None
        self._current_key = None
        self.busy_changed.emit(False)

    def load_initial(self, controller_id: str) -> None:
        self.cancel()
        if self.controller_service.is_live:
            self._enqueue(
                controller_id,
                "status",
                "/api/editor/status",
                parse_editor_status,
            )
            self._enqueue(
                controller_id,
                "system",
                "/api/editor/system",
                parse_system_config,
            )
            self._enqueue(
                controller_id,
                "plans",
                "/api/editor/plans",
                parse_plans_index,
            )
            self._start_next()
        else:
            self._load_mock_initial(controller_id)

    def load_plan(self, controller_id: str, plan_number: int) -> None:
        if not 1 <= plan_number <= 24:
            return
        if self.controller_service.is_live:
            self._drop_queued(controller_id, "plan-")
            self._enqueue(
                controller_id,
                f"plan-{plan_number}",
                f"/api/editor/plan?plan={plan_number}",
                parse_plan,
            )
            self._start_next()
        else:
            QTimer.singleShot(
                0,
                lambda: self.plan_loaded.emit(
                    controller_id,
                    plan_number,
                    _mock_plan(plan_number),
                ),
            )

    def load_schedule(self, controller_id: str, day: int) -> None:
        if not 0 <= day <= 7:
            return
        if self.controller_service.is_live:
            self._drop_queued(controller_id, "schedule-")
            self._enqueue(
                controller_id,
                f"schedule-{day}",
                f"/api/editor/schedule?day={day}",
                parse_schedule,
            )
            self._start_next()
        else:
            QTimer.singleShot(
                0,
                lambda: self.schedule_loaded.emit(
                    controller_id,
                    day,
                    _mock_schedule(day),
                ),
            )

    def load_holidays(self, controller_id: str) -> None:
        if self.controller_service.is_live:
            self._enqueue(
                controller_id,
                "holidays",
                "/api/editor/holidays",
                parse_holidays,
            )
            self._start_next()
        else:
            QTimer.singleShot(
                0,
                lambda: self.holidays_loaded.emit(
                    controller_id,
                    _mock_holidays(),
                ),
            )

    def _enqueue(
        self,
        controller_id: str,
        resource: str,
        endpoint: str,
        parser: Callable[[dict[str, Any]], Any],
    ) -> None:
        duplicate = any(
            item[0] == controller_id and item[1] == resource
            for item in self._queue
        )
        if duplicate or self._current_key == (controller_id, resource):
            return
        self._queue.append(
            (controller_id, resource, endpoint, parser, self._generation)
        )

    def _drop_queued(self, controller_id: str, resource_prefix: str) -> None:
        self._queue = deque(
            item
            for item in self._queue
            if not (
                item[0] == controller_id
                and item[1].startswith(resource_prefix)
            )
        )

    def _start_next(self) -> None:
        if self._reply or not self._queue:
            if not self._reply and not self._queue:
                self.busy_changed.emit(False)
            return
        controller_id, resource, endpoint, parser, generation = self._queue.popleft()
        if generation != self._generation:
            return self._start_next()
        base_url = self.controller_service.base_url(controller_id)
        if not base_url:
            self.request_failed.emit(
                controller_id,
                resource,
                "Base URL controller tidak tersedia.",
            )
            return self._start_next()
        self.busy_changed.emit(True)
        request = QNetworkRequest(QUrl(f"{base_url}{endpoint}"))
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"Traffic-Command-Center/0.5.02")
        request.setTransferTimeout(3500)
        reply = self._network.get(request)
        self._reply = reply
        self._current_key = (controller_id, resource)
        reply.finished.connect(
            lambda current=reply, args=(
                controller_id,
                resource,
                parser,
                generation,
            ): self._request_finished(current, *args)
        )

    def _request_finished(
        self,
        reply: QNetworkReply,
        controller_id: str,
        resource: str,
        parser: Callable[[dict[str, Any]], Any],
        generation: int,
    ) -> None:
        if self._reply is not reply:
            reply.deleteLater()
            return
        self._reply = None
        self._current_key = None
        if generation != self._generation:
            reply.deleteLater()
            return self._start_next()
        error = reply.error()
        raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
        reply.deleteLater()
        if error != QNetworkReply.NetworkError.NoError:
            error_name = getattr(error, "name", str(error))
            self.request_failed.emit(
                controller_id,
                resource,
                f"HTTP request gagal: {error_name}",
            )
            return self._start_next()
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Root JSON bukan object.")
            result = parser(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            self.request_failed.emit(controller_id, resource, str(exc))
            return self._start_next()
        self._emit_result(controller_id, resource, result)
        self._start_next()

    def _emit_result(self, controller_id: str, resource: str, result: Any) -> None:
        if resource == "status":
            self.status_loaded.emit(controller_id, result)
        elif resource == "system":
            self.system_loaded.emit(controller_id, result)
        elif resource == "plans":
            self.plans_loaded.emit(controller_id, result)
        elif resource.startswith("plan-"):
            self.plan_loaded.emit(
                controller_id,
                int(resource.split("-", 1)[1]),
                result,
            )
        elif resource.startswith("schedule-"):
            self.schedule_loaded.emit(
                controller_id,
                int(resource.split("-", 1)[1]),
                result,
            )
        elif resource == "holidays":
            self.holidays_loaded.emit(controller_id, result)

    def _load_mock_initial(self, controller_id: str) -> None:
        status = TrafficEditorStatus(
            editing=False,
            modified=False,
            config_dirty=False,
            config_revision=12,
            runtime_revision=12,
            apply_state="IDLE",
            apply_busy=False,
            safety="OK",
            active_sg=4,
            plan_count=4,
            schedule_count=24,
            holiday_count=3,
            conflict_count=2,
        )
        system = TrafficSystemConfig(
            editing=False,
            source="MOCK DATA",
            active_sg=4,
            sg_names=["North", "East", "South", "West"] + [""] * 8,
        )
        plans = PlansIndex(
            editing=False,
            source="MOCK DATA",
            plans=[
                PlanSummary(number=index, stage_count=4 if index <= 4 else 0)
                for index in range(1, 25)
            ],
        )
        QTimer.singleShot(0, lambda: self.status_loaded.emit(controller_id, status))
        QTimer.singleShot(0, lambda: self.system_loaded.emit(controller_id, system))
        QTimer.singleShot(0, lambda: self.plans_loaded.emit(controller_id, plans))


def _mock_plan(plan_number: int) -> PlanConfig:
    stages: list[StageConfig] = []
    if plan_number <= 4:
        patterns = (
            [3, 1, 1, 1],
            [2, 1, 1, 1],
            [1, 1, 3, 1],
            [1, 1, 2, 1],
        )
        stages = [
            StageConfig(
                number=index + 1,
                duration_seconds=(35, 4, 30, 4)[index],
                signal_states=pattern + [0] * 8,
            )
            for index, pattern in enumerate(patterns)
        ]
    return PlanConfig(False, "MOCK DATA", plan_number, stages)


def _mock_schedule(day: int) -> ScheduleDayConfig:
    day_names = (
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Holiday",
    )
    defined = [
        ScheduleEntryConfig(1, 3, 0, 0),
        ScheduleEntryConfig(2, 1, 6, 0),
        ScheduleEntryConfig(3, 2, 16, 0),
        ScheduleEntryConfig(4, 3, 22, 0),
    ]
    entries = defined + [
        ScheduleEntryConfig(slot, 0, 0, 0) for slot in range(5, 25)
    ]
    return ScheduleDayConfig(False, "MOCK DATA", day, day_names[day], entries)


def _mock_holidays() -> HolidaysConfig:
    dates = ((17, 8, 2026), (25, 12, 2026), (1, 1, 2027))
    entries = [
        HolidayConfig(index + 1, day, month, year)
        for index, (day, month, year) in enumerate(dates)
    ]
    entries.extend(
        HolidayConfig(slot, 0, 0, 0) for slot in range(4, 33)
    )
    return HolidaysConfig(False, "MOCK DATA", entries)


def _require_ok(payload: dict[str, Any]) -> None:
    if payload.get("ok") is False:
        raise ValueError(str(payload.get("message") or "Controller menolak request."))


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
