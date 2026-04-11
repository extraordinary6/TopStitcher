"""Manual-first connection engine built around an explicit workspace."""

from __future__ import annotations

from topstitcher.core.data_model import (
    Connection,
    ConnectionType,
    ConnectedPort,
    DesignWorkspace,
    InstanceInfo,
    NetRecord,
    NetType,
    PortAssignment,
    PortDirection,
    PortInfo,
    PortRef,
    TOP_LEVEL_INSTANCE,
    TopModuleDesign,
)


S_PROMOTED = "Promoted"
S_WIDTH_MISMATCH = "Width Mismatch"
S_MULTI_DRIVER = "Multi-Driver"
S_UNDRIVEN = "Undriven"
S_CONFLICT = "Conflict"


class ConnectionEngine:
    """Workspace-first connection engine."""

    def initialize_workspace(
        self,
        instances: list[InstanceInfo],
    ) -> DesignWorkspace:
        nets: dict[str, NetRecord] = {}
        port_to_net: dict[PortRef, str] = {}

        for inst in instances:
            for port in inst.ports:
                ref = PortRef(inst.instance_name, port.name)
                net_id = f"net::{inst.instance_name}::{port.name}"
                nets[net_id] = NetRecord(
                    net_id=net_id,
                    net_name=f"{inst.instance_name}_{port.name}",
                    net_type=NetType.WIRE,
                    width=port.width,
                    msb_expr=port.msb_expr,
                    lsb_expr=port.lsb_expr,
                    connected_ports=[ref],
                    warnings=[],
                )
                port_to_net[ref] = net_id

        workspace = DesignWorkspace(
            instances=list(instances),
            nets=nets,
            port_to_net=port_to_net,
        )
        self.run_diagnostics(workspace)
        return workspace

    def flatten_workspace(
        self,
        workspace: DesignWorkspace,
    ) -> list[PortAssignment]:
        assignments: list[PortAssignment] = []
        instance_map = {inst.instance_name: inst for inst in workspace.instances}

        for inst in workspace.instances:
            for port in inst.ports:
                ref = PortRef(inst.instance_name, port.name)
                net = self._get_net_for_port(workspace, ref)
                status_tags: list[str] = []
                if net.net_type in (NetType.INPUT, NetType.OUTPUT):
                    status_tags.append(S_PROMOTED)
                status_tags.extend(net.warnings)
                assignments.append(PortAssignment(
                    instance_name=inst.instance_name,
                    module_name=instance_map[inst.instance_name].module_name,
                    port_name=port.name,
                    direction=port.direction,
                    width=port.width,
                    msb_expr=port.msb_expr,
                    lsb_expr=port.lsb_expr,
                    assigned_net=net.net_name,
                    status=", ".join(dict.fromkeys(status_tags)),
                ))

        return assignments

    def connect_ports(
        self,
        workspace: DesignWorkspace,
        left_port: PortRef,
        right_port: PortRef,
    ) -> NetRecord:
        self._validate_connect_pair(workspace, left_port, right_port)

        left_net_id = self._resolve_net_id_for_endpoint(workspace, left_port)
        right_net_id = self._resolve_net_id_for_endpoint(workspace, right_port)
        if left_net_id == right_net_id:
            self.run_diagnostics(workspace)
            return workspace.nets[left_net_id]

        left_net = workspace.nets[left_net_id]
        right_net = workspace.nets[right_net_id]
        left_info = self._get_endpoint_info(workspace, left_port)
        right_info = self._get_endpoint_info(workspace, right_port)

        merged_ports: list[PortRef] = []
        for ref in left_net.connected_ports + right_net.connected_ports:
            if ref not in merged_ports:
                merged_ports.append(ref)

        best = self._pick_width(left_info, right_info)
        merged_net_name = self._merged_net_name(
            workspace, left_port, right_port, left_net, right_net
        )
        merged_net = NetRecord(
            net_id=left_net.net_id,
            net_name=merged_net_name,
            net_type=self._merge_net_type(left_net.net_type, right_net.net_type),
            width=best.width,
            msb_expr=best.msb_expr,
            lsb_expr=best.lsb_expr,
            connected_ports=merged_ports,
            warnings=[],
        )
        if not self._same_width_expr(left_info, right_info):
            merged_net.warnings.append(S_WIDTH_MISMATCH)

        workspace.nets[left_net_id] = merged_net
        for ref in merged_ports:
            workspace.port_to_net[ref] = left_net_id
        del workspace.nets[right_net_id]

        self.run_diagnostics(workspace)
        return merged_net

    def disconnect_ports(
        self,
        workspace: DesignWorkspace,
        left_port: PortRef,
        right_port: PortRef,
    ) -> None:
        left_net_id = self._resolve_net_id_for_endpoint(workspace, left_port)
        right_net_id = self._resolve_net_id_for_endpoint(workspace, right_port)
        if left_net_id != right_net_id:
            return

        net = workspace.nets[left_net_id]
        if self._is_top_ref(left_port) or self._is_top_ref(right_port):
            detached = right_port if not self._is_top_ref(right_port) else left_port
            if self._is_top_ref(detached):
                return
            detached_info = self._get_port_info(workspace, detached)
            net.connected_ports = [ref for ref in net.connected_ports if ref != detached]
            new_net = self._make_singleton_net(detached, detached_info)
            workspace.nets[new_net.net_id] = new_net
            workspace.port_to_net[detached] = new_net.net_id
            if net.connected_ports:
                self._recompute_net_shape(workspace, net)
            self.run_diagnostics(workspace)
            return

        if left_port not in net.connected_ports or right_port not in net.connected_ports:
            return

        left_info = self._get_port_info(workspace, left_port)
        right_info = self._get_port_info(workspace, right_port)
        detached_port = right_port
        detached_info = right_info
        kept_port = left_port
        kept_info = left_info

        if left_info.direction == PortDirection.INPUT and right_info.direction == PortDirection.OUTPUT:
            detached_port = left_port
            detached_info = left_info
            kept_port = right_port
            kept_info = right_info

        remaining_ports = [ref for ref in net.connected_ports if ref != detached_port]

        if len(net.connected_ports) == 2:
            workspace.nets[left_net_id] = self._make_singleton_net(kept_port, kept_info)
            workspace.port_to_net[kept_port] = left_net_id
            new_net = self._make_singleton_net(detached_port, detached_info)
            workspace.nets[new_net.net_id] = new_net
            workspace.port_to_net[detached_port] = new_net.net_id
        else:
            net.connected_ports = remaining_ports
            self._recompute_net_shape(workspace, net)
            new_net = self._make_singleton_net(detached_port, detached_info)
            workspace.nets[new_net.net_id] = new_net
            workspace.port_to_net[detached_port] = new_net.net_id

        self.run_diagnostics(workspace)

    def auto_io(
        self,
        workspace: DesignWorkspace,
        port_ref: PortRef,
    ) -> NetRecord:
        port = self._get_port_info(workspace, port_ref)
        net = self._get_net_for_port(workspace, port_ref)
        if port.direction == PortDirection.INPUT:
            net.net_type = NetType.INPUT
        elif port.direction == PortDirection.OUTPUT:
            net.net_type = NetType.OUTPUT
        self.run_diagnostics(workspace)
        return net

    def auto_connect_same_name_same_width(
        self,
        workspace: DesignWorkspace,
    ) -> None:
        port_groups: dict[str, list[tuple[InstanceInfo, PortInfo]]] = {}
        for inst in workspace.instances:
            for port in inst.ports:
                if port.direction == PortDirection.INOUT:
                    continue
                port_groups.setdefault(port.name, []).append((inst, port))

        for entries in port_groups.values():
            if len(entries) < 2:
                continue
            drivers = [
                (inst, port) for inst, port in entries
                if port.direction == PortDirection.OUTPUT
            ]
            receivers = [
                (inst, port) for inst, port in entries
                if port.direction == PortDirection.INPUT
            ]
            for src_inst, src_port in drivers:
                for dst_inst, dst_port in receivers:
                    if src_inst.instance_name == dst_inst.instance_name:
                        continue
                    if not self._same_width_expr(src_port, dst_port):
                        continue
                    self.connect_ports(
                        workspace,
                        PortRef(src_inst.instance_name, src_port.name),
                        PortRef(dst_inst.instance_name, dst_port.name),
                    )
                    break

        self.run_diagnostics(workspace)

    def rename_net(
        self,
        workspace: DesignWorkspace,
        endpoint: PortRef,
        new_name: str,
    ) -> None:
        net_id = self._resolve_net_id_for_endpoint(workspace, endpoint)
        workspace.nets[net_id].net_name = new_name.strip()

    def resolve_design_from_workspace(
        self,
        workspace: DesignWorkspace,
        module_name: str,
    ) -> TopModuleDesign:
        internal_wires: list[Connection] = []
        top_ports: list[Connection] = []
        inst_map = {inst.instance_name: inst for inst in workspace.instances}

        for net in sorted(workspace.nets.values(), key=lambda item: item.net_name):
            connected = [
                ConnectedPort(
                    instance_name=ref.instance_name,
                    module_name=inst_map[ref.instance_name].module_name,
                    port_name=ref.port_name,
                )
                for ref in net.connected_ports
            ]

            if net.net_type == NetType.WIRE:
                internal_wires.append(Connection(
                    net_name=net.net_name,
                    width=net.width,
                    conn_type=ConnectionType.INTERNAL_WIRE,
                    connected_ports=connected,
                    msb_expr=net.msb_expr,
                    lsb_expr=net.lsb_expr,
                ))
                continue

            top_ports.append(Connection(
                net_name=net.net_name,
                width=net.width,
                conn_type=ConnectionType.TOP_LEVEL_PORT,
                direction=(
                    PortDirection.INPUT
                    if net.net_type == NetType.INPUT
                    else PortDirection.OUTPUT
                ),
                connected_ports=connected,
                msb_expr=net.msb_expr,
                lsb_expr=net.lsb_expr,
            ))

        return TopModuleDesign(
            module_name=module_name,
            instances=workspace.instances,
            internal_wires=internal_wires,
            top_ports=top_ports,
        )

    def run_diagnostics(
        self,
        workspace: DesignWorkspace,
    ) -> None:
        for net in workspace.nets.values():
            net.warnings = [warning for warning in net.warnings if warning == S_WIDTH_MISMATCH]
            ports = [self._get_port_info(workspace, ref) for ref in net.connected_ports]
            output_count = sum(
                1 for port in ports
                if port.direction in (PortDirection.OUTPUT, PortDirection.INOUT)
            )
            input_count = sum(
                1 for port in ports
                if port.direction in (PortDirection.INPUT, PortDirection.INOUT)
            )

            if output_count >= 2:
                net.warnings.append(S_MULTI_DRIVER)
            if net.net_type == NetType.WIRE and output_count == 0 and input_count >= 1:
                net.warnings.append(S_UNDRIVEN)

    def build_assignments(
        self,
        instances: list[InstanceInfo],
        global_signals: list[str] | None = None,
        promoted_ports: set[tuple[str, str]] | None = None,
    ) -> list[PortAssignment]:
        workspace = self.initialize_workspace(instances)
        return self.flatten_workspace(workspace)

    def resolve_design(
        self,
        module_name: str,
        instances: list[InstanceInfo],
        assignments: list[PortAssignment],
        global_signals: list[str] | None = None,
        promoted_ports: set[tuple[str, str]] | None = None,
    ) -> TopModuleDesign:
        workspace = self.workspace_from_assignments(instances, assignments)
        return self.resolve_design_from_workspace(workspace, module_name)

    def workspace_from_assignments(
        self,
        instances: list[InstanceInfo],
        assignments: list[PortAssignment],
    ) -> DesignWorkspace:
        workspace = self.initialize_workspace(instances)
        by_net: dict[str, list[PortAssignment]] = {}
        for assignment in assignments:
            by_net.setdefault(assignment.assigned_net, []).append(assignment)

        workspace.nets = {}
        workspace.port_to_net = {}
        for index, (net_name, group) in enumerate(by_net.items(), start=1):
            refs = [PortRef(item.instance_name, item.port_name) for item in group]
            best = max(group, key=lambda item: item.width)
            net_type = NetType.WIRE
            if any(S_PROMOTED in item.status for item in group):
                if best.direction == PortDirection.INPUT:
                    net_type = NetType.INPUT
                elif best.direction == PortDirection.OUTPUT:
                    net_type = NetType.OUTPUT
            net = NetRecord(
                net_id=f"net::{index}",
                net_name=net_name,
                net_type=net_type,
                width=best.width,
                msb_expr=best.msb_expr,
                lsb_expr=best.lsb_expr,
                connected_ports=refs,
                warnings=[],
            )
            if self._group_has_width_mismatch(workspace, refs):
                net.warnings.append(S_WIDTH_MISMATCH)
            workspace.nets[net.net_id] = net
            for ref in refs:
                workspace.port_to_net[ref] = net.net_id

        self.run_diagnostics(workspace)
        return workspace

    def _group_has_width_mismatch(
        self,
        workspace: DesignWorkspace,
        refs: list[PortRef],
    ) -> bool:
        if len(refs) < 2:
            return False
        first = self._get_port_info(workspace, refs[0])
        return any(
            not self._same_width_expr(first, self._get_port_info(workspace, ref))
            for ref in refs[1:]
        )

    def _validate_connect_pair(
        self,
        workspace: DesignWorkspace,
        left_port: PortRef,
        right_port: PortRef,
    ) -> None:
        left_kind = self._endpoint_kind(workspace, left_port)
        right_kind = self._endpoint_kind(workspace, right_port)

        allowed = {
            ("output", "input"),
            ("top_input", "input"),
            ("output", "top_output"),
        }
        if (left_kind, right_kind) not in allowed:
            raise ValueError("Only output->input, top input->input, or output->top output are allowed.")

        if (not self._is_top_ref(left_port)
                and not self._is_top_ref(right_port)
                and left_port.instance_name == right_port.instance_name):
            raise ValueError("Cannot connect ports on the same instance.")

    def _merge_net_type(self, left: NetType, right: NetType) -> NetType:
        if left != NetType.WIRE:
            return left
        if right != NetType.WIRE:
            return right
        return NetType.WIRE

    def _pick_width(self, left: PortInfo, right: PortInfo) -> PortInfo:
        return left if left.width >= right.width else right

    def _same_width_expr(self, left: PortInfo, right: PortInfo) -> bool:
        return (
            left.width == right.width
            and left.msb_expr == right.msb_expr
            and left.lsb_expr == right.lsb_expr
        )

    def _merged_net_name(
        self,
        workspace: DesignWorkspace,
        left_port: PortRef,
        right_port: PortRef,
        left_net: NetRecord,
        right_net: NetRecord,
    ) -> str:
        if self._is_top_ref(left_port):
            return left_net.net_name
        if self._is_top_ref(right_port):
            return right_net.net_name
        return f"{self._endpoint_label(workspace, left_port)}_to_{self._endpoint_label(workspace, right_port)}"

    def _make_singleton_net(self, ref: PortRef, port: PortInfo) -> NetRecord:
        net_id = f"net::{ref.instance_name}::{ref.port_name}"
        return NetRecord(
            net_id=net_id,
            net_name=f"{ref.instance_name}_{ref.port_name}",
            net_type=NetType.WIRE,
            width=port.width,
            msb_expr=port.msb_expr,
            lsb_expr=port.lsb_expr,
            connected_ports=[ref],
            warnings=[],
        )

    def _recompute_net_shape(
        self,
        workspace: DesignWorkspace,
        net: NetRecord,
    ) -> None:
        if not net.connected_ports:
            return
        ports = [self._get_port_info(workspace, ref) for ref in net.connected_ports]
        best = max(ports, key=lambda port: port.width)
        net.width = best.width
        net.msb_expr = best.msb_expr
        net.lsb_expr = best.lsb_expr
        if len(ports) > 1 and any(
            not self._same_width_expr(ports[0], port) for port in ports[1:]
        ) and S_WIDTH_MISMATCH not in net.warnings:
            net.warnings.append(S_WIDTH_MISMATCH)

    def _is_top_ref(self, ref: PortRef) -> bool:
        return ref.instance_name == TOP_LEVEL_INSTANCE

    def _resolve_net_id_for_endpoint(
        self,
        workspace: DesignWorkspace,
        ref: PortRef,
    ) -> str:
        if self._is_top_ref(ref):
            return ref.port_name
        return workspace.port_to_net[ref]

    def _get_net_for_port(
        self,
        workspace: DesignWorkspace,
        ref: PortRef,
    ) -> NetRecord:
        return workspace.nets[workspace.port_to_net[ref]]

    def _get_port_info(
        self,
        workspace: DesignWorkspace,
        ref: PortRef,
    ) -> PortInfo:
        for inst in workspace.instances:
            if inst.instance_name != ref.instance_name:
                continue
            for port in inst.ports:
                if port.name == ref.port_name:
                    return port
        raise KeyError(f"Port not found: {ref.instance_name}.{ref.port_name}")

    def _get_endpoint_info(
        self,
        workspace: DesignWorkspace,
        ref: PortRef,
    ) -> PortInfo:
        if not self._is_top_ref(ref):
            return self._get_port_info(workspace, ref)
        net = workspace.nets[ref.port_name]
        direction = PortDirection.OUTPUT if net.net_type == NetType.INPUT else PortDirection.INPUT
        return PortInfo(
            name=net.net_name,
            direction=direction,
            width=net.width,
            msb_expr=net.msb_expr,
            lsb_expr=net.lsb_expr,
        )

    def _endpoint_kind(
        self,
        workspace: DesignWorkspace,
        ref: PortRef,
    ) -> str:
        if self._is_top_ref(ref):
            net = workspace.nets[ref.port_name]
            if net.net_type == NetType.INPUT:
                return "top_input"
            if net.net_type == NetType.OUTPUT:
                return "top_output"
            return "top_wire"

        port = self._get_port_info(workspace, ref)
        if port.direction == PortDirection.INPUT:
            return "input"
        if port.direction == PortDirection.OUTPUT:
            return "output"
        return "inout"

    def _endpoint_label(
        self,
        workspace: DesignWorkspace,
        ref: PortRef,
    ) -> str:
        if self._is_top_ref(ref):
            return workspace.nets[ref.port_name].net_name
        return ref.port_name
