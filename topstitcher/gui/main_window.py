"""Main window for TopStitcher V2."""

import logging

from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QFileDialog, QStatusBar,
    QPushButton, QVBoxLayout, QHBoxLayout, QWidget,
    QMessageBox, QLabel, QLineEdit, QGroupBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence

from topstitcher.core.rtl_parser import RtlParser
from topstitcher.core.connection_engine import ConnectionEngine, DEFAULT_GLOBAL_SIGNALS
from topstitcher.core.verilog_generator import VerilogGenerator
from topstitcher.core.data_model import PortAssignment, InstanceInfo
from topstitcher.gui.module_tree import ModuleTreeWidget
from topstitcher.gui.connection_view import ConnectionViewWidget
from topstitcher.gui.code_preview_dialog import CodePreviewDialog

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TopStitcher V2 - Verilog Top Module Generator")
        self.resize(1200, 700)

        self.parser = RtlParser()
        self.engine = ConnectionEngine()
        self.generator = VerilogGenerator()

        self._promoted_ports: set[tuple[str, str]] = set()

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
        rerun_action = QAction("&Re-run Auto-Connect", self)
        rerun_action.setShortcut(QKeySequence("Ctrl+R"))
        rerun_action.triggered.connect(self._on_rerun_auto)
        edit_menu.addAction(rerun_action)

        edit_menu.addSeparator()

        promote_action = QAction("&Promote Selected to Top", self)
        promote_action.setShortcut(QKeySequence("Ctrl+P"))
        promote_action.triggered.connect(self._on_promote_selected)
        edit_menu.addAction(promote_action)

        demote_action = QAction("&Demote Selected from Top", self)
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

        ctrl_layout.addWidget(QLabel("Global Signals (comma-separated):"))
        self.global_signals_edit = QLineEdit(", ".join(DEFAULT_GLOBAL_SIGNALS))
        ctrl_layout.addWidget(self.global_signals_edit)

        main_layout.addWidget(controls)

        # Main splitter: left (module library + instances) | right (connection table)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.module_tree = ModuleTreeWidget()
        self.module_tree.instances_changed.connect(self._on_instances_changed)
        splitter.addWidget(self.module_tree)

        self.connection_view = ConnectionViewWidget()
        splitter.addWidget(self.connection_view)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        main_layout.addWidget(splitter)

        # Bottom buttons
        btn_row = QHBoxLayout()
        self.rerun_btn = QPushButton("Re-run Auto-Connect")
        self.rerun_btn.setEnabled(False)
        self.rerun_btn.clicked.connect(self._on_rerun_auto)
        btn_row.addWidget(self.rerun_btn)

        self.promote_btn = QPushButton("Promote Selected to Top")
        self.promote_btn.setEnabled(False)
        self.promote_btn.clicked.connect(self._on_promote_selected)
        btn_row.addWidget(self.promote_btn)

        self.demote_btn = QPushButton("Demote Selected")
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

    def _get_global_signals(self) -> list[str]:
        text = self.global_signals_edit.text().strip()
        if not text:
            return []
        return [s.strip() for s in text.split(",") if s.strip()]

    def _run_auto_connect(self):
        instances = self.module_tree.get_instances()
        if not instances:
            return

        # Preserve any user-edited parameter values before reloading
        self._apply_edited_params(instances)

        global_sigs = self._get_global_signals()
        assignments = self.engine.build_assignments(
            instances, global_sigs, self._promoted_ports,
        )
        self.connection_view.load_assignments(
            assignments,
            promoted_ports=self._promoted_ports,
            global_signals=global_sigs,
        )
        self.connection_view.load_parameters(instances)
        self._update_buttons(True)
        n_params = sum(len(i.params) for i in instances)
        n_promoted = len(self._promoted_ports)
        self.status_bar.showMessage(
            f"Auto-connected {len(instances)} instance(s), "
            f"{len(assignments)} port(s), {n_params} parameter(s), "
            f"{n_promoted} promoted."
        )

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
        self.rerun_btn.setEnabled(has_data)
        self.promote_btn.setEnabled(has_data)
        self.demote_btn.setEnabled(has_data)

    def _get_selected_port_keys(self) -> set[tuple[str, str]]:
        """Get (instance_name, port_name) for selected rows in port table."""
        table = self.connection_view.table
        selected_rows = set(idx.row() for idx in table.selectedIndexes())
        keys = set()
        for row in selected_rows:
            inst = table.item(row, 0).text()
            port = table.item(row, 1).text()
            keys.add((inst, port))
        return keys

    # ── Event Handlers ────────────────────────────────────────────

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

        self._promoted_ports.clear()
        self.module_tree.load_modules(modules)
        # instances_changed signal triggers _on_instances_changed → _run_auto_connect

    def _on_instances_changed(self):
        self._run_auto_connect()

    def _on_rerun_auto(self):
        self._run_auto_connect()

    def _on_promote_selected(self):
        """Mark selected table rows as promoted-to-top and re-run auto-connect."""
        keys = self._get_selected_port_keys()
        if not keys:
            QMessageBox.information(
                self, "No Selection",
                "Select one or more rows in the connection table first."
            )
            return

        self._promoted_ports.update(keys)
        self._run_auto_connect()
        self.status_bar.showMessage(
            f"Promoted {len(keys)} port(s) to top-level. "
            f"Total promoted: {len(self._promoted_ports)}."
        )

    def _on_demote_selected(self):
        """Remove selected table rows from the promoted set and re-run."""
        keys = self._get_selected_port_keys()
        if not keys:
            QMessageBox.information(
                self, "No Selection",
                "Select one or more rows in the connection table first."
            )
            return

        removed = keys & self._promoted_ports
        if not removed:
            QMessageBox.information(
                self, "Nothing to Demote",
                "The selected port(s) are not currently promoted."
            )
            return

        self._promoted_ports -= removed
        self._run_auto_connect()
        self.status_bar.showMessage(
            f"Demoted {len(removed)} port(s). "
            f"Remaining promoted: {len(self._promoted_ports)}."
        )

    def _on_generate(self):
        instances = self.module_tree.get_instances()
        if not instances:
            QMessageBox.warning(self, "No Instances", "Add instances first.")
            return

        # Apply edited parameter values from the parameter table
        self._apply_edited_params(instances)

        # Read final state from the interactive port table
        assignments = self.connection_view.read_assignments()
        inst_map = {i.instance_name: i.module_name for i in instances}
        for a in assignments:
            if not a.module_name:
                a.module_name = inst_map.get(a.instance_name, "")
            for inst in instances:
                if inst.instance_name == a.instance_name:
                    for p in inst.ports:
                        if p.name == a.port_name:
                            a.msb_expr = p.msb_expr
                            a.lsb_expr = p.lsb_expr
                            a.width = p.width
                            break
                    break

        module_name = self.top_name_edit.text().strip() or "top_module"
        global_sigs = self._get_global_signals()

        code = self.generator.generate_from_table(
            module_name, instances, assignments,
            global_sigs, self._promoted_ports,
        )
        dialog = CodePreviewDialog(code, self)
        dialog.exec()

    def _on_clear(self):
        self.module_tree.clear()
        self.connection_view.clear()
        self._promoted_ports.clear()
        self._update_buttons(False)
        self.status_bar.showMessage("Cleared. Import Verilog files to begin.")

    def _on_about(self):
        QMessageBox.about(
            self, "About TopStitcher",
            "TopStitcher V2\n\n"
            "Automatic Verilog top-level module generator\n"
            "with manual override support.\n\n"
            "Features:\n"
            "- Global signal promotion\n"
            "- Multiple instantiation\n"
            "- Interactive connection table\n"
            "- Top module customization\n"
            "- Parameter editing"
        )
