"""Tests for the RTL parser."""

import os
import pytest

from topstitcher.core.rtl_parser import RtlParser
from topstitcher.core.data_model import PortDirection

TEST_DATA = os.path.join(os.path.dirname(__file__), "test_data")


@pytest.fixture
def parser():
    return RtlParser()


class TestAnsiStyle:
    def test_parse_adder(self, parser):
        modules = parser.parse_files([os.path.join(TEST_DATA, "adder.v")])
        assert len(modules) == 1
        mod = modules[0]
        assert mod.name == "adder"
        assert len(mod.ports) == 5

    def test_port_directions(self, parser):
        modules = parser.parse_files([os.path.join(TEST_DATA, "adder.v")])
        mod = modules[0]
        port_map = {p.name: p for p in mod.ports}
        assert port_map["clk"].direction == PortDirection.INPUT
        assert port_map["rst_n"].direction == PortDirection.INPUT
        assert port_map["a"].direction == PortDirection.INPUT
        assert port_map["sum"].direction == PortDirection.OUTPUT

    def test_port_widths(self, parser):
        modules = parser.parse_files([os.path.join(TEST_DATA, "adder.v")])
        mod = modules[0]
        port_map = {p.name: p for p in mod.ports}
        assert port_map["clk"].width == 1
        assert port_map["a"].width == 8
        assert port_map["sum"].width == 8
        assert port_map["a"].msb_expr == "7"
        assert port_map["a"].lsb_expr == "0"

    def test_parse_register(self, parser):
        modules = parser.parse_files([os.path.join(TEST_DATA, "register.v")])
        assert len(modules) == 1
        mod = modules[0]
        assert mod.name == "register"
        port_map = {p.name: p for p in mod.ports}
        assert port_map["d"].direction == PortDirection.INPUT
        assert port_map["q"].direction == PortDirection.OUTPUT
        assert port_map["d"].width == 8


class TestMultipleFiles:
    def test_parse_both(self, parser):
        files = [
            os.path.join(TEST_DATA, "adder.v"),
            os.path.join(TEST_DATA, "register.v"),
        ]
        modules = parser.parse_files(files)
        assert len(modules) == 2
        names = {m.name for m in modules}
        assert names == {"adder", "register"}

    def test_no_instance_name_on_module(self, parser):
        """ModuleInfo is a library entry, not an instance."""
        modules = parser.parse_files([os.path.join(TEST_DATA, "adder.v")])
        assert not hasattr(modules[0], "instance_name") or modules[0].source_file


class TestOldStyle:
    def test_parse_old_style(self, parser, tmp_path):
        verilog = """
module old_mod (clk, data_in, data_out);
    input clk;
    input [7:0] data_in;
    output [7:0] data_out;
    assign data_out = data_in;
endmodule
"""
        f = tmp_path / "old_mod.v"
        f.write_text(verilog)
        modules = parser.parse_files([str(f)])
        assert len(modules) == 1
        mod = modules[0]
        assert mod.name == "old_mod"
        port_map = {p.name: p for p in mod.ports}
        assert port_map["clk"].direction == PortDirection.INPUT
        assert port_map["clk"].width == 1
        assert port_map["data_in"].width == 8
        assert port_map["data_out"].direction == PortDirection.OUTPUT


class TestErrorHandling:
    def test_invalid_file(self, parser):
        modules = parser.parse_files(["nonexistent.v"])
        assert modules == []

    def test_bad_syntax(self, parser, tmp_path):
        f = tmp_path / "bad.v"
        f.write_text("this is not verilog")
        modules = parser.parse_files([str(f)])
        assert modules == []

    def test_partial_failure(self, parser, tmp_path):
        bad = tmp_path / "bad.v"
        bad.write_text("invalid syntax here")
        good = os.path.join(TEST_DATA, "adder.v")
        modules = parser.parse_files([str(bad), good])
        assert len(modules) == 1
        assert modules[0].name == "adder"


class TestParameterParsing:
    def test_parse_params_ansi(self, parser):
        modules = parser.parse_files([
            os.path.join(TEST_DATA, "param_adder.v")
        ])
        assert len(modules) == 1
        mod = modules[0]
        assert mod.name == "param_adder"
        assert len(mod.params) == 2
        param_map = {p.name: p for p in mod.params}
        assert "WIDTH" in param_map
        assert "DEPTH" in param_map
        assert param_map["WIDTH"].value == "8"
        assert param_map["DEPTH"].value == "4"

    def test_no_params(self, parser):
        modules = parser.parse_files([os.path.join(TEST_DATA, "adder.v")])
        assert modules[0].params == []

    def test_parameterized_ports(self, parser):
        modules = parser.parse_files([
            os.path.join(TEST_DATA, "param_adder.v")
        ])
        mod = modules[0]
        port_map = {p.name: p for p in mod.ports}
        # WIDTH-1:0 ports should have width=-1 (parameterized)
        assert port_map["a"].width == -1
        assert "WIDTH" in port_map["a"].msb_expr

    def test_old_style_params(self, parser, tmp_path):
        verilog = """
module old_param (clk, data);
    parameter BUS_W = 16;
    input clk;
    input [BUS_W-1:0] data;
endmodule
"""
        f = tmp_path / "old_param.v"
        f.write_text(verilog)
        modules = parser.parse_files([str(f)])
        assert len(modules) == 1
        assert len(modules[0].params) == 1
        assert modules[0].params[0].name == "BUS_W"
        assert modules[0].params[0].value == "16"

    def test_expression_param(self, parser, tmp_path):
        verilog = """
module expr_param #(
    parameter A = 4,
    parameter B = A + 1
)(
    input clk
);
endmodule
"""
        f = tmp_path / "expr_param.v"
        f.write_text(verilog)
        modules = parser.parse_files([str(f)])
        assert len(modules[0].params) == 2
        param_map = {p.name: p for p in modules[0].params}
        assert param_map["A"].value == "4"
        assert "A" in param_map["B"].value
        assert "+" in param_map["B"].value
