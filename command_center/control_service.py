from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .controller_service import ControllerService


class ControlService(QObject):
    """Sends one guarded traffic-control command at a time."""

    completed = Signal(str, str, object)
    failed = Signal(str, str, str)
    busy_changed = Signal(bool)

    def __init__(self, controller_service: ControllerService, parent=None) -> None:
        super().__init__(parent)
        self.controller_service = controller_service
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._controller_id = ""
        self._action = ""

    def send(self, controller_id: str, action: str, active: bool | None = None) -> None:
        if self._reply is not None:
            self.failed.emit(controller_id, action, "Perintah lain masih diproses.")
            return
        base_url = self.controller_service.base_url(controller_id)
        if not base_url:
            self.failed.emit(controller_id, action, "Base URL controller tidak tersedia.")
            return
        endpoints = {
            "skip": "/api/control/skip",
            "hold": "/api/control/hold",
            "flashing": "/api/control/flashing",
        }
        endpoint = endpoints.get(action)
        if endpoint is None:
            self.failed.emit(controller_id, action, "Perintah Traffic Control tidak dikenal.")
            return
        if active is not None:
            endpoint += "?" + urlencode({"active": 1 if active else 0})

        self._controller_id = controller_id
        self._action = action
        self.controller_service.suspend_polling(controller_id, owner="traffic-control")
        self.busy_changed.emit(True)
        request = QNetworkRequest(QUrl(f"{base_url}{endpoint}"))
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"Traffic-Command-Center/0.5.05-FIX7-TEST")
        request.setTransferTimeout(4500)
        reply = self._network.post(request, QByteArray())
        self._reply = reply
        reply.finished.connect(lambda current=reply: self._finished(current))

    def _finished(self, reply: QNetworkReply) -> None:
        if self._reply is not reply:
            reply.deleteLater()
            return
        controller_id = self._controller_id
        action = self._action
        self._reply = None
        self._controller_id = ""
        self._action = ""
        raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
        network_error = reply.error()
        reply.deleteLater()
        payload: dict[str, Any] | None = None
        try:
            decoded = json.loads(raw) if raw else None
            if isinstance(decoded, dict):
                payload = decoded
        except json.JSONDecodeError:
            pass

        self.busy_changed.emit(False)
        self.controller_service.resume_polling(
            controller_id, owner="traffic-control", refresh=True
        )
        if payload is not None and not bool(payload.get("ok", False)):
            self.failed.emit(
                controller_id,
                action,
                str(payload.get("message") or "Perintah ditolak controller."),
            )
        elif network_error != QNetworkReply.NetworkError.NoError or payload is None:
            self.failed.emit(controller_id, action, "Controller tidak dapat merespons perintah.")
        else:
            self.completed.emit(controller_id, action, payload)
        QTimer.singleShot(250, self.controller_service.poll_now)
