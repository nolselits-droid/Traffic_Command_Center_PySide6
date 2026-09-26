from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from .models import CameraConfiguration, CameraRole


DISPLAY_LAYOUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "command_center_data"
    / "display_layouts.json"
)

INTERSECTION_TYPES = {
    "FOUR_WAY": "Four-Way Intersection",
    "T_JUNCTION": "T-Junction",
    "STRAIGHT_ROAD": "Straight Road",
    "SINGLE_APPROACH": "Single Approach",
}

VEHICLE_MOVEMENT_OPTIONS = {
    "STRAIGHT": "Straight",
    "LEFT": "Left Turn",
    "RIGHT": "Right Turn",
}

FLOW_DIRECTIONS = {
    "INBOUND": "One Way → Intersection",
    "OUTBOUND": "One Way ← Intersection",
    "TWO_WAY": "Two Way",
    "HIDDEN": "Hidden",
}


@dataclass(slots=True)
class SignalPlacement:
    x: float
    y: float
    rotation: int = -1
    movements: list[str] = field(default_factory=lambda: ["STRAIGHT"])
    flow_direction: str = "INBOUND"


@dataclass(slots=True)
class IntersectionLayoutConfig:
    diagram_type: str = "FOUR_WAY"
    rotation: int = 0
    placements: dict[int, SignalPlacement] = field(default_factory=dict)


@dataclass(slots=True)
class CameraTilePlacement:
    visible: bool = True
    row: int = 0
    column: int = 0
    row_span: int = 1
    column_span: int = 1
    order: int = 0


@dataclass(slots=True)
class CameraLayoutConfig:
    mode: str = "AUTO"
    primary_camera_id: str = ""
    tiles: dict[str, CameraTilePlacement] = field(default_factory=dict)


@dataclass(slots=True)
class ControllerDisplayLayout:
    intersection: IntersectionLayoutConfig = field(
        default_factory=IntersectionLayoutConfig
    )
    cameras: CameraLayoutConfig = field(default_factory=CameraLayoutConfig)


def _rotate_point(x: float, y: float, rotation: int) -> tuple[float, float]:
    turns = (rotation // 90) % 4
    for _ in range(turns):
        x, y = 1.0 - y, x
    return x, y


def default_signal_placements(
    diagram_type: str,
    rotation: int,
    count: int,
) -> dict[int, SignalPlacement]:
    """Return tidy defaults while still allowing all twelve SGs."""
    base_by_type = {
        "FOUR_WAY": [
            (0.68, 0.25), (0.75, 0.68), (0.32, 0.75), (0.25, 0.32),
            (0.82, 0.25), (0.75, 0.82), (0.18, 0.75), (0.25, 0.18),
            (0.54, 0.25), (0.75, 0.54), (0.46, 0.75), (0.25, 0.46),
        ],
        "T_JUNCTION": [
            (0.68, 0.25), (0.75, 0.68), (0.25, 0.68),
            (0.82, 0.25), (0.75, 0.82), (0.25, 0.82),
            (0.54, 0.25), (0.75, 0.54), (0.25, 0.54),
            (0.40, 0.25), (0.88, 0.68), (0.12, 0.68),
        ],
        "STRAIGHT_ROAD": [
            (0.68, 0.25), (0.32, 0.75), (0.82, 0.25), (0.18, 0.75),
            (0.54, 0.25), (0.46, 0.75), (0.40, 0.25), (0.60, 0.75),
            (0.26, 0.25), (0.74, 0.75), (0.88, 0.25), (0.12, 0.75),
        ],
        "SINGLE_APPROACH": [
            (0.68, 0.32), (0.82, 0.32), (0.54, 0.32), (0.40, 0.32),
            (0.26, 0.32), (0.88, 0.46), (0.74, 0.46), (0.60, 0.46),
            (0.46, 0.46), (0.32, 0.46), (0.18, 0.46), (0.12, 0.60),
        ],
    }
    points = base_by_type.get(diagram_type, base_by_type["FOUR_WAY"])
    placements: dict[int, SignalPlacement] = {}
    for index in range(max(0, min(12, count))):
        x, y = _rotate_point(*points[index], rotation)
        placements[index + 1] = SignalPlacement(x=x, y=y)
    return placements


def automatic_camera_positions(
    cameras: list[CameraConfiguration],
    primary_camera_id: str = "",
) -> dict[str, tuple[int, int, int, int]]:
    """Create a stable grid for the enabled/visible cameras."""
    if not cameras:
        return {}
    primary = next(
        (item for item in cameras if item.camera_id == primary_camera_id),
        None,
    )
    if primary is None:
        primary = next(
            (item for item in cameras if item.role == CameraRole.PTZ),
            None,
        )

    if primary is not None and len(cameras) > 1:
        secondary = [item for item in cameras if item is not primary]
        rows = max(1, (len(secondary) + 1) // 2)
        positions = {primary.camera_id: (0, 0, rows, 2)}
        for index, camera in enumerate(secondary):
            positions[camera.camera_id] = (
                index // 2,
                2 + index % 2,
                1,
                1,
            )
        return positions

    count = len(cameras)
    columns = 1 if count == 1 else 2 if count in {2, 4} else 3 if count <= 9 else 4
    rows = (count + columns - 1) // columns
    return {
        camera.camera_id: (index // columns, index % columns, 1, 1)
        for index, camera in enumerate(cameras)
    }


class DisplayLayoutRepository(QObject):
    """Local, per-controller presentation settings for Live View."""

    layout_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._records = self._load_records()

    def get(
        self,
        controller_id: str,
        active_signal_groups: int,
        cameras: list[CameraConfiguration],
    ) -> ControllerDisplayLayout:
        raw = self._records.get(controller_id, {})
        layout = self._decode(raw)
        layout.intersection.diagram_type = (
            layout.intersection.diagram_type
            if layout.intersection.diagram_type in INTERSECTION_TYPES
            else "FOUR_WAY"
        )
        layout.intersection.rotation = (
            layout.intersection.rotation
            if layout.intersection.rotation in {0, 90, 180, 270}
            else 0
        )
        defaults = default_signal_placements(
            layout.intersection.diagram_type,
            layout.intersection.rotation,
            active_signal_groups,
        )
        for number, placement in defaults.items():
            if number not in layout.intersection.placements:
                layout.intersection.placements[number] = placement
        layout.intersection.placements = {
            number: placement
            for number, placement in layout.intersection.placements.items()
            if 1 <= number <= max(1, active_signal_groups)
        }

        for order, camera in enumerate(cameras):
            layout.cameras.tiles.setdefault(
                camera.camera_id,
                CameraTilePlacement(
                    row=order // 4,
                    column=order % 4,
                    order=order,
                ),
            )
        return layout

    def save(self, controller_id: str, layout: ControllerDisplayLayout) -> None:
        self._records[controller_id] = self._encode(deepcopy(layout))
        self._save_records()
        self.layout_changed.emit(controller_id)

    def _load_records(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(DISPLAY_LAYOUT_PATH.read_text(encoding="utf-8"))
            records = data.get("controllers", {}) if isinstance(data, dict) else {}
            return records if isinstance(records, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _save_records(self) -> None:
        DISPLAY_LAYOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = DISPLAY_LAYOUT_PATH.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"schemaVersion": 1, "controllers": self._records},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(DISPLAY_LAYOUT_PATH)

    @staticmethod
    def _encode(layout: ControllerDisplayLayout) -> dict[str, Any]:
        data = asdict(layout)
        data["intersection"]["placements"] = {
            str(number): value
            for number, value in data["intersection"]["placements"].items()
        }
        return data

    @staticmethod
    def _decode(raw: Any) -> ControllerDisplayLayout:
        if not isinstance(raw, dict):
            raw = {}
        intersection_raw = raw.get("intersection", {})
        if not isinstance(intersection_raw, dict):
            intersection_raw = {}
        try:
            rotation = int(intersection_raw.get("rotation", 0) or 0)
        except (TypeError, ValueError):
            rotation = 0
        placements: dict[int, SignalPlacement] = {}
        raw_placements = intersection_raw.get("placements", {})
        if isinstance(raw_placements, dict):
            for key, value in raw_placements.items():
                if not isinstance(value, dict):
                    continue
                try:
                    number = int(key)
                    x = max(0.05, min(0.95, float(value.get("x", 0.5))))
                    y = max(0.05, min(0.95, float(value.get("y", 0.5))))
                except (TypeError, ValueError):
                    continue
                try:
                    signal_rotation = int(value.get("rotation", -1))
                except (TypeError, ValueError):
                    signal_rotation = -1
                if signal_rotation not in {-1, 0, 90, 180, 270}:
                    signal_rotation = -1
                raw_movements = value.get("movements")
                if isinstance(raw_movements, list):
                    movements = [
                        str(item).upper()
                        for item in raw_movements
                        if str(item).upper() in VEHICLE_MOVEMENT_OPTIONS
                    ]
                else:
                    legacy = str(
                        value.get("movement", "STRAIGHT")
                    ).upper()
                    movements = {
                        "LEFT": ["LEFT"],
                        "RIGHT": ["RIGHT"],
                        "STRAIGHT_LEFT": ["STRAIGHT", "LEFT"],
                        "STRAIGHT_RIGHT": ["STRAIGHT", "RIGHT"],
                    }.get(legacy, ["STRAIGHT"])
                if not movements:
                    movements = ["STRAIGHT"]
                flow_direction = str(
                    value.get("flow_direction", "INBOUND")
                ).upper()
                if flow_direction not in FLOW_DIRECTIONS:
                    flow_direction = "INBOUND"
                placements[number] = SignalPlacement(
                    x=x,
                    y=y,
                    rotation=signal_rotation,
                    movements=movements,
                    flow_direction=flow_direction,
                )

        camera_raw = raw.get("cameras", {})
        if not isinstance(camera_raw, dict):
            camera_raw = {}
        tiles: dict[str, CameraTilePlacement] = {}
        raw_tiles = camera_raw.get("tiles", {})
        if isinstance(raw_tiles, dict):
            for camera_id, value in raw_tiles.items():
                if not isinstance(value, dict):
                    continue
                try:
                    tiles[str(camera_id)] = CameraTilePlacement(
                        visible=bool(value.get("visible", True)),
                        row=max(0, min(3, int(value.get("row", 0)))),
                        column=max(0, min(3, int(value.get("column", 0)))),
                        row_span=max(1, min(4, int(value.get("row_span", 1)))),
                        column_span=max(1, min(4, int(value.get("column_span", 1)))),
                        order=max(0, int(value.get("order", 0))),
                    )
                except (TypeError, ValueError):
                    continue

        return ControllerDisplayLayout(
            intersection=IntersectionLayoutConfig(
                diagram_type=str(
                    intersection_raw.get("diagram_type", "FOUR_WAY")
                ),
                rotation=rotation,
                placements=placements,
            ),
            cameras=CameraLayoutConfig(
                mode=(
                    "CUSTOM"
                    if str(camera_raw.get("mode", "AUTO")).upper() == "CUSTOM"
                    else "AUTO"
                ),
                primary_camera_id=str(
                    camera_raw.get("primary_camera_id", "") or ""
                ),
                tiles=tiles,
            ),
        )
