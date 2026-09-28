from __future__ import annotations

from copy import deepcopy
import json
from dataclasses import dataclass
from time import monotonic

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .display_layout import (
    DisplayLayoutRepository,
    IntersectionLayoutConfig,
    intersection_from_api,
    intersection_to_api,
)


@dataclass(slots=True)
class _LayoutRequest:
    controller_id: str
    action: str
    expected_revision: int = 0
    submitted_layout: IntersectionLayoutConfig | None = None
    notify_busy: bool = False


class IntersectionLayoutService(QObject):
    """Synchronize controller-owned Intersection Layout with an offline cache."""

    layout_loaded = Signal(str, object, int, int, str)
    save_completed = Signal(str, object, int, str)
    request_failed = Signal(str, str, str, int)
    busy_changed = Signal(str, bool)

    def __init__(
        self,
        controller_service,
        repository: DisplayLayoutRepository,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller_service = controller_service
        self.repository = repository
        self._network = QNetworkAccessManager(self)
        self._pending: dict[str, QNetworkReply] = {}
        self._jobs: dict[QNetworkReply, _LayoutRequest] = {}
        self._last_loaded_at: dict[str, float] = {}
        self._next_retry_at: dict[str, float] = {}
        self._reload_after_save: set[str] = set()
        self._observed_layout_revision: dict[str, int] = {}
        controller_service.snapshot_updated.connect(self._snapshot_updated)
        controller_service.controllers_changed.connect(self._controllers_changed)

    def refresh(
        self,
        controller_id: str,
        *,
        force: bool = False,
        interactive: bool = False,
    ) -> None:
        snapshot = self.controller_service.get_controller(controller_id)
        if snapshot is None or not snapshot.online:
            if force:
                self.request_failed.emit(
                    controller_id,
                    "load",
                    "Controller offline. Cache terakhir tetap ditampilkan.",
                    0,
                )
            return
        if controller_id in self._pending:
            return
        if not force and monotonic() < self._next_retry_at.get(controller_id, 0.0):
            return
        if self.controller_service.request_owner_active(
            controller_id,
            excluding="intersection-layout",
        ):
            if force:
                QTimer.singleShot(
                    350,
                    lambda key=controller_id, show=interactive: self.refresh(
                        key,
                        force=True,
                        interactive=show,
                    ),
                )
            return
        if not force and monotonic() - self._last_loaded_at.get(controller_id, 0.0) < 30.0:
            return
        self._start(
            controller_id,
            "load",
            notify_busy=interactive,
        )

    def save(
        self,
        controller_id: str,
        layout: IntersectionLayoutConfig,
        expected_revision: int,
    ) -> None:
        snapshot = self.controller_service.get_controller(controller_id)
        if snapshot is None or not snapshot.online:
            self.request_failed.emit(
                controller_id,
                "save",
                "Controller offline. Intersection Layout tidak disimpan.",
                0,
            )
            return
        if controller_id in self._pending:
            self.request_failed.emit(
                controller_id,
                "save",
                "Request Intersection Layout lain masih berjalan.",
                0,
            )
            return
        if self.controller_service.request_owner_active(
            controller_id,
            excluding="intersection-layout",
        ):
            self.request_failed.emit(
                controller_id,
                "save",
                "Request controller lain masih berjalan. Coba simpan kembali.",
                0,
            )
            return
        try:
            payload = intersection_to_api(layout, expected_revision)
        except ValueError as error:
            self.request_failed.emit(controller_id, "save", str(error), 0)
            return
        self._start(
            controller_id,
            "save",
            QByteArray(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
            expected_revision,
            deepcopy(layout),
            True,
        )

    def _start(
        self,
        controller_id: str,
        action: str,
        body: QByteArray | None = None,
        expected_revision: int = 0,
        submitted_layout: IntersectionLayoutConfig | None = None,
        notify_busy: bool = False,
    ) -> None:
        base_url = self.controller_service.base_url(controller_id)
        if not base_url:
            self.request_failed.emit(
                controller_id,
                action,
                "Base URL controller tidak tersedia.",
                0,
            )
            return
        self.controller_service.suspend_polling(
            controller_id,
            owner="intersection-layout",
        )
        if notify_busy:
            self.busy_changed.emit(controller_id, True)
        request = QNetworkRequest(QUrl(f"{base_url}/api/intersection/layout"))
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"Connection", b"close")
        request.setRawHeader(
            b"User-Agent",
            b"Traffic-Command-Center/0.6.01-TEST1-FIX8",
        )
        request.setTransferTimeout(6000)
        if action == "save":
            request.setRawHeader(b"Content-Type", b"application/json")
            reply = self._network.post(request, body or QByteArray())
        else:
            reply = self._network.get(request)
        self._pending[controller_id] = reply
        self._jobs[reply] = _LayoutRequest(
            controller_id=controller_id,
            action=action,
            expected_revision=expected_revision,
            submitted_layout=submitted_layout,
            notify_busy=notify_busy,
        )
        reply.finished.connect(lambda current=reply: self._finished(current))

    def _finished(self, reply: QNetworkReply) -> None:
        job = self._jobs.pop(reply, None)
        if job is None:
            reply.deleteLater()
            return
        if self._pending.get(job.controller_id) is reply:
            self._pending.pop(job.controller_id, None)
        status_value = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        try:
            status_code = int(status_value or 0)
        except (TypeError, ValueError):
            status_code = 0
        raw = bytes(reply.readAll())
        network_error = reply.error()
        network_message = reply.errorString()
        reply.deleteLater()
        self.controller_service.resume_polling(
            job.controller_id,
            owner="intersection-layout",
            refresh=job.action != "save",
        )
        if job.notify_busy:
            self.busy_changed.emit(job.controller_id, False)

        payload: dict[str, object] | None = None
        try:
            decoded = json.loads(raw.decode("utf-8")) if raw else None
            if isinstance(decoded, dict):
                payload = decoded
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None

        if (
            network_error != QNetworkReply.NetworkError.NoError
            or payload is None
            or payload.get("ok") is False
        ):
            message = (
                str(payload.get("message"))
                if payload and payload.get("message")
                else network_message
                if network_error != QNetworkReply.NetworkError.NoError
                else "Respons Intersection Layout tidak valid."
            )
            if status_code == 409:
                message = (
                    "Layout sudah berubah di controller. Tekan RELOAD sebelum "
                    "mengedit dan menyimpan kembali."
                )
            revision = 0
            if payload:
                try:
                    revision = int(payload.get("layoutRevision", 0) or 0)
                except (TypeError, ValueError):
                    revision = 0
            self.request_failed.emit(
                job.controller_id,
                job.action,
                message,
                status_code or revision,
            )
            self._next_retry_at[job.controller_id] = monotonic() + 15.0
            return

        if job.action == "save":
            try:
                revision = int(payload.get("layoutRevision", 0) or 0)
            except (TypeError, ValueError):
                revision = 0
            message = str(
                payload.get("message")
                or "Intersection Layout tersimpan di controller."
            )
            if job.submitted_layout is not None:
                self.repository.cache_intersection(
                    job.controller_id,
                    job.submitted_layout,
                    force_notify=True,
                )
            if revision > 0:
                self._observed_layout_revision[job.controller_id] = revision
            self.save_completed.emit(
                job.controller_id,
                deepcopy(job.submitted_layout),
                revision,
                message,
            )
            self._reload_after_save.add(job.controller_id)
            QTimer.singleShot(
                120,
                lambda key=job.controller_id: self.refresh(
                    key,
                    force=True,
                    interactive=False,
                ),
            )
            return

        try:
            layout, schema_version, revision = intersection_from_api(payload)
        except (TypeError, ValueError) as error:
            self.request_failed.emit(
                job.controller_id,
                "load",
                str(error),
                status_code,
            )
            return
        # The first successful controller read and every operator-initiated
        # RELOAD must redraw Live View even when the controller payload is
        # byte-for-byte equal to the offline cache.  Without this notification,
        # a view created from the startup placeholder can remain stale until a
        # SAVE happens to force an update.
        force_notify = (
            job.notify_busy
            or job.controller_id not in self._last_loaded_at
        )
        self.repository.cache_intersection(
            job.controller_id,
            layout,
            force_notify=force_notify,
        )
        if revision > 0:
            self._observed_layout_revision[job.controller_id] = revision
        self._last_loaded_at[job.controller_id] = monotonic()
        self._next_retry_at.pop(job.controller_id, None)
        source = (
            "CONTROLLER · SAVED"
            if job.controller_id in self._reload_after_save
            else "CONTROLLER · NVS"
            if bool(payload.get("saved", False))
            else "CONTROLLER · DEFAULT"
        )
        self._reload_after_save.discard(job.controller_id)
        self.layout_loaded.emit(
            job.controller_id,
            layout,
            schema_version,
            revision,
            source,
        )

    def _snapshot_updated(self, controller_id: str) -> None:
        snapshot = self.controller_service.get_controller(controller_id)
        if snapshot is None:
            return
        revision = snapshot.layout_revision
        previous = self._observed_layout_revision.get(controller_id)
        if revision > 0:
            self._observed_layout_revision[controller_id] = revision
        if revision > 0 and previous is not None and revision != previous:
            self.refresh(controller_id, force=True, interactive=False)
            return
        self.refresh(controller_id, force=False)

    def _controllers_changed(self) -> None:
        valid_ids = {
            controller.controller_id
            for controller in self.controller_service.controllers
        }
        self._last_loaded_at = {
            key: value
            for key, value in self._last_loaded_at.items()
            if key in valid_ids
        }
        self._next_retry_at = {
            key: value
            for key, value in self._next_retry_at.items()
            if key in valid_ids
        }
        self._observed_layout_revision = {
            key: value
            for key, value in self._observed_layout_revision.items()
            if key in valid_ids
        }
