import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from topstitcher.core.connection_engine import ConnectionEngine
from topstitcher.core.data_model import InstanceInfo, ModuleInfo, PortDirection, PortInfo, PortRef
from topstitcher.gui.connection_view import ConnectionViewWidget


@pytest.fixture(scope="session")
def app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_connection_view_workspace_smoke(app):
    adder_mod = ModuleInfo(
        name="adder",
        ports=[
            PortInfo("a", PortDirection.INPUT, 8, "7", "0"),
            PortInfo("sum", PortDirection.OUTPUT, 8, "7", "0"),
        ],
    )
    reg_mod = ModuleInfo(
        name="register",
        ports=[
            PortInfo("d", PortDirection.INPUT, 8, "7", "0"),
            PortInfo("q", PortDirection.OUTPUT, 8, "7", "0"),
        ],
    )
    engine = ConnectionEngine()
    workspace = engine.initialize_workspace([
        InstanceInfo.from_module(adder_mod, "u_adder"),
        InstanceInfo.from_module(reg_mod, "u_reg"),
    ])
    engine.connect_ports(workspace, PortRef("u_adder", "sum"), PortRef("u_reg", "d"))
    engine.auto_io(workspace, PortRef("u_adder", "a"))

    view = ConnectionViewWidget()
    try:
        view.load_assignments(engine.flatten_workspace(workspace), workspace)
        view.load_parameters(workspace.instances)
        view.load_instances_to_canvas(workspace.instances)

        assert view.tabs.count() >= 4
        assert view.left_tree.topLevelItemCount() >= 1
        assert view.right_tree.topLevelItemCount() >= 1
        assert view.table.rowCount() == 4
        assert len(view.canvas._nodes) == 2
        assert len(view.canvas._connection_projection) == 4
    finally:
        view.close()
        view.deleteLater()
        app.processEvents()
