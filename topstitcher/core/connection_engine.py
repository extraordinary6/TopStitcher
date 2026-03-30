"""Connection engine with direction-aware rules, width tolerance, suggestions, and diagnostics."""

from topstitcher.core.data_model import (
    PortInfo, PortDirection, InstanceInfo, ConnectionType,
    Connection, ConnectedPort, PortAssignment, TopModuleDesign,
)

DEFAULT_GLOBAL_SIGNALS = ["clk", "clock", "rst_n", "reset", "rst", "reset_n"]

# Status tags
S_GLOBAL = "Global"
S_PROMOTED = "Promoted"
S_SUGGESTED = "Suggested"
S_WIDTH_MISMATCH = "Width Mismatch"
S_MULTI_DRIVER = "Multi-Driver"
S_UNDRIVEN = "Undriven"
S_CONFLICT = "Conflict"


def _has_driver(entries: list[tuple[InstanceInfo, PortInfo]]) -> bool:
    return any(p.direction in (PortDirection.OUTPUT, PortDirection.INOUT)
               for _, p in entries)


def _has_receiver(entries: list[tuple[InstanceInfo, PortInfo]]) -> bool:
    return any(p.direction in (PortDirection.INPUT, PortDirection.INOUT)
               for _, p in entries)


def _all_outputs(entries: list[tuple[InstanceInfo, PortInfo]]) -> bool:
    return all(p.direction == PortDirection.OUTPUT for _, p in entries)


def _max_width_entry(entries: list[tuple[InstanceInfo, PortInfo]]) -> PortInfo:
    """Return the port with the largest width (for wire declaration)."""
    return max(entries, key=lambda e: e[1].width)[1]


class ConnectionEngine:
    """Analyzes instance ports and determines default net assignments."""

    def build_assignments(
        self,
        instances: list[InstanceInfo],
        global_signals: list[str] | None = None,
        promoted_ports: set[tuple[str, str]] | None = None,
    ) -> list[PortAssignment]:
        if global_signals is None:
            global_signals = []
        if promoted_ports is None:
            promoted_ports = set()

        global_set = set(global_signals)

        # Phase 1: Build port index {port_name: [(instance, port), ...]}
        port_index: dict[str, list[tuple[InstanceInfo, PortInfo]]] = {}
        for inst in instances:
            for port in inst.ports:
                port_index.setdefault(port.name, []).append((inst, port))

        # Phase 2: Classify ports with direction-aware Rule A + width mismatch tolerance
        rule_a_nets: dict[str, str] = {}  # port_name -> status ("" or "Width Mismatch")
        conflict_nets: set[str] = set()

        for port_name, entries in port_index.items():
            if port_name in global_set:
                continue
            if len(entries) < 2:
                continue
            # Check none are promoted
            if any((inst.instance_name, port.name) in promoted_ports
                   for inst, port in entries):
                continue
            # Skip parameterized
            if any(port.width == -1 for _, port in entries):
                continue

            # Direction check: all outputs = conflict
            if _all_outputs(entries):
                conflict_nets.add(port_name)
                continue

            # Direction OK (has at least some input/inout alongside output, or all inputs)
            widths = {port.width for _, port in entries}
            if len(widths) == 1:
                rule_a_nets[port_name] = ""
            else:
                # Width mismatch but direction OK → connect with warning
                rule_a_nets[port_name] = S_WIDTH_MISMATCH

        # Phase 3: Build assignments
        assignments: list[PortAssignment] = []
        used_top_names: set[str] = set()

        for inst in instances:
            for port in inst.ports:
                is_promoted = (inst.instance_name, port.name) in promoted_ports
                is_global = port.name in global_set
                is_conflict = port.name in conflict_nets

                if is_global:
                    net = port.name
                    status = S_GLOBAL
                elif is_promoted:
                    net = self._unique_top_name(
                        port.name, inst, port_index.get(port.name, []),
                        used_top_names,
                    )
                    used_top_names.add(net)
                    status = S_PROMOTED
                elif port.name in rule_a_nets:
                    net = port.name
                    status = rule_a_nets[port.name]  # "" or "Width Mismatch"
                elif is_conflict:
                    net = self._unique_top_name(
                        port.name, inst, port_index.get(port.name, []),
                        used_top_names,
                    )
                    used_top_names.add(net)
                    status = S_CONFLICT
                else:
                    # Rule B: top-level port
                    net = self._unique_top_name(
                        port.name, inst, port_index.get(port.name, []),
                        used_top_names,
                    )
                    used_top_names.add(net)
                    status = ""

                assignments.append(PortAssignment(
                    instance_name=inst.instance_name,
                    module_name=inst.module_name,
                    port_name=port.name,
                    direction=port.direction,
                    width=port.width,
                    msb_expr=port.msb_expr,
                    lsb_expr=port.lsb_expr,
                    assigned_net=net,
                    status=status,
                ))

        # Phase 4: Suggested connections for remaining Rule B ports
        self._suggest_connections(assignments, global_set, rule_a_nets)

        # Phase 5: Diagnostics
        self._run_diagnostics(assignments)

        return assignments

    def _suggest_connections(
        self,
        assignments: list[PortAssignment],
        global_set: set[str],
        rule_a_nets: dict[str, str],
    ):
        """For Rule B leftovers, try to match output→input with same width across instances."""
        # Collect Rule B ports (no status, not global, not rule_a)
        rule_b: list[PortAssignment] = [
            a for a in assignments
            if a.status == "" and a.port_name not in global_set
            and a.port_name not in rule_a_nets
        ]

        # Group by width
        outputs_by_width: dict[int, list[PortAssignment]] = {}
        inputs_by_width: dict[int, list[PortAssignment]] = {}
        for a in rule_b:
            if a.width <= 0:
                continue
            if a.direction == PortDirection.OUTPUT:
                outputs_by_width.setdefault(a.width, []).append(a)
            elif a.direction == PortDirection.INPUT:
                inputs_by_width.setdefault(a.width, []).append(a)

        # For each output, if exactly one input candidate from a different instance
        used_inputs: set[tuple[str, str]] = set()
        for width, outputs in outputs_by_width.items():
            inputs = inputs_by_width.get(width, [])
            if not inputs:
                continue
            for out_a in outputs:
                # Find unused input from a different instance
                candidates = [
                    inp for inp in inputs
                    if inp.instance_name != out_a.instance_name
                    and (inp.instance_name, inp.port_name) not in used_inputs
                ]
                if len(candidates) == 1:
                    inp_a = candidates[0]
                    # Create a shared net name
                    net_name = f"{out_a.port_name}_to_{inp_a.port_name}"
                    out_a.assigned_net = net_name
                    out_a.status = S_SUGGESTED
                    inp_a.assigned_net = net_name
                    inp_a.status = S_SUGGESTED
                    used_inputs.add((inp_a.instance_name, inp_a.port_name))

    def _run_diagnostics(self, assignments: list[PortAssignment]):
        """Post-assignment diagnostics: multi-driver, undriven."""
        # Group by net
        net_groups: dict[str, list[PortAssignment]] = {}
        for a in assignments:
            net_groups.setdefault(a.assigned_net, []).append(a)

        for net_name, group in net_groups.items():
            if len(group) < 2:
                continue

            output_count = sum(
                1 for a in group
                if a.direction in (PortDirection.OUTPUT, PortDirection.INOUT)
            )
            input_count = sum(
                1 for a in group
                if a.direction in (PortDirection.INPUT, PortDirection.INOUT)
            )

            # Multi-driver: >=2 outputs on same net
            if output_count >= 2:
                for a in group:
                    if a.direction in (PortDirection.OUTPUT, PortDirection.INOUT):
                        a.status = _append_status(a.status, S_MULTI_DRIVER)

            # Undriven: only inputs, no output driving the net
            if output_count == 0 and input_count >= 1:
                # Skip globals (they're driven from top level)
                if not any(a.status and S_GLOBAL in a.status for a in group):
                    for a in group:
                        a.status = _append_status(a.status, S_UNDRIVEN)

    def resolve_design(
        self,
        module_name: str,
        instances: list[InstanceInfo],
        assignments: list[PortAssignment],
        global_signals: list[str] | None = None,
        promoted_ports: set[tuple[str, str]] | None = None,
    ) -> TopModuleDesign:
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
            # Use max width for the wire/port declaration
            max_w = max(a.width for a in group)
            best = next(
                (a for a in group if a.width == max_w),
                group[0],
            )

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
                top_ports.append(Connection(
                    net_name=net_name,
                    width=best.width,
                    conn_type=ConnectionType.TOP_LEVEL_PORT,
                    direction=PortDirection.INPUT,
                    connected_ports=connected,
                    msb_expr=best.msb_expr,
                    lsb_expr=best.lsb_expr,
                ))
            elif is_promoted or is_single:
                top_ports.append(Connection(
                    net_name=net_name,
                    width=best.width,
                    conn_type=ConnectionType.TOP_LEVEL_PORT,
                    direction=best.direction,
                    connected_ports=connected,
                    msb_expr=best.msb_expr,
                    lsb_expr=best.lsb_expr,
                ))
            else:
                internal_wires.append(Connection(
                    net_name=net_name,
                    width=best.width,
                    conn_type=ConnectionType.INTERNAL_WIRE,
                    connected_ports=connected,
                    msb_expr=best.msb_expr,
                    lsb_expr=best.lsb_expr,
                ))

        return TopModuleDesign(
            module_name=module_name,
            instances=instances,
            internal_wires=internal_wires,
            top_ports=top_ports,
        )

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


def _append_status(existing: str, new_tag: str) -> str:
    """Append a status tag, avoiding duplicates."""
    if not existing:
        return new_tag
    if new_tag in existing:
        return existing
    return f"{existing}, {new_tag}"
