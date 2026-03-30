"""Data models for TopStitcher V2."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import copy


class PortDirection(Enum):
    INPUT = "input"
    OUTPUT = "output"
    INOUT = "inout"


class ConnectionType(Enum):
    INTERNAL_WIRE = "internal_wire"
    TOP_LEVEL_PORT = "top_level_port"


@dataclass
class PortInfo:
    name: str
    direction: PortDirection
    width: int = 1  # -1 for parameterized widths
    msb_expr: str = "0"
    lsb_expr: str = "0"

    @property
    def range_str(self) -> str:
        if self.width == 1:
            return ""
        return f"[{self.msb_expr}:{self.lsb_expr}]"


@dataclass
class ParamInfo:
    """A module parameter with name and default value string."""
    name: str
    value: str  # default value as string expression


@dataclass
class ModuleInfo:
    """A parsed module definition (library entry). No instance_name."""
    name: str
    ports: list[PortInfo] = field(default_factory=list)
    params: list[ParamInfo] = field(default_factory=list)
    source_file: str = ""


@dataclass
class InstanceInfo:
    """A concrete instance of a module in the design."""
    module_name: str
    instance_name: str
    ports: list[PortInfo] = field(default_factory=list)
    params: list[ParamInfo] = field(default_factory=list)

    @staticmethod
    def from_module(module: ModuleInfo, instance_name: str) -> "InstanceInfo":
        return InstanceInfo(
            module_name=module.name,
            instance_name=instance_name,
            ports=copy.deepcopy(module.ports),
            params=copy.deepcopy(module.params),
        )


@dataclass
class PortAssignment:
    """One row in the interactive connection table."""
    instance_name: str
    module_name: str
    port_name: str
    direction: PortDirection
    width: int
    msb_expr: str
    lsb_expr: str
    assigned_net: str  # editable by user
    status: str = ""   # e.g. "Global", "Promoted", "Suggested", "Width Mismatch", etc.

    @property
    def range_str(self) -> str:
        if self.width == 1:
            return ""
        return f"[{self.msb_expr}:{self.lsb_expr}]"


@dataclass
class ConnectedPort:
    instance_name: str
    module_name: str
    port_name: str


@dataclass
class Connection:
    net_name: str
    width: int
    conn_type: ConnectionType
    direction: Optional[PortDirection] = None
    connected_ports: list[ConnectedPort] = field(default_factory=list)
    msb_expr: str = "0"
    lsb_expr: str = "0"

    @property
    def range_str(self) -> str:
        if self.width == 1:
            return ""
        return f"[{self.msb_expr}:{self.lsb_expr}]"


@dataclass
class TopModuleDesign:
    module_name: str = "top_module"
    instances: list[InstanceInfo] = field(default_factory=list)
    internal_wires: list[Connection] = field(default_factory=list)
    top_ports: list[Connection] = field(default_factory=list)

    # V1 compat alias
    @property
    def sub_modules(self) -> list:
        return self.instances
