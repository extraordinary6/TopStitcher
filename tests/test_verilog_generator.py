import pytest

from topstitcher.core.connection_engine import ConnectionEngine
from topstitcher.core.data_model import (
    InstanceInfo,
    ModuleInfo,
    ParamInfo,
    PortDirection,
    PortInfo,
    PortRef,
    TOP_LEVEL_INSTANCE,
)
from topstitcher.core.verilog_generator import VerilogGenerator


@pytest.fixture
def engine():
    return ConnectionEngine()


@pytest.fixture
def generator():
    return VerilogGenerator()


def ref(instance_name: str, port_name: str) -> PortRef:
    return PortRef(instance_name, port_name)


def make_adder_inst(name="u_adder"):
    mod = ModuleInfo(
        name="adder",
        ports=[
            PortInfo("a", PortDirection.INPUT, 8, "7", "0"),
            PortInfo("b", PortDirection.INPUT, 8, "7", "0"),
            PortInfo("sum", PortDirection.OUTPUT, 8, "7", "0"),
        ],
    )
    return InstanceInfo.from_module(mod, name)


def make_register_inst(name="u_reg"):
    mod = ModuleInfo(
        name="register",
        ports=[
            PortInfo("d", PortDirection.INPUT, 8, "7", "0"),
            PortInfo("q", PortDirection.OUTPUT, 8, "7", "0"),
        ],
    )
    return InstanceInfo.from_module(mod, name)


def make_design_workspace(engine: ConnectionEngine):
    workspace = engine.initialize_workspace([
        make_adder_inst("u_adder"),
        make_register_inst("u_reg"),
    ])
    engine.connect_ports(workspace, ref("u_adder", "sum"), ref("u_reg", "d"))
    engine.auto_io(workspace, ref("u_adder", "a"))
    engine.auto_io(workspace, ref("u_reg", "q"))
    return workspace


class TestWorkspaceResolve:
    def test_wire_net_generates_internal_wire(self, engine):
        workspace = make_design_workspace(engine)
        design = engine.resolve_design_from_workspace(workspace, "top")

        wire_names = {wire.net_name for wire in design.internal_wires}
        assert "sum_to_d" in wire_names

    def test_only_input_output_nets_generate_top_ports(self, engine):
        workspace = make_design_workspace(engine)
        design = engine.resolve_design_from_workspace(workspace, "top")

        top_names = {port.net_name for port in design.top_ports}
        assert "u_adder_a" in top_names
        assert "u_reg_q" in top_names
        assert "sum_to_d" not in top_names

    def test_singleton_wire_is_not_auto_promoted(self, engine):
        mod = ModuleInfo(
            name="m",
            ports=[PortInfo("din", PortDirection.INPUT, 1, "0", "0")],
        )
        workspace = engine.initialize_workspace([InstanceInfo.from_module(mod, "u_m")])
        design = engine.resolve_design_from_workspace(workspace, "top")

        assert len(design.top_ports) == 0
        assert {wire.net_name for wire in design.internal_wires} == {"u_m_din"}


class TestGeneratorOutput:
    def test_generate_from_workspace_emits_top_ports_and_wire(self, engine, generator):
        workspace = make_design_workspace(engine)

        code = generator.generate_from_workspace("top", workspace)

        assert "module top (" in code
        assert "input  [7:0] u_adder_a" in code or "input [7:0] u_adder_a" in code
        assert "output [7:0] u_reg_q" in code or "output  [7:0] u_reg_q" in code
        assert "sum_to_d;" in code
        assert ".sum(sum_to_d" in code
        assert ".d  (sum_to_d)" in code or ".d(sum_to_d)" in code

    def test_width_mismatch_uses_max_width_in_output(self, engine, generator):
        src_mod = ModuleInfo(
            name="src",
            ports=[PortInfo("data", PortDirection.OUTPUT, 32, "31", "0")],
        )
        dst_mod = ModuleInfo(
            name="dst",
            ports=[PortInfo("din", PortDirection.INPUT, 4, "3", "0")],
        )
        workspace = engine.initialize_workspace([
            InstanceInfo.from_module(src_mod, "u_src"),
            InstanceInfo.from_module(dst_mod, "u_dst"),
        ])
        engine.connect_ports(workspace, ref("u_src", "data"), ref("u_dst", "din"))

        code = generator.generate_from_workspace("top", workspace)

        assert "data_to_din;" in code

    def test_top_promoted_mixed_connection_generates_correctly(self, engine, generator):
        workspace = engine.initialize_workspace([make_adder_inst(), make_register_inst()])
        engine.auto_io(workspace, ref("u_reg", "q"))
        top_ref = PortRef(TOP_LEVEL_INSTANCE, workspace.port_to_net[ref("u_reg", "q")])
        engine.connect_ports(workspace, ref("u_adder", "sum"), top_ref)

        code = generator.generate_from_workspace("top", workspace)

        assert "output [7:0] u_reg_q" in code or "output  [7:0] u_reg_q" in code
        assert ".sum(u_reg_q" in code

    def test_parameter_block_still_generated(self, engine, generator):
        mod = ModuleInfo(
            name="fifo",
            ports=[PortInfo("clk", PortDirection.INPUT, 1, "0", "0")],
            params=[ParamInfo("DEPTH", "8")],
        )
        inst = InstanceInfo.from_module(mod, "u_fifo")
        inst.params[0].value = "32"
        workspace = engine.initialize_workspace([inst])
        engine.auto_io(workspace, ref("u_fifo", "clk"))

        code = generator.generate_from_workspace("top", workspace)

        assert "fifo #( " not in code
        assert "fifo #(\n" in code or "fifo #(\r\n" in code
        assert ".DEPTH(32)" in code
        assert ") u_fifo (" in code
