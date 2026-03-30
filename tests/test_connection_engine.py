"""Tests for connection engine V2."""

import pytest

from topstitcher.core.data_model import (
    PortInfo, PortDirection, ModuleInfo, InstanceInfo,
    ConnectionType, PortAssignment,
)
from topstitcher.core.connection_engine import ConnectionEngine


@pytest.fixture
def engine():
    return ConnectionEngine()


def make_adder_inst(name="u_adder"):
    mod = ModuleInfo(
        name="adder",
        ports=[
            PortInfo("clk", PortDirection.INPUT, 1, "0", "0"),
            PortInfo("rst_n", PortDirection.INPUT, 1, "0", "0"),
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
            PortInfo("rst_n", PortDirection.INPUT, 1, "0", "0"),
            PortInfo("d", PortDirection.INPUT, 8, "7", "0"),
            PortInfo("q", PortDirection.OUTPUT, 8, "7", "0"),
        ],
    )
    return InstanceInfo.from_module(mod, name)


class TestGlobalSignals:
    """Issue 1: Global signals must be promoted to top-level ports."""

    def test_clk_rst_promoted_with_global(self, engine):
        instances = [make_adder_inst(), make_register_inst()]
        assignments = engine.build_assignments(
            instances, global_signals=["clk", "rst_n"]
        )
        # clk/rst_n should all be assigned the same net name (global)
        clk_nets = {a.assigned_net for a in assignments if a.port_name == "clk"}
        assert clk_nets == {"clk"}
        rst_nets = {a.assigned_net for a in assignments if a.port_name == "rst_n"}
        assert rst_nets == {"rst_n"}

    def test_global_becomes_top_port(self, engine):
        instances = [make_adder_inst(), make_register_inst()]
        assignments = engine.build_assignments(
            instances, global_signals=["clk", "rst_n"]
        )
        design = engine.resolve_design(
            "top", instances, assignments,
            global_signals=["clk", "rst_n"],
        )
        top_names = {p.net_name for p in design.top_ports}
        assert "clk" in top_names
        assert "rst_n" in top_names
        # clk should NOT be an internal wire
        wire_names = {w.net_name for w in design.internal_wires}
        assert "clk" not in wire_names

    def test_without_global_clk_is_internal(self, engine):
        """Without global signals, clk becomes an internal wire (Rule A)."""
        instances = [make_adder_inst(), make_register_inst()]
        assignments = engine.build_assignments(instances, global_signals=[])
        design = engine.resolve_design("top", instances, assignments)
        wire_names = {w.net_name for w in design.internal_wires}
        assert "clk" in wire_names


class TestMultipleInstantiation:
    """Issue 2: Same module instantiated multiple times."""

    def test_two_adder_instances(self, engine):
        inst0 = make_adder_inst("u_adder_0")
        inst1 = make_adder_inst("u_adder_1")
        assignments = engine.build_assignments(
            [inst0, inst1], global_signals=["clk", "rst_n"]
        )
        # 'a' has same name and width on both → Rule A → shared internal wire
        a_assignments = [a for a in assignments if a.port_name == "a"]
        assert len(a_assignments) == 2
        nets = {a.assigned_net for a in a_assignments}
        assert nets == {"a"}  # Rule A ties them together
        # User can manually override in the table if needed

    def test_two_instances_ports_not_confused(self, engine):
        inst0 = make_adder_inst("u_adder_0")
        inst1 = make_adder_inst("u_adder_1")
        assignments = engine.build_assignments(
            [inst0, inst1], global_signals=["clk", "rst_n"]
        )
        # 'a' appears in both → Rule A would fire (same width),
        # but each should be unique since same module instantiated twice
        # Actually with global_signals off for 'a', Rule A connects them.
        # Let's check: with no global on 'a', and same width → Rule A
        a_nets = {a.assigned_net for a in assignments if a.port_name == "a"}
        # 'a' has same width across both instances → Rule A → internal wire "a"
        assert a_nets == {"a"}


class TestRuleAB:
    """Standard Rule A/B behavior with global signals."""

    def test_unique_ports_become_top(self, engine):
        instances = [make_adder_inst(), make_register_inst()]
        assignments = engine.build_assignments(
            instances, global_signals=["clk", "rst_n"]
        )
        design = engine.resolve_design(
            "top", instances, assignments,
            global_signals=["clk", "rst_n"],
        )
        top_names = {p.net_name for p in design.top_ports}
        assert "a" in top_names
        assert "b" in top_names
        assert "sum" in top_names
        assert "d" in top_names
        assert "q" in top_names

    def test_top_port_directions(self, engine):
        instances = [make_adder_inst(), make_register_inst()]
        assignments = engine.build_assignments(
            instances, global_signals=["clk", "rst_n"]
        )
        design = engine.resolve_design(
            "top", instances, assignments,
            global_signals=["clk", "rst_n"],
        )
        port_map = {p.net_name: p for p in design.top_ports}
        assert port_map["a"].direction == PortDirection.INPUT
        assert port_map["sum"].direction == PortDirection.OUTPUT
        assert port_map["q"].direction == PortDirection.OUTPUT


class TestPromotion:
    """Issue 3: Force promotion of specific ports to top-level."""

    def test_promoted_port_becomes_top(self, engine):
        instances = [make_adder_inst(), make_register_inst()]
        # Promote sum from adder → should be top port, not internal wire
        promoted = {("u_adder", "sum")}
        assignments = engine.build_assignments(
            instances, global_signals=["clk", "rst_n"],
            promoted_ports=promoted,
        )
        design = engine.resolve_design(
            "top", instances, assignments,
            global_signals=["clk", "rst_n"],
            promoted_ports=promoted,
        )
        top_names = {p.net_name for p in design.top_ports}
        assert "sum" in top_names


class TestWidthMismatch:
    def test_width_mismatch_goes_to_rule_b(self, engine):
        mod1 = ModuleInfo(
            name="mod1",
            ports=[PortInfo("data", PortDirection.INPUT, 8, "7", "0")],
        )
        mod2 = ModuleInfo(
            name="mod2",
            ports=[PortInfo("data", PortDirection.OUTPUT, 16, "15", "0")],
        )
        inst1 = InstanceInfo.from_module(mod1, "u_mod1")
        inst2 = InstanceInfo.from_module(mod2, "u_mod2")
        assignments = engine.build_assignments([inst1, inst2])
        design = engine.resolve_design("top", [inst1, inst2], assignments)
        assert len(design.internal_wires) == 0
        assert len(design.top_ports) == 2


class TestParameterizedWidth:
    def test_parameterized_not_auto_connected(self, engine):
        mod1 = ModuleInfo(
            name="mod1",
            ports=[PortInfo("data", PortDirection.INPUT, -1, "WIDTH-1", "0")],
        )
        mod2 = ModuleInfo(
            name="mod2",
            ports=[PortInfo("data", PortDirection.OUTPUT, -1, "WIDTH-1", "0")],
        )
        inst1 = InstanceInfo.from_module(mod1, "u_mod1")
        inst2 = InstanceInfo.from_module(mod2, "u_mod2")
        assignments = engine.build_assignments([inst1, inst2])
        design = engine.resolve_design("top", [inst1, inst2], assignments)
        assert len(design.internal_wires) == 0
        assert len(design.top_ports) == 2


class TestNameDedup:
    def test_dedup_on_width_mismatch(self, engine):
        mod1 = ModuleInfo(
            name="mod1",
            ports=[PortInfo("data", PortDirection.INPUT, 8, "7", "0")],
        )
        mod2 = ModuleInfo(
            name="mod2",
            ports=[PortInfo("data", PortDirection.OUTPUT, 16, "15", "0")],
        )
        inst1 = InstanceInfo.from_module(mod1, "u_mod1")
        inst2 = InstanceInfo.from_module(mod2, "u_mod2")
        assignments = engine.build_assignments([inst1, inst2])
        port_names = {p.net_name for p in engine.resolve_design(
            "top", [inst1, inst2], assignments
        ).top_ports}
        assert "u_mod1_data" in port_names
        assert "u_mod2_data" in port_names


class TestCustomTopModuleName:
    """Issue 3: Top module name customization."""

    def test_custom_name(self, engine):
        instances = [make_adder_inst()]
        assignments = engine.build_assignments(instances)
        design = engine.resolve_design("my_chip_top", instances, assignments)
        assert design.module_name == "my_chip_top"
