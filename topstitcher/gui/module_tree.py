"""Left panel: Module Library tree + Active Instances list with Add/Remove."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QListWidget, QListWidgetItem, QPushButton,
    QHBoxLayout, QInputDialog, QMessageBox,
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import pyqtSignal

from topstitcher.core.data_model import ModuleInfo, InstanceInfo, PortDirection

_DIR_COLORS = {
    PortDirection.INPUT: QColor(34, 139, 34),
    PortDirection.OUTPUT: QColor(210, 105, 30),
    PortDirection.INOUT: QColor(30, 90, 210),
}


class ModuleTreeWidget(QWidget):
    """Left panel containing Module Library tree and Active Instances list."""

    instances_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._modules: list[ModuleInfo] = []
        self._instances: list[InstanceInfo] = []
        self._instance_counter: dict[str, int] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Module Library section
        layout.addWidget(QLabel("Module Library"))
        self.module_tree = QTreeWidget()
        self.module_tree.setHeaderLabels(["Name", "Direction", "Width"])
        self.module_tree.setColumnCount(3)
        header = self.module_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.module_tree)

        # Add Instance button
        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add Instance")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._on_add_instance)
        btn_row.addWidget(self.add_btn)

        self.remove_btn = QPushButton("Remove Instance")
        self.remove_btn.setEnabled(False)
        self.remove_btn.clicked.connect(self._on_remove_instance)
        btn_row.addWidget(self.remove_btn)
        layout.addLayout(btn_row)

        # Active Instances list
        layout.addWidget(QLabel("Active Instances"))
        self.instance_list = QListWidget()
        self.instance_list.currentRowChanged.connect(
            lambda: self.remove_btn.setEnabled(
                self.instance_list.currentRow() >= 0
            )
        )
        layout.addWidget(self.instance_list)

    def load_modules(self, modules: list[ModuleInfo]):
        self._modules = modules
        self.module_tree.clear()
        for mod in modules:
            mod_item = QTreeWidgetItem([mod.name, "", ""])
            self.module_tree.addTopLevelItem(mod_item)
            # Show parameters
            if mod.params:
                params_item = QTreeWidgetItem(["Parameters", "", ""])
                params_item.setForeground(0, QColor(128, 128, 128))
                mod_item.addChild(params_item)
                for param in mod.params:
                    p_item = QTreeWidgetItem([
                        param.name, "parameter", param.value
                    ])
                    p_item.setForeground(0, QColor(128, 0, 128))
                    p_item.setForeground(1, QColor(128, 128, 128))
                    p_item.setForeground(2, QColor(128, 0, 128))
                    params_item.addChild(p_item)
                params_item.setExpanded(True)
            # Show ports
            for port in mod.ports:
                width_str = str(port.width) if port.width > 0 else "param"
                port_item = QTreeWidgetItem([
                    port.name, port.direction.value, width_str
                ])
                color = _DIR_COLORS.get(port.direction)
                if color:
                    for col in range(3):
                        port_item.setForeground(col, color)
                mod_item.addChild(port_item)
            mod_item.setExpanded(True)
        self.add_btn.setEnabled(len(modules) > 0)

        # Auto-add one instance per module on first import
        self._instances.clear()
        self._instance_counter.clear()
        self.instance_list.clear()
        for mod in modules:
            self._add_instance_for(mod)
        self.instances_changed.emit()

    def _on_add_instance(self):
        if not self._modules:
            return
        selected = self.module_tree.currentItem()
        # Find which module is selected (top-level item)
        if selected is None:
            QMessageBox.information(
                self, "Select Module",
                "Select a module in the library tree first."
            )
            return
        # Walk up to top-level
        while selected.parent():
            selected = selected.parent()
        mod_name = selected.text(0)
        mod = next((m for m in self._modules if m.name == mod_name), None)
        if not mod:
            return

        inst_name = self._next_instance_name(mod.name)
        name, ok = QInputDialog.getText(
            self, "Instance Name",
            f"Instance name for module '{mod.name}':",
            text=inst_name,
        )
        if ok and name.strip():
            name = name.strip()
            # Check uniqueness
            existing = {i.instance_name for i in self._instances}
            if name in existing:
                QMessageBox.warning(
                    self, "Duplicate",
                    f"Instance name '{name}' already exists."
                )
                return
            inst = InstanceInfo.from_module(mod, name)
            self._instances.append(inst)
            self.instance_list.addItem(f"{name} ({mod.name})")
            self.instances_changed.emit()

    def _on_remove_instance(self):
        row = self.instance_list.currentRow()
        if row < 0:
            return
        self._instances.pop(row)
        self.instance_list.takeItem(row)
        self.instances_changed.emit()

    def _add_instance_for(self, mod: ModuleInfo):
        name = self._next_instance_name(mod.name)
        inst = InstanceInfo.from_module(mod, name)
        self._instances.append(inst)
        self.instance_list.addItem(f"{name} ({mod.name})")

    def _next_instance_name(self, mod_name: str) -> str:
        count = self._instance_counter.get(mod_name, 0)
        self._instance_counter[mod_name] = count + 1
        if count == 0:
            return f"u_{mod_name}"
        return f"u_{mod_name}_{count}"

    def get_instances(self) -> list[InstanceInfo]:
        return list(self._instances)

    def get_modules(self) -> list[ModuleInfo]:
        return list(self._modules)

    def clear(self):
        self._modules.clear()
        self._instances.clear()
        self._instance_counter.clear()
        self.module_tree.clear()
        self.instance_list.clear()
        self.add_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
