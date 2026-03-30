"""RTL parser using PyVerilog."""

import logging
from pathlib import Path

from pyverilog.vparser.parser import VerilogParser
from pyverilog.vparser.ast import (
    Source, ModuleDef, Portlist, Port, Ioport,
    Input, Output, Inout, Width, IntConst, Decl,
    Parameter, Rvalue, Plus, Minus, Times, Divide, Mod,
    Power, Sll, Srl, Sla, Sra, And, Or, Xor, Xnor,
    Land, Lor, Ulnot, Unot, Uminus, Uplus,
    GreaterThan, GreaterEq, LessThan, LessEq,
    Eq, NotEq, Eql, NotEql, Cond,
    SystemCall, Identifier, StringConst, FloatConst, Concat,
    Repeat, Partselect, Pointer,
)

from topstitcher.core.data_model import PortInfo, PortDirection, ParamInfo, ModuleInfo

logger = logging.getLogger(__name__)

_DIR_MAP = {
    Input: PortDirection.INPUT,
    Output: PortDirection.OUTPUT,
    Inout: PortDirection.INOUT,
}

# Binary operator AST class → symbol
_BINOP_MAP = {
    Plus: "+", Minus: "-", Times: "*", Divide: "/", Mod: "%",
    Power: "**", Sll: "<<", Srl: ">>", Sla: "<<<", Sra: ">>>",
    And: "&", Or: "|", Xor: "^", Xnor: "~^",
    Land: "&&", Lor: "||",
    GreaterThan: ">", GreaterEq: ">=", LessThan: "<", LessEq: "<=",
    Eq: "==", NotEq: "!=", Eql: "===", NotEql: "!==",
}

# Unary operator AST class → symbol
_UNOP_MAP = {
    Ulnot: "!", Unot: "~", Uminus: "-", Uplus: "+",
}


class RtlParser:
    """Parses Verilog files and extracts module definitions (library entries)."""

    def parse_files(self, file_paths: list[str]) -> list[ModuleInfo]:
        modules = []
        for path in file_paths:
            try:
                result = self._parse_single_file(path)
                if result:
                    modules.extend(result)
            except Exception as e:
                logger.error(f"Failed to parse {path}: {e}")
        return modules

    def _parse_single_file(self, file_path: str) -> list[ModuleInfo]:
        text = Path(file_path).read_text(encoding="utf-8")
        parser = VerilogParser()
        ast = parser.parse(text, debug=0)

        modules = []
        source = list(ast.children())[0]  # Description
        for node in source.children():
            if isinstance(node, ModuleDef):
                mod = self._parse_module(node, file_path)
                if mod:
                    modules.append(mod)
        return modules

    def _parse_module(self, moddef: ModuleDef, file_path: str) -> ModuleInfo:
        # Parse parameters
        params = self._parse_params(moddef)

        # Parse ports
        portlist = moddef.portlist
        port_nodes = list(portlist.children()) if portlist else []

        if not port_nodes:
            return ModuleInfo(name=moddef.name, ports=[], params=params,
                              source_file=file_path)

        if port_nodes and isinstance(port_nodes[0], Ioport):
            ports = self._parse_ansi_ports(port_nodes)
        elif port_nodes and isinstance(port_nodes[0], Port):
            ports = self._parse_old_style_ports(port_nodes, moddef)
        else:
            ports = []

        return ModuleInfo(name=moddef.name, ports=ports, params=params,
                          source_file=file_path)

    def _parse_params(self, moddef: ModuleDef) -> list[ParamInfo]:
        """Extract parameter declarations from module's paramlist and body."""
        params = []
        seen = set()

        # From paramlist (ANSI-style #(...) parameters)
        if moddef.paramlist:
            for decl in moddef.paramlist.children():
                if isinstance(decl, Decl):
                    for child in decl.children():
                        if isinstance(child, Parameter) and child.name not in seen:
                            value_str = self._rvalue_to_str(child.value)
                            params.append(ParamInfo(child.name, value_str))
                            seen.add(child.name)

        # From module body (old-style parameter declarations)
        items = moddef.items if moddef.items else []
        for item in items:
            if isinstance(item, Decl):
                for child in item.children():
                    if isinstance(child, Parameter) and child.name not in seen:
                        value_str = self._rvalue_to_str(child.value)
                        params.append(ParamInfo(child.name, value_str))
                        seen.add(child.name)

        return params

    def _rvalue_to_str(self, node) -> str:
        """Convert an Rvalue AST node to its string expression."""
        if node is None:
            return ""
        if isinstance(node, Rvalue):
            children = list(node.children())
            if children:
                return self._expr_to_str(children[0])
            return ""
        return self._expr_to_str(node)

    def _parse_ansi_ports(self, port_nodes) -> list[PortInfo]:
        ports = []
        for ioport in port_nodes:
            if not isinstance(ioport, Ioport):
                continue
            first = ioport.first
            direction = _DIR_MAP.get(type(first))
            if direction is None:
                continue
            width, msb_str, lsb_str = self._resolve_width(first.width)
            ports.append(PortInfo(
                name=first.name,
                direction=direction,
                width=width,
                msb_expr=msb_str,
                lsb_expr=lsb_str,
            ))
        return ports

    def _parse_old_style_ports(self, port_nodes, moddef: ModuleDef) -> list[PortInfo]:
        port_info_map: dict[str, tuple[PortDirection, int, str, str]] = {}
        items = moddef.items if moddef.items else []
        for item in items:
            if not isinstance(item, Decl):
                continue
            for child in item.children():
                dir_cls = type(child)
                direction = _DIR_MAP.get(dir_cls)
                if direction is None:
                    continue
                width, msb_str, lsb_str = self._resolve_width(child.width)
                port_info_map[child.name] = (direction, width, msb_str, lsb_str)

        ports = []
        for pnode in port_nodes:
            if not isinstance(pnode, Port):
                continue
            name = pnode.name
            if name in port_info_map:
                direction, width, msb_str, lsb_str = port_info_map[name]
                ports.append(PortInfo(
                    name=name,
                    direction=direction,
                    width=width,
                    msb_expr=msb_str,
                    lsb_expr=lsb_str,
                ))
        return ports

    def _resolve_width(self, width_node) -> tuple[int, str, str]:
        if width_node is None:
            return 1, "0", "0"

        msb = width_node.msb
        lsb = width_node.lsb

        msb_str = self._expr_to_str(msb)
        lsb_str = self._expr_to_str(lsb)

        try:
            msb_val = int(msb_str)
            lsb_val = int(lsb_str)
            return abs(msb_val - lsb_val) + 1, msb_str, lsb_str
        except (ValueError, TypeError):
            return -1, msb_str, lsb_str

    def _expr_to_str(self, node) -> str:
        """Recursively convert an AST expression node to a string."""
        if node is None:
            return ""
        if isinstance(node, IntConst):
            return str(node.value)
        if isinstance(node, FloatConst):
            return str(node.value)
        if isinstance(node, StringConst):
            return f'"{node.value}"'
        if isinstance(node, Identifier):
            return str(node.name)

        # Binary operators
        binop = _BINOP_MAP.get(type(node))
        if binop is not None:
            children = list(node.children())
            if len(children) == 2:
                left = self._expr_to_str(children[0])
                right = self._expr_to_str(children[1])
                return f"{left} {binop} {right}"

        # Unary operators
        unop = _UNOP_MAP.get(type(node))
        if unop is not None:
            children = list(node.children())
            if children:
                operand = self._expr_to_str(children[0])
                return f"{unop}{operand}"

        # Ternary conditional: Cond(cond, true_expr, false_expr)
        if isinstance(node, Cond):
            children = list(node.children())
            if len(children) == 3:
                cond = self._expr_to_str(children[0])
                t = self._expr_to_str(children[1])
                f = self._expr_to_str(children[2])
                return f"{cond} ? {t} : {f}"

        # System call: $clog2(X)
        if isinstance(node, SystemCall):
            children = list(node.children())
            args = ", ".join(self._expr_to_str(c) for c in children)
            syscall = str(node.syscall) if hasattr(node, 'syscall') else ""
            return f"${syscall}({args})"

        # Concatenation: {a, b, c}
        if isinstance(node, Concat):
            children = list(node.children())
            parts = ", ".join(self._expr_to_str(c) for c in children)
            return "{" + parts + "}"

        # Repeat: {N{expr}}
        if isinstance(node, Repeat):
            children = list(node.children())
            if len(children) == 2:
                times = self._expr_to_str(children[0])
                value = self._expr_to_str(children[1])
                return "{" + times + "{" + value + "}}"

        # Part select: a[msb:lsb]
        if isinstance(node, Partselect):
            children = list(node.children())
            if len(children) == 3:
                var = self._expr_to_str(children[0])
                msb = self._expr_to_str(children[1])
                lsb = self._expr_to_str(children[2])
                return f"{var}[{msb}:{lsb}]"

        # Pointer: a[idx]
        if isinstance(node, Pointer):
            children = list(node.children())
            if len(children) == 2:
                var = self._expr_to_str(children[0])
                idx = self._expr_to_str(children[1])
                return f"{var}[{idx}]"

        # Fallback: name attribute or str
        if hasattr(node, "name") and node.name:
            return str(node.name)
        if hasattr(node, "value") and node.value:
            return str(node.value)
        return str(node)
