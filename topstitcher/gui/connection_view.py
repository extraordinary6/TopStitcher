"""Workspace editor, debug projection, canvas, and parameter editor."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from topstitcher.core.data_model import (
    DesignWorkspace,
    InstanceInfo,
    NetType,
    PortAssignment,
    PortDirection,
    PortRef,
    TOP_LEVEL_INSTANCE,
)
from topstitcher.core.connection_engine import (
    S_CONFLICT,
    S_MULTI_DRIVER,
    S_PROMOTED,
    S_UNDRIVEN,
    S_WIDTH_MISMATCH,
)
from topstitcher.gui.schematic_canvas import SchematicCanvas

COL_INSTANCE = 0
COL_PORT = 1
COL_DIR = 2
COL_WIDTH = 3
COL_NET = 4
COL_STATUS = 5

PCOL_INSTANCE = 0
PCOL_PARAM = 1
PCOL_VALUE = 2

ROLE_PORT_REF = Qt.ItemDataRole.UserRole

_DIR_COLORS = {
    PortDirection.INPUT: QColor(34, 139, 34),
    PortDirection.OUTPUT: QColor(210, 105, 30),
    PortDirection.INOUT: QColor(30, 90, 210),
}

_STATUS_STYLES: dict[str, tuple[QColor, QColor]] = {
    S_PROMOTED:       (QColor(255, 235, 205), QColor(200, 100, 0)),
    S_WIDTH_MISMATCH: (QColor(255, 255, 200), QColor(180, 140, 0)),
    S_MULTI_DRIVER:   (QColor(255, 210, 210), QColor(200, 0, 0)),
    S_UNDRIVEN:       (QColor(255, 230, 210), QColor(200, 80, 0)),
    S_CONFLICT:       (QColor(255, 200, 200), QColor(180, 0, 0)),
}


def _status_style(status: str) -> tuple[QColor | None, QColor | None]:
    priority = [
        S_MULTI_DRIVER,
        S_CONFLICT,
        S_UNDRIVEN,
        S_WIDTH_MISMATCH,
        S_PROMOTED,
    ]
    for tag in priority:
        if tag in status:
            return _STATUS_STYLES[tag]
    return None, None


def _range_str(width: int, msb_expr: str, lsb_expr: str) -> str:
    if width == 1:
        return ""
    return f" [{msb_expr}:{lsb_expr}]"


class ConnectionViewWidget(QWidget):
    """Tabbed workspace with a three-column connection editor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workspace: DesignWorkspace | None = None
        self._rename_callback = None
        self._connect_action_callback = None
        self._disconnect_action_callback = None
        self._auto_io_action_callback = None
        self._auto_connect_action_callback = None
        self._connect_callback = None
        self._disconnect_callback = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_workspace_tab()
        self._build_debug_table_tab()
        self._build_canvas_tab()
        self._build_param_tab()

        self._mode_btn.setEnabled(True)
        self._sync_btn.setEnabled(True)
        self._del_wire_btn.setEnabled(True)
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(False)
        self._auto_io_btn.setEnabled(False)
        self._auto_connect_btn.setEnabled(False)
        self._rename_btn.setEnabled(False)

        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _build_workspace_tab(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        page_layout.addWidget(splitter, 1)

        left_box = QGroupBox("Left: Instance Inputs / Top Outputs")
        left_layout = QVBoxLayout(left_box)
        self.left_tree = self._make_tree()
        left_layout.addWidget(self.left_tree)
        splitter.addWidget(left_box)

        center_box = QGroupBox("Actions")
        center_layout = QVBoxLayout(center_box)
        self.left_selected_label = QLabel("Left: —")
        self.right_selected_label = QLabel("Right: —")
        center_layout.addWidget(self.left_selected_label)
        center_layout.addWidget(self.right_selected_label)
        center_layout.addSpacing(8)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        center_layout.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        center_layout.addWidget(self._disconnect_btn)

        self._auto_io_btn = QPushButton("Auto IO")
        self._auto_io_btn.clicked.connect(self._on_auto_io_clicked)
        center_layout.addWidget(self._auto_io_btn)

        self._auto_connect_btn = QPushButton("Auto Connect")
        self._auto_connect_btn.clicked.connect(self._on_auto_connect_clicked)
        center_layout.addWidget(self._auto_connect_btn)

        center_layout.addSpacing(8)
        center_layout.addWidget(QLabel("Rename Net"))
        self.rename_net_edit = QLineEdit()
        center_layout.addWidget(self.rename_net_edit)
        self._rename_btn = QPushButton("Rename Selected Net")
        self._rename_btn.clicked.connect(self._on_rename_clicked)
        center_layout.addWidget(self._rename_btn)
        center_layout.addStretch(1)
        splitter.addWidget(center_box)

        right_box = QGroupBox("Right: Instance Outputs / Top Inputs")
        right_layout = QVBoxLayout(right_box)
        self.right_tree = self._make_tree()
        right_layout.addWidget(self.right_tree)
        splitter.addWidget(right_box)

        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 5)

        inout_box = QGroupBox("Inout")
        inout_layout = QVBoxLayout(inout_box)
        self.inout_tree = self._make_tree()
        inout_layout.addWidget(self.inout_tree)
        page_layout.addWidget(inout_box, 0)

        self.tabs.addTab(page, "Workspace")

    def _build_debug_table_tab(self):
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Instance Name", "Port Name", "Direction", "Width",
            "Assigned Net / Top Port Name", "Status",
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.tabs.addTab(self.table, "Netlist Table (Debug)")

    def _build_canvas_tab(self):
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        self._mode_btn = QPushButton("Mode: Auto-Wiring")
        self._mode_btn.setCheckable(True)
        self._mode_btn.toggled.connect(self._on_mode_toggled)
        toolbar.addWidget(self._mode_btn)

        self._sync_btn = QPushButton("Refresh Canvas")
        self._sync_btn.clicked.connect(self._on_sync_clicked)
        toolbar.addWidget(self._sync_btn)

        self._del_wire_btn = QPushButton("Delete Selected Wire")
        self._del_wire_btn.clicked.connect(self._on_delete_wire_clicked)
        toolbar.addWidget(self._del_wire_btn)

        toolbar.addStretch()

        self._auto_layout_btn = QPushButton("Auto Layout")
        self._auto_layout_btn.clicked.connect(self._on_auto_layout_clicked)
        toolbar.addWidget(self._auto_layout_btn)

        canvas_layout.addLayout(toolbar)

        self.canvas = SchematicCanvas()
        self.canvas.set_connection_callback(self._on_canvas_connection)
        self.canvas.set_removal_callback(self._on_canvas_wire_removed)
        canvas_layout.addWidget(self.canvas)

        self.tabs.addTab(canvas_container, "Schematic Canvas")

    def _build_param_tab(self):
        self.param_table = QTableWidget()
        self.param_table.setColumnCount(3)
        self.param_table.setHorizontalHeaderLabels([
            "Instance Name", "Parameter", "Value",
        ])
        pheader = self.param_table.horizontalHeader()
        pheader.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.param_table.setSortingEnabled(True)
        self.tabs.addTab(self.param_table, "Instance Parameters")

    def _make_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(1)
        tree.setHeaderHidden(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.itemSelectionChanged.connect(self._on_workspace_selection_changed)
        return tree

    def set_rename_callback(self, callback):
        self._rename_callback = callback

    def set_connect_action_callback(self, callback):
        self._connect_action_callback = callback

    def set_disconnect_action_callback(self, callback):
        self._disconnect_action_callback = callback

    def set_auto_io_action_callback(self, callback):
        self._auto_io_action_callback = callback

    def set_auto_connect_action_callback(self, callback):
        self._auto_connect_action_callback = callback

    def set_connect_callback(self, callback):
        self._connect_callback = callback

    def set_disconnect_callback(self, callback):
        self._disconnect_callback = callback

    def get_selected_instance_port_keys(self) -> set[tuple[str, str]]:
        result: set[tuple[str, str]] = set()
        for ref in self._selected_refs():
            if ref and ref.instance_name != TOP_LEVEL_INSTANCE:
                result.add((ref.instance_name, ref.port_name))
        return result

    def get_selected_connect_pair(self) -> tuple[PortRef, PortRef] | None:
        left = self._selected_ref_from_tree(self.left_tree)
        right = self._selected_ref_from_tree(self.right_tree)
        if left and right:
            return left, right
        return None

    def get_selected_disconnect_pair(self) -> tuple[PortRef, PortRef] | None:
        left = self._selected_ref_from_tree(self.left_tree)
        right = self._selected_ref_from_tree(self.right_tree)
        if left and right:
            return left, right
        return None

    def get_selected_auto_io_ref(self) -> PortRef | None:
        return (
            self._selected_ref_from_tree(self.left_tree)
            or self._selected_ref_from_tree(self.right_tree)
            or self._selected_ref_from_tree(self.inout_tree)
        )

    def load_assignments(
        self,
        assignments: list[PortAssignment],
        workspace: DesignWorkspace | None = None,
    ):
        self._workspace = workspace
        self._populate_workspace_editor(assignments)
        self._populate_debug_table(assignments)

    def _populate_workspace_editor(self, assignments: list[PortAssignment]):
        self.left_tree.clear()
        self.right_tree.clear()
        self.inout_tree.clear()
        self.left_selected_label.setText("Left: —")
        self.right_selected_label.setText("Right: —")
        self.rename_net_edit.clear()
        self._rename_btn.setEnabled(False)

        if not self._workspace:
            return

        assignment_map = {
            (a.instance_name, a.port_name): a
            for a in assignments
        }

        left_groups: dict[str, QTreeWidgetItem] = {}
        right_groups: dict[str, QTreeWidgetItem] = {}
        inout_groups: dict[str, QTreeWidgetItem] = {}

        for inst in self._workspace.instances:
            for port in sorted(inst.ports, key=lambda item: item.name):
                assignment = assignment_map[(inst.instance_name, port.name)]
                ref = PortRef(inst.instance_name, port.name)
                if port.direction == PortDirection.INPUT:
                    group = self._ensure_group(self.left_tree, left_groups, inst.instance_name)
                    self._add_port_item(group, ref, port.name, assignment.width, assignment.msb_expr, assignment.lsb_expr, assignment.assigned_net, assignment.status)
                elif port.direction == PortDirection.OUTPUT:
                    group = self._ensure_group(self.right_tree, right_groups, inst.instance_name)
                    self._add_port_item(group, ref, port.name, assignment.width, assignment.msb_expr, assignment.lsb_expr, assignment.assigned_net, assignment.status)
                else:
                    group = self._ensure_group(self.inout_tree, inout_groups, inst.instance_name)
                    self._add_port_item(group, ref, port.name, assignment.width, assignment.msb_expr, assignment.lsb_expr, assignment.assigned_net, assignment.status)

        top_outputs_group = None
        top_inputs_group = None
        for net in sorted(self._workspace.nets.values(), key=lambda item: item.net_name):
            top_ref = PortRef(TOP_LEVEL_INSTANCE, net.net_id)
            if net.net_type == NetType.OUTPUT:
                if top_outputs_group is None:
                    top_outputs_group = self._ensure_group(self.left_tree, left_groups, "Top Outputs")
                self._add_top_item(top_outputs_group, top_ref, net.net_name, net.width, net.msb_expr, net.lsb_expr, ", ".join(net.warnings))
            elif net.net_type == NetType.INPUT:
                if top_inputs_group is None:
                    top_inputs_group = self._ensure_group(self.right_tree, right_groups, "Top Inputs")
                self._add_top_item(top_inputs_group, top_ref, net.net_name, net.width, net.msb_expr, net.lsb_expr, ", ".join(net.warnings))

        self.left_tree.expandAll()
        self.right_tree.expandAll()
        self.inout_tree.expandAll()

    def _ensure_group(
        self,
        tree: QTreeWidget,
        groups: dict[str, QTreeWidgetItem],
        title: str,
    ) -> QTreeWidgetItem:
        if title in groups:
            return groups[title]
        item = QTreeWidgetItem([title])
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        tree.addTopLevelItem(item)
        groups[title] = item
        return item

    def _add_port_item(
        self,
        parent: QTreeWidgetItem,
        ref: PortRef,
        port_name: str,
        width: int,
        msb_expr: str,
        lsb_expr: str,
        net_name: str,
        status: str,
    ):
        text = f"{port_name}{_range_str(width, msb_expr, lsb_expr)}  [{net_name}]"
        if status:
            text += f"  ({status})"
        item = QTreeWidgetItem([text])
        item.setData(0, ROLE_PORT_REF, (ref.instance_name, ref.port_name))
        bg, fg = _status_style(status)
        if bg:
            item.setBackground(0, bg)
        if fg:
            item.setForeground(0, fg)
        parent.addChild(item)

    def _add_top_item(
        self,
        parent: QTreeWidgetItem,
        ref: PortRef,
        net_name: str,
        width: int,
        msb_expr: str,
        lsb_expr: str,
        status: str,
    ):
        text = f"{net_name}{_range_str(width, msb_expr, lsb_expr)}"
        if status:
            text += f"  ({status})"
        item = QTreeWidgetItem([text])
        item.setData(0, ROLE_PORT_REF, (ref.instance_name, ref.port_name))
        bg, fg = _status_style(status)
        if bg:
            item.setBackground(0, bg)
        if fg:
            item.setForeground(0, fg)
        parent.addChild(item)

    def _selected_ref_from_tree(self, tree: QTreeWidget) -> PortRef | None:
        items = tree.selectedItems()
        if not items:
            return None
        payload = items[0].data(0, ROLE_PORT_REF)
        if not payload:
            return None
        return PortRef(payload[0], payload[1])

    def _selected_refs(self) -> list[PortRef | None]:
        return [
            self._selected_ref_from_tree(self.left_tree),
            self._selected_ref_from_tree(self.right_tree),
            self._selected_ref_from_tree(self.inout_tree),
        ]

    def _on_workspace_selection_changed(self):
        left = self._selected_ref_from_tree(self.left_tree)
        right = self._selected_ref_from_tree(self.right_tree)
        self.left_selected_label.setText(f"Left: {self._describe_ref(left)}")
        self.right_selected_label.setText(f"Right: {self._describe_ref(right)}")

        current = left or right or self._selected_ref_from_tree(self.inout_tree)
        current_net = self._current_net_name(current)
        self.rename_net_edit.setText(current_net)
        self._rename_btn.setEnabled(bool(current))
        self._connect_btn.setEnabled(bool(left and right))
        self._disconnect_btn.setEnabled(bool(left and right))
        self._auto_io_btn.setEnabled(bool(current and current.instance_name != TOP_LEVEL_INSTANCE))
        self._auto_connect_btn.setEnabled(bool(self._workspace and self._workspace.instances))

    def _describe_ref(self, ref: PortRef | None) -> str:
        if not ref:
            return "—"
        if ref.instance_name == TOP_LEVEL_INSTANCE and self._workspace:
            return f"top.{self._workspace.nets[ref.port_name].net_name}"
        return f"{ref.instance_name}.{ref.port_name}"

    def _current_net_name(self, ref: PortRef | None) -> str:
        if not ref or not self._workspace:
            return ""
        if ref.instance_name == TOP_LEVEL_INSTANCE:
            return self._workspace.nets[ref.port_name].net_name
        net_id = self._workspace.port_to_net.get(ref)
        if not net_id:
            return ""
        return self._workspace.nets[net_id].net_name

    def _on_connect_clicked(self):
        if self._connect_action_callback:
            self._connect_action_callback()

    def _on_disconnect_clicked(self):
        if self._disconnect_action_callback:
            self._disconnect_action_callback()

    def _on_auto_io_clicked(self):
        if self._auto_io_action_callback:
            self._auto_io_action_callback()

    def _on_auto_connect_clicked(self):
        if self._auto_connect_action_callback:
            self._auto_connect_action_callback()

    def _on_rename_clicked(self):
        if not self._rename_callback:
            return
        current = (
            self._selected_ref_from_tree(self.left_tree)
            or self._selected_ref_from_tree(self.right_tree)
            or self._selected_ref_from_tree(self.inout_tree)
        )
        if not current:
            return
        new_name = self.rename_net_edit.text().strip()
        if not new_name:
            return
        self._rename_callback(current, new_name)

    def _build_canvas_projection(self, assignments: list[PortAssignment]) -> list[tuple[str, str, str, str]]:
        return [
            (a.instance_name, a.port_name, a.direction.value, a.assigned_net)
            for a in assignments
        ]

    def _is_canvas_tab_active(self) -> bool:
        return self.tabs.currentWidget() is not None and self.tabs.tabText(self.tabs.currentIndex()) == "Schematic Canvas"

    def _populate_debug_table(self, assignments: list[PortAssignment]):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(assignments))

        for row, a in enumerate(assignments):
            bg, fg = _status_style(a.status)

            inst_item = QTableWidgetItem(a.instance_name)
            inst_item.setFlags(inst_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if bg:
                inst_item.setBackground(bg)
            self.table.setItem(row, COL_INSTANCE, inst_item)

            port_item = QTableWidgetItem(a.port_name)
            port_item.setFlags(port_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if bg:
                port_item.setBackground(bg)
            self.table.setItem(row, COL_PORT, port_item)

            dir_item = QTableWidgetItem(a.direction.value)
            dir_item.setFlags(dir_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            color = _DIR_COLORS.get(a.direction)
            if color:
                dir_item.setForeground(color)
            if bg:
                dir_item.setBackground(bg)
            self.table.setItem(row, COL_DIR, dir_item)

            width_str = str(a.width) if a.width > 0 else "param"
            width_item = QTableWidgetItem(width_str)
            width_item.setFlags(width_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if bg:
                width_item.setBackground(bg)
            self.table.setItem(row, COL_WIDTH, width_item)

            net_item = QTableWidgetItem(a.assigned_net)
            net_item.setFlags(net_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if bg:
                net_item.setBackground(bg)
            self.table.setItem(row, COL_NET, net_item)

            status_item = QTableWidgetItem(a.status)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if bg:
                status_item.setBackground(bg)
            if fg:
                status_item.setForeground(fg)
            self.table.setItem(row, COL_STATUS, status_item)

        self.canvas.set_connection_projection(self._build_canvas_projection(assignments))
        self.table.setSortingEnabled(True)
        if not self.canvas.manual_mode and self._is_canvas_tab_active():
            self.canvas.sync_wires_from_projection()

    def load_parameters(self, instances: list[InstanceInfo]):
        self.param_table.setSortingEnabled(False)
        rows = []
        for inst in instances:
            for param in inst.params:
                rows.append((inst.instance_name, param.name, param.value))

        self.param_table.setRowCount(len(rows))
        for row, (inst_name, pname, pval) in enumerate(rows):
            inst_item = QTableWidgetItem(inst_name)
            inst_item.setFlags(inst_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.param_table.setItem(row, PCOL_INSTANCE, inst_item)

            name_item = QTableWidgetItem(pname)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.param_table.setItem(row, PCOL_PARAM, name_item)

            val_item = QTableWidgetItem(pval)
            self.param_table.setItem(row, PCOL_VALUE, val_item)

        self.param_table.setSortingEnabled(True)

    def load_instances_to_canvas(self, instances: list[InstanceInfo]):
        current_names = set(self.canvas._nodes.keys())
        new_names = {inst.instance_name for inst in instances}
        if current_names == new_names:
            return
        self.canvas.load_instances(instances)
        if not self.canvas.manual_mode and self._is_canvas_tab_active():
            self.canvas.sync_wires_from_projection()

    def read_parameters(self) -> dict[tuple[str, str], str]:
        result = {}
        for row in range(self.param_table.rowCount()):
            inst = self.param_table.item(row, PCOL_INSTANCE).text()
            pname = self.param_table.item(row, PCOL_PARAM).text()
            pval = self.param_table.item(row, PCOL_VALUE).text().strip()
            result[(inst, pname)] = pval
        return result

    def clear(self):
        self._workspace = None
        self.left_tree.clear()
        self.right_tree.clear()
        self.inout_tree.clear()
        self.table.setRowCount(0)
        self.param_table.setRowCount(0)
        self.canvas.clear_all()
        self.left_selected_label.setText("Left: —")
        self.right_selected_label.setText("Right: —")
        self.rename_net_edit.clear()
        self._rename_btn.setEnabled(False)
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(False)
        self._auto_io_btn.setEnabled(False)
        self._auto_connect_btn.setEnabled(False)

    def _on_mode_toggled(self, checked: bool):
        self.canvas.manual_mode = checked
        if checked:
            self._mode_btn.setText("Mode: Manual Wiring")
            for wire in list(self.canvas._wires):
                if wire.scene():
                    self.canvas._scene.removeItem(wire)
            self.canvas._wires.clear()
        else:
            self._mode_btn.setText("Mode: Auto-Wiring")
            self.canvas.sync_wires_from_projection()

    def _on_sync_clicked(self):
        was_manual = self.canvas.manual_mode
        self.canvas.manual_mode = False
        self.canvas.sync_wires_from_projection()
        self.canvas.manual_mode = was_manual

    def _on_delete_wire_clicked(self):
        self.canvas.delete_selected_wires()

    def _on_auto_layout_clicked(self):
        if not self.canvas.manual_mode:
            self.canvas.sync_wires_from_projection()
        self.canvas.auto_layout()

    def _on_tab_changed(self, index: int):
        widget = self.tabs.widget(index)
        if self.canvas.isAncestorOf(widget) or widget is self.canvas:
            if not self.canvas.manual_mode:
                self.canvas.sync_wires_from_projection()
        if hasattr(widget, "findChild"):
            child = widget.findChild(SchematicCanvas)
            if child is self.canvas and not self.canvas.manual_mode:
                self.canvas.sync_wires_from_projection()

    def _on_canvas_connection(
        self, src_inst: str, src_port: str,
        dst_inst: str, dst_port: str, net_name: str,
    ):
        if self._connect_callback:
            return self._connect_callback(PortRef(src_inst, src_port), PortRef(dst_inst, dst_port))
        return False

    def _on_canvas_wire_removed(
        self, src_inst: str, src_port: str,
        dst_inst: str, dst_port: str, net_name: str,
    ):
        if self._disconnect_callback:
            self._disconnect_callback(PortRef(src_inst, src_port), PortRef(dst_inst, dst_port))

