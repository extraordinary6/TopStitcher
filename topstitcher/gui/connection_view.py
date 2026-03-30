"""Interactive connection table + parameter editor + schematic canvas (V5)."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QPushButton,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from topstitcher.core.data_model import (
    PortAssignment, PortDirection, InstanceInfo,
)
from topstitcher.core.connection_engine import (
    S_GLOBAL, S_PROMOTED, S_SUGGESTED, S_WIDTH_MISMATCH,
    S_MULTI_DRIVER, S_UNDRIVEN, S_CONFLICT,
)
from topstitcher.gui.schematic_canvas import SchematicCanvas

# Port table column indices
COL_INSTANCE = 0
COL_PORT = 1
COL_DIR = 2
COL_WIDTH = 3
COL_NET = 4
COL_STATUS = 5

# Param table column indices
PCOL_INSTANCE = 0
PCOL_PARAM = 1
PCOL_VALUE = 2

_DIR_COLORS = {
    PortDirection.INPUT: QColor(34, 139, 34),
    PortDirection.OUTPUT: QColor(210, 105, 30),
    PortDirection.INOUT: QColor(30, 90, 210),
}

_STATUS_STYLES: dict[str, tuple[QColor, QColor]] = {
    S_GLOBAL:         (QColor(220, 240, 255), QColor(0, 100, 200)),
    S_PROMOTED:       (QColor(255, 235, 205), QColor(200, 100, 0)),
    S_SUGGESTED:      (QColor(220, 255, 220), QColor(0, 130, 0)),
    S_WIDTH_MISMATCH: (QColor(255, 255, 200), QColor(180, 140, 0)),
    S_MULTI_DRIVER:   (QColor(255, 210, 210), QColor(200, 0, 0)),
    S_UNDRIVEN:       (QColor(255, 230, 210), QColor(200, 80, 0)),
    S_CONFLICT:       (QColor(255, 200, 200), QColor(180, 0, 0)),
}


def _status_style(status: str) -> tuple[QColor | None, QColor | None]:
    priority = [S_MULTI_DRIVER, S_CONFLICT, S_UNDRIVEN, S_WIDTH_MISMATCH,
                S_PROMOTED, S_GLOBAL, S_SUGGESTED]
    for tag in priority:
        if tag in status:
            return _STATUS_STYLES[tag]
    return None, None


class ConnectionViewWidget(QWidget):
    """Tabbed workspace: Netlist Table | Schematic Canvas | Instance Parameters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: Netlist Table (port connections)
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
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSortingEnabled(True)
        self.tabs.addTab(self.table, "Netlist Table")

        # Tab 2: Schematic Canvas (wrapped in a widget with toolbar)
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar for canvas
        toolbar = QHBoxLayout()

        self._mode_btn = QPushButton("Mode: Auto-Wiring")
        self._mode_btn.setCheckable(True)
        self._mode_btn.setToolTip(
            "Auto: wires sync from the Netlist Table automatically.\n"
            "Manual: draw and delete wires by hand (updates the table)."
        )
        self._mode_btn.toggled.connect(self._on_mode_toggled)
        toolbar.addWidget(self._mode_btn)

        self._sync_btn = QPushButton("Sync from Table")
        self._sync_btn.setToolTip("Re-draw wires from the current Netlist Table data.")
        self._sync_btn.clicked.connect(self._on_sync_clicked)
        toolbar.addWidget(self._sync_btn)

        self._del_wire_btn = QPushButton("Delete Selected Wire")
        self._del_wire_btn.setToolTip("Delete the selected wire(s). Shortcut: Delete key.")
        self._del_wire_btn.clicked.connect(self._on_delete_wire_clicked)
        toolbar.addWidget(self._del_wire_btn)

        toolbar.addStretch()
        canvas_layout.addLayout(toolbar)

        self.canvas = SchematicCanvas(table_widget=self.table)
        self.canvas.set_connection_callback(self._on_canvas_connection)
        self.canvas.set_removal_callback(self._on_canvas_wire_removed)
        canvas_layout.addWidget(self.canvas)

        self.tabs.addTab(canvas_container, "Schematic Canvas")

        # Tab 3: Instance Parameters
        self.param_table = QTableWidget()
        self.param_table.setColumnCount(3)
        self.param_table.setHorizontalHeaderLabels([
            "Instance Name", "Parameter", "Value",
        ])
        pheader = self.param_table.horizontalHeader()
        pheader.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.param_table.setSortingEnabled(True)
        self.tabs.addTab(self.param_table, "Instance Parameters")

        # Sync canvas when switching to schematic tab
        self.tabs.currentChanged.connect(self._on_tab_changed)

    # ── Mode toggle ───────────────────────────────────────

    def _on_mode_toggled(self, checked: bool):
        self.canvas.manual_mode = checked
        if checked:
            self._mode_btn.setText("Mode: Manual Wiring")
            # Clear auto-synced wires so user starts fresh
            for w in list(self.canvas._wires):
                if w.scene():
                    self.canvas._scene.removeItem(w)
            self.canvas._wires.clear()
        else:
            self._mode_btn.setText("Mode: Auto-Wiring")
            self.canvas.sync_wires_from_table()

    def _on_sync_clicked(self):
        """Force re-sync wires from table regardless of mode."""
        was_manual = self.canvas.manual_mode
        self.canvas.manual_mode = False
        self.canvas.sync_wires_from_table()
        self.canvas.manual_mode = was_manual

    def _on_delete_wire_clicked(self):
        self.canvas.delete_selected_wires()

    # ── Tab change sync ───────────────────────────────────

    def _on_tab_changed(self, index: int):
        widget = self.tabs.widget(index)
        # The canvas is inside a container widget
        if self.canvas.isAncestorOf(widget) or widget is self.canvas:
            if not self.canvas.manual_mode:
                self.canvas.sync_wires_from_table()
        # Also check if the container has our canvas
        if hasattr(widget, 'findChild'):
            from topstitcher.gui.schematic_canvas import SchematicCanvas as SC
            child = widget.findChild(SC)
            if child is self.canvas and not self.canvas.manual_mode:
                self.canvas.sync_wires_from_table()

    # ── Canvas callbacks ──────────────────────────────────

    def _on_canvas_connection(
        self, src_inst: str, src_port: str,
        dst_inst: str, dst_port: str, net_name: str,
    ):
        """Called when user draws a wire on the canvas. Update the table."""
        self._set_net_in_table(src_inst, src_port, net_name)
        self._set_net_in_table(dst_inst, dst_port, net_name)

    def _on_canvas_wire_removed(
        self, src_inst: str, src_port: str,
        dst_inst: str, dst_port: str, net_name: str,
    ):
        """Called when user deletes a wire on the canvas. Clear net in the table."""
        # Build the list of all (inst, port) that share this net
        ports_on_net = []
        for row in range(self.table.rowCount()):
            inst_item = self.table.item(row, COL_INSTANCE)
            net_item = self.table.item(row, COL_NET)
            if inst_item and net_item and net_item.text().strip() == net_name:
                port_item = self.table.item(row, COL_PORT)
                ports_on_net.append((inst_item.text(), port_item.text(), row))

        # The deleted wire connects src and dst. Check if this net still
        # has other wires keeping it alive in the canvas.
        remaining_wires_on_net = [
            w for w in self.canvas._wires if w.net_name == net_name
        ]

        if not remaining_wires_on_net:
            # No more wires for this net: reset all ports on this net
            # to their own unique name (effectively disconnecting them)
            for inst, port, row in ports_on_net:
                self.table.item(row, COL_NET).setText(f"{inst}_{port}")
        else:
            # Only reset the two specific ports from the deleted wire
            # if they have no other wire on this net
            for inst, port in [(src_inst, src_port), (dst_inst, dst_port)]:
                still_wired = any(
                    (w.source.instance_name == inst and w.source.port_name == port)
                    or (w.target and w.target.instance_name == inst
                        and w.target.port_name == port)
                    for w in remaining_wires_on_net
                )
                if not still_wired:
                    self._set_net_in_table(inst, port, f"{inst}_{port}")

    def _set_net_in_table(self, instance_name: str, port_name: str, net_name: str):
        for row in range(self.table.rowCount()):
            inst_item = self.table.item(row, COL_INSTANCE)
            port_item = self.table.item(row, COL_PORT)
            if (inst_item and port_item
                    and inst_item.text() == instance_name
                    and port_item.text() == port_name):
                self.table.item(row, COL_NET).setText(net_name)
                return

    # ── Table population ──────────────────────────────────

    def load_assignments(self, assignments: list[PortAssignment]):
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
            if bg:
                net_item.setBackground(bg)
            self.table.setItem(row, COL_NET, net_item)

            status_item = QTableWidgetItem(a.status)
            status_item.setFlags(
                status_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            if bg:
                status_item.setBackground(bg)
            if fg:
                status_item.setForeground(fg)
            self.table.setItem(row, COL_STATUS, status_item)

        self.table.setSortingEnabled(True)

        # Auto-sync canvas if visible and in auto mode
        if not self.canvas.manual_mode:
            self.canvas.sync_wires_from_table()

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
        self.canvas.load_instances(instances)

    # ── Read back ─────────────────────────────────────────

    def read_assignments(self) -> list[PortAssignment]:
        assignments = []
        for row in range(self.table.rowCount()):
            inst = self.table.item(row, COL_INSTANCE).text()
            port = self.table.item(row, COL_PORT).text()
            dir_str = self.table.item(row, COL_DIR).text()
            width_str = self.table.item(row, COL_WIDTH).text()
            net = self.table.item(row, COL_NET).text().strip()

            direction = PortDirection(dir_str)
            width = int(width_str) if width_str != "param" else -1

            if width > 1:
                msb = str(width - 1)
                lsb = "0"
            elif width == -1:
                msb = "?"
                lsb = "0"
            else:
                msb = "0"
                lsb = "0"

            assignments.append(PortAssignment(
                instance_name=inst,
                module_name="",
                port_name=port,
                direction=direction,
                width=width,
                msb_expr=msb,
                lsb_expr=lsb,
                assigned_net=net,
            ))
        return assignments

    def read_parameters(self) -> dict[tuple[str, str], str]:
        result = {}
        for row in range(self.param_table.rowCount()):
            inst = self.param_table.item(row, PCOL_INSTANCE).text()
            pname = self.param_table.item(row, PCOL_PARAM).text()
            pval = self.param_table.item(row, PCOL_VALUE).text().strip()
            result[(inst, pname)] = pval
        return result

    def clear(self):
        self.table.setRowCount(0)
        self.param_table.setRowCount(0)
        self.canvas.clear_all()
