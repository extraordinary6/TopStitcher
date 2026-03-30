"""Tests for connection engine V4 (direction-aware, width tolerance, suggestions, diagnostics)."""

import pytest

from topstitcher.core.data_model import (
    PortInfo, PortDirection, ModuleInfo, InstanceInfo,
    ConnectionType, PortAssignment,
)
from topstitcher.core.connection_engine import (
    ConnectionEngine, S_GLOBAL, S_PROMOTED, S_SUGGESTED,
    S_WIDTH_MISMATCH, S_MULTI_DRIVER, S_UNDRIVEN, S_CONFLICT,
)


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


# ── Global Signals ─────────────────────────────────────

class TestGlobalSignals:
    def test_clk_rst_promoted_with_global(self, engine):
        instances = [make_adder_inst(), make_register_inst()]
        assignments = engine.build_assignments(
            instances, global_signals=["clk", "rst_n"]
        )
        clk_nets = {a.assigned_net for a in assignments if a.port_name == "clk"}
        assert clk_nets == {"clk"}
        for a in assignments:
            if a.port_name == "clk":
                assert S_GLOBAL in a.status

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
        wire_names = {w.net_name for w in design.internal_wires}
        assert "clk" not in wire_names

    def test_without_global_clk_is_internal(self, engine):
        instances = [make_adder_inst(), make_register_inst()]
        assignments = engine.build_assignments(instances, global_signals=[])
        design = engine.resolve_design("top", instances, assignments)
        wire_names = {w.net_name for w in design.internal_wires}
        assert "clk" in wire_names


# ── Multiple Instantiation ────────────────────────────

class TestMultipleInstantiation:
    def test_two_adder_instances_rule_a(self, engine):
        inst0 = make_adder_inst("u_adder_0")
        inst1 = make_adder_inst("u_adder_1")
        assignments = engine.build_assignments(
            [inst0, inst1], global_signals=["clk", "rst_n"]
        )
        a_assignments = [a for a in assignments if a.port_name == "a"]
        assert len(a_assignments) == 2
        nets = {a.assigned_net for a in a_assignments}
        assert nets == {"a"}  # all inputs, same width → Rule A


# ── Direction-Aware Rule A ─────────────────────────────

class TestDirectionAware:
    def test_all_inputs_same_name_rule_a(self, engine):
        """All inputs with same name → valid Rule A (shared net from top)."""
        instances = [make_adder_inst(), make_register_inst()]
        assignments = engine.build_assignments(instances, global_signals=[])
        clk_nets = {a.assigned_net for a in assignments if a.port_name == "clk"}
        assert clk_nets == {"clk"}  # Rule A: all inputs, same width

    def test_mixed_direction_rule_a(self, engine):
        """One output + one input same name same width → valid Rule A."""
        mod1 = ModuleInfo(name="tx", ports=[
            PortInfo("data", PortDirection.OUTPUT, 8, "7", "0"),
        ])
        mod2 = ModuleInfo(name="rx", ports=[
            PortInfo("data", PortDirection.INPUT, 8, "7", "0"),
        ])
        inst1 = InstanceInfo.from_module(mod1, "u_tx")
        inst2 = InstanceInfo.from_module(mod2, "u_rx")
        assignments = engine.build_assignments([inst1, inst2])
        data_nets = {a.assigned_net for a in assignments if a.port_name == "data"}
        assert data_nets == {"data"}

    def test_all_outputs_conflict(self, engine):
        """Two outputs with same name → Conflict, NOT auto-connected."""
        mod1 = ModuleInfo(name="gen1", ports=[
            PortInfo("data", PortDirection.OUTPUT, 8, "7", "0"),
        ])
        mod2 = ModuleInfo(name="gen2", ports=[
            PortInfo("data", PortDirection.OUTPUT, 8, "7", "0"),
        ])
        inst1 = InstanceInfo.from_module(mod1, "u_gen1")
        inst2 = InstanceInfo.from_module(mod2, "u_gen2")
        assignments = engine.build_assignments([inst1, inst2])
        data_assignments = [a for a in assignments if a.port_name == "data"]
        # Should NOT be tied together
        nets = {a.assigned_net for a in data_assignments}
        assert len(nets) == 2
        # Should have Conflict status
        for a in data_assignments:
            assert S_CONFLICT in a.status


# ── Width Mismatch Tolerance ──────────────────────────

class TestWidthMismatch:
    def test_width_mismatch_still_connects(self, engine):
        """Different widths but direction OK → connect with warning."""
        mod1 = ModuleInfo(name="src", ports=[
            PortInfo("data", PortDirection.OUTPUT, 32, "31", "0"),
        ])
        mod2 = ModuleInfo(name="dst", ports=[
            PortInfo("data", PortDirection.INPUT, 4, "3", "0"),
        ])
        inst1 = InstanceInfo.from_module(mod1, "u_src")
        inst2 = InstanceInfo.from_module(mod2, "u_dst")
        assignments = engine.build_assignments([inst1, inst2])
        data_nets = {a.assigned_net for a in assignments if a.port_name == "data"}
        # Should be connected (same net name)
        assert len(data_nets) == 1
        for a in assignments:
            if a.port_name == "data":
                assert S_WIDTH_MISMATCH in a.status

    def test_width_mismatch_uses_max_width(self, engine):
        """Wire declaration should use the larger width."""
        mod1 = ModuleInfo(name="src", ports=[
            PortInfo("data", PortDirection.OUTPUT, 32, "31", "0"),
        ])
        mod2 = ModuleInfo(name="dst", ports=[
            PortInfo("data", PortDirection.INPUT, 4, "3", "0"),
        ])
        inst1 = InstanceInfo.from_module(mod1, "u_src")
        inst2 = InstanceInfo.from_module(mod2, "u_dst")
        assignments = engine.build_assignments([inst1, inst2])
        design = engine.resolve_design("top", [inst1, inst2], assignments)
        wire = next(w for w in design.internal_wires if w.net_name == "data")
        assert wire.width == 32

    def test_all_outputs_width_mismatch_no_connect(self, engine):
        """All outputs, different widths → Conflict, separate top ports."""
        mod1 = ModuleInfo(name="gen1", ports=[
            PortInfo("data", PortDirection.OUTPUT, 8, "7", "0"),
        ])
        mod2 = ModuleInfo(name="gen2", ports=[
            PortInfo("data", PortDirection.OUTPUT, 16, "15", "0"),
        ])
        inst1 = InstanceInfo.from_module(mod1, "u_gen1")
        inst2 = InstanceInfo.from_module(mod2, "u_gen2")
        assignments = engine.build_assignments([inst1, inst2])
        data_nets = {a.assigned_net for a in assignments if a.port_name == "data"}
        assert len(data_nets) == 2  # Not connected


# ── Suggested Connections ─────────────────────────────

class TestSuggested:
    def test_output_to_input_suggestion(self, engine):
        """One output + one input of same width, different names → Suggested."""
        mod1 = ModuleInfo(name="adder", ports=[
            PortInfo("sum", PortDirection.OUTPUT, 8, "7", "0"),
        ])
        mod2 = ModuleInfo(name="register", ports=[
            PortInfo("d", PortDirection.INPUT, 8, "7", "0"),
        ])
        inst1 = InstanceInfo.from_module(mod1, "u_adder")
        inst2 = InstanceInfo.from_module(mod2, "u_register")
        assignments = engine.build_assignments([inst1, inst2])
        sum_a = next(a for a in assignments if a.port_name == "sum")
        d_a = next(a for a in assignments if a.port_name == "d")
        # Should be suggested to connect
        assert S_SUGGESTED in sum_a.status
        assert S_SUGGESTED in d_a.status
        assert sum_a.assigned_net == d_a.assigned_net

    def test_no_suggestion_when_ambiguous(self, engine):
        """Multiple input candidates → no suggestion."""
        mod1 = ModuleInfo(name="src", ports=[
            PortInfo("out", PortDirection.OUTPUT, 8, "7", "0"),
        ])
        mod2 = ModuleInfo(name="dst1", ports=[
            PortInfo("in_a", PortDirection.INPUT, 8, "7", "0"),
        ])
        mod3 = ModuleInfo(name="dst2", ports=[
            PortInfo("in_b", PortDirection.INPUT, 8, "7", "0"),
        ])
        inst1 = InstanceInfo.from_module(mod1, "u_src")
        inst2 = InstanceInfo.from_module(mod2, "u_dst1")
        inst3 = InstanceInfo.from_module(mod3, "u_dst2")
        assignments = engine.build_assignments([inst1, inst2, inst3])
        out_a = next(a for a in assignments if a.port_name == "out")
        # Ambiguous: two possible inputs → no suggestion
        assert S_SUGGESTED not in out_a.status

    def test_suggestion_not_applied_to_rule_a_ports(self, engine):
        """Ports already connected via Rule A should not get suggested."""
        instances = [make_adder_inst(), make_register_inst()]
        assignments = engine.build_assignments(instances, global_signals=["clk", "rst_n"])
        # sum(output,8) and d(input,8) are the only unmatched output/input pair
        sum_a = next(a for a in assignments if a.port_name == "sum")
        d_a = next(a for a in assignments if a.port_name == "d")
        # They should be suggested
        assert S_SUGGESTED in sum_a.status
        assert S_SUGGESTED in d_a.status
        assert sum_a.assigned_net == d_a.assigned_net


# ── Diagnostics ────────────────────────────────────────

class TestDiagnostics:
    def test_multi_driver_detected(self, engine):
        """Two outputs manually tied to same net → Multi-Driver warning."""
        mod1 = ModuleInfo(name="gen1", ports=[
            PortInfo("out", PortDirection.OUTPUT, 8, "7", "0"),
        ])
        mod2 = ModuleInfo(name="gen2", ports=[
            PortInfo("out", PortDirection.OUTPUT, 8, "7", "0"),
        ])
        inst1 = InstanceInfo.from_module(mod1, "u_gen1")
        inst2 = InstanceInfo.from_module(mod2, "u_gen2")
        # Build default assignments (Conflict → separate nets)
        assignments = engine.build_assignments([inst1, inst2])
        # Simulate user manually tying them together
        for a in assignments:
            a.assigned_net = "shared_out"
            a.status = ""
        engine._run_diagnostics(assignments)
        for a in assignments:
            assert S_MULTI_DRIVER in a.status

    def test_undriven_detected(self, engine):
        """Multiple inputs on same net with no output → Undriven warning."""
        assignments = [
            PortAssignment("u_a", "mod_a", "clk", PortDirection.INPUT,
                           1, "0", "0", "my_clk"),
            PortAssignment("u_b", "mod_b", "clk", PortDirection.INPUT,
                           1, "0", "0", "my_clk"),
        ]
        engine._run_diagnostics(assignments)
        for a in assignments:
            assert S_UNDRIVEN in a.status

    def test_global_not_undriven(self, engine):
        """Global signals should not be flagged as undriven."""
        instances = [make_adder_inst(), make_register_inst()]
        assignments = engine.build_assignments(
            instances, global_signals=["clk", "rst_n"]
        )
        clk_assignments = [a for a in assignments if a.port_name == "clk"]
        for a in clk_assignments:
            assert S_UNDRIVEN not in a.status

    def test_driven_net_no_warning(self, engine):
        """One output + inputs on same net → no warnings."""
        mod1 = ModuleInfo(name="src", ports=[
            PortInfo("data", PortDirection.OUTPUT, 8, "7", "0"),
        ])
        mod2 = ModuleInfo(name="dst", ports=[
            PortInfo("data", PortDirection.INPUT, 8, "7", "0"),
        ])
        inst1 = InstanceInfo.from_module(mod1, "u_src")
        inst2 = InstanceInfo.from_module(mod2, "u_dst")
        assignments = engine.build_assignments([inst1, inst2])
        for a in assignments:
            if a.port_name == "data":
                assert S_MULTI_DRIVER not in a.status
                assert S_UNDRIVEN not in a.status


# ── Existing tests (updated) ──────────────────────────

class TestRuleAB:
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
        assert "clk" in top_names
        assert "rst_n" in top_names

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
        assert port_map["clk"].direction == PortDirection.INPUT


class TestPromotion:
    def test_promoted_port_becomes_top(self, engine):
        instances = [make_adder_inst(), make_register_inst()]
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
        sum_a = next(a for a in assignments
                     if a.instance_name == "u_adder" and a.port_name == "sum")
        assert S_PROMOTED in sum_a.status


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


class TestCustomTopModuleName:
    def test_custom_name(self, engine):
        instances = [make_adder_inst()]
        assignments = engine.build_assignments(instances)
        design = engine.resolve_design("my_chip_top", instances, assignments)
        assert design.module_name == "my_chip_top"
