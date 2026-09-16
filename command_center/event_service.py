from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from .controller_service import ControllerService
from .models import ControllerMode, ControllerSnapshot


EVENT_DATABASE_PATH = (
    Path(__file__).resolve().parent.parent
    / "command_center_data"
    / "events.db"
)


@dataclass(slots=True)
class EventRecord:
    event_id: int
    occurred_at: str
    resolved_at: str | None
    controller_id: str
    controller_name: str
    category: str
    severity: str
    message: str
    event_key: str | None
    is_active: bool
    acknowledged: bool
    acknowledged_at: str | None
    details: str


class EventService(QObject):
    """Persistent event/alarm journal and transition detector."""

    events_changed = Signal()
    active_alarm_count_changed = Signal(int, int, int)

    def __init__(
        self,
        controller_service: ControllerService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller_service = controller_service
        self.database_path = EVENT_DATABASE_PATH
        self._active_keys: set[str] = set()
        self._camera_states: dict[str, bool] = {}
        self._initialise_database()
        self._load_active_keys()
        self._remove_expired_events(days=90)

        controller_service.snapshot_updated.connect(
            self._controller_snapshot_updated
        )
        controller_service.controllers_changed.connect(
            self._controllers_changed
        )
        self._controllers_changed()
        self._emit_counts()

    def query_events(
        self,
        *,
        controller_id: str = "",
        severity: str = "",
        state: str = "all",
        search: str = "",
        limit: int = 2000,
    ) -> list[EventRecord]:
        clauses: list[str] = []
        values: list[Any] = []
        if controller_id:
            clauses.append("controller_id = ?")
            values.append(controller_id)
        if severity:
            clauses.append("severity = ?")
            values.append(severity)
        if state == "active":
            clauses.append("is_active = 1")
        elif state == "unacknowledged":
            clauses.append("is_active = 1 AND acknowledged = 0")
        elif state == "resolved":
            clauses.append("resolved_at IS NOT NULL")
        if search:
            clauses.append(
                "(controller_name LIKE ? OR category LIKE ? OR message LIKE ?)"
            )
            pattern = f"%{search}%"
            values.extend([pattern, pattern, pattern])

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, occurred_at, resolved_at, controller_id, "
            "controller_name, category, severity, message, event_key, "
            "is_active, acknowledged, acknowledged_at, details "
            f"FROM events{where} ORDER BY id DESC LIMIT ?"
        )
        values.append(max(1, min(10000, limit)))
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        return [self._record_from_row(row) for row in rows]

    def summary(self) -> dict[str, int]:
        today = datetime.now().date().isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN is_active = 1 AND severity = 'CRITICAL'
                             THEN 1 ELSE 0 END),
                    SUM(CASE WHEN is_active = 1 AND severity = 'WARNING'
                             THEN 1 ELSE 0 END),
                    SUM(CASE WHEN is_active = 1 AND acknowledged = 0
                                  AND severity IN ('CRITICAL', 'WARNING')
                             THEN 1 ELSE 0 END),
                    SUM(CASE WHEN substr(occurred_at, 1, 10) = ?
                             THEN 1 ELSE 0 END)
                FROM events
                """,
                (today,),
            ).fetchone()
        return {
            "critical": int(row[0] or 0),
            "warning": int(row[1] or 0),
            "unacknowledged": int(row[2] or 0),
            "today": int(row[3] or 0),
        }

    def acknowledge(self, event_ids: list[int]) -> int:
        unique_ids = sorted({int(item) for item in event_ids if int(item) > 0})
        if not unique_ids:
            return 0
        placeholders = ",".join("?" for _ in unique_ids)
        now = self._timestamp()
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE events
                   SET acknowledged = 1, acknowledged_at = ?
                 WHERE id IN ({placeholders})
                   AND severity IN ('CRITICAL', 'WARNING')
                   AND acknowledged = 0
                """,
                [now, *unique_ids],
            )
            count = cursor.rowcount
        if count:
            self.events_changed.emit()
            self._emit_counts()
        return count

    def acknowledge_all_active(self) -> int:
        now = self._timestamp()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE events
                   SET acknowledged = 1, acknowledged_at = ?
                 WHERE is_active = 1
                   AND severity IN ('CRITICAL', 'WARNING')
                   AND acknowledged = 0
                """,
                (now,),
            )
            count = cursor.rowcount
        if count:
            self.events_changed.emit()
            self._emit_counts()
        return count

    def export_csv(
        self,
        path: str | Path,
        *,
        controller_id: str = "",
        severity: str = "",
        state: str = "all",
        search: str = "",
    ) -> int:
        records = self.query_events(
            controller_id=controller_id,
            severity=severity,
            state=state,
            search=search,
            limit=10000,
        )
        destination = Path(path)
        with destination.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "Time",
                    "Resolved",
                    "Controller ID",
                    "Controller Name",
                    "Severity",
                    "Category",
                    "Event",
                    "Active",
                    "Acknowledged",
                    "Acknowledged At",
                    "Details",
                ]
            )
            for record in records:
                writer.writerow(
                    [
                        record.occurred_at,
                        record.resolved_at or "",
                        record.controller_id,
                        record.controller_name,
                        record.severity,
                        record.category,
                        record.message,
                        "YES" if record.is_active else "NO",
                        "YES" if record.acknowledged else "NO",
                        record.acknowledged_at or "",
                        record.details,
                    ]
                )
        return len(records)

    def record_audit(
        self,
        controller_id: str,
        controller_name: str,
        message: str,
        *,
        details: str = "",
    ) -> None:
        self._insert_event(
            controller_id=controller_id,
            controller_name=controller_name,
            category="AUDIT",
            severity="AUDIT",
            message=message,
            details=details,
        )

    def reset_monitoring_state(self) -> None:
        """Close stale alarms before the monitored controller set changes."""
        if not self._active_keys:
            self._camera_states.clear()
            return
        now = self._timestamp()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE events
                   SET is_active = 0, resolved_at = ?
                 WHERE is_active = 1
                """,
                (now,),
            )
        self._active_keys.clear()
        self._camera_states.clear()
        self.events_changed.emit()
        self._emit_counts()

    def handle_camera_status(
        self,
        controller_id: str,
        camera_id: str,
        camera_name: str,
        online: bool,
    ) -> None:
        key = f"{controller_id}:camera:{camera_id}"
        previous = self._camera_states.get(key)
        self._camera_states[key] = online
        snapshot = self.controller_service.get_controller(controller_id)
        controller_name = snapshot.name if snapshot else controller_id
        if online:
            self._resolve_alarm(
                key,
                controller_id,
                controller_name,
                "CAMERA",
                f"{camera_name} kembali online",
            )
        elif previous is not False:
            self._open_alarm(
                key,
                controller_id,
                controller_name,
                "CAMERA",
                "WARNING",
                f"{camera_name} offline",
            )

    def _controllers_changed(self) -> None:
        for snapshot in self.controller_service.controllers:
            self._observe_snapshot(snapshot)

    def _controller_snapshot_updated(self, controller_id: str) -> None:
        snapshot = self.controller_service.get_controller(controller_id)
        if snapshot:
            self._observe_snapshot(snapshot)

    def _observe_snapshot(self, snapshot: ControllerSnapshot) -> None:
        base = snapshot.controller_id
        waiting = snapshot.safety_status.upper() == "WAITING FOR DATA"
        offline_key = f"{base}:communication"
        if snapshot.online:
            self._resolve_alarm(
                offline_key,
                base,
                snapshot.name,
                "COMMUNICATION",
                "Komunikasi controller kembali normal",
            )
        elif not waiting:
            self._open_alarm(
                offline_key,
                base,
                snapshot.name,
                "COMMUNICATION",
                "CRITICAL",
                "Controller tidak dapat dihubungi",
                details=(
                    f"Consecutive failures: {snapshot.consecutive_failures}"
                ),
            )

        mode_definitions = {
            ControllerMode.HOLD: (
                "WARNING",
                "Controller berada pada mode HOLD",
            ),
            ControllerMode.FLASHING: (
                "WARNING",
                "Controller berada pada mode FLASHING",
            ),
            ControllerMode.SAFETY: (
                "CRITICAL",
                "Controller berada pada mode SAFETY",
            ),
        }
        for mode, (severity, message) in mode_definitions.items():
            key = f"{base}:mode:{mode.value.lower()}"
            if snapshot.online and snapshot.mode == mode:
                self._open_alarm(
                    key,
                    base,
                    snapshot.name,
                    "OPERATION MODE",
                    severity,
                    message,
                )
            elif snapshot.online:
                self._resolve_alarm(
                    key,
                    base,
                    snapshot.name,
                    "OPERATION MODE",
                    f"Mode {mode.value} selesai",
                )

        safety = snapshot.safety_status.strip() or "UNKNOWN"
        safety_upper = safety.upper()
        safety_key = f"{base}:safety"
        normal_safety = safety_upper in {
            "OK",
            "NORMAL",
            "READY",
            "WAITING FOR DATA",
            "NO COMMUNICATION",
        }
        if snapshot.online and not normal_safety:
            critical_tokens = (
                "CONFLICT",
                "FAULT",
                "INVALID",
                "ERROR",
                "FAIL",
            )
            severity = (
                "CRITICAL"
                if any(token in safety_upper for token in critical_tokens)
                else "WARNING"
            )
            self._open_alarm(
                safety_key,
                base,
                snapshot.name,
                "SAFETY",
                severity,
                f"Safety status: {safety}",
            )
        elif snapshot.online and normal_safety:
            self._resolve_alarm(
                safety_key,
                base,
                snapshot.name,
                "SAFETY",
                "Safety status kembali normal",
            )

    def _open_alarm(
        self,
        event_key: str,
        controller_id: str,
        controller_name: str,
        category: str,
        severity: str,
        message: str,
        *,
        details: str = "",
    ) -> None:
        if event_key in self._active_keys:
            return
        self._insert_event(
            controller_id=controller_id,
            controller_name=controller_name,
            category=category,
            severity=severity,
            message=message,
            event_key=event_key,
            is_active=True,
            details=details,
        )
        self._active_keys.add(event_key)

    def _resolve_alarm(
        self,
        event_key: str,
        controller_id: str,
        controller_name: str,
        category: str,
        recovery_message: str,
    ) -> None:
        if event_key not in self._active_keys:
            return
        now = self._timestamp()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE events
                   SET is_active = 0, resolved_at = ?
                 WHERE event_key = ? AND is_active = 1
                """,
                (now, event_key),
            )
        self._active_keys.discard(event_key)
        self._insert_event(
            controller_id=controller_id,
            controller_name=controller_name,
            category=category,
            severity="INFO",
            message=recovery_message,
        )

    def _insert_event(
        self,
        *,
        controller_id: str,
        controller_name: str,
        category: str,
        severity: str,
        message: str,
        event_key: str | None = None,
        is_active: bool = False,
        details: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events (
                    occurred_at, controller_id, controller_name, category,
                    severity, message, event_key, is_active, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._timestamp(),
                    controller_id,
                    controller_name,
                    category,
                    severity,
                    message,
                    event_key,
                    int(is_active),
                    details,
                ),
            )
        self.events_changed.emit()
        self._emit_counts()

    def _initialise_database(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    resolved_at TEXT,
                    controller_id TEXT NOT NULL,
                    controller_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    event_key TEXT,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    acknowledged INTEGER NOT NULL DEFAULT 0,
                    acknowledged_at TEXT,
                    details TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_time "
                "ON events(occurred_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_active "
                "ON events(is_active, severity)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_controller "
                "ON events(controller_id, occurred_at DESC)"
            )

    def _load_active_keys(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_key FROM events "
                "WHERE is_active = 1 AND event_key IS NOT NULL"
            ).fetchall()
        self._active_keys = {str(row[0]) for row in rows}

    def _remove_expired_events(self, *, days: int) -> None:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(
            timespec="seconds"
        )
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM events WHERE is_active = 0 AND occurred_at < ?",
                (cutoff,),
            )

    def _emit_counts(self) -> None:
        counts = self.summary()
        self.active_alarm_count_changed.emit(
            counts["critical"],
            counts["warning"],
            counts["unacknowledged"],
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=3.0)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            event_id=int(row["id"]),
            occurred_at=str(row["occurred_at"]),
            resolved_at=row["resolved_at"],
            controller_id=str(row["controller_id"]),
            controller_name=str(row["controller_name"]),
            category=str(row["category"]),
            severity=str(row["severity"]),
            message=str(row["message"]),
            event_key=row["event_key"],
            is_active=bool(row["is_active"]),
            acknowledged=bool(row["acknowledged"]),
            acknowledged_at=row["acknowledged_at"],
            details=str(row["details"]),
        )
