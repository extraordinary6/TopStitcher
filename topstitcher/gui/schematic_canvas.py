"""Schematic canvas with interactive node editor (QGraphicsView-based)."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsTextItem,
    QGraphicsItem, QGraphicsSceneMouseEvent, QMenu,
)
from PyQt6.QtCore import Qt, QPointF, QVariantAnimation, QEasingCurve
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
    """A cubic Bezier wire between two PortItems."""

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
        self._update_pen()
        self.update_path(end_pos)

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
        p1 = self.source.center_scene_pos()
        if self.target:
            p2 = self.target.center_scene_pos()
        elif end_pos:
            p2 = end_pos
        else:
            return

        dx = abs(p2.x() - p1.x()) * 0.5
        dx = max(dx, 40)

        if self.source.direction in (PortDirection.OUTPUT, PortDirection.INOUT):
            c1 = QPointF(p1.x() + dx, p1.y())
        else:
            c1 = QPointF(p1.x() - dx, p1.y())

        if self.target:
            if self.target.direction in (PortDirection.INPUT, PortDirection.INOUT):
                c2 = QPointF(p2.x() - dx, p2.y())
            else:
                c2 = QPointF(p2.x() + dx, p2.y())
        else:
            c2 = QPointF(p2.x() - dx, p2.y())

        path = QPainterPath(p1)
        path.cubicTo(c1, c2, p2)
        self.setPath(path)

    def finalize(self, target: PortItem, net_name: str):
        self.target = target
        self.net_name = net_name
        self._temporary = False
        self._update_pen()
        self.update_path()


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

        from topstitcher.gui.connection_view import COL_INSTANCE, COL_PORT, COL_NET
        net_map: dict[str, list[tuple[str, str]]] = {}
        for row in range(self._table.rowCount()):
            inst_item = self._table.item(row, COL_INSTANCE)
            port_item = self._table.item(row, COL_PORT)
            net_item = self._table.item(row, COL_NET)
            if not (inst_item and port_item and net_item):
                continue
            inst = inst_item.text()
            port = port_item.text()
            net = net_item.text().strip()
            if net:
                net_map.setdefault(net, []).append((inst, port))

        for net_name, ports in net_map.items():
            if len(ports) < 2:
                continue
            src_inst, src_port = ports[0]
            src_pi = self._find_port_item(src_inst, src_port)
            if not src_pi:
                continue
            for dst_inst, dst_port in ports[1:]:
                dst_pi = self._find_port_item(dst_inst, dst_port)
                if not dst_pi:
                    continue
                wire = WireItem(src_pi, dst_pi)
                wire.net_name = net_name
                self._scene.addItem(wire)
                self._wires.append(wire)

    def update_wires_for_node(self, node: NodeItem):
        for wire in self._wires:
            if (wire.source.instance_name == node.instance_name
                    or (wire.target and wire.target.instance_name == node.instance_name)):
                wire.update_path()

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

    # ── Context menu ──────────────────────────────────────

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

            self._drag_wire.finalize(target, net_name)
            self._wires.append(self._drag_wire)
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
