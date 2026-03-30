"""Interactive connection table + parameter editor (V4: status from engine)."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
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

# Status → (background color, foreground color)
_STATUS_STYLES: dict[str, tuple[QColor, QColor]] = {
    S_GLOBAL:         (QColor(220, 240, 255), QColor(0, 100, 200)),     # light blue
    S_PROMOTED:       (QColor(255, 235, 205), QColor(200, 100, 0)),     # light orange
    S_SUGGESTED:      (QColor(220, 255, 220), QColor(0, 130, 0)),       # light green
    S_WIDTH_MISMATCH: (QColor(255, 255, 200), QColor(180, 140, 0)),     # light yellow
    S_MULTI_DRIVER:   (QColor(255, 210, 210), QColor(200, 0, 0)),       # light red
    S_UNDRIVEN:       (QColor(255, 230, 210), QColor(200, 80, 0)),      # light amber
    S_CONFLICT:       (QColor(255, 200, 200), QColor(180, 0, 0)),       # red
}


def _status_style(status: str) -> tuple[QColor | None, QColor | None]:
    """Pick the highest-priority style from a possibly comma-separated status."""
    priority = [S_MULTI_DRIVER, S_CONFLICT, S_UNDRIVEN, S_WIDTH_MISMATCH,
                S_PROMOTED, S_GLOBAL, S_SUGGESTED]
    for tag in priority:
        if tag in status:
            return _STATUS_STYLES[tag]
    return None, None


class ConnectionViewWidget(QWidget):
    """Tabbed view: Port Connections (editable) + Instance Parameters (editable)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: Port Connections
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
        self.tabs.addTab(self.table, "Port Connections")

        # Tab 2: Instance Parameters
        self.param_table = QTableWidget()
        self.param_table.setColumnCount(3)
        self.param_table.setHorizontalHeaderLabels([
            "Instance Name", "Parameter", "Value",
        ])
        pheader = self.param_table.horizontalHeader()
        pheader.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.param_table.setSortingEnabled(True)
        self.tabs.addTab(self.param_table, "Instance Parameters")

    def load_assignments(self, assignments: list[PortAssignment]):
        """Populate port connection table. Status comes from PortAssignment.status."""
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(assignments))

        for row, a in enumerate(assignments):
            bg, fg = _status_style(a.status)

            # Instance Name (read-only)
            inst_item = QTableWidgetItem(a.instance_name)
            inst_item.setFlags(inst_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if bg:
                inst_item.setBackground(bg)
            self.table.setItem(row, COL_INSTANCE, inst_item)

            # Port Name (read-only)
            port_item = QTableWidgetItem(a.port_name)
            port_item.setFlags(port_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if bg:
                port_item.setBackground(bg)
            self.table.setItem(row, COL_PORT, port_item)

            # Direction (read-only, colored)
            dir_item = QTableWidgetItem(a.direction.value)
            dir_item.setFlags(dir_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            color = _DIR_COLORS.get(a.direction)
            if color:
                dir_item.setForeground(color)
            if bg:
                dir_item.setBackground(bg)
            self.table.setItem(row, COL_DIR, dir_item)

            # Width (read-only)
            width_str = str(a.width) if a.width > 0 else "param"
            width_item = QTableWidgetItem(width_str)
            width_item.setFlags(width_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if bg:
                width_item.setBackground(bg)
            self.table.setItem(row, COL_WIDTH, width_item)

            # Assigned Net (EDITABLE)
            net_item = QTableWidgetItem(a.assigned_net)
            if bg:
                net_item.setBackground(bg)
            self.table.setItem(row, COL_NET, net_item)

            # Status (read-only)
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

    def load_parameters(self, instances: list[InstanceInfo]):
        """Populate parameter table from instance list."""
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

    def read_assignments(self) -> list[PortAssignment]:
        """Read current port table state back into PortAssignment list."""
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
        """Read edited parameter values: {(instance_name, param_name): value}."""
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
