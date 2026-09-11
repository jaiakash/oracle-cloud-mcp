"""Lazy, cached OCI service clients.

Clients are built on first use rather than at import: constructing every service
client up front is slow, and it would make the whole server fail to start when
any single service is misconfigured.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import oci

from .config import settings


class ConfigError(RuntimeError):
    """Raised when ~/.oci/config cannot be used as-is."""


@cache
def auth() -> tuple[dict[str, Any], Any]:
    """Return (config, signer). Signer is None for plain API-key auth.

    Supports API-key and session-token (`oci session authenticate`) profiles.
    Instance/resource principals would slot in here as additional branches
    without touching any caller.
    """
    s = settings()
    try:
        config = oci.config.from_file(profile_name=s.profile)
    except oci.exceptions.ConfigFileNotFound as exc:
        raise ConfigError(
            "No OCI config file found. Run `oci setup config` to create one."
        ) from exc
    except oci.exceptions.ProfileNotFound as exc:
        raise ConfigError(
            f"Profile [{s.profile}] not found in your OCI config. "
            "Set OCI_CLI_PROFILE to a profile that exists."
        ) from exc

    if s.region:
        config["region"] = s.region

    token_file = config.get("security_token_file")
    if token_file:
        # Session-token profile: the signer carries the token, so the config
        # intentionally lacks the fingerprint/user that validate_config wants.
        try:
            token = Path(token_file).expanduser().read_text().strip()
            private_key = oci.signer.load_private_key_from_file(config["key_file"])
        except (OSError, KeyError) as exc:
            raise ConfigError(
                f"Profile [{s.profile}] looks like a session-token profile but its "
                f"token or key file is unreadable: {exc}. "
                "Re-authenticate with `oci session authenticate`."
            ) from exc
        return config, oci.auth.signers.SecurityTokenSigner(token, private_key)

    try:
        oci.config.validate_config(config)
    except oci.exceptions.InvalidConfig as exc:
        raise ConfigError(
            f"Profile [{s.profile}] is invalid: {exc}. "
            "Check the user, tenancy, fingerprint and key_file entries."
        ) from exc
    return config, None


def config() -> dict[str, Any]:
    return auth()[0]


def _kwargs() -> dict[str, Any]:
    cfg, signer = auth()
    return {"config": cfg} if signer is None else {"config": cfg, "signer": signer}


@cache
def identity() -> oci.identity.IdentityClient:
    return oci.identity.IdentityClient(**_kwargs())


@cache
def compute() -> oci.core.ComputeClient:
    return oci.core.ComputeClient(**_kwargs())


@cache
def network() -> oci.core.VirtualNetworkClient:
    return oci.core.VirtualNetworkClient(**_kwargs())


@cache
def blockstorage() -> oci.core.BlockstorageClient:
    return oci.core.BlockstorageClient(**_kwargs())


@cache
def objectstorage() -> oci.object_storage.ObjectStorageClient:
    return oci.object_storage.ObjectStorageClient(**_kwargs())


@cache
def container_engine() -> oci.container_engine.ContainerEngineClient:
    return oci.container_engine.ContainerEngineClient(**_kwargs())


@cache
def search() -> oci.resource_search.ResourceSearchClient:
    return oci.resource_search.ResourceSearchClient(**_kwargs())


@cache
def database() -> oci.database.DatabaseClient:
    """Base Database: Autonomous DB, DB Systems, Exadata."""
    return oci.database.DatabaseClient(**_kwargs())


@cache
def mysql() -> oci.mysql.DbSystemClient:
    """MySQL HeatWave is a separate service from Base Database."""
    return oci.mysql.DbSystemClient(**_kwargs())


@cache
def nosql() -> oci.nosql.NosqlClient:
    return oci.nosql.NosqlClient(**_kwargs())


@cache
def load_balancer() -> oci.load_balancer.LoadBalancerClient:
    return oci.load_balancer.LoadBalancerClient(**_kwargs())


@cache
def os_namespace() -> str:
    """Object Storage namespace for this tenancy. Cached; never a tool parameter."""
    return objectstorage().get_namespace().data


def tenancy_id() -> str:
    return config()["tenancy"]


def region() -> str:
    return config()["region"]


def auth_method() -> str:
    return "security_token" if auth()[1] is not None else "api_key"


@cache
def availability_domains(compartment_id: str) -> tuple[str, ...]:
    """AD names for a compartment.

    A few list APIs (notably list_boot_volume_attachments) are AD-scoped rather
    than compartment-scoped, so callers must fan out across these.
    """
    response = identity().list_availability_domains(compartment_id=compartment_id)
    return tuple(ad.name for ad in response.data)
