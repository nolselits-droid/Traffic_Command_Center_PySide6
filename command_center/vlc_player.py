from __future__ import annotations

import os
import struct
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .models import CameraConfiguration


_VLC_DLL_DIRECTORY_HANDLE = None


def _prepare_windows_vlc_path() -> None:
    global _VLC_DLL_DIRECTORY_HANDLE
    if not sys.platform.startswith("win"):
        return

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get(
        "ProgramFiles(x86)",
        r"C:\Program Files (x86)",
    )
    roots = (
        [program_files, program_files_x86]
        if struct.calcsize("P") * 8 == 64
        else [program_files_x86, program_files]
    )
    for root in roots:
        vlc_directory = Path(root) / "VideoLAN" / "VLC"
        if not (vlc_directory / "libvlc.dll").exists():
            continue
        os.environ.setdefault(
            "VLC_PLUGIN_PATH",
            str(vlc_directory / "plugins"),
        )
        if hasattr(os, "add_dll_directory"):
            _VLC_DLL_DIRECTORY_HANDLE = os.add_dll_directory(
                str(vlc_directory)
            )
        break


_prepare_windows_vlc_path()

try:
    import vlc
except (ImportError, OSError) as exc:
    vlc = None
    VLC_IMPORT_ERROR = str(exc)
else:
    VLC_IMPORT_ERROR = ""


class VlcRuntime:
    _instance: Any = None
    _error = VLC_IMPORT_ERROR

    @classmethod
    def instance(cls):
        if cls._instance is not None:
            return cls._instance
        if vlc is None:
            return None
        try:
            cls._instance = vlc.Instance(
                "--no-video-title-show",
                "--verbose=0",
            )
        except Exception as exc:  # libVLC may be missing or wrong architecture.
            cls._error = str(exc)
            cls._instance = None
        return cls._instance

    @classmethod
    def error_message(cls) -> str:
        if cls._error:
            return cls._error
        if vlc is None:
            return "python-vlc belum terpasang"
        return "libVLC tidak ditemukan"


def build_rtsp_url(
    camera: CameraConfiguration,
    *,
    main_stream: bool,
    include_credentials: bool = True,
) -> str:
    path = camera.main_path if main_stream else camera.sub_path
    path = path.strip()
    host = camera.host.strip()

    if path.lower().startswith("rtsp://"):
        raw_url = path
    elif host.lower().startswith("rtsp://"):
        host_parts = urlsplit(host)
        if host_parts.path and host_parts.path != "/":
            # A complete RTSP URL was entered in the host field.
            raw_url = host
        else:
            raw_url = host.rstrip("/")
            if path:
                raw_url += "/" + path.lstrip("/")
    else:
        raw_url = f"rtsp://{host}:{camera.port}/{path.lstrip('/')}"

    parts = urlsplit(raw_url)
    if include_credentials and camera.username and "@" not in parts.netloc:
        username = quote(camera.username, safe="")
        password = quote(camera.password, safe="")
        credentials = username if not password else f"{username}:{password}"
        parts = parts._replace(netloc=f"{credentials}@{parts.netloc}")
    return urlunsplit(parts)


class VlcPlayerController:
    def __init__(self) -> None:
        self._runtime = VlcRuntime.instance()
        self._player = None
        self._target: QWidget | None = None
        self._last_error = ""

    @property
    def available(self) -> bool:
        return self._runtime is not None

    def play(
        self,
        target: QWidget,
        url: str,
        caching_ms: int = 1200,
        *,
        username: str = "",
        password: str = "",
    ) -> bool:
        self.stop()
        if self._runtime is None or not url:
            self._last_error = VlcRuntime.error_message()
            return False
        try:
            target.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
            target.show()
            player = self._runtime.media_player_new()
            media = self._runtime.media_new(url)
            media.add_option(":rtsp-tcp")
            media.add_option(f":network-caching={caching_ms}")
            media.add_option(f":live-caching={caching_ms}")
            if username:
                media.add_option(f":rtsp-user={username}")
            if password:
                media.add_option(f":rtsp-pwd={password}")
            media.add_option(":clock-jitter=0")
            media.add_option(":clock-synchro=0")
            player.set_media(media)
            player.audio_set_mute(True)
            player.video_set_key_input(False)
            player.video_set_mouse_input(False)
            self._player = player
            self._target = target
            self._bind_video_target()
            result = player.play()
            if result == -1:
                self._last_error = "libVLC menolak perintah play"
                self.stop()
                return False
            self._last_error = ""
            return True
        except Exception as exc:
            self._last_error = str(exc)
            self.stop()
            return False

    def rebind_video_target(self) -> None:
        if self._player is not None and self._target is not None:
            self._bind_video_target()

    def _bind_video_target(self) -> None:
        if self._player is None or self._target is None:
            return
        window_id = int(self._target.winId())
        if sys.platform.startswith("win"):
            self._player.set_hwnd(window_id)
        elif sys.platform == "darwin":
            self._player.set_nsobject(window_id)
        else:
            self._player.set_xwindow(window_id)

    def stop(self) -> None:
        if self._player is None:
            return
        try:
            self._player.stop()
            self._player.release()
        except Exception:
            pass
        self._player = None
        self._target = None

    def state_name(self) -> str:
        if self._player is None:
            return "Stopped"
        try:
            return str(self._player.get_state()).rsplit(".", 1)[-1]
        except Exception:
            return "Error"

    def last_error_message(self) -> str:
        return self._last_error or "Unknown libVLC error"


class FullscreenCameraDialog(QDialog):
    def __init__(
        self,
        camera: CameraConfiguration,
        parent: QWidget | None = None,
        *,
        main_stream: bool = True,
    ) -> None:
        super().__init__(parent)
        self.camera = camera
        self.main_stream = main_stream
        self.player = VlcPlayerController()
        self._connect_ticks = 0
        self._rebound = False
        self.setWindowTitle(camera.name)
        self.setStyleSheet("background-color:#03070b;color:#ffffff;")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        header = QHBoxLayout()
        stream_name = "MAIN STREAM" if main_stream else "SUBSTREAM"
        title = QLabel(f"{camera.name} · {stream_name}")
        title.setStyleSheet("font-size:16px;font-weight:600;")
        close_button = QPushButton("CLOSE · ESC")
        close_button.clicked.connect(self.close)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_button)
        root.addLayout(header)

        self.video_surface = QFrame()
        self.video_surface.setStyleSheet("background-color:#000000;")
        self.video_surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        root.addWidget(self.video_surface, 1)

        self.status_label = QLabel(f"Connecting {stream_name.lower()}...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.status_label)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(600)
        self.poll_timer.timeout.connect(self._poll_state)

    def open_fullscreen(self) -> None:
        self.showFullScreen()
        QTimer.singleShot(50, self._start)
        self.exec()

    def open_preview(self) -> None:
        self.resize(960, 560)
        self.show()
        QTimer.singleShot(50, self._start)
        self.exec()

    def _start(self) -> None:
        if not self.player.available:
            self.status_label.setText(
                "VLC tidak tersedia · " + VlcRuntime.error_message()
            )
            return
        url = build_rtsp_url(
            self.camera,
            main_stream=self.main_stream,
            include_credentials=False,
        )
        if self.player.play(
            self.video_surface,
            url,
            caching_ms=self.camera.rtsp_cache_ms,
            username=self.camera.username,
            password=self.camera.password,
        ):
            self._connect_ticks = 0
            self._rebound = False
            self.poll_timer.start()
        else:
            self.status_label.setText(
                "Gagal membuka stream RTSP · "
                + self.player.last_error_message()
            )

    def _poll_state(self) -> None:
        state = self.player.state_name()
        if state == "Playing":
            if not self._rebound:
                self.player.rebind_video_target()
                self._rebound = True
            self.status_label.setText(
                "LIVE · video bound · double-click/ESC untuk kembali"
            )
        elif state in {"Error", "Ended", "Stopped"}:
            self.status_label.setText(
                f"Stream {state.upper()} · periksa URL, autentikasi, dan codec"
            )
        else:
            self._connect_ticks += 1
            self.status_label.setText(
                f"RTSP {state.upper()} · {self._connect_ticks * 0.6:.1f} s"
            )
            if self._connect_ticks >= 20:
                self.poll_timer.stop()
                self.player.stop()
                self.status_label.setText(
                    "RTSP TIMEOUT 12 s · periksa URL, user/password, dan port 554"
                )

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.close()
        event.accept()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.poll_timer.stop()
        self.player.stop()
        super().closeEvent(event)
