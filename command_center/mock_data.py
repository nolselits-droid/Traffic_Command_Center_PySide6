from __future__ import annotations

from .models import (
    CameraConfiguration,
    CameraRole,
    ControllerMode,
    ControllerSnapshot,
    NetworkInterface,
    SignalGroupState,
)


APPROACH_NAMES = [
    "Arah Utara",
    "Arah Timur",
    "Arah Selatan",
    "Arah Barat",
    "Arah Timur Laut",
    "Arah Tenggara",
    "Arah Barat Daya",
    "Arah Barat Laut",
]


def make_signal_groups(count: int, active_stage: int) -> list[SignalGroupState]:
    states: list[SignalGroupState] = []
    for index in range(count):
        name = APPROACH_NAMES[index] if index < len(APPROACH_NAMES) else f"Arah SG{index + 1}"
        aspect = "GREEN" if index == (active_stage - 1) % count else "RED"
        states.append(SignalGroupState(index + 1, name, aspect))
    return states


def make_cameras(controller_number: int, count: int) -> list[CameraConfiguration]:
    cameras: list[CameraConfiguration] = []
    subnet = 20 + controller_number
    for index in range(count):
        camera_number = index + 1
        name = APPROACH_NAMES[index] if index < len(APPROACH_NAMES) else f"Arah SG{camera_number}"
        cameras.append(
            CameraConfiguration(
                camera_id=f"TLC-{controller_number:03d}-SG{camera_number}",
                name=f"Camera SG{camera_number} · {name}",
                role=CameraRole.SIGNAL_GROUP,
                signal_group=camera_number,
                host=f"192.168.{subnet}.{100 + camera_number}",
            )
        )

    cameras.append(
        CameraConfiguration(
            camera_id=f"TLC-{controller_number:03d}-PTZ",
            name="Dome / PTZ · Overview",
            role=CameraRole.PTZ,
            host=f"192.168.{subnet}.120",
        )
    )
    return cameras


def build_mock_controllers() -> list[ControllerSnapshot]:
    definitions = [
        (1, "Simpang Ahmad Yani", NetworkInterface.ETHERNET, ControllerMode.NORMAL, 1, 1, 2, 4, 18, 4),
        (2, "Simpang Sudirman", NetworkInterface.ETHERNET, ControllerMode.NORMAL, 3, 3, 1, 3, 31, 3),
        (3, "Simpang Merdeka", NetworkInterface.WIFI, ControllerMode.HOLD, 2, 2, 3, 4, 24, 4),
        (4, "Simpang Veteran", NetworkInterface.ETHERNET, ControllerMode.NORMAL, 1, 1, 4, 4, 7, 4),
        (5, "Simpang Diponegoro", NetworkInterface.WIFI, ControllerMode.NORMAL, 4, 4, 2, 3, 22, 3),
    ]

    controllers: list[ControllerSnapshot] = []
    for number, name, interface, mode, current_plan, scheduled_plan, stage, total, remaining, sg_count in definitions:
        snapshot = ControllerSnapshot(
            controller_id=f"TLC-{number:03d}",
            name=name,
            ip_address=f"192.168.10.{20 + number}",
            network_interface=interface,
            mode=mode,
            current_plan=current_plan,
            scheduled_plan=scheduled_plan,
            current_stage=stage,
            total_stages=total,
            remaining_seconds=remaining,
            last_update_at="MOCK",
            active_signal_groups=sg_count,
        )
        snapshot.signal_groups = make_signal_groups(sg_count, stage)
        snapshot.cameras = make_cameras(number, sg_count)
        controllers.append(snapshot)

    controllers[2].cameras[1].online = False
    return controllers
