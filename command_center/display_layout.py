from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from math import atan2, cos, degrees, radians, sin
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
    "FIVE_WAY": "Five-Way Intersection",
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
    "INBOUND": "One Way - Inbound",
    "OUTBOUND": "One Way - Outbound",
    "TWO_WAY": "Two Way",
    "HIDDEN": "Hidden",
}


@dataclass(slots=True)
class RoadArm:
    arm_id: str
    name: str
    angle: float
    flow_direction: str = "TWO_WAY"


@dataclass(slots=True)
class SignalPlacement:
    x: float
    y: float
    rotation: int = -1
    movements: list[str] = field(default_factory=lambda: ["STRAIGHT"])
    flow_direction: str = "INBOUND"
    road_arm_id: str = ""
    lane_position: int = 1
    destination_arm_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class IntersectionLayoutConfig:
    diagram_type: str = "FOUR_WAY"
    rotation: int = 0
    road_arms: dict[str, RoadArm] = field(default_factory=dict)
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


def default_road_arms(diagram_type: str) -> dict[str, RoadArm]:
    specifications = {
        "FOUR_WAY": [
            ("North", 0.0),
            ("East", 90.0),
            ("South", 180.0),
            ("West", 270.0),
        ],
        "FIVE_WAY": [
            ("Arm 1", 0.0),
            ("Arm 2", 72.0),
            ("Arm 3", 144.0),
            ("Arm 4", 216.0),
            ("Arm 5", 288.0),
        ],
        "T_JUNCTION": [
            ("North", 0.0),
            ("East", 90.0),
            ("West", 270.0),
        ],
        "STRAIGHT_ROAD": [
            ("North", 0.0),
            ("South", 180.0),
        ],
        "SINGLE_APPROACH": [("North", 0.0)],
    }
    selected = specifications.get(
        diagram_type,
        specifications["FOUR_WAY"],
    )
    arms: dict[str, RoadArm] = {}
    for index, (name, angle) in enumerate(selected, start=1):
        arm_id = f"ARM{index}"
        arms[arm_id] = RoadArm(
            arm_id=arm_id,
            name=name,
            angle=angle,
            flow_direction=(
                "INBOUND" if diagram_type == "SINGLE_APPROACH" else "TWO_WAY"
            ),
        )
    return arms


def effective_arm_angle(arm: RoadArm, rotation: int) -> float:
    return (float(arm.angle) + float(rotation)) % 360.0


def nearest_road_arm_id(
    x: float,
    y: float,
    road_arms: dict[str, RoadArm],
    rotation: int = 0,
) -> str:
    if not road_arms:
        return ""
    point_angle = degrees(atan2(x - 0.5, -(y - 0.5))) % 360.0
    return min(
        road_arms,
        key=lambda arm_id: _angle_distance(
            point_angle,
            effective_arm_angle(road_arms[arm_id], rotation),
        ),
    )


def destination_ids_for_movements(
    source_arm_id: str,
    movements: list[str],
    road_arms: dict[str, RoadArm],
) -> list[str]:
    source = road_arms.get(source_arm_id)
    candidates = [
        arm
        for arm in road_arms.values()
        if arm.arm_id != source_arm_id
    ]
    if source is None or not candidates:
        return []
    targets = {
        "STRAIGHT": (source.angle + 180.0) % 360.0,
        "LEFT": (source.angle + 90.0) % 360.0,
        "RIGHT": (source.angle - 90.0) % 360.0,
    }
    result: list[str] = []
    for movement in ("STRAIGHT", "LEFT", "RIGHT"):
        if movement not in movements:
            continue
        target = min(
            candidates,
            key=lambda arm: _angle_distance(arm.angle, targets[movement]),
        )
        if target.arm_id not in result:
            result.append(target.arm_id)
    if result:
        return result
    opposite = min(
        candidates,
        key=lambda arm: _angle_distance(
            arm.angle,
            (source.angle + 180.0) % 360.0,
        ),
    )
    return [opposite.arm_id]


def movement_name_between(source: RoadArm, destination: RoadArm) -> str:
    inbound_heading = (source.angle + 180.0) % 360.0
    delta = _signed_angle(destination.angle - inbound_heading)
    magnitude = abs(delta)
    if magnitude <= 24.0:
        return "Straight"
    if delta < 0:
        return "Slight Left" if magnitude < 70.0 else "Left"
    return "Slight Right" if magnitude < 70.0 else "Right"


def _angle_distance(first: float, second: float) -> float:
    return abs(_signed_angle(float(first) - float(second)))


def _signed_angle(value: float) -> float:
    return (float(value) + 180.0) % 360.0 - 180.0


def _five_way_points(count: int) -> list[tuple[float, float]]:
    arms = list(default_road_arms("FIVE_WAY").values())
    offsets = (0.115, 0.19, 0.04)
    points: list[tuple[float, float]] = []
    for index in range(max(0, min(12, count))):
        arm = arms[index % len(arms)]
        lane_index = index // len(arms)
        angle = radians(arm.angle)
        radial = 0.285
        tangent = offsets[min(lane_index, len(offsets) - 1)]
        points.append(
            (
                0.5 + sin(angle) * radial + cos(angle) * tangent,
                0.5 - cos(angle) * radial + sin(angle) * tangent,
            )
        )
    return points


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
    points = (
        _five_way_points(count)
        if diagram_type == "FIVE_WAY"
        else base_by_type.get(diagram_type, base_by_type["FOUR_WAY"])
    )
    road_arms = default_road_arms(diagram_type)
    arm_order = list(road_arms)
    placements: dict[int, SignalPlacement] = {}
    lane_counts: dict[str, int] = {}
    for index in range(max(0, min(12, count))):
        x, y = _rotate_point(*points[index], rotation)
        arm_id = arm_order[index % len(arm_order)] if arm_order else ""
        lane_counts[arm_id] = lane_counts.get(arm_id, 0) + 1
        placements[index + 1] = SignalPlacement(
            x=x,
            y=y,
            road_arm_id=arm_id,
            lane_position=lane_counts[arm_id],
            destination_arm_ids=destination_ids_for_movements(
                arm_id,
                ["STRAIGHT"],
                road_arms,
            ),
        )
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
        if not layout.intersection.road_arms:
            layout.intersection.road_arms = default_road_arms(
                layout.intersection.diagram_type
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
        for placement in layout.intersection.placements.values():
            if placement.road_arm_id not in layout.intersection.road_arms:
                placement.road_arm_id = nearest_road_arm_id(
                    placement.x,
                    placement.y,
                    layout.intersection.road_arms,
                    layout.intersection.rotation,
                )
            placement.lane_position = max(
                1,
                min(4, int(placement.lane_position)),
            )
            placement.destination_arm_ids = [
                arm_id
                for arm_id in placement.destination_arm_ids
                if arm_id in layout.intersection.road_arms
                and arm_id != placement.road_arm_id
            ]
            if not placement.destination_arm_ids:
                placement.destination_arm_ids = destination_ids_for_movements(
                    placement.road_arm_id,
                    placement.movements,
                    layout.intersection.road_arms,
                )

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
                {"schemaVersion": 2, "controllers": self._records},
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
        diagram_type = str(
            intersection_raw.get("diagram_type", "FOUR_WAY")
        )
        if diagram_type not in INTERSECTION_TYPES:
            diagram_type = "FOUR_WAY"
        road_arms: dict[str, RoadArm] = {}
        raw_road_arms = intersection_raw.get("road_arms", {})
        if isinstance(raw_road_arms, dict):
            for key, value in raw_road_arms.items():
                if not isinstance(value, dict):
                    continue
                arm_id = str(value.get("arm_id", key) or key).upper()
                try:
                    angle = float(value.get("angle", 0.0)) % 360.0
                except (TypeError, ValueError):
                    angle = 0.0
                flow_direction = str(
                    value.get("flow_direction", "TWO_WAY")
                ).upper()
                if flow_direction not in FLOW_DIRECTIONS:
                    flow_direction = "TWO_WAY"
                if arm_id and len(road_arms) < 5:
                    road_arms[arm_id] = RoadArm(
                        arm_id=arm_id,
                        name=str(value.get("name", arm_id) or arm_id),
                        angle=angle,
                        flow_direction=flow_direction,
                    )
        if not road_arms:
            road_arms = default_road_arms(diagram_type)
        placements: dict[int, SignalPlacement] = {}
        legacy_lane_counts: dict[str, int] = {}
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
                road_arm_id = str(
                    value.get("road_arm_id", "") or ""
                ).upper()
                if road_arm_id not in road_arms:
                    legacy_default = default_signal_placements(
                        diagram_type,
                        rotation,
                        max(1, min(12, number)),
                    ).get(number)
                    road_arm_id = (
                        legacy_default.road_arm_id
                        if legacy_default is not None
                        else nearest_road_arm_id(
                            x,
                            y,
                            road_arms,
                            rotation,
                        )
                    )
                if "lane_position" in value:
                    try:
                        lane_position = max(
                            1,
                            min(4, int(value.get("lane_position", 1))),
                        )
                    except (TypeError, ValueError):
                        lane_position = 1
                else:
                    legacy_lane_counts[road_arm_id] = (
                        legacy_lane_counts.get(road_arm_id, 0) + 1
                    )
                    lane_position = min(
                        4,
                        legacy_lane_counts[road_arm_id],
                    )
                raw_destinations = value.get("destination_arm_ids", [])
                destination_arm_ids = (
                    [
                        str(item).upper()
                        for item in raw_destinations
                        if str(item).upper() in road_arms
                        and str(item).upper() != road_arm_id
                    ]
                    if isinstance(raw_destinations, list)
                    else []
                )
                if not destination_arm_ids:
                    destination_arm_ids = destination_ids_for_movements(
                        road_arm_id,
                        movements,
                        road_arms,
                    )
                placements[number] = SignalPlacement(
                    x=x,
                    y=y,
                    rotation=signal_rotation,
                    movements=movements,
                    flow_direction=flow_direction,
                    road_arm_id=road_arm_id,
                    lane_position=lane_position,
                    destination_arm_ids=destination_arm_ids,
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
                diagram_type=diagram_type,
                rotation=rotation,
                road_arms=road_arms,
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
