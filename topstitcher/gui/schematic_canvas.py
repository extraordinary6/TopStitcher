"""Schematic canvas with interactive node editor (QGraphicsView-based)."""

from __future__ import annotations

import heapq
import math
from typing import Optional

from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsTextItem,
    QGraphicsItem, QGraphicsSceneMouseEvent, QMenu,
)
from PyQt6.QtCore import Qt, QPointF, QVariantAnimation, QEasingCurve, QTimer
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QFont, QPainter,
    QWheelEvent, QMouseEvent,
)

from topstitcher.core.data_model import PortDirection, InstanceInfo

# ── Constants ────────────────────────────────────────────

PORT_RADIUS = 6
PORT_SPACING = 24
NODE_MIN_WIDTH = 160
NODE_HEADER_H = 28
NODE_PAD = 12

_INPUT_COLOR = QColor(34, 139, 34)
_OUTPUT_COLOR = QColor(210, 105, 30)
_INOUT_COLOR = QColor(30, 90, 210)
_PORT_COLORS = {
    PortDirection.INPUT: _INPUT_COLOR,
    PortDirection.OUTPUT: _OUTPUT_COLOR,
    PortDirection.INOUT: _INOUT_COLOR,
}

_WIRE_COLOR = QColor(80, 80, 200)
_WIRE_DRAG_COLOR = QColor(80, 80, 200, 140)
_WIRE_SELECTED_COLOR = QColor(220, 60, 60)
_NODE_BG = QColor(240, 245, 255)
_NODE_BORDER = QColor(100, 120, 160)
_NODE_HEADER_BG = QColor(70, 90, 140)
GRID_STEP = 16
NODE_CLEARANCE = 28
PORT_ANCHOR_OFFSET = 48
WIRE_RESERVED_PENALTY = 180.0
TURN_PENALTY = 0.8
LOCAL_PAD_MIN = 8
LOCAL_PAD_MAX = 28
LOCAL_EXPAND_STEP = 14
ROUTE_DEBOUNCE_MS = 24
RESERVED_HALO_RADIUS = 1
ROUTE_BAND_MARGIN = 12
ROUTE_OUT_OF_BAND_PENALTY = 0.7
LANE_STEP = GRID_STEP * 2
LANE_SCAN_STEPS = 72
LANE_OUTER_MARGIN = 128
RESERVED_OVERLAP_PENALTY = 220
BLOCK_CONFLICT_PENALTY = 12000


def _same_x(a: QPointF, b: QPointF) -> bool:
    return math.isclose(a.x(), b.x(), abs_tol=0.5)


def _same_y(a: QPointF, b: QPointF) -> bool:
    return math.isclose(a.y(), b.y(), abs_tol=0.5)


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _simplify_points(points: list[QPointF]) -> list[QPointF]:
    simplified: list[QPointF] = []
    for point in points:
        if simplified and math.isclose(
            simplified[-1].x(), point.x(), abs_tol=0.5
        ) and math.isclose(simplified[-1].y(), point.y(), abs_tol=0.5):
            continue
        simplified.append(point)

    changed = True
    while changed and len(simplified) >= 3:
        changed = False
        result = [simplified[0]]
        for idx in range(1, len(simplified) - 1):
            prev_point = result[-1]
            point = simplified[idx]
            next_point = simplified[idx + 1]
            same_x = _same_x(prev_point, point) and _same_x(point, next_point)
            same_y = _same_y(prev_point, point) and _same_y(point, next_point)
            if same_x or same_y:
                changed = True
                continue
            result.append(point)
        result.append(simplified[-1])
        simplified = result

    return simplified


def _unique_cells_in_order(
    cells: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    unique: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for cell in cells:
        if cell in seen:
            continue
        seen.add(cell)
        unique.append(cell)
    return unique


# ── PortItem ─────────────────────────────────────────────

class PortItem(QGraphicsEllipseItem):
    """A single pin on a NodeItem. Initiates wire drawing on drag."""

    def __init__(
        self, instance_name: str, port_name: str, direction: PortDirection,
        parent: NodeItem,
    ):
        r = PORT_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r, parent)
        self.instance_name = instance_name
        self.port_name = port_name
        self.direction = direction
        self.node: NodeItem = parent

        color = _PORT_COLORS.get(direction, _INOUT_COLOR)
        self.setBrush(QBrush(color))
        self.setPen(QPen(color.darker(130), 1.5))
        self.setZValue(2)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

        # Label
        self._label = QGraphicsTextItem(port_name, self)
        self._label.setFont(QFont("Consolas", 8))
        self._label.setDefaultTextColor(QColor(40, 40, 40))
        if direction == PortDirection.INPUT:
            self._label.setPos(r + 3, -self._label.boundingRect().height() / 2)
        else:
            lw = self._label.boundingRect().width()
            self._label.setPos(-r - 3 - lw, -self._label.boundingRect().height() / 2)

    def center_scene_pos(self) -> QPointF:
        return self.scenePos()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            canvas = self._canvas()
            if canvas and canvas.manual_mode:
                canvas.start_wire_drag(self, event.scenePos())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        canvas = self._canvas()
        if canvas and canvas.is_dragging_wire():
            canvas.update_wire_drag(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        canvas = self._canvas()
        if canvas and canvas.is_dragging_wire():
            canvas.finish_wire_drag(event.scenePos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _canvas(self) -> Optional[SchematicCanvas]:
        scene = self.scene()
        if scene:
            views = scene.views()
            if views and isinstance(views[0], SchematicCanvas):
                return views[0]
        return None


# ── NodeItem ─────────────────────────────────────────────

class NodeItem(QGraphicsRectItem):
    """A movable block representing an instantiated module."""

    def __init__(self, instance: InstanceInfo, x: float = 0, y: float = 0):
        super().__init__()
        self.instance_name = instance.instance_name
        self.module_name = instance.module_name
        self.port_items: dict[str, PortItem] = {}

        inputs = [p for p in instance.ports if p.direction == PortDirection.INPUT]
        outputs = [p for p in instance.ports
                   if p.direction in (PortDirection.OUTPUT, PortDirection.INOUT)]

        n_ports = max(len(inputs), len(outputs), 1)
        body_h = n_ports * PORT_SPACING + NODE_PAD
        total_h = NODE_HEADER_H + body_h
        width = NODE_MIN_WIDTH

        self.setRect(0, 0, width, total_h)
        self.setBrush(QBrush(_NODE_BG))
        self.setPen(QPen(_NODE_BORDER, 2))
        self.setPos(x, y)
        self.setZValue(1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        # Header background
        self._header = QGraphicsRectItem(0, 0, width, NODE_HEADER_H, self)
        self._header.setBrush(QBrush(_NODE_HEADER_BG))
        self._header.setPen(QPen(Qt.PenStyle.NoPen))

        # Instance name label
        label = QGraphicsTextItem(instance.instance_name, self)
        label.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        label.setDefaultTextColor(QColor(255, 255, 255))
        lw = label.boundingRect().width()
        label.setPos((width - lw) / 2, 2)

        # Module name subtitle
        sub = QGraphicsTextItem(instance.module_name, self)
        sub.setFont(QFont("Consolas", 7))
        sub.setDefaultTextColor(QColor(200, 210, 230))
        sw = sub.boundingRect().width()
        sub.setPos((width - sw) / 2, 14)

        # Create port items
        y_start = NODE_HEADER_H + NODE_PAD / 2 + PORT_SPACING / 2
        for i, port in enumerate(inputs):
            py = y_start + i * PORT_SPACING
            pi = PortItem(instance.instance_name, port.name, port.direction, self)
            pi.setPos(0, py)
            self.port_items[port.name] = pi

        for i, port in enumerate(outputs):
            py = y_start + i * PORT_SPACING
            pi = PortItem(instance.instance_name, port.name, port.direction, self)
            pi.setPos(width, py)
            self.port_items[port.name] = pi

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            canvas = self._canvas()
            if canvas:
                canvas.update_wires_for_node(self)
        return super().itemChange(change, value)

    def _canvas(self) -> Optional[SchematicCanvas]:
        scene = self.scene()
        if scene:
            views = scene.views()
            if views and isinstance(views[0], SchematicCanvas):
                return views[0]
        return None


# ── WireItem ─────────────────────────────────────────────

class WireItem(QGraphicsPathItem):
    """An orthogonal wire between two PortItems."""

    def __init__(
        self,
        source: PortItem,
        target: PortItem | None = None,
        end_pos: QPointF | None = None,
    ):
        super().__init__()
        self.source = source
        self.target = target
        self.net_name = ""
        self.setZValue(0)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._temporary = target is None
        self._lane_hint = 0
        self._route_cells: list[tuple[int, int]] = []
        self._update_pen()
        if end_pos is not None:
            self._pending_end_pos = end_pos
        else:
            self._pending_end_pos = None

    def _update_pen(self):
        if self._temporary:
            self.setPen(QPen(_WIRE_DRAG_COLOR, 2.5, Qt.PenStyle.SolidLine))
        elif self.isSelected():
            self.setPen(QPen(_WIRE_SELECTED_COLOR, 3.0, Qt.PenStyle.SolidLine))
        else:
            self.setPen(QPen(_WIRE_COLOR, 2.5, Qt.PenStyle.SolidLine))

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._update_pen()
        return super().itemChange(change, value)

    def update_path(self, end_pos: QPointF | None = None):
        if end_pos is None and self._pending_end_pos is not None and self.target is None:
            end_pos = self._pending_end_pos
        canvas = self._canvas()
        if canvas:
            if self.target:
                points, cells = canvas.route_between_ports(
                    self.source, self.target, exclude_wire=self,
                    lane_hint=self._lane_hint,
                )
            elif end_pos:
                points, cells = canvas.route_drag_preview(self.source, end_pos)
            else:
                return
        else:
            p1 = self.source.center_scene_pos()
            p2 = self.target.center_scene_pos() if self.target else end_pos
            if p2 is None:
                return
            mid_x = (p1.x() + p2.x()) / 2.0
            points = [p1, QPointF(mid_x, p1.y()), QPointF(mid_x, p2.y()), p2]
            cells = []

        self._route_cells = cells
        path = self._orthogonal_path(points)
        self.setPath(path)

    def finalize(self, target: PortItem, net_name: str):
        self.target = target
        self.net_name = net_name
        self._temporary = False
        self._pending_end_pos = None
        self._update_pen()
        self.update_path()

    def set_route(
        self, points: list[QPointF], cells: list[tuple[int, int]]
    ):
        self._route_cells = list(cells)
        self.setPath(self._orthogonal_path(points))

    def _orthogonal_path(self, points: list[QPointF]) -> QPainterPath:
        route = _simplify_points(points)
        if not route:
            route = [self.source.center_scene_pos()]

        path = QPainterPath(route[0])
        for point in route[1:]:
            path.lineTo(point)
        return path

    def _canvas(self) -> Optional[SchematicCanvas]:
        scene = self.scene()
        if scene:
            views = scene.views()
            if views and isinstance(views[0], SchematicCanvas):
                return views[0]
        return None


# ── SchematicCanvas ──────────────────────────────────────

class SchematicCanvas(QGraphicsView):
    """Interactive schematic view with nodes, ports, and wires."""

    # Layout spacing constants
    H_SPACING = 300
    V_SPACING = 200

    def __init__(self, table_widget=None, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(-2000, -2000, 4000, 4000)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        self._table = table_widget
        self._nodes: dict[str, NodeItem] = {}
        self._wires: list[WireItem] = []
        self._drag_wire: WireItem | None = None
        self._drag_source: PortItem | None = None
        self._on_connection_made = None
        self._on_connection_removed = None
        self._animations: list[QVariantAnimation] = []
        self._reroute_pending = False

        # Manual mode: user draws wires by hand. Auto mode: sync from table.
        self.manual_mode: bool = False

    def set_connection_callback(self, callback):
        self._on_connection_made = callback

    def set_removal_callback(self, callback):
        self._on_connection_removed = callback

    # ── Node management ───────────────────────────────────

    def add_node(self, instance: InstanceInfo):
        if instance.instance_name in self._nodes:
            return
        n = len(self._nodes)
        col = n % 3
        row = n // 3
        x = col * 250 - 250
        y = row * 220 - 100
        node = NodeItem(instance, x, y)
        self._scene.addItem(node)
        self._nodes[instance.instance_name] = node

    def remove_node(self, instance_name: str):
        node = self._nodes.pop(instance_name, None)
        if node:
            to_remove = [
                w for w in self._wires
                if (w.source.instance_name == instance_name
                    or (w.target and w.target.instance_name == instance_name))
            ]
            for w in to_remove:
                self._remove_wire(w, update_table=False)
            self._scene.removeItem(node)

    def clear_all(self):
        self._nodes.clear()
        self._wires.clear()
        self._drag_wire = None
        self._drag_source = None
        self._reroute_pending = False
        self._scene.clear()

    # ── Wire management ───────────────────────────────────

    def sync_wires_from_table(self):
        """Read the table (source of truth) and redraw all wires. Only in auto mode."""
        if self.manual_mode:
            return

        for w in self._wires:
            if w.scene():
                self._scene.removeItem(w)
        self._wires.clear()

        if not self._table:
            return

        from topstitcher.gui.connection_view import (
            COL_DIR, COL_INSTANCE, COL_PORT, COL_NET,
        )
        net_map: dict[str, list[tuple[str, str, str]]] = {}
        for row in range(self._table.rowCount()):
            inst_item = self._table.item(row, COL_INSTANCE)
            port_item = self._table.item(row, COL_PORT)
            dir_item = self._table.item(row, COL_DIR)
            net_item = self._table.item(row, COL_NET)
            if not (inst_item and port_item and dir_item and net_item):
                continue
            inst = inst_item.text()
            port = port_item.text()
            direction = dir_item.text()
            net = net_item.text().strip()
            if net:
                net_map.setdefault(net, []).append((inst, port, direction))

        def endpoint_x(ep: tuple[str, str, str]) -> float:
            pi = self._find_port_item(ep[0], ep[1])
            if pi:
                return pi.center_scene_pos().x()
            return float("inf")

        lane_counters: dict[tuple[str, str], int] = {}
        for net_name, endpoints in net_map.items():
            ports = list(endpoints)
            if len(ports) < 2:
                continue
            drivers = [p for p in ports if p[2] in ("output", "inout")]
            if drivers:
                src_entry = min(drivers, key=endpoint_x)
                src_inst, src_port, _ = src_entry
                targets = [p for p in ports if p != src_entry]
            else:
                # Pure input nets (clk/rst style) should fan out from the leftmost node.
                src_entry = min(ports, key=endpoint_x)
                src_inst, src_port, _ = src_entry
                targets = [p for p in ports if p != src_entry]
            src_pi = self._find_port_item(src_inst, src_port)
            if not src_pi:
                continue
            targets.sort(key=endpoint_x)
            for dst_inst, dst_port, _ in targets:
                dst_pi = self._find_port_item(dst_inst, dst_port)
                if not dst_pi:
                    continue
                wire = WireItem(src_pi, dst_pi)
                wire.net_name = net_name
                lane_key = self._lane_key(src_pi, dst_pi)
                wire._lane_hint = lane_counters.get(lane_key, 0)
                lane_counters[lane_key] = wire._lane_hint + 1
                self._scene.addItem(wire)
                self._wires.append(wire)
        self._reroute_all_wires()

    def update_wires_for_node(self, node: NodeItem):
        self._schedule_reroute()

    def delete_selected_wires(self):
        """Delete all currently selected wires and update the table."""
        to_delete = [w for w in self._wires if w.isSelected()]
        for wire in to_delete:
            self._remove_wire(wire, update_table=True)

    def _remove_wire(self, wire: WireItem, update_table: bool = True):
        """Remove a single wire from the scene and optionally clear its net in the table."""
        if wire in self._wires:
            self._wires.remove(wire)
        if wire.scene():
            self._scene.removeItem(wire)
        if update_table and wire.target and self._on_connection_removed:
            self._on_connection_removed(
                wire.source.instance_name, wire.source.port_name,
                wire.target.instance_name, wire.target.port_name,
                wire.net_name,
            )
        self._schedule_reroute()

    # ── Context menu ──────────────────────────────────────

    def _schedule_reroute(self):
        if self._reroute_pending:
            return
        self._reroute_pending = True
        QTimer.singleShot(ROUTE_DEBOUNCE_MS, self._flush_reroute)

    def _flush_reroute(self):
        self._reroute_pending = False
        self._reroute_all_wires()

    def _reroute_all_wires(self):
        if not self._wires:
            return

        blocked = self._blocked_cells()
        blocked_x = self._blocked_x_intervals()
        reserved: set[tuple[int, int]] = set()
        groups = self._group_wires_for_routing()
        for group in groups:
            if self._can_route_group_as_bus(group):
                self._route_bus_group(
                    group, blocked, blocked_x, reserved,
                )
                continue
            for wire in group:
                if not wire.target:
                    continue
                points, cells = self.route_between_ports(
                    wire.source, wire.target, exclude_wire=wire,
                    blocked_cells=blocked, reserved_cells=reserved,
                    lane_hint=wire._lane_hint,
                    blocked_x_intervals=blocked_x,
                )
                wire.set_route(points, cells)
                reserved.update(cells)

    def _group_wires_for_routing(self) -> list[list[WireItem]]:
        by_key: dict[tuple[str, str, str], list[WireItem]] = {}
        for wire in self._wires:
            if not wire.target:
                continue
            key = (
                wire.net_name,
                wire.source.instance_name,
                wire.source.port_name,
            )
            by_key.setdefault(key, []).append(wire)

        ordered: list[tuple[int, int, tuple[str, str, str], list[WireItem]]] = []
        for idx, (key, wires) in enumerate(by_key.items()):
            source = wires[0].source
            sx = source.center_scene_pos().x()
            sy = source.center_scene_pos().y()
            tx = sum(w.target.center_scene_pos().x() for w in wires if w.target) / len(wires)
            ty = sum(w.target.center_scene_pos().y() for w in wires if w.target) / len(wires)
            metric = abs(int(round(sx - tx))) + abs(int(round(sy - ty)))
            ordered.append((metric, idx, key, wires))

        ordered.sort(key=lambda item: (item[0], item[1]))
        return [wires for _, _, _, wires in ordered]

    def _can_route_group_as_bus(self, wires: list[WireItem]) -> bool:
        if len(wires) < 2:
            return False
        src_inst = wires[0].source.instance_name
        src_port = wires[0].source.port_name
        same_source = all(
            wire.target is not None
            and wire.source.instance_name == src_inst
            and wire.source.port_name == src_port
            for wire in wires
        )
        if not same_source:
            return False

        src_x = wires[0].source.center_scene_pos().x()
        directions = set()
        for wire in wires:
            if not wire.target:
                continue
            dx = wire.target.center_scene_pos().x() - src_x
            if abs(dx) < GRID_STEP:
                continue
            directions.add(1 if dx > 0 else -1)
        return len(directions) <= 1

    def _route_bus_group(
        self,
        wires: list[WireItem],
        blocked: set[tuple[int, int]],
        blocked_x: list[tuple[float, float]],
        reserved: set[tuple[int, int]],
    ):
        if not wires:
            return
        source = wires[0].source
        lane_hint = min(w._lane_hint for w in wires)
        start = source.center_scene_pos()
        start_anchor = self._port_anchor(source, lane_hint=min(lane_hint, 4))
        targets = [w.target for w in wires if w.target]
        if not targets:
            return

        avg_target_x = sum(t.center_scene_pos().x() for t in targets) / len(targets)
        avg_target_y = sum(t.center_scene_pos().y() for t in targets) / len(targets)
        prefer_forward = start.x() <= avg_target_x
        proxy_anchor = QPointF(avg_target_x, avg_target_y)
        base_trunk_x = self._select_trunk_x(
            start_anchor,
            proxy_anchor,
            blocked_x,
            lane_hint,
            prefer_forward=prefer_forward,
        )

        candidates = self._bus_trunk_candidates(
            base_trunk_x, blocked_x, prefer_forward,
        )
        reserved_halo = self._expanded_cells(reserved, RESERVED_HALO_RADIUS)
        targets_sorted = sorted(
            wires,
            key=lambda w: w.target.center_scene_pos().y() if w.target else 0.0
        )

        best_x = candidates[0] if candidates else base_trunk_x
        best_score = float("inf")
        best_routes: list[tuple[WireItem, list[QPointF], list[tuple[int, int]]]] = []

        for trunk_x in candidates:
            score = 0.0
            routes: list[tuple[WireItem, list[QPointF], list[tuple[int, int]]]] = []
            for idx, wire in enumerate(targets_sorted):
                if not wire.target:
                    continue
                target = wire.target
                end = target.center_scene_pos()
                end_anchor = self._port_anchor(target, lane_hint=min(lane_hint + idx, 4))
                points = self._compose_lane_route_points(
                    start, start_anchor, end_anchor, end, trunk_x,
                )
                cells = self._orthogonal_cells_from_points(points)
                block_hits = self._blocked_conflicts(
                    cells, blocked, start_anchor, end_anchor
                )
                reserve_hits = len(set(cells).intersection(reserved_halo))
                score += (
                    block_hits * BLOCK_CONFLICT_PENALTY
                    + reserve_hits * RESERVED_OVERLAP_PENALTY
                    + len(cells)
                )
                routes.append((wire, points, cells))

            if score < best_score:
                best_score = score
                best_x = trunk_x
                best_routes = routes

            if score == 0:
                break

        if not best_routes:
            return

        for idx, (wire, points, cells) in enumerate(best_routes):
            if wire.target is None:
                continue
            source_anchor = self._port_anchor(source, lane_hint=min(lane_hint, 4))
            target_anchor = self._port_anchor(
                wire.target, lane_hint=min(lane_hint + idx, 4)
            )
            if self._blocked_conflicts(cells, blocked, source_anchor, target_anchor) > 0:
                alt_points, alt_cells = self.route_between_ports(
                    wire.source,
                    wire.target,
                    exclude_wire=wire,
                    blocked_cells=blocked,
                    reserved_cells=reserved,
                    lane_hint=wire._lane_hint,
                    blocked_x_intervals=blocked_x,
                )
                wire.set_route(alt_points, alt_cells)
                reserved.update(alt_cells)
                continue

            wire.set_route(points, cells)
            reserved.update(cells)

    def _bus_trunk_candidates(
        self,
        base_trunk_x: float,
        blocked_x: list[tuple[float, float]],
        prefer_forward: bool,
    ) -> list[float]:
        candidates: list[float] = []
        signs = [1, -1]
        if not prefer_forward:
            signs = [-1, 1]

        def add_candidate(x: float, sign: int):
            snapped = self._find_clear_lane_x(x, blocked_x, preferred_sign=sign)
            if any(math.isclose(snapped, existing, abs_tol=0.5) for existing in candidates):
                return
            candidates.append(snapped)

        add_candidate(base_trunk_x, signs[0])
        for step in range(1, 6):
            for sign in signs:
                add_candidate(base_trunk_x + sign * step * LANE_STEP, sign)
        return candidates if candidates else [base_trunk_x]

    def _on_context_menu(self, pos):
        scene_pos = self.mapToScene(pos)
        menu = QMenu(self)

        # Check if a wire is under cursor
        wire_under = self._wire_at(scene_pos)
        selected_wires = [w for w in self._wires if w.isSelected()]

        if wire_under or selected_wires:
            if wire_under and wire_under not in selected_wires:
                # Select the wire under cursor
                wire_under.setSelected(True)
                selected_wires = [wire_under]

            n = len(selected_wires)
            action = menu.addAction(f"Delete Wire{'s' if n > 1 else ''} ({n})")
            action.triggered.connect(self.delete_selected_wires)
            menu.addSeparator()

        menu.exec(self.mapToGlobal(pos))

    def _wire_at(self, scene_pos: QPointF) -> WireItem | None:
        """Find the topmost WireItem near scene_pos."""
        # Use a small area around the cursor for easier clicking on thin wires
        from PyQt6.QtCore import QRectF
        r = 6
        area = QRectF(scene_pos.x() - r, scene_pos.y() - r, 2 * r, 2 * r)
        items = self._scene.items(area, Qt.ItemSelectionMode.IntersectsItemShape,
                                  Qt.SortOrder.DescendingOrder)
        for item in items:
            if isinstance(item, WireItem) and not item._temporary:
                return item
        return None

    # ── Wire drag interaction ─────────────────────────────

    def start_wire_drag(self, port: PortItem, scene_pos: QPointF):
        self._drag_source = port
        self._drag_wire = WireItem(port, end_pos=scene_pos)
        self._scene.addItem(self._drag_wire)
        self._drag_wire.update_path(scene_pos)

    def is_dragging_wire(self) -> bool:
        return self._drag_wire is not None

    def update_wire_drag(self, scene_pos: QPointF):
        if self._drag_wire:
            self._drag_wire.update_path(scene_pos)

    def finish_wire_drag(self, scene_pos: QPointF):
        if not self._drag_wire or not self._drag_source:
            self._cancel_drag()
            return

        target = self._port_at(scene_pos)
        if target and target is not self._drag_source:
            src = self._drag_source
            if (src.direction == PortDirection.OUTPUT
                    and target.direction == PortDirection.OUTPUT):
                self._cancel_drag()
                return
            if src.instance_name == target.instance_name:
                self._cancel_drag()
                return

            if src.direction == PortDirection.OUTPUT:
                net_name = f"{src.instance_name}_{src.port_name}"
            else:
                net_name = f"{target.instance_name}_{target.port_name}"

            lane_key = self._lane_key(src, target)
            self._drag_wire._lane_hint = self._next_lane_hint(lane_key)
            self._drag_wire.finalize(target, net_name)
            self._wires.append(self._drag_wire)
            self._schedule_reroute()
            self._drag_wire = None
            self._drag_source = None

            if self._on_connection_made:
                self._on_connection_made(
                    src.instance_name, src.port_name,
                    target.instance_name, target.port_name,
                    net_name,
                )
        else:
            self._cancel_drag()

    def _cancel_drag(self):
        if self._drag_wire and self._drag_wire.scene():
            self._scene.removeItem(self._drag_wire)
        self._drag_wire = None
        self._drag_source = None

    def _port_at(self, scene_pos: QPointF) -> PortItem | None:
        items = self._scene.items(scene_pos, Qt.ItemSelectionMode.IntersectsItemBoundingRect,
                                  Qt.SortOrder.DescendingOrder)
        for item in items:
            if isinstance(item, PortItem):
                return item
        return None

    def _find_port_item(self, instance_name: str, port_name: str) -> PortItem | None:
        node = self._nodes.get(instance_name)
        if node:
            return node.port_items.get(port_name)
        return None

    def _lane_key(self, source: PortItem, target: PortItem) -> tuple[str, str]:
        src_x = source.center_scene_pos().x()
        dst_x = target.center_scene_pos().x()
        if source.direction == PortDirection.INPUT and target.direction == PortDirection.INPUT:
            owner = source.instance_name if src_x <= dst_x else target.instance_name
            return ("left_bus", owner)
        if src_x <= dst_x:
            return ("fwd", source.instance_name)
        return ("back", source.instance_name)

    def _next_lane_hint(self, lane_key: tuple[str, str]) -> int:
        used = {
            wire._lane_hint
            for wire in self._wires
            if wire.target and self._lane_key(wire.source, wire.target) == lane_key
        }
        lane = 0
        while lane in used:
            lane += 1
        return lane

    def _blocked_x_intervals(self) -> list[tuple[float, float]]:
        intervals: list[tuple[float, float]] = []
        for node in self._nodes.values():
            rect = node.mapRectToScene(node.rect()).adjusted(
                -NODE_CLEARANCE, 0,
                NODE_CLEARANCE, 0,
            )
            intervals.append((rect.left(), rect.right()))
        return self._merge_intervals(intervals)

    def _merge_intervals(
        self, intervals: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        if not intervals:
            return []
        ordered = sorted(intervals, key=lambda x: x[0])
        merged: list[tuple[float, float]] = [ordered[0]]
        for left, right in ordered[1:]:
            last_left, last_right = merged[-1]
            if left <= last_right + GRID_STEP:
                merged[-1] = (last_left, max(last_right, right))
            else:
                merged.append((left, right))
        return merged

    def _x_is_blocked(
        self, x: float, intervals: list[tuple[float, float]],
    ) -> bool:
        return any(left <= x <= right for left, right in intervals)

    def _snap_x_to_grid(self, x: float) -> float:
        return round(x / GRID_STEP) * GRID_STEP

    def _find_clear_lane_x(
        self,
        base_x: float,
        intervals: list[tuple[float, float]],
        preferred_sign: int = 1,
    ) -> float:
        snapped = self._snap_x_to_grid(base_x)
        if not self._x_is_blocked(snapped, intervals):
            return snapped

        signs = [1, -1] if preferred_sign >= 0 else [-1, 1]
        for step in range(1, LANE_SCAN_STEPS + 1):
            for sign in signs:
                candidate = self._snap_x_to_grid(
                    snapped + sign * step * LANE_STEP
                )
                if not self._x_is_blocked(candidate, intervals):
                    return candidate

        return snapped

    def _select_trunk_x(
        self,
        start_anchor: QPointF,
        end_anchor: QPointF,
        intervals: list[tuple[float, float]],
        lane_hint: int,
        prefer_forward: bool | None = None,
    ) -> float:
        sx = start_anchor.x()
        ex = end_anchor.x()
        is_forward = (sx <= ex) if prefer_forward is None else prefer_forward
        if is_forward:
            # Forward links: spread lanes around midpoint to avoid dense overlaps.
            base = (sx + ex) / 2.0
            if lane_hint == 0:
                desired = base
                preferred_sign = 1
            else:
                magnitude = (lane_hint + 1) // 2
                sign = 1 if lane_hint % 2 == 1 else -1
                desired = base + sign * magnitude * LANE_STEP
                preferred_sign = sign
            return self._find_clear_lane_x(desired, intervals, preferred_sign)

        # Backward links: route from outer side (left or right) by cost.
        left_outer = min(sx, ex) - LANE_OUTER_MARGIN
        right_outer = max(sx, ex) + LANE_OUTER_MARGIN
        left_cost = abs(sx - left_outer) + abs(ex - left_outer)
        right_cost = abs(sx - right_outer) + abs(ex - right_outer)
        if left_cost <= right_cost:
            desired = left_outer - lane_hint * LANE_STEP
            preferred_sign = -1
        else:
            desired = right_outer + lane_hint * LANE_STEP
            preferred_sign = 1
        return self._find_clear_lane_x(desired, intervals, preferred_sign)

    def _compose_lane_route_points(
        self,
        start: QPointF,
        start_anchor: QPointF,
        end_anchor: QPointF,
        end: QPointF,
        trunk_x: float,
        detour_y: float | None = None,
    ) -> list[QPointF]:
        points: list[QPointF] = [start]

        def add_point(point: QPointF):
            last = points[-1]
            if _same_x(last, point) and _same_y(last, point):
                return
            if (not _same_x(last, point)) and (not _same_y(last, point)):
                elbow = QPointF(point.x(), last.y())
                if not (_same_x(last, elbow) and _same_y(last, elbow)):
                    points.append(elbow)
            points.append(point)

        add_point(QPointF(start_anchor.x(), start.y()))
        add_point(start_anchor)
        if detour_y is not None:
            add_point(QPointF(start_anchor.x(), detour_y))
            add_point(QPointF(trunk_x, detour_y))
            add_point(QPointF(end_anchor.x(), detour_y))
        else:
            add_point(QPointF(trunk_x, start_anchor.y()))
            add_point(QPointF(trunk_x, end_anchor.y()))
        add_point(end_anchor)
        add_point(QPointF(end_anchor.x(), end.y()))
        add_point(end)
        return _simplify_points(points)

    def _detour_y_from_hint(
        self,
        start_anchor: QPointF,
        end_anchor: QPointF,
        hint: int,
        blocked: set[tuple[int, int]],
    ) -> float | None:
        if hint <= 0:
            return None
        if not blocked:
            mid_y = (start_anchor.y() + end_anchor.y()) / 2.0
            step = ((hint + 1) // 2) * PORT_SPACING
            sign = 1 if hint % 2 == 1 else -1
            return round((mid_y + sign * step) / GRID_STEP) * GRID_STEP

        rows = [cell[1] for cell in blocked]
        top_outer = (min(rows) - 2) * GRID_STEP
        bottom_outer = (max(rows) + 2) * GRID_STEP
        band_step = ((hint - 1) // 2) * PORT_SPACING
        if hint % 2 == 1:
            return top_outer - band_step
        return bottom_outer + band_step

    def _orthogonal_cells_from_points(
        self, points: list[QPointF],
    ) -> list[tuple[int, int]]:
        if not points:
            return []
        cells: list[tuple[int, int]] = []
        for idx in range(len(points) - 1):
            start_cell = self._scene_to_grid(points[idx])
            end_cell = self._scene_to_grid(points[idx + 1])
            segment = self._straight_cells(start_cell, end_cell)
            if idx > 0 and segment:
                segment = segment[1:]
            cells.extend(segment)
        return _unique_cells_in_order(cells)

    def _blocked_conflicts(
        self,
        cells: list[tuple[int, int]],
        blocked: set[tuple[int, int]],
        start_anchor: QPointF,
        end_anchor: QPointF,
    ) -> int:
        if not cells or not blocked:
            return 0
        start_cell = self._scene_to_grid(start_anchor)
        end_cell = self._scene_to_grid(end_anchor)
        # Let wire leave/enter the owning modules naturally near endpoints.
        endpoint_allow = max(3, PORT_ANCHOR_OFFSET // GRID_STEP + 2)

        conflicts = 0
        for cell in cells:
            if cell not in blocked:
                continue
            if _manhattan(cell, start_cell) <= endpoint_allow:
                continue
            if _manhattan(cell, end_cell) <= endpoint_allow:
                continue
            conflicts += 1
        return conflicts

    def route_between_ports(
        self,
        source: PortItem,
        target: PortItem,
        exclude_wire: WireItem | None = None,
        blocked_cells: set[tuple[int, int]] | None = None,
        reserved_cells: set[tuple[int, int]] | None = None,
        lane_hint: int = 0,
        blocked_x_intervals: list[tuple[float, float]] | None = None,
    ) -> tuple[list[QPointF], list[tuple[int, int]]]:
        start = source.center_scene_pos()
        end = target.center_scene_pos()
        # Keep anchor fan-out small; major separation is handled by trunk lanes.
        start_anchor = self._port_anchor(source, lane_hint=min(lane_hint, 4))
        end_anchor = self._port_anchor(target, lane_hint=min(lane_hint, 4))
        if blocked_cells is None:
            blocked = self._blocked_cells()
        else:
            blocked = blocked_cells
        if reserved_cells is None:
            reserved = self._reserved_cells(exclude_wire=exclude_wire)
        else:
            reserved = reserved_cells
        blocked_x = (
            blocked_x_intervals
            if blocked_x_intervals is not None
            else self._blocked_x_intervals()
        )
        reserved_halo = self._expanded_cells(reserved, RESERVED_HALO_RADIUS)

        best_points: list[QPointF] | None = None
        best_cells: list[tuple[int, int]] | None = None
        best_score: float = float("inf")
        max_attempts = max(4, lane_hint + 6)
        for extra in range(max_attempts):
            effective_hint = lane_hint + extra
            trunk_x = self._select_trunk_x(
                start_anchor, end_anchor, blocked_x, effective_hint,
                prefer_forward=start.x() <= end.x(),
            )
            detour_y = self._detour_y_from_hint(
                start_anchor, end_anchor, extra, blocked
            )
            points = self._compose_lane_route_points(
                start, start_anchor, end_anchor, end, trunk_x, detour_y,
            )
            cells = self._orthogonal_cells_from_points(points)
            block_hits = self._blocked_conflicts(
                cells, blocked, start_anchor, end_anchor
            )
            reserve_hits = len(set(cells).intersection(reserved_halo))
            score = (
                block_hits * BLOCK_CONFLICT_PENALTY
                + reserve_hits * RESERVED_OVERLAP_PENALTY
                + len(cells)
                + extra * 4
            )
            if score < best_score:
                best_score = score
                best_points = points
                best_cells = cells
            if block_hits == 0 and reserve_hits == 0:
                break

        if best_points is None or best_cells is None:
            return [start, end], [self._scene_to_grid(start), self._scene_to_grid(end)]

        # Geometrically hard cases fallback to local A* search for correctness.
        if self._blocked_conflicts(best_cells, blocked, start_anchor, end_anchor) > 0:
            start_cell = self._scene_to_grid(start_anchor)
            end_cell = self._scene_to_grid(end_anchor)
            band = self._routing_band(start_cell, end_cell)
            for bounds in (
                self._local_grid_bounds(start_cell, end_cell),
                None,
            ):
                alt_cells = self._find_grid_path(
                    start_anchor,
                    end_anchor,
                    blocked,
                    reserved,
                    bounds,
                    preferred_band=band,
                )
                if not alt_cells:
                    alt_cells = self._find_grid_path(
                        start_anchor,
                        end_anchor,
                        blocked,
                        set(),
                        bounds,
                        preferred_band=band,
                    )
                if alt_cells:
                    alt_points = self._compose_route_points(
                        start, start_anchor, alt_cells, end_anchor, end,
                    )
                    return alt_points, alt_cells

        return best_points, best_cells

    def route_drag_preview(
        self, source: PortItem, end_pos: QPointF,
    ) -> tuple[list[QPointF], list[tuple[int, int]]]:
        start = source.center_scene_pos()
        start_anchor = self._port_anchor(source)
        preview_anchor = self._snap_to_grid(end_pos)
        blocked = self._blocked_cells()
        blocked_x = self._blocked_x_intervals()
        trunk_x = self._select_trunk_x(
            start_anchor, preview_anchor, blocked_x, lane_hint=0,
            prefer_forward=start.x() <= end_pos.x(),
        )
        points = self._compose_lane_route_points(
            start, start_anchor, preview_anchor, end_pos, trunk_x
        )
        cells = self._orthogonal_cells_from_points(points)

        if self._blocked_conflicts(cells, blocked, start_anchor, preview_anchor) > 0:
            start_cell = self._scene_to_grid(start_anchor)
            end_cell = self._scene_to_grid(preview_anchor)
            bounds = self._local_grid_bounds(start_cell, end_cell)
            band = self._routing_band(start_cell, end_cell)
            alt_cells = self._find_grid_path(
                start_anchor, preview_anchor, blocked, set(), bounds,
                preferred_band=band,
            )
            if alt_cells:
                alt_points = self._compose_route_points(
                    start, start_anchor, alt_cells, preview_anchor, end_pos,
                )
                return alt_points, alt_cells

        return points, cells

    def _compose_route_points(
        self,
        start: QPointF,
        start_anchor: QPointF,
        cells: list[tuple[int, int]],
        end_anchor: QPointF,
        end: QPointF,
    ) -> list[QPointF]:
        points: list[QPointF] = [start]

        def add_point(point: QPointF):
            last = points[-1]
            if _same_x(last, point) and _same_y(last, point):
                return
            if (not _same_x(last, point)) and (not _same_y(last, point)):
                elbow = QPointF(point.x(), last.y())
                if not (_same_x(last, elbow) and _same_y(last, elbow)):
                    points.append(elbow)
            points.append(point)

        if not _same_x(start, start_anchor):
            add_point(QPointF(start_anchor.x(), start.y()))
        add_point(start_anchor)

        grid_points = [self._grid_to_scene(cell) for cell in cells]
        if grid_points:
            for point in grid_points[1:-1]:
                add_point(point)

        add_point(end_anchor)
        if not _same_y(points[-1], end):
            add_point(QPointF(points[-1].x(), end.y()))
        add_point(end)

        return _simplify_points(points)

    def _blocked_cells(self) -> set[tuple[int, int]]:
        blocked: set[tuple[int, int]] = set()
        for node in self._nodes.values():
            rect = node.mapRectToScene(node.rect()).adjusted(
                -NODE_CLEARANCE, -NODE_CLEARANCE,
                NODE_CLEARANCE, NODE_CLEARANCE,
            )
            gx0 = math.floor(rect.left() / GRID_STEP)
            gx1 = math.ceil(rect.right() / GRID_STEP)
            gy0 = math.floor(rect.top() / GRID_STEP)
            gy1 = math.ceil(rect.bottom() / GRID_STEP)
            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    blocked.add((gx, gy))
        return blocked

    def _reserved_cells(
        self, exclude_wire: WireItem | None = None,
    ) -> set[tuple[int, int]]:
        reserved: set[tuple[int, int]] = set()
        for wire in self._wires:
            if wire is exclude_wire:
                continue
            reserved.update(wire._route_cells)
        return reserved

    def _port_anchor(self, port: PortItem, lane_hint: int = 0) -> QPointF:
        pos = port.center_scene_pos()
        lane_offset = min(max(0, lane_hint), 4) * GRID_STEP
        offset = PORT_ANCHOR_OFFSET + lane_offset
        if port.direction in (PortDirection.OUTPUT, PortDirection.INOUT):
            anchor = QPointF(pos.x() + offset, pos.y())
        else:
            anchor = QPointF(pos.x() - offset, pos.y())
        return self._snap_to_grid(anchor)

    def _snap_to_grid(self, point: QPointF) -> QPointF:
        return self._grid_to_scene(self._scene_to_grid(point))

    def _scene_to_grid(self, point: QPointF) -> tuple[int, int]:
        return (
            int(round(point.x() / GRID_STEP)),
            int(round(point.y() / GRID_STEP)),
        )

    def _grid_to_scene(self, cell: tuple[int, int]) -> QPointF:
        return QPointF(cell[0] * GRID_STEP, cell[1] * GRID_STEP)

    def _local_grid_bounds(
        self, start_cell: tuple[int, int], end_cell: tuple[int, int],
    ) -> tuple[int, int, int, int]:
        dx = abs(start_cell[0] - end_cell[0])
        dy = abs(start_cell[1] - end_cell[1])
        pad = max(LOCAL_PAD_MIN, min(LOCAL_PAD_MAX, (dx + dy) // 2 + 6))
        return (
            min(start_cell[0], end_cell[0]) - pad,
            max(start_cell[0], end_cell[0]) + pad,
            min(start_cell[1], end_cell[1]) - pad,
            max(start_cell[1], end_cell[1]) + pad,
        )

    def _search_bounds(
        self, start_cell: tuple[int, int], end_cell: tuple[int, int],
    ) -> list[tuple[int, int, int, int] | None]:
        local = self._local_grid_bounds(start_cell, end_cell)
        return [
            local,
            self._expand_bounds(local, LOCAL_EXPAND_STEP),
            self._expand_bounds(local, LOCAL_EXPAND_STEP * 2),
            None,
        ]

    def _expand_bounds(
        self, bounds: tuple[int, int, int, int], pad: int,
    ) -> tuple[int, int, int, int]:
        min_x, max_x, min_y, max_y = bounds
        return (min_x - pad, max_x + pad, min_y - pad, max_y + pad)

    def _routing_band(
        self, start_cell: tuple[int, int], end_cell: tuple[int, int],
    ) -> tuple[int, int]:
        return (
            min(start_cell[1], end_cell[1]) - ROUTE_BAND_MARGIN,
            max(start_cell[1], end_cell[1]) + ROUTE_BAND_MARGIN,
        )

    def _expanded_cells(
        self, cells: set[tuple[int, int]], radius: int,
    ) -> set[tuple[int, int]]:
        if radius <= 0 or not cells:
            return set(cells)
        expanded = set(cells)
        for cx, cy in cells:
            for ox in range(-radius, radius + 1):
                for oy in range(-radius, radius + 1):
                    if abs(ox) + abs(oy) <= radius:
                        expanded.add((cx + ox, cy + oy))
        return expanded

    def _fallback_outer_lane(
        self,
        start_cell: tuple[int, int],
        end_cell: tuple[int, int],
        blocked: set[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        if not blocked:
            return [start_cell, end_cell]

        ys = [cell[1] for cell in blocked]
        top_lane = min(ys) - 2
        bottom_lane = max(ys) + 2

        candidates = []
        top_cells = self._cells_via_lane(start_cell, end_cell, top_lane)
        if self._cells_clear(top_cells, blocked, start_cell, end_cell):
            candidates.append(top_cells)

        bottom_cells = self._cells_via_lane(start_cell, end_cell, bottom_lane)
        if self._cells_clear(bottom_cells, blocked, start_cell, end_cell):
            candidates.append(bottom_cells)

        if not candidates:
            return []
        return min(candidates, key=len)

    def _cells_via_lane(
        self,
        start_cell: tuple[int, int],
        end_cell: tuple[int, int],
        lane_y: int,
    ) -> list[tuple[int, int]]:
        cells = self._straight_cells(start_cell, (start_cell[0], lane_y))
        cells.extend(self._straight_cells((start_cell[0], lane_y), (end_cell[0], lane_y))[1:])
        cells.extend(self._straight_cells((end_cell[0], lane_y), end_cell)[1:])
        return _unique_cells_in_order(cells)

    def _cells_clear(
        self,
        cells: list[tuple[int, int]],
        blocked: set[tuple[int, int]],
        start_cell: tuple[int, int],
        end_cell: tuple[int, int],
    ) -> bool:
        for cell in cells:
            if cell in (start_cell, end_cell):
                continue
            if cell in blocked:
                return False
        return True

    def _straight_cells(
        self, start_cell: tuple[int, int], end_cell: tuple[int, int],
    ) -> list[tuple[int, int]]:
        if start_cell == end_cell:
            return [start_cell]
        x0, y0 = start_cell
        x1, y1 = end_cell
        cells = [start_cell]
        if x0 == x1:
            step = 1 if y1 >= y0 else -1
            for y in range(y0 + step, y1 + step, step):
                cells.append((x0, y))
            return cells
        if y0 == y1:
            step = 1 if x1 >= x0 else -1
            for x in range(x0 + step, x1 + step, step):
                cells.append((x, y0))
            return cells
        # For any diagonal request, use one elbow.
        cells.extend(self._straight_cells(start_cell, (x1, y0))[1:])
        cells.extend(self._straight_cells((x1, y0), end_cell)[1:])
        return _unique_cells_in_order(cells)

    def _find_grid_path(
        self,
        start: QPointF,
        end: QPointF,
        blocked: set[tuple[int, int]],
        reserved: set[tuple[int, int]],
        bounds: tuple[int, int, int, int] | None,
        preferred_band: tuple[int, int] | None = None,
    ) -> list[tuple[int, int]]:
        start_cell = self._scene_to_grid(start)
        end_cell = self._scene_to_grid(end)
        if start_cell == end_cell:
            return [start_cell]

        blocked = set(blocked)
        blocked.discard(start_cell)
        blocked.discard(end_cell)

        if bounds is None:
            rect = self._scene.sceneRect()
            min_x = math.floor(rect.left() / GRID_STEP) - 2
            max_x = math.ceil(rect.right() / GRID_STEP) + 2
            min_y = math.floor(rect.top() / GRID_STEP) - 2
            max_y = math.ceil(rect.bottom() / GRID_STEP) + 2
        else:
            min_x, max_x, min_y, max_y = bounds

        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        start_state = (start_cell, None)
        open_heap: list[tuple[float, float, tuple[int, int], int | None]] = [
            (_manhattan(start_cell, end_cell), 0.0, start_cell, None)
        ]
        came_from: dict[
            tuple[tuple[int, int], int | None],
            tuple[tuple[int, int], int | None] | None,
        ] = {start_state: None}
        best_cost = {start_state: 0.0}

        while open_heap:
            _, cost, cell, prev_dir = heapq.heappop(open_heap)
            state = (cell, prev_dir)
            if cost > best_cost.get(state, float("inf")):
                continue
            if cell == end_cell:
                return self._reconstruct_cells(came_from, state)

            for dir_idx, (dx, dy) in enumerate(directions):
                neighbor = (cell[0] + dx, cell[1] + dy)
                if neighbor[0] < min_x or neighbor[0] > max_x:
                    continue
                if neighbor[1] < min_y or neighbor[1] > max_y:
                    continue
                if neighbor in blocked:
                    continue

                step_cost = 1.0
                if prev_dir is not None and dir_idx != prev_dir:
                    step_cost += TURN_PENALTY
                if neighbor in reserved and neighbor not in (start_cell, end_cell):
                    step_cost += WIRE_RESERVED_PENALTY
                elif neighbor not in (start_cell, end_cell):
                    # Also avoid hugging existing wires too closely.
                    nearby_reserved = any(
                        (neighbor[0] + ox, neighbor[1] + oy) in reserved
                        for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    )
                    if nearby_reserved:
                        step_cost += WIRE_RESERVED_PENALTY * 0.35
                if preferred_band is not None:
                    band_top, band_bottom = preferred_band
                    if neighbor[1] < band_top:
                        step_cost += (band_top - neighbor[1]) * ROUTE_OUT_OF_BAND_PENALTY
                    elif neighbor[1] > band_bottom:
                        step_cost += (neighbor[1] - band_bottom) * ROUTE_OUT_OF_BAND_PENALTY

                next_cost = cost + step_cost
                next_state = (neighbor, dir_idx)
                if next_cost >= best_cost.get(next_state, float("inf")):
                    continue

                best_cost[next_state] = next_cost
                came_from[next_state] = state
                priority = next_cost + _manhattan(neighbor, end_cell)
                heapq.heappush(
                    open_heap,
                    (priority, next_cost, neighbor, dir_idx),
                )

        return []

    def _reconstruct_cells(
        self,
        came_from: dict[
            tuple[tuple[int, int], int | None],
            tuple[tuple[int, int], int | None] | None,
        ],
        state: tuple[tuple[int, int], int | None],
    ) -> list[tuple[int, int]]:
        cells: list[tuple[int, int]] = []
        while state is not None:
            cell, _ = state
            cells.append(cell)
            state = came_from.get(state)
        cells.reverse()
        return cells

    # ── Keyboard shortcuts ────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected_wires()
            event.accept()
            return
        super().keyPressEvent(event)

    # ── Zoom ──────────────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    # ── Load instances ────────────────────────────────────

    def load_instances(self, instances: list[InstanceInfo]):
        self.clear_all()
        for inst in instances:
            self.add_node(inst)

    # ── Auto-Layout (Hierarchical Left-to-Right Dataflow) ─

    def auto_layout(self):
        """Execute the hierarchical left-to-right auto-layout algorithm.

        Step A: Build a directed dependency graph from the QTableWidget.
        Step B: Assign levels via topological sort (with cycle-break fail-safe).
        Step C: Calculate (X, Y) coordinates and animate nodes.
        """
        if not self._nodes or not self._table:
            return

        # Step A
        adj = self._build_dependency_graph()

        # Step B
        levels = self._assign_levels(adj)

        # Step C
        positions = self._calculate_positions(levels)

        # Animate
        self._animate_to_positions(positions)

    # ── Step A: Dependency Graph ──────────────────────────

    def _build_dependency_graph(self) -> dict[str, set[str]]:
        """Analyse the table to create inst_A → inst_B edges.

        An edge exists when an *output* of A shares a net name with
        an *input* of B.
        """
        from topstitcher.gui.connection_view import (
            COL_INSTANCE, COL_DIR, COL_NET,
        )

        # net_name → [(instance_name, direction_str)]
        net_map: dict[str, list[tuple[str, str]]] = {}
        for row in range(self._table.rowCount()):
            inst_item = self._table.item(row, COL_INSTANCE)
            dir_item = self._table.item(row, COL_DIR)
            net_item = self._table.item(row, COL_NET)
            if not (inst_item and dir_item and net_item):
                continue
            inst = inst_item.text()
            direction = dir_item.text()
            net = net_item.text().strip()
            if net:
                net_map.setdefault(net, []).append((inst, direction))

        # Build adjacency: output→input across different instances
        adj: dict[str, set[str]] = {name: set() for name in self._nodes}

        for net_name, ports in net_map.items():
            if len(ports) < 2:
                continue
            drivers = [
                inst for inst, d in ports
                if d in ("output", "inout") and inst in self._nodes
            ]
            receivers = [
                inst for inst, d in ports
                if d in ("input", "inout") and inst in self._nodes
            ]
            for drv in drivers:
                for rcv in receivers:
                    if drv != rcv:
                        adj[drv].add(rcv)

        return adj

    # ── Step B: Level Assignment (Topological Sort) ───────

    def _assign_levels(self, adj: dict[str, set[str]]) -> dict[str, int]:
        """Assign each node a *level* (column) using Kahn's algorithm.

        Nodes driven only by top-level inputs (in-degree 0) are Level 0.
        A fail-safe breaks feedback loops by forcing the node with the
        smallest in-degree into the current level.
        """
        all_nodes = set(self._nodes.keys())

        # Compute in-degree (only for edges among existing nodes)
        in_degree: dict[str, int] = {n: 0 for n in all_nodes}
        for src in all_nodes:
            for dst in adj.get(src, set()):
                if dst in in_degree:
                    in_degree[dst] += 1

        levels: dict[str, int] = {}
        remaining = set(all_nodes)
        current_level = 0

        while remaining:
            # Collect nodes with in-degree 0
            zero_in = [n for n in remaining if in_degree[n] == 0]

            if not zero_in:
                # ── Cycle detected! Break it gracefully ──
                # Pick the node with the smallest in-degree to minimise
                # layout disruption.
                node = min(remaining, key=lambda n: in_degree[n])
                in_degree[node] = 0
                zero_in = [node]

            for node in zero_in:
                levels[node] = current_level
                remaining.discard(node)

            # Reduce in-degree of successors
            for node in zero_in:
                for neighbor in adj.get(node, set()):
                    if neighbor in remaining:
                        in_degree[neighbor] = max(0, in_degree[neighbor] - 1)

            current_level += 1

        return levels

    # ── Step C: Coordinate Calculation ────────────────────

    def _calculate_positions(
        self, levels: dict[str, int],
    ) -> dict[str, tuple[float, float]]:
        """Map level assignments to (X, Y) pixel coordinates.

        Nodes in the same level are stacked vertically; the entire
        layout is centred around the scene origin.
        """
        if not levels:
            return {}

        # Group by level
        level_groups: dict[int, list[str]] = {}
        for node_name, level in levels.items():
            level_groups.setdefault(level, []).append(node_name)

        # Sort within each level for deterministic output
        for lvl in level_groups:
            level_groups[lvl].sort()

        positions: dict[str, tuple[float, float]] = {}

        for lvl, nodes in level_groups.items():
            x = lvl * self.H_SPACING
            # Centre this column vertically
            total_h = (len(nodes) - 1) * self.V_SPACING
            start_y = -total_h / 2.0
            for i, name in enumerate(nodes):
                positions[name] = (x, start_y + i * self.V_SPACING)

        # Centre the whole layout around (0, 0)
        if positions:
            avg_x = sum(p[0] for p in positions.values()) / len(positions)
            avg_y = sum(p[1] for p in positions.values()) / len(positions)
            positions = {
                n: (x - avg_x, y - avg_y)
                for n, (x, y) in positions.items()
            }

        return positions

    # ── Smooth Animation ─────────────────────────────────

    def _animate_to_positions(
        self, positions: dict[str, tuple[float, float]],
    ):
        """Slide every node to its target (X, Y) over 300 ms."""
        # Stop any running animations from a previous layout run
        for anim in self._animations:
            anim.stop()
        self._animations.clear()

        for node_name, (tx, ty) in positions.items():
            node = self._nodes.get(node_name)
            if node is None:
                continue

            start = node.pos()
            end = QPointF(tx, ty)

            anim = QVariantAnimation()
            anim.setDuration(300)
            anim.setStartValue(start)
            anim.setEndValue(end)
            anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

            # Closure helper to capture *this* node
            def _make_slot(n: NodeItem):
                def _on_value(value):
                    n.setPos(value)
                return _on_value

            anim.valueChanged.connect(_make_slot(node))
            anim.start()
            self._animations.append(anim)
