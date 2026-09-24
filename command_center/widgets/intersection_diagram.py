from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..models import SignalGroupState


class IntersectionDiagram(QWidget):
    """Dynamic road-junction schematic for up to four approach SGs."""

    ASPECT_COLORS = {
        "RED": QColor("#ef5a64"),
        "YELLOW": QColor("#f6c453"),
        "GREEN": QColor("#42d58b"),
        "OFF": QColor("#344353"),
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._signal_groups: list[SignalGroupState] = []
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(100)
        self._flash_timer.timeout.connect(self.update)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def set_signal_groups(self, signal_groups: list[SignalGroupState]) -> None:
        self._signal_groups = signal_groups
        flashing = any(
            item.aspect.upper().startswith("FLASH YELLOW")
            for item in signal_groups
        )
        if flashing and not self._flash_timer.isActive():
            self._flash_timer.start()
        elif not flashing:
            self._flash_timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = float(self.width())
        height = float(self.height())
        center_x = width / 2.0
        center_y = height / 2.0
        road_width = min(width, height) * 0.34
        half_road = road_width / 2.0

        painter.fillRect(self.rect(), QColor("#0c2823"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#303944"))

        approach_count = min(4, len(self._signal_groups))
        central = QRectF(
            center_x - half_road,
            center_y - half_road,
            road_width,
            road_width,
        )
        painter.drawRect(central)

        # Default direction mapping: SG1 North, SG2 East,
        # SG3 South and SG4 West.
        if approach_count >= 1:
            painter.drawRect(
                QRectF(center_x - half_road, 0, road_width, center_y)
            )
        if approach_count >= 2:
            painter.drawRect(
                QRectF(center_x, center_y - half_road, width - center_x, road_width)
            )
        if approach_count >= 3:
            painter.drawRect(
                QRectF(center_x - half_road, center_y, road_width, height - center_y)
            )
        if approach_count >= 4:
            painter.drawRect(
                QRectF(0, center_y - half_road, center_x, road_width)
            )

        self._draw_lane_markings(
            painter,
            approach_count,
            center_x,
            center_y,
            half_road,
            width,
            height,
        )
        self._draw_direction_labels(painter, approach_count, width, height)

        signal_positions = [
            QPointF(center_x + half_road + 7, center_y - half_road - 43),
            QPointF(center_x + half_road + 7, center_y + half_road + 9),
            QPointF(center_x - half_road - 100, center_y + half_road + 9),
            QPointF(center_x - half_road - 100, center_y - half_road - 43),
        ]
        for index, signal_group in enumerate(self._signal_groups[:4]):
            self._draw_signal(painter, signal_positions[index], signal_group)

        if len(self._signal_groups) > 4:
            painter.setPen(QColor("#d7e3ef"))
            painter.setFont(QFont("Segoe UI", 8))
            extra = "  ".join(
                f"SG{item.number}:{item.aspect[0]}"
                for item in self._signal_groups[4:]
            )
            painter.drawText(
                QRectF(8, height - 25, width - 16, 18),
                Qt.AlignmentFlag.AlignCenter,
                f"Additional SG · {extra}",
            )

    def _draw_lane_markings(
        self,
        painter: QPainter,
        approach_count: int,
        center_x: float,
        center_y: float,
        half_road: float,
        width: float,
        height: float,
    ) -> None:
        pen = QPen(QColor("#d9c66d"), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)

        margin = half_road + 8
        if approach_count >= 1:
            painter.drawLine(
                QPointF(center_x, 8),
                QPointF(center_x, center_y - margin),
            )
        if approach_count >= 2:
            painter.drawLine(
                QPointF(center_x + margin, center_y),
                QPointF(width - 8, center_y),
            )
        if approach_count >= 3:
            painter.drawLine(
                QPointF(center_x, center_y + margin),
                QPointF(center_x, height - 8),
            )
        if approach_count >= 4:
            painter.drawLine(
                QPointF(8, center_y),
                QPointF(center_x - margin, center_y),
            )

        stop_pen = QPen(QColor("#edf3f8"), 3)
        painter.setPen(stop_pen)
        inset = 6
        if approach_count >= 1:
            painter.drawLine(
                QPointF(center_x - half_road + inset, center_y - half_road - 5),
                QPointF(center_x + half_road - inset, center_y - half_road - 5),
            )
        if approach_count >= 2:
            painter.drawLine(
                QPointF(center_x + half_road + 5, center_y - half_road + inset),
                QPointF(center_x + half_road + 5, center_y + half_road - inset),
            )
        if approach_count >= 3:
            painter.drawLine(
                QPointF(center_x - half_road + inset, center_y + half_road + 5),
                QPointF(center_x + half_road - inset, center_y + half_road + 5),
            )
        if approach_count >= 4:
            painter.drawLine(
                QPointF(center_x - half_road - 5, center_y - half_road + inset),
                QPointF(center_x - half_road - 5, center_y + half_road - inset),
            )

    def _draw_direction_labels(
        self,
        painter: QPainter,
        approach_count: int,
        width: float,
        height: float,
    ) -> None:
        painter.setPen(QColor("#b8c9d8"))
        direction_font = QFont("Segoe UI", 9)
        direction_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(direction_font)
        labels = [
            ("UTARA · SG1", QRectF(width / 2 - 55, 7, 110, 20)),
            ("TIMUR · SG2", QRectF(width - 120, height / 2 - 30, 112, 20)),
            ("SELATAN · SG3", QRectF(width / 2 - 60, height - 28, 120, 20)),
            ("BARAT · SG4", QRectF(8, height / 2 + 10, 112, 20)),
        ]
        for index in range(approach_count):
            text, rect = labels[index]
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_signal(
        self,
        painter: QPainter,
        top_left: QPointF,
        signal_group: SignalGroupState,
    ) -> None:
        housing = QRectF(top_left.x(), top_left.y(), 94, 34)
        painter.setPen(QPen(QColor("#516477"), 1))
        painter.setBrush(QColor("#071019"))
        painter.drawRoundedRect(housing, 6, 6)

        painter.setPen(QColor("#dce8f3"))
        signal_font = QFont("Segoe UI", 8)
        signal_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(signal_font)
        painter.drawText(
            QRectF(top_left.x() + 4, top_left.y(), 31, 34),
            Qt.AlignmentFlag.AlignCenter,
            f"SG{signal_group.number}",
        )

        aspects = ["RED", "YELLOW", "GREEN"]
        active_aspect = signal_group.aspect.upper()
        if active_aspect.startswith("FLASH YELLOW"):
            period_ms = 1000 if active_aspect.endswith("1000") else 500
            active_aspect = (
                "YELLOW"
                if int(monotonic() * 1000 / period_ms) % 2 == 0
                else "OFF"
            )
        for index, aspect in enumerate(aspects):
            aspect_active = active_aspect == aspect or (
                active_aspect == "RED + YELLOW"
                and aspect in {"RED", "YELLOW"}
            )
            color = (
                self.ASPECT_COLORS[aspect]
                if aspect_active
                else QColor("#26313b")
            )
            painter.setPen(QPen(QColor("#596775"), 1))
            painter.setBrush(color)
            painter.drawEllipse(
                QPointF(top_left.x() + 45 + index * 19, top_left.y() + 17),
                6,
                6,
            )
