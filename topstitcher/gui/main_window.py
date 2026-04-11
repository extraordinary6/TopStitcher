"""Main window for the manual-first TopStitcher workspace."""

import logging

from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QFileDialog, QStatusBar,
    QPushButton, QVBoxLayout, QHBoxLayout, QWidget,
    QMessageBox, QLabel, QLineEdit, QGroupBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence

from topstitcher.core.rtl_parser import RtlParser
from topstitcher.core.connection_engine import ConnectionEngine
from topstitcher.core.verilog_generator import VerilogGenerator
from topstitcher.core.data_model import InstanceInfo, DesignWorkspace
from topstitcher.gui.module_tree import ModuleTreeWidget
from topstitcher.gui.connection_view import ConnectionViewWidget
from topstitcher.gui.code_preview_dialog import CodePreviewDialog

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TopStitcher - Manual-First Connection Workspace")
        self.resize(1200, 700)

        self.parser = RtlParser()
        self.engine = ConnectionEngine()
        self.generator = VerilogGenerator()

        self.workspace = DesignWorkspace()

        self._setup_menu()
        self._setup_ui()
        self._setup_statusbar()

    # ── Menu ──────────────────────────────────────────────────────

    def _setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        import_action = QAction("&Import Verilog Files...", self)
        import_action.setShortcut(QKeySequence("Ctrl+O"))
        import_action.triggered.connect(self._on_import_files)
        file_menu.addAction(import_action)

        clear_action = QAction("&Clear All", self)
        clear_action.triggered.connect(self._on_clear)
        file_menu.addAction(clear_action)

        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        gen_menu = menubar.addMenu("&Generate")
        gen_action = QAction("&Generate Top Module", self)
        gen_action.setShortcut(QKeySequence("Ctrl+G"))
        gen_action.triggered.connect(self._on_generate)
        gen_menu.addAction(gen_action)

        edit_menu = menubar.addMenu("&Edit")
        connect_action = QAction("&Connect Selected", self)
        connect_action.setShortcut(QKeySequence("Ctrl+L"))
        connect_action.triggered.connect(self._on_connect_selected)
        edit_menu.addAction(connect_action)

        rerun_action = QAction("&Auto Connect", self)
        rerun_action.setShortcut(QKeySequence("Ctrl+R"))
        rerun_action.triggered.connect(self._on_rerun_auto)
        edit_menu.addAction(rerun_action)

        edit_menu.addSeparator()

        promote_action = QAction("&Auto IO for Selected", self)
        promote_action.setShortcut(QKeySequence("Ctrl+P"))
        promote_action.triggered.connect(self._on_promote_selected)
        edit_menu.addAction(promote_action)

        demote_action = QAction("&Disconnect Selected", self)
        demote_action.setShortcut(QKeySequence("Ctrl+D"))
        demote_action.triggered.connect(self._on_demote_selected)
        edit_menu.addAction(demote_action)

        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    # ── UI Layout ─────────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Top controls row
        controls = QGroupBox("Design Settings")
        ctrl_layout = QHBoxLayout(controls)

        ctrl_layout.addWidget(QLabel("Top Module Name:"))
        self.top_name_edit = QLineEdit("top_module")
        self.top_name_edit.setMaximumWidth(200)
        ctrl_layout.addWidget(self.top_name_edit)

        main_layout.addWidget(controls)

        # Main splitter: left library/instances | right workspace editor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.module_tree = ModuleTreeWidget()
        self.module_tree.instances_changed.connect(self._on_instances_changed)
        splitter.addWidget(self.module_tree)

        self.connection_view = ConnectionViewWidget()
        self.connection_view.set_rename_callback(self._on_rename_net)
        self.connection_view.set_connect_action_callback(self._on_connect_selected)
        self.connection_view.set_disconnect_action_callback(self._on_disconnect_selected)
        self.connection_view.set_auto_io_action_callback(self._on_auto_io_selected)
        self.connection_view.set_auto_connect_action_callback(self._on_rerun_auto)
        self.connection_view.set_connect_callback(self._on_canvas_connect)
        self.connection_view.set_disconnect_callback(self._on_canvas_disconnect)
        splitter.addWidget(self.connection_view)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        main_layout.addWidget(splitter)

        # Legacy shortcut buttons; core actions live in the workspace center panel
        btn_row = QHBoxLayout()
        self.connect_btn = QPushButton("Connect Selected")
        self.connect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self._on_connect_selected)
        btn_row.addWidget(self.connect_btn)

        self.rerun_btn = QPushButton("Auto Connect")
        self.rerun_btn.setEnabled(False)
        self.rerun_btn.clicked.connect(self._on_rerun_auto)
        btn_row.addWidget(self.rerun_btn)

        self.promote_btn = QPushButton("Auto IO for Selected")
        self.promote_btn.setEnabled(False)
        self.promote_btn.clicked.connect(self._on_promote_selected)
        btn_row.addWidget(self.promote_btn)

        self.demote_btn = QPushButton("Disconnect Selected")
        self.demote_btn.setEnabled(False)
        self.demote_btn.clicked.connect(self._on_demote_selected)
        btn_row.addWidget(self.demote_btn)

        btn_row.addStretch()

        self.gen_btn = QPushButton("Generate Top Module")
        self.gen_btn.setEnabled(False)
        self.gen_btn.clicked.connect(self._on_generate)
        btn_row.addWidget(self.gen_btn)

        main_layout.addLayout(btn_row)

    def _setup_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Import Verilog files to begin.")

    # ── Helpers ────────────────────────────────────────────────────

    def _refresh_workspace_view(self, reload_canvas_instances: bool = False):
        assignments = self.engine.flatten_workspace(self.workspace)
        instances = self.module_tree.get_instances()
        self.connection_view.load_assignments(assignments, self.workspace)
        self.connection_view.load_parameters(instances)
        if reload_canvas_instances:
            self.connection_view.load_instances_to_canvas(instances)
        self._update_buttons(bool(instances))

        warnings = sum(len(net.warnings) for net in self.workspace.nets.values())
        self.status_bar.showMessage(
            f"Workspace ready: {len(instances)} instance(s), "
            f"{len(self.workspace.nets)} net(s), {warnings} warning(s)."
        )

    def _run_auto_connect(self):
        if not self.workspace.instances:
            return

        instances = self.module_tree.get_instances()
        self._apply_edited_params(instances)
        self.workspace.instances = instances
        self.engine.auto_connect_same_name_same_width(self.workspace)
        self._refresh_workspace_view()

    def _apply_edited_params(self, instances: list[InstanceInfo]):
        """Read parameter edits from the table and apply to instances."""
        if self.connection_view.param_table.rowCount() == 0:
            return
        edited = self.connection_view.read_parameters()
        for inst in instances:
            for param in inst.params:
                key = (inst.instance_name, param.name)
                if key in edited:
                    param.value = edited[key]

    def _update_buttons(self, has_data: bool):
        self.gen_btn.setEnabled(has_data)
        self.connect_btn.setEnabled(has_data)
        self.rerun_btn.setEnabled(has_data)
        self.promote_btn.setEnabled(has_data)
        self.demote_btn.setEnabled(has_data)

    def _get_selected_port_keys(self) -> set[tuple[str, str]]:
        return self.connection_view.get_selected_instance_port_keys()

    def _make_port_ref(self, instance_name: str, port_name: str):
        from topstitcher.core.data_model import PortRef
        return PortRef(instance_name, port_name)

    def _on_import_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Verilog Files", "",
            "Verilog Files (*.v *.sv);;All Files (*)"
        )
        if not paths:
            return

        self.status_bar.showMessage(f"Parsing {len(paths)} file(s)...")
        modules = self.parser.parse_files(paths)
        if not modules:
            self.status_bar.showMessage("No modules found in selected files.")
            QMessageBox.warning(
                self, "No Modules",
                "No valid Verilog modules were found in the selected files."
            )
            return

        self.workspace = DesignWorkspace()
        self.connection_view.clear()
        self.module_tree.load_modules(modules)

    def _on_instances_changed(self):
        instances = self.module_tree.get_instances()
        self._apply_edited_params(instances)
        self.workspace = self.engine.initialize_workspace(instances)
        self._refresh_workspace_view(reload_canvas_instances=True)

    def _on_rerun_auto(self):
        self._run_auto_connect()

    def _connect_pair(self, left_ref, right_ref) -> None:
        try:
            self.engine.connect_ports(self.workspace, left_ref, right_ref)
            return
        except ValueError:
            self.engine.connect_ports(self.workspace, right_ref, left_ref)

    def _on_connect_selected(self):
        pair = self.connection_view.get_selected_connect_pair()
        if not pair:
            QMessageBox.information(
                self, "Need Left And Right",
                "Select one endpoint on the left and one endpoint on the right."
            )
            return

        try:
            self._connect_pair(pair[0], pair[1])
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Connection", str(exc))
            return

        self._refresh_workspace_view()
        self.status_bar.showMessage("Connected selected ports.")

    def _on_auto_io_selected(self):
        ref = self.connection_view.get_selected_auto_io_ref()
        if not ref or ref.instance_name == "__top__":
            QMessageBox.information(
                self, "No Selection",
                "Select one instance port for Auto IO."
            )
            return

        self.engine.auto_io(self.workspace, ref)
        self._refresh_workspace_view()
        self.status_bar.showMessage("Auto IO applied to selected port.")

    def _on_promote_selected(self):
        self._on_auto_io_selected()

    def _on_disconnect_selected(self):
        pair = self.connection_view.get_selected_disconnect_pair()
        if not pair:
            QMessageBox.information(
                self, "Need Left And Right",
                "Select one endpoint on the left and one endpoint on the right."
            )
            return

        self.engine.disconnect_ports(self.workspace, pair[0], pair[1])
        self._refresh_workspace_view()
        self.status_bar.showMessage("Disconnected selected endpoints.")

    def _on_demote_selected(self):
        self._on_disconnect_selected()

    def _on_rename_net(self, port_ref, new_name: str):
        self.engine.rename_net(self.workspace, port_ref, new_name)
        self._refresh_workspace_view()
        self.status_bar.showMessage(f"Renamed net to {new_name}.")

    def _on_generate(self):
        instances = self.module_tree.get_instances()
        if not instances:
            QMessageBox.warning(self, "No Instances", "Add instances first.")
            return

        self._apply_edited_params(instances)
        self.workspace.instances = instances

        module_name = self.top_name_edit.text().strip() or "top_module"
        code = self.generator.generate_from_workspace(module_name, self.workspace)
        dialog = CodePreviewDialog(code, self)
        dialog.exec()

    def _on_canvas_connect(self, left_ref, right_ref):
        try:
            self._connect_pair(left_ref, right_ref)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Connection", str(exc))
            self._refresh_workspace_view()
            return False
        self._refresh_workspace_view()
        return True

    def _on_canvas_disconnect(self, left_ref, right_ref):
        self.engine.disconnect_ports(self.workspace, left_ref, right_ref)
        self._refresh_workspace_view()

    def _on_clear(self):
        self.module_tree.clear()
        self.connection_view.clear()
        self.workspace = DesignWorkspace()
        self._update_buttons(False)
        self.status_bar.showMessage("Cleared. Import Verilog files to begin.")

    def _on_about(self):
        QMessageBox.about(
            self, "About TopStitcher",
            "TopStitcher\n\n"
            "Manual-first Verilog top module workspace.\n\n"
            "Features:\n"
            "- Explicit Connect / Disconnect\n"
            "- Auto IO promotion by net type\n"
            "- Explicit Auto Connect\n"
            "- Three-column workspace editor\n"
            "- Schematic canvas and parameter editing"
        )
