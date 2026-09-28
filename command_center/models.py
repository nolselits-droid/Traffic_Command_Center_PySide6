from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ControllerMode(str, Enum):
    NORMAL = "NORMAL"
    HOLD = "HOLD"
    FLASHING = "FLASHING"
    SAFETY = "SAFETY"
    OFFLINE = "OFFLINE"


class NetworkInterface(str, Enum):
    ETHERNET = "ETHERNET"
    WIFI = "WI-FI"


class CameraRole(str, Enum):
    SIGNAL_GROUP = "SIGNAL_GROUP"
    PTZ = "PTZ"


@dataclass(slots=True)
class CameraConfiguration:
    camera_id: str
    name: str
    role: CameraRole
    signal_group: int | None = None
    enabled: bool = True
    online: bool = True
    profile: str = "Hikvision Standard"
    host: str = "192.168.10.101"
    port: int = 554
    username: str = "admin"
    password: str = ""
    main_path: str = "/Streaming/Channels/101"
    sub_path: str = "/Streaming/Channels/102"
    rtsp_cache_ms: int = 1400


@dataclass(slots=True)
class SignalGroupState:
    number: int
    name: str
    aspect: str


@dataclass(slots=True)
class ControllerSnapshot:
    controller_id: str
    name: str
    ip_address: str
    network_interface: NetworkInterface
    reported_controller_id: int | None = None
    firmware_version: str = "V1.24 TEST4"
    online: bool = True
    mode: ControllerMode = ControllerMode.NORMAL
    safety_status: str = "OK"
    current_plan: int = 1
    scheduled_plan: int = 1
    current_stage: int = 1
    total_stages: int = 4
    remaining_seconds: int = 30
    last_update_at: str = ""
    response_time_ms: int | None = None
    consecutive_failures: int = 0
    config_revision: int = 1
    runtime_revision: int = 1
    layout_revision: int = 0
    apply_state: str = "UNKNOWN"
    config_dirty: bool = False
    editor_editing: bool = False
    editor_modified: bool = False
    web_hold_active: bool = False
    hold_active: bool = False
    hold_remaining_seconds: int = 0
    skip_pending: bool = False
    web_flashing_active: bool = False
    local_flashing_active: bool = False
    flashing_active: bool = False
    active_signal_groups: int = 4
    signal_groups: list[SignalGroupState] = field(default_factory=list)
    cameras: list[CameraConfiguration] = field(default_factory=list)

    @property
    def camera_online_count(self) -> int:
        return sum(camera.enabled and camera.online for camera in self.cameras)

    @property
    def camera_enabled_count(self) -> int:
        return sum(camera.enabled for camera in self.cameras)
