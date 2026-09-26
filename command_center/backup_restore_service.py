from __future__ import annotations

import json
import re
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .controller_service import ControllerService


class BackupRestoreService(QObject):
    export_completed = Signal(str, object, str)
    validated = Signal(str, object)
    action_completed = Signal(str, str, object)
    failed = Signal(str, str, str)
    busy_changed = Signal(bool)
    progress_changed = Signal(str, str, int, int)

    def __init__(self, controller_service: ControllerService, parent=None) -> None:
        super().__init__(parent)
        self.controller_service = controller_service
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._controller_id = ""
        self._action = ""
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(20000)
        self._watchdog.timeout.connect(self._request_timed_out)

    def export_backup(self, controller_id: str) -> None:
        self._request(controller_id, "export", "/api/backup/export", "GET")

    def validate_backup(self, controller_id: str, content: bytes) -> None:
        if len(content) > 96 * 1024:
            self.failed.emit(controller_id, "validate", "Ukuran file melebihi batas 96 KB.")
            return
        self._request(
            controller_id, "validate", "/api/backup/validate", "POST", content,
            content_type=b"application/json",
        )

    def restore(self, controller_id: str, mode: str) -> None:
        selected = "full" if mode == "full" else "traffic"
        self._request(
            controller_id, f"restore-{selected}",
            f"/api/backup/restore?mode={selected}", "POST",
        )

    def cancel(self, controller_id: str) -> None:
        self._request(controller_id, "cancel", "/api/backup/cancel", "POST")

    def _request(
        self, controller_id: str, action: str, endpoint: str, method: str,
        body: bytes = b"", *, content_type: bytes | None = None,
    ) -> None:
        if self._reply is not None or self._action:
            self.failed.emit(controller_id, action, "Proses Backup/Restore lain masih berjalan.")
            return
        base_url = self.controller_service.base_url(controller_id)
        if not base_url:
            self.failed.emit(controller_id, action, "Base URL controller tidak tersedia.")
            return
        self._controller_id = controller_id
        self._action = action
        self.controller_service.suspend_polling(controller_id, owner="backup-restore")
        self.busy_changed.emit(True)
        # Give the ESP32 web server time to observe the aborted monitoring
        # connection before opening the larger Backup/Restore transaction.
        QTimer.singleShot(
            180,
            lambda: self._start_http_request(
                controller_id,
                action,
                base_url,
                endpoint,
                method,
                body,
                content_type,
            ),
        )

    def _start_http_request(
        self,
        controller_id: str,
        action: str,
        base_url: str,
        endpoint: str,
        method: str,
        body: bytes,
        content_type: bytes | None,
    ) -> None:
        if self._controller_id != controller_id or self._action != action:
            return
        request = QNetworkRequest(QUrl(f"{base_url}{endpoint}"))
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"Connection", b"close")
        request.setRawHeader(b"User-Agent", b"Traffic-Command-Center/0.6.00-FIX1-TEST")
        if content_type:
            request.setRawHeader(b"Content-Type", content_type)
        request.setTransferTimeout(12000)
        reply = (
            self._network.get(request)
            if method == "GET"
            else self._network.post(request, QByteArray(body))
        )
        self._reply = reply
        reply.finished.connect(lambda current=reply: self._finished(current))
        reply.downloadProgress.connect(
            lambda received, total, current=reply, key=controller_id, name=action: (
                self._download_progress(
                    current,
                    key,
                    name,
                    received,
                    total,
                )
            )
        )
        self._watchdog.start()

    def _download_progress(
        self,
        reply: QNetworkReply,
        controller_id: str,
        action: str,
        received: int,
        total: int,
    ) -> None:
        self.progress_changed.emit(
            controller_id,
            action,
            received,
            total,
        )
        if (
            action == "export"
            and self._reply is reply
        ):
            # A valid complete JSON object is a stronger completion marker
            # than connection close. It also handles a stale/mismatched
            # Content-Length reported by an embedded HTTP transport.
            QTimer.singleShot(
                0,
                lambda current=reply: self._complete_export_if_json_ready(current),
            )

    def _complete_export_if_json_ready(self, reply: QNetworkReply) -> None:
        if self._reply is not reply:
            return
        available = reply.bytesAvailable()
        if available <= 0:
            return
        try:
            preview = json.loads(
                bytes(reply.peek(available)).decode("utf-8", errors="strict")
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(preview, dict):
            return
        if preview.get("fileType") == "TLC_BACKUP" or "ok" in preview:
            self._finished(reply, content_complete=True)

    def _finished(
        self,
        reply: QNetworkReply,
        *,
        content_complete: bool = False,
    ) -> None:
        if self._reply is not reply:
            reply.deleteLater()
            return
        controller_id, action = self._controller_id, self._action
        self._watchdog.stop()
        self._reply = None
        self._controller_id = self._action = ""
        try:
            # PySide6 6.11 expects str here, while some older bindings also
            # accepted QByteArray/bytes. Use str for cross-version support.
            content_type = bytes(reply.rawHeader("Content-Type")).decode(
                "utf-8", errors="replace"
            )
            disposition = bytes(
                reply.rawHeader("Content-Disposition")
            ).decode("utf-8", errors="replace")
            raw = bytes(reply.readAll())
        except Exception as exc:  # Qt binding/API mismatch must never lock UI.
            reply.deleteLater()
            self.busy_changed.emit(False)
            self.controller_service.resume_polling(
                controller_id,
                owner="backup-restore",
                refresh=True,
            )
            self.failed.emit(
                controller_id,
                action,
                f"Respons Backup tidak dapat diproses: {exc}",
            )
            return
        network_error = (
            QNetworkReply.NetworkError.NoError
            if content_complete
            else reply.error()
        )
        if content_complete:
            # State is already detached above, therefore the finished signal
            # caused by abort cannot process the same response twice.
            reply.abort()
        reply.deleteLater()
        self.busy_changed.emit(False)
        self.controller_service.resume_polling(
            controller_id, owner="backup-restore", refresh=True
        )

        payload: dict[str, Any] | None = None
        if "json" in content_type.lower() or action != "export":
            try:
                decoded = json.loads(raw.decode("utf-8", errors="replace"))
                if isinstance(decoded, dict):
                    payload = decoded
            except json.JSONDecodeError:
                pass
        if (
            payload is not None
            and "ok" in payload
            and not bool(payload.get("ok", False))
        ):
            self.failed.emit(controller_id, action, str(payload.get("message") or "Operasi ditolak controller."))
        elif network_error != QNetworkReply.NetworkError.NoError:
            self.failed.emit(controller_id, action, "Controller tidak dapat merespons operasi.")
        elif action == "export":
            if payload is not None and "ok" in payload:
                self.failed.emit(controller_id, action, str(payload.get("message") or "Backup gagal dibuat."))
            elif payload is None or payload.get("fileType") != "TLC_BACKUP":
                self.failed.emit(
                    controller_id,
                    action,
                    "Data Backup tidak lengkap atau format JSON tidak valid. "
                    "File tidak disimpan.",
                )
            else:
                match = re.search(r'filename="?([^";]+)', disposition, re.I)
                self.export_completed.emit(controller_id, raw, match.group(1) if match else "TLC_Backup.json")
        elif payload is None:
            self.failed.emit(controller_id, action, "Respons controller bukan JSON yang valid.")
        elif action == "validate":
            self.validated.emit(controller_id, payload)
        else:
            self.action_completed.emit(controller_id, action, payload)
        QTimer.singleShot(250, self.controller_service.poll_now)

    def _request_timed_out(self) -> None:
        reply = self._reply
        controller_id, action = self._controller_id, self._action
        self._reply = None
        self._controller_id = self._action = ""
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        self.busy_changed.emit(False)
        self.controller_service.resume_polling(
            controller_id,
            owner="backup-restore",
            refresh=True,
        )
        self.failed.emit(
            controller_id,
            action,
            "Controller tidak menyelesaikan respons dalam 20 detik. "
            "Proses dibatalkan dan tombol sudah diaktifkan kembali.",
        )
