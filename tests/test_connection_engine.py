import pytest

from topstitcher.core.connection_engine import (
    ConnectionEngine,
    S_MULTI_DRIVER,
    S_UNDRIVEN,
    S_WIDTH_MISMATCH,
)
from topstitcher.core.data_model import (
    InstanceInfo,
    ModuleInfo,
    NetType,
    PortDirection,
    PortInfo,
    PortRef,
    TOP_LEVEL_INSTANCE,
)


@pytest.fixture
def engine():
    return ConnectionEngine()


def make_adder_inst(name="u_adder"):
    mod = ModuleInfo(
        name="adder",
        ports=[
            PortInfo("clk", PortDirection.INPUT, 1, "0", "0"),
            PortInfo("a", PortDirection.INPUT, 8, "7", "0"),
            PortInfo("b", PortDirection.INPUT, 8, "7", "0"),
            PortInfo("sum", PortDirection.OUTPUT, 8, "7", "0"),
        ],
    )
    return InstanceInfo.from_module(mod, name)


def make_register_inst(name="u_register"):
    mod = ModuleInfo(
        name="register",
        ports=[
            PortInfo("clk", PortDirection.INPUT, 1, "0", "0"),
            PortInfo("d", PortDirection.INPUT, 8, "7", "0"),
            PortInfo("q", PortDirection.OUTPUT, 8, "7", "0"),
        ],
    )
    return InstanceInfo.from_module(mod, name)


def ref(instance_name: str, port_name: str) -> PortRef:
    return PortRef(instance_name, port_name)


class TestInitializeWorkspace:
    def test_import_starts_with_singleton_wire_nets(self, engine):
        instances = [make_adder_inst(), make_register_inst()]
        workspace = engine.initialize_workspace(instances)

        assert len(workspace.nets) == 7
        assert len(workspace.port_to_net) == 7
        for net in workspace.nets.values():
            assert net.net_type == NetType.WIRE
            assert len(net.connected_ports) == 1

    def test_import_has_no_auto_connect_and_no_top_ports(self, engine):
        instances = [make_adder_inst(), make_register_inst()]
        workspace = engine.initialize_workspace(instances)
        design = engine.resolve_design_from_workspace(workspace, "top")

        assert len(design.top_ports) == 0
        assert len(design.internal_wires) == 7


class TestConnect:
    def test_connect_valid_output_to_input(self, engine):
        workspace = engine.initialize_workspace([make_adder_inst(), make_register_inst()])

        net = engine.connect_ports(
            workspace,
            ref("u_adder", "sum"),
            ref("u_register", "d"),
        )

        assert net.net_name == "sum_to_d"
        assert set(net.connected_ports) == {ref("u_adder", "sum"), ref("u_register", "d")}
        assert net.net_type == NetType.WIRE

    def test_connect_rejects_invalid_direction(self, engine):
        workspace = engine.initialize_workspace([make_adder_inst(), make_register_inst()])

        with pytest.raises(ValueError):
            engine.connect_ports(
                workspace,
                ref("u_adder", "a"),
                ref("u_register", "d"),
            )

    def test_connect_width_mismatch_allowed_and_warned(self, engine):
        src_mod = ModuleInfo(
            name="src",
            ports=[PortInfo("data", PortDirection.OUTPUT, 32, "31", "0")],
        )
        dst_mod = ModuleInfo(
            name="dst",
            ports=[PortInfo("data_in", PortDirection.INPUT, 4, "3", "0")],
        )
        workspace = engine.initialize_workspace([
            InstanceInfo.from_module(src_mod, "u_src"),
            InstanceInfo.from_module(dst_mod, "u_dst"),
        ])

        net = engine.connect_ports(
            workspace,
            ref("u_src", "data"),
            ref("u_dst", "data_in"),
        )

        assert net.width == 32
        assert S_WIDTH_MISMATCH in net.warnings


class TestDisconnect:
    def test_disconnect_two_port_net_splits_into_two_singletons(self, engine):
        workspace = engine.initialize_workspace([make_adder_inst(), make_register_inst()])
        engine.connect_ports(workspace, ref("u_adder", "sum"), ref("u_register", "d"))

        engine.disconnect_ports(workspace, ref("u_adder", "sum"), ref("u_register", "d"))

        sum_net = workspace.nets[workspace.port_to_net[ref("u_adder", "sum")]]
        d_net = workspace.nets[workspace.port_to_net[ref("u_register", "d")]]
        assert sum_net.net_name == "u_adder_sum"
        assert d_net.net_name == "u_register_d"
        assert len(sum_net.connected_ports) == 1
        assert len(d_net.connected_ports) == 1

    def test_disconnect_only_detaches_selected_receiver(self, engine):
        fanout_mod = ModuleInfo(
            name="fanout",
            ports=[PortInfo("out", PortDirection.OUTPUT, 8, "7", "0")],
        )
        sink_mod = ModuleInfo(
            name="sink",
            ports=[PortInfo("din", PortDirection.INPUT, 8, "7", "0")],
        )
        workspace = engine.initialize_workspace([
            InstanceInfo.from_module(fanout_mod, "u_src"),
            InstanceInfo.from_module(sink_mod, "u_a"),
            InstanceInfo.from_module(sink_mod, "u_b"),
        ])
        engine.connect_ports(workspace, ref("u_src", "out"), ref("u_a", "din"))
        engine.connect_ports(workspace, ref("u_src", "out"), ref("u_b", "din"))

        engine.disconnect_ports(workspace, ref("u_src", "out"), ref("u_b", "din"))

        shared_net = workspace.nets[workspace.port_to_net[ref("u_src", "out")]]
        detached_net = workspace.nets[workspace.port_to_net[ref("u_b", "din")]]
        assert set(shared_net.connected_ports) == {ref("u_src", "out"), ref("u_a", "din")}
        assert detached_net.net_name == "u_b_din"


class TestAutoIo:
    def test_auto_io_changes_input_net_type(self, engine):
        workspace = engine.initialize_workspace([make_adder_inst()])
        net = engine.auto_io(workspace, ref("u_adder", "a"))
        assert net.net_type == NetType.INPUT

    def test_auto_io_changes_output_net_type(self, engine):
        workspace = engine.initialize_workspace([make_adder_inst()])
        net = engine.auto_io(workspace, ref("u_adder", "sum"))
        assert net.net_type == NetType.OUTPUT


class TestAutoConnect:
    def test_auto_connect_only_same_name_same_width(self, engine):
        tx_mod = ModuleInfo(
            name="tx",
            ports=[
                PortInfo("data", PortDirection.OUTPUT, 8, "7", "0"),
                PortInfo("other", PortDirection.OUTPUT, 8, "7", "0"),
            ],
        )
        rx_mod = ModuleInfo(
            name="rx",
            ports=[
                PortInfo("data", PortDirection.INPUT, 8, "7", "0"),
                PortInfo("din", PortDirection.INPUT, 8, "7", "0"),
            ],
        )
        workspace = engine.initialize_workspace([
            InstanceInfo.from_module(tx_mod, "u_tx"),
            InstanceInfo.from_module(rx_mod, "u_rx"),
        ])

        engine.auto_connect_same_name_same_width(workspace)

        shared_net = workspace.nets[workspace.port_to_net[ref("u_tx", "data")]]
        other_net = workspace.nets[workspace.port_to_net[ref("u_tx", "other")]]
        assert set(shared_net.connected_ports) == {ref("u_tx", "data"), ref("u_rx", "data")}
        assert other_net.net_name == "u_tx_other"

    def test_auto_connect_parameterized_requires_exact_expr_match(self, engine):
        src_mod = ModuleInfo(
            name="src",
            ports=[PortInfo("data", PortDirection.OUTPUT, -1, "WIDTH-1", "0")],
        )
        dst_mod = ModuleInfo(
            name="dst",
            ports=[PortInfo("data", PortDirection.INPUT, -1, "DEPTH-1", "0")],
        )
        workspace = engine.initialize_workspace([
            InstanceInfo.from_module(src_mod, "u_src"),
            InstanceInfo.from_module(dst_mod, "u_dst"),
        ])

        engine.auto_connect_same_name_same_width(workspace)

        src_net = workspace.nets[workspace.port_to_net[ref("u_src", "data")]]
        dst_net = workspace.nets[workspace.port_to_net[ref("u_dst", "data")]]
        assert src_net.net_name == "u_src_data"
        assert dst_net.net_name == "u_dst_data"

    def test_inout_does_not_participate_in_auto_connect(self, engine):
        io_mod = ModuleInfo(
            name="io_mod",
            ports=[PortInfo("pad", PortDirection.INOUT, 1, "0", "0")],
        )
        workspace = engine.initialize_workspace([
            InstanceInfo.from_module(io_mod, "u_a"),
            InstanceInfo.from_module(io_mod, "u_b"),
        ])

        engine.auto_connect_same_name_same_width(workspace)

        assert workspace.nets[workspace.port_to_net[ref("u_a", "pad")]].net_name == "u_a_pad"
        assert workspace.nets[workspace.port_to_net[ref("u_b", "pad")]].net_name == "u_b_pad"


class TestTopPseudoEndpoints:
    def test_top_input_can_connect_to_instance_input(self, engine):
        workspace = engine.initialize_workspace([make_adder_inst()])
        engine.auto_io(workspace, ref("u_adder", "a"))

        top_ref = PortRef(TOP_LEVEL_INSTANCE, workspace.port_to_net[ref("u_adder", "a")])
        net = engine.connect_ports(workspace, top_ref, ref("u_adder", "clk"))

        assert net.net_type == NetType.INPUT
        assert ref("u_adder", "clk") in net.connected_ports

    def test_top_input_can_connect_to_multiple_instance_inputs(self, engine):
        workspace = engine.initialize_workspace([make_adder_inst(), make_register_inst()])
        engine.auto_io(workspace, ref("u_adder", "clk"))

        top_ref = PortRef(TOP_LEVEL_INSTANCE, workspace.port_to_net[ref("u_adder", "clk")])
        engine.connect_ports(workspace, top_ref, ref("u_register", "clk"))

        net = workspace.nets[workspace.port_to_net[ref("u_register", "clk")]]
        assert net.net_type == NetType.INPUT
        assert ref("u_adder", "clk") in net.connected_ports
        assert ref("u_register", "clk") in net.connected_ports

        workspace = engine.initialize_workspace([make_adder_inst(), make_register_inst()])
        engine.auto_io(workspace, ref("u_register", "q"))
        top_ref = PortRef(TOP_LEVEL_INSTANCE, workspace.port_to_net[ref("u_register", "q")])

        net = engine.connect_ports(workspace, ref("u_adder", "sum"), top_ref)

        assert net.net_type == NetType.OUTPUT
        assert ref("u_adder", "sum") in net.connected_ports

    def test_rename_net_changes_workspace_name(self, engine):
        workspace = engine.initialize_workspace([make_adder_inst(), make_register_inst()])
        engine.connect_ports(workspace, ref("u_adder", "sum"), ref("u_register", "d"))
        engine.rename_net(workspace, ref("u_adder", "sum"), "result_bus")

        net = workspace.nets[workspace.port_to_net[ref("u_adder", "sum")]]
        assert net.net_name == "result_bus"


class TestDiagnostics:
    def test_multi_driver_warning(self, engine):
        src_mod = ModuleInfo(
            name="src",
            ports=[PortInfo("out", PortDirection.OUTPUT, 8, "7", "0")],
        )
        workspace = engine.initialize_workspace([
            InstanceInfo.from_module(src_mod, "u_a"),
            InstanceInfo.from_module(src_mod, "u_b"),
        ])
        assignments = engine.flatten_workspace(workspace)
        assignments[0].assigned_net = "shared"
        assignments[1].assigned_net = "shared"

        merged = engine.workspace_from_assignments(workspace.instances, assignments)
        net = next(iter(merged.nets.values()))
        assert S_MULTI_DRIVER in net.warnings

    def test_undriven_warning(self, engine):
        sink_mod = ModuleInfo(
            name="sink",
            ports=[PortInfo("din", PortDirection.INPUT, 8, "7", "0")],
        )
        workspace = engine.initialize_workspace([
            InstanceInfo.from_module(sink_mod, "u_a"),
            InstanceInfo.from_module(sink_mod, "u_b"),
        ])
        assignments = engine.flatten_workspace(workspace)
        assignments[0].assigned_net = "shared"
        assignments[1].assigned_net = "shared"

        merged = engine.workspace_from_assignments(workspace.instances, assignments)
        net = next(iter(merged.nets.values()))
        assert S_UNDRIVEN in net.warnings
