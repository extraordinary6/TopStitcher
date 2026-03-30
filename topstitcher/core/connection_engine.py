"""Connection engine implementing Rule A, Rule B, global signals, and promotions."""

from topstitcher.core.data_model import (
    PortInfo, PortDirection, InstanceInfo, ConnectionType,
    Connection, ConnectedPort, PortAssignment, TopModuleDesign,
)

DEFAULT_GLOBAL_SIGNALS = ["clk", "clock", "rst_n", "reset", "rst", "reset_n"]


class ConnectionEngine:
    """Analyzes instance ports and determines default net assignments."""

    def build_assignments(
        self,
        instances: list[InstanceInfo],
        global_signals: list[str] | None = None,
        promoted_ports: set[tuple[str, str]] | None = None,
    ) -> list[PortAssignment]:
        """Build default PortAssignment rows for all instance ports.

        Args:
            instances: Active instances in the design.
            global_signals: Port names to promote as top-level inputs.
            promoted_ports: Set of (instance_name, port_name) forced to top.

        Returns:
            List of PortAssignment rows (one per instance port).
        """
        if global_signals is None:
            global_signals = []
        if promoted_ports is None:
            promoted_ports = set()

        global_set = set(global_signals)

        # Build port index: {port_name: [(instance, port), ...]}
        port_index: dict[str, list[tuple[InstanceInfo, PortInfo]]] = {}
        for inst in instances:
            for port in inst.ports:
                port_index.setdefault(port.name, []).append((inst, port))

        # Determine which port names qualify for Rule A (internal wire)
        rule_a_nets: set[str] = set()
        for port_name, entries in port_index.items():
            if port_name in global_set:
                continue  # global signals skip Rule A
            if len(entries) < 2:
                continue
            if not self._can_auto_connect(entries):
                continue
            # Check none are promoted
            any_promoted = any(
                (inst.instance_name, port.name) in promoted_ports
                for inst, port in entries
            )
            if any_promoted:
                continue
            rule_a_nets.add(port_name)

        # Build assignments
        assignments = []
        # Track used net names for dedup
        used_top_names: set[str] = set()

        for inst in instances:
            for port in inst.ports:
                is_promoted = (inst.instance_name, port.name) in promoted_ports
                is_global = port.name in global_set

                if is_global:
                    # Global signal: net name = port name (shared top-level input)
                    net = port.name
                elif is_promoted:
                    # Promoted port: unique top-level port
                    net = self._unique_top_name(
                        port.name, inst, port_index.get(port.name, []),
                        used_top_names,
                    )
                    used_top_names.add(net)
                elif port.name in rule_a_nets:
                    # Rule A: internal wire with port name
                    net = port.name
                else:
                    # Rule B: top-level port
                    net = self._unique_top_name(
                        port.name, inst, port_index.get(port.name, []),
                        used_top_names,
                    )
                    used_top_names.add(net)

                assignments.append(PortAssignment(
                    instance_name=inst.instance_name,
                    module_name=inst.module_name,
                    port_name=port.name,
                    direction=port.direction,
                    width=port.width,
                    msb_expr=port.msb_expr,
                    lsb_expr=port.lsb_expr,
                    assigned_net=net,
                ))

        return assignments

    def resolve_design(
        self,
        module_name: str,
        instances: list[InstanceInfo],
        assignments: list[PortAssignment],
        global_signals: list[str] | None = None,
        promoted_ports: set[tuple[str, str]] | None = None,
    ) -> TopModuleDesign:
        """Resolve final assignments into a TopModuleDesign for code generation.

        Groups assignments by net name. Nets connected to >=2 ports that are
        not global/promoted become internal wires. Others become top-level ports.
        """
        if global_signals is None:
            global_signals = []
        if promoted_ports is None:
            promoted_ports = set()

        global_set = set(global_signals)

        # Group assignments by net name
        net_groups: dict[str, list[PortAssignment]] = {}
        for a in assignments:
            net_groups.setdefault(a.assigned_net, []).append(a)

        internal_wires = []
        top_ports = []

        for net_name, group in sorted(net_groups.items()):
            first = group[0]

            # Determine if this net is a top-level port
            is_global = net_name in global_set
            is_promoted = any(
                (a.instance_name, a.port_name) in promoted_ports for a in group
            )
            is_single = len(group) == 1

            connected = [
                ConnectedPort(a.instance_name, a.module_name, a.port_name)
                for a in group
            ]

            if is_global:
                # Global signal: top-level input
                top_ports.append(Connection(
                    net_name=net_name,
                    width=first.width,
                    conn_type=ConnectionType.TOP_LEVEL_PORT,
                    direction=PortDirection.INPUT,
                    connected_ports=connected,
                    msb_expr=first.msb_expr,
                    lsb_expr=first.lsb_expr,
                ))
            elif is_promoted or is_single:
                # Promoted or unique port: top-level, use first port's direction
                direction = first.direction
                top_ports.append(Connection(
                    net_name=net_name,
                    width=first.width,
                    conn_type=ConnectionType.TOP_LEVEL_PORT,
                    direction=direction,
                    connected_ports=connected,
                    msb_expr=first.msb_expr,
                    lsb_expr=first.lsb_expr,
                ))
            else:
                # Multiple connections, not global/promoted: internal wire
                internal_wires.append(Connection(
                    net_name=net_name,
                    width=first.width,
                    conn_type=ConnectionType.INTERNAL_WIRE,
                    connected_ports=connected,
                    msb_expr=first.msb_expr,
                    lsb_expr=first.lsb_expr,
                ))

        return TopModuleDesign(
            module_name=module_name,
            instances=instances,
            internal_wires=internal_wires,
            top_ports=top_ports,
        )

    def _can_auto_connect(
        self, entries: list[tuple[InstanceInfo, PortInfo]]
    ) -> bool:
        widths = {port.width for _, port in entries}
        return len(widths) == 1 and -1 not in widths

    def _unique_top_name(
        self,
        port_name: str,
        inst: InstanceInfo,
        entries: list[tuple[InstanceInfo, PortInfo]],
        used: set[str],
    ) -> str:
        if len(entries) > 1 or port_name in used:
            return f"{inst.instance_name}_{port_name}"
        return port_name
