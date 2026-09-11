"""Resource-type table backing oci_list / oci_get.

Read operations are uniform enough ("show me X in compartment Y") that one tool
per API call would be waste: ~30 calls collapse into two dispatch tools plus this
table. Write operations are NOT uniform and stay explicit elsewhere.

Every `list_fn` / `get_fn` is a zero-arg lambda so the underlying service client
is built lazily on first use, never at import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from . import clients
from .shaping import FieldSpec

# Shared prefixes so projections stay consistent across types.
_ID = ("name=display_name", "ocid=id", "state=lifecycle_state")


@dataclass(frozen=True, slots=True)
class ResourceKind:
    """How to list, get and project one resource type."""

    service: str
    list_fn: Callable[[], Callable[..., Any]]
    fields: FieldSpec
    get_fn: Callable[[], Callable[..., Any]] | None = None
    # Static extras the API demands but the caller should not have to supply.
    list_kwargs: Mapping[str, Any] = field(default_factory=dict)
    # "compartment": fan out across compartments (or the one requested).
    # "tenancy":     one call against the root compartment — for things like
    #                availability domains that are identical in every compartment.
    # "global":      one call with no compartment at all (regions).
    scope: str = "compartment"
    # True when the list API is availability-domain-scoped, so reads must fan out.
    needs_ad: bool = False
    # True for Object Storage, whose calls take a namespace.
    needs_namespace: bool = False
    # True when get() takes a name rather than an OCID (buckets).
    get_by_name: bool = False
    # False for the few list APIs that return everything in one unpaged call
    # and reject the limit/page kwargs the pagination helper would send.
    paginated: bool = True
    note: str = ""


REGISTRY: dict[str, ResourceKind] = {
    # ---------------------------------------------------------------- compute
    "instance": ResourceKind(
        service="compute",
        list_fn=lambda: clients.compute().list_instances,
        get_fn=lambda: clients.compute().get_instance,
        fields=(*_ID, "shape", "ad=availability_domain", "fault_domain",
                "ocpus=shape_config.ocpus", "created=time_created", "compartment_id"),
        note="A VM or bare-metal compute instance. Terminated instances are "
             "returned too unless you filter by lifecycle_state=RUNNING.",
    ),
    "image": ResourceKind(
        service="compute",
        list_fn=lambda: clients.compute().list_images,
        get_fn=lambda: clients.compute().get_image,
        fields=(*_ID, "os=operating_system", "os_version=operating_system_version",
                "created=time_created", "size_mb=size_in_mbs"),
    ),
    "shape": ResourceKind(
        service="compute",
        list_fn=lambda: clients.compute().list_shapes,
        fields=("name=shape", "ocpus", "memory_gb=memory_in_gbs",
                "gpus", "local_disks", "network_gbps=networking_bandwidth_in_gbps"),
        note="Instance shapes available in the compartment. No get: list and filter.",
    ),
    "vnic_attachment": ResourceKind(
        service="compute",
        list_fn=lambda: clients.compute().list_vnic_attachments,
        get_fn=lambda: clients.compute().get_vnic_attachment,
        fields=(*_ID, "instance_id", "vnic_id", "subnet_id", "nic_index"),
    ),
    "volume_attachment": ResourceKind(
        service="compute",
        list_fn=lambda: clients.compute().list_volume_attachments,
        get_fn=lambda: clients.compute().get_volume_attachment,
        fields=(*_ID, "instance_id", "volume_id", "device", "attachment_type",
                "is_read_only", "created=time_created"),
    ),
    "boot_volume_attachment": ResourceKind(
        service="compute",
        list_fn=lambda: clients.compute().list_boot_volume_attachments,
        get_fn=lambda: clients.compute().get_boot_volume_attachment,
        fields=(*_ID, "instance_id", "boot_volume_id", "ad=availability_domain"),
        needs_ad=True,
        note="Availability-domain scoped: reads fan out across every AD.",
    ),

    # ---------------------------------------------------------- block storage
    "volume": ResourceKind(
        service="block_storage",
        list_fn=lambda: clients.blockstorage().list_volumes,
        get_fn=lambda: clients.blockstorage().get_volume,
        fields=(*_ID, "size_gb=size_in_gbs", "ad=availability_domain",
                "vpus_per_gb=vpus_per_gb", "is_hydrated", "created=time_created"),
    ),
    "boot_volume": ResourceKind(
        service="block_storage",
        list_fn=lambda: clients.blockstorage().list_boot_volumes,
        get_fn=lambda: clients.blockstorage().get_boot_volume,
        fields=(*_ID, "size_gb=size_in_gbs", "ad=availability_domain",
                "image_id", "is_hydrated", "created=time_created"),
    ),
    "volume_backup": ResourceKind(
        service="block_storage",
        list_fn=lambda: clients.blockstorage().list_volume_backups,
        get_fn=lambda: clients.blockstorage().get_volume_backup,
        fields=(*_ID, "volume_id", "type", "size_gb=size_in_gbs",
                "source_type", "created=time_created", "expires=time_request_received"),
    ),
    "boot_volume_backup": ResourceKind(
        service="block_storage",
        list_fn=lambda: clients.blockstorage().list_boot_volume_backups,
        get_fn=lambda: clients.blockstorage().get_boot_volume_backup,
        fields=(*_ID, "boot_volume_id", "type", "size_gb=size_in_gbs",
                "created=time_created"),
    ),
    "volume_group": ResourceKind(
        service="block_storage",
        list_fn=lambda: clients.blockstorage().list_volume_groups,
        get_fn=lambda: clients.blockstorage().get_volume_group,
        fields=(*_ID, "ad=availability_domain", "size_gb=size_in_gbs",
                "volume_ids", "created=time_created"),
    ),

    # ---------------------------------------------------------------- network
    "vcn": ResourceKind(
        service="network",
        list_fn=lambda: clients.network().list_vcns,
        get_fn=lambda: clients.network().get_vcn,
        fields=(*_ID, "cidr=cidr_block", "cidrs=cidr_blocks", "dns_label",
                "default_route_table_id", "default_security_list_id", "created=time_created"),
    ),
    "subnet": ResourceKind(
        service="network",
        list_fn=lambda: clients.network().list_subnets,
        get_fn=lambda: clients.network().get_subnet,
        fields=(*_ID, "cidr=cidr_block", "vcn_id", "ad=availability_domain",
                "public=prohibit_public_ip_on_vnic", "route_table_id",
                "security_list_ids", "created=time_created"),
        note="`public` is prohibit_public_ip_on_vnic: true means PRIVATE subnet.",
    ),
    "security_list": ResourceKind(
        service="network",
        list_fn=lambda: clients.network().list_security_lists,
        get_fn=lambda: clients.network().get_security_list,
        fields=(*_ID, "vcn_id", "ingress_security_rules", "egress_security_rules"),
    ),
    "nsg": ResourceKind(
        service="network",
        list_fn=lambda: clients.network().list_network_security_groups,
        get_fn=lambda: clients.network().get_network_security_group,
        fields=(*_ID, "vcn_id", "created=time_created"),
        note="Network security group. Its rules are a separate call, not a field.",
    ),
    "route_table": ResourceKind(
        service="network",
        list_fn=lambda: clients.network().list_route_tables,
        get_fn=lambda: clients.network().get_route_table,
        fields=(*_ID, "vcn_id", "route_rules", "created=time_created"),
    ),
    "internet_gateway": ResourceKind(
        service="network",
        list_fn=lambda: clients.network().list_internet_gateways,
        get_fn=lambda: clients.network().get_internet_gateway,
        fields=(*_ID, "vcn_id", "is_enabled", "created=time_created"),
    ),
    "nat_gateway": ResourceKind(
        service="network",
        list_fn=lambda: clients.network().list_nat_gateways,
        get_fn=lambda: clients.network().get_nat_gateway,
        fields=(*_ID, "vcn_id", "nat_ip", "block_traffic", "created=time_created"),
    ),
    "service_gateway": ResourceKind(
        service="network",
        list_fn=lambda: clients.network().list_service_gateways,
        get_fn=lambda: clients.network().get_service_gateway,
        fields=(*_ID, "vcn_id", "block_traffic", "route_table_id"),
    ),
    "drg": ResourceKind(
        service="network",
        list_fn=lambda: clients.network().list_drgs,
        get_fn=lambda: clients.network().get_drg,
        fields=(*_ID, "created=time_created", "compartment_id"),
    ),
    "dhcp_options": ResourceKind(
        service="network",
        list_fn=lambda: clients.network().list_dhcp_options,
        get_fn=lambda: clients.network().get_dhcp_options,
        fields=(*_ID, "vcn_id", "options", "domain_name_type"),
    ),
    "public_ip": ResourceKind(
        service="network",
        list_fn=lambda: clients.network().list_public_ips,
        get_fn=lambda: clients.network().get_public_ip,
        fields=(*_ID, "ip_address", "private_ip_id", "scope", "assigned_entity_type"),
        list_kwargs={"scope": "REGION"},
        note="Defaults to REGION scope; ephemeral IPs are AD-scoped and not listed.",
    ),
    "load_balancer": ResourceKind(
        service="network",
        list_fn=lambda: clients.load_balancer().list_load_balancers,
        get_fn=lambda: clients.load_balancer().get_load_balancer,
        fields=(*_ID, "shape=shape_name", "ip_addresses", "subnet_ids",
                "is_private", "created=time_created"),
    ),

    # -------------------------------------------------------------------- oke
    "cluster": ResourceKind(
        service="oke",
        list_fn=lambda: clients.container_engine().list_clusters,
        get_fn=lambda: clients.container_engine().get_cluster,
        fields=("name", "ocid=id", "state=lifecycle_state", "k8s_version=kubernetes_version",
                "vcn_id", "type", "endpoint=endpoints", "compartment_id"),
        note="OKE cluster. NOT indexed by Resource Search, so oci_search will "
             "never return one: use oci_list.",
    ),
    "node_pool": ResourceKind(
        service="oke",
        list_fn=lambda: clients.container_engine().list_node_pools,
        get_fn=lambda: clients.container_engine().get_node_pool,
        fields=("name", "ocid=id", "state=lifecycle_state", "cluster_id",
                "k8s_version=kubernetes_version", "shape=node_shape",
                "size=node_config_details.size", "compartment_id"),
    ),
    "virtual_node_pool": ResourceKind(
        service="oke",
        list_fn=lambda: clients.container_engine().list_virtual_node_pools,
        get_fn=lambda: clients.container_engine().get_virtual_node_pool,
        fields=("name=display_name", "ocid=id", "state=lifecycle_state",
                "cluster_id", "size", "compartment_id"),
    ),

    # --------------------------------------------------------------- database
    "autonomous_database": ResourceKind(
        service="database",
        list_fn=lambda: clients.database().list_autonomous_databases,
        get_fn=lambda: clients.database().get_autonomous_database,
        fields=(*_ID, "db_name", "workload=db_workload", "version=db_version",
                "ocpus=cpu_core_count", "storage_tb=data_storage_size_in_tbs",
                "is_free_tier", "created=time_created"),
        note="Autonomous Database (ATP/ADW/AJD).",
    ),
    "db_system": ResourceKind(
        service="database",
        list_fn=lambda: clients.database().list_db_systems,
        get_fn=lambda: clients.database().get_db_system,
        fields=(*_ID, "shape", "version=version", "edition=database_edition",
                "node_count", "ad=availability_domain", "storage_gb=data_storage_size_in_gbs",
                "created=time_created"),
        note="Base Database Service DB system (VM/BM/Exadata).",
    ),
    "db_home": ResourceKind(
        service="database",
        list_fn=lambda: clients.database().list_db_homes,
        get_fn=lambda: clients.database().get_db_home,
        fields=(*_ID, "db_system_id", "version=db_version", "created=time_created"),
    ),
    "db_node": ResourceKind(
        service="database",
        list_fn=lambda: clients.database().list_db_nodes,
        get_fn=lambda: clients.database().get_db_node,
        fields=("name=hostname", "ocid=id", "state=lifecycle_state", "db_system_id",
                "vnic_id", "ocpus=cpu_core_count", "memory_gb=memory_size_in_gbs"),
    ),
    "mysql_db_system": ResourceKind(
        service="database",
        list_fn=lambda: clients.mysql().list_db_systems,
        get_fn=lambda: clients.mysql().get_db_system,
        fields=(*_ID, "shape=shape_name", "version=mysql_version",
                "storage_gb=data_storage_size_in_gbs", "ad=availability_domain",
                "endpoints", "created=time_created"),
        note="MySQL HeatWave is a separate service from Base Database.",
    ),
    "nosql_table": ResourceKind(
        service="database",
        list_fn=lambda: clients.nosql().list_tables,
        get_fn=lambda: clients.nosql().get_table,
        fields=("name", "ocid=id", "state=lifecycle_state", "created=time_created",
                "compartment_id"),
    ),

    # --------------------------------------------------------- object storage
    "bucket": ResourceKind(
        service="object_storage",
        list_fn=lambda: clients.objectstorage().list_buckets,
        get_fn=lambda: clients.objectstorage().get_bucket,
        fields=("name", "namespace", "created=time_created", "etag", "compartment_id"),
        needs_namespace=True,
        get_by_name=True,
        note="Buckets are addressed by NAME, not OCID. oci_get('bucket', 'my-bucket').",
    ),

    # --------------------------------------------------------------- identity
    "compartment": ResourceKind(
        service="identity",
        list_fn=lambda: clients.identity().list_compartments,
        get_fn=lambda: clients.identity().get_compartment,
        fields=("name", "ocid=id", "state=lifecycle_state", "description",
                "compartment_id", "created=time_created"),
    ),
    "user": ResourceKind(
        service="identity",
        list_fn=lambda: clients.identity().list_users,
        get_fn=lambda: clients.identity().get_user,
        fields=("name", "ocid=id", "state=lifecycle_state", "email",
                "is_mfa_activated", "created=time_created"),
    ),
    "group": ResourceKind(
        service="identity",
        list_fn=lambda: clients.identity().list_groups,
        get_fn=lambda: clients.identity().get_group,
        fields=("name", "ocid=id", "state=lifecycle_state", "description"),
    ),
    "policy": ResourceKind(
        service="identity",
        list_fn=lambda: clients.identity().list_policies,
        get_fn=lambda: clients.identity().get_policy,
        fields=("name", "ocid=id", "state=lifecycle_state", "statements",
                "description", "created=time_created"),
    ),
    "availability_domain": ResourceKind(
        service="identity",
        list_fn=lambda: clients.identity().list_availability_domains,
        fields=("name", "ocid=id"),
        scope="tenancy",
        paginated=False,
        note="Identical for every compartment in a region. No get: list and filter.",
    ),
    "region": ResourceKind(
        service="identity",
        list_fn=lambda: clients.identity().list_regions,
        fields=("name", "key"),
        scope="global",
        paginated=False,
        note="Tenancy-wide; ignores any compartment argument.",
    ),
}

RESOURCE_TYPES: tuple[str, ...] = tuple(REGISTRY)


def kind(resource_type: str) -> ResourceKind:
    try:
        return REGISTRY[resource_type]
    except KeyError:
        raise KeyError(
            f"Unknown resource_type {resource_type!r}. "
            f"Supported: {', '.join(RESOURCE_TYPES)}"
        ) from None


def by_service() -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for name, spec in REGISTRY.items():
        grouped.setdefault(spec.service, []).append(name)
    return grouped
