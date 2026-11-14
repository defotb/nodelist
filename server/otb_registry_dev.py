#!/usr/bin/env python3
"""OTB collector registration and identity helpers."""

import copy
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path("/home/def/otb-node-directory")
STATUS = BASE / "private/collector-status.json"

VALID_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
VALID_NODE_ID = re.compile(r"^[0-9a-fA-F]{128}$")

VALID_STATES = {
    "pending",
    "enabled",
    "suspended",
    "revoked",
}


def normalize_node_id(value):
    """Return canonical Geth node ID (uncompressed public key)."""
    if not isinstance(value, str):
        raise ValueError("Node ID must be a string")

    if not VALID_NODE_ID.fullmatch(value):
        raise ValueError("Invalid Geth node ID")

    return value.lower()



def node_id_from_enode(enode):
    """Extract the stable public-key identity from an enode URL."""
    if not isinstance(enode, str):
        raise ValueError("Enode must be a string")

    if not enode.startswith("enode://"):
        raise ValueError("Invalid enode URL")

    address = enode[len("enode://"):]

    if "@" not in address:
        raise ValueError("Enode has no network address")

    public_key, network_address = address.split("@", 1)

    if not network_address:
        raise ValueError("Enode network address missing")

    return normalize_node_id(public_key)


def load_registry(path=STATUS):
    """Read and validate the collector status registry."""
    data = json.loads(Path(path).read_text())

    if data.get("version") != 1:
        raise ValueError("Unsupported registry version")

    chains = data.get("collectors")

    if not isinstance(chains, dict):
        raise ValueError("Invalid collector registry")

    for chain, collectors in chains.items():
        if not VALID_NAME.fullmatch(chain):
            raise ValueError("Invalid blockchain name")

        if not isinstance(collectors, dict):
            raise ValueError("Invalid blockchain collector entries")

        identities = set()

        for name, record in collectors.items():
            if not VALID_NAME.fullmatch(name):
                raise ValueError("Invalid collector name")

            if not isinstance(record, dict):
                raise ValueError("Invalid collector record")

            if record.get("status") not in VALID_STATES:
                raise ValueError("Invalid collector status")

            node_id = record.get("node_id")

            # Legacy collectors do not yet have node IDs.
            if node_id is None:
                continue

            node_id = normalize_node_id(node_id)

            # Revoked identities remain permanently reserved.
            if node_id in identities:
                raise ValueError(
                    "Duplicate active node identity: " + chain
                )

            identities.add(node_id)

    return data


def find_node(registry, chain, node_id):
    """Find an existing registration, including revoked identities."""
    node_id = normalize_node_id(node_id)

    collectors = registry["collectors"].get(chain, {})

    for name, record in collectors.items():
        existing = record.get("node_id")

        if existing is not None:
            if normalize_node_id(existing) == node_id:
                return name, record

    return None


def registration_available(registry, chain, collector, node_id):
    """Check that neither collector name nor node ID is taken."""
    node_id = normalize_node_id(node_id)

    if not VALID_NAME.fullmatch(chain):
        raise ValueError("Invalid blockchain name")

    if not VALID_NAME.fullmatch(collector):
        raise ValueError("Invalid collector name")

    existing = registry["collectors"].get(chain, {})

    if collector in existing:
        return False, "Collector name already registered"

    match = find_node(registry, chain, node_id)

    if match is not None:
        return False, "Node already registered as " + match[0]

    return True, "Available"


def prepare_provisional_registration(
    registry, chain, collector, enode, now=None
):
    """Prepare a provisional registration without writing files."""
    node_id = node_id_from_enode(enode)

    if chain not in registry["collectors"]:
        raise ValueError("Unknown blockchain")

    available, reason = registration_available(
        registry, chain, collector, node_id
    )

    if not available:
        raise ValueError(reason)

    if now is None:
        now = datetime.now(timezone.utc)

    if now.tzinfo is None:
        raise ValueError("Registration time requires timezone")

    expires = now + timedelta(hours=24)
    token = secrets.token_urlsafe(48)

    record = {
        "status": "pending",
        "node_id": node_id,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "last_action": "provisional_registration"
    }

    return record, token


def stage_provisional_registration(
    registry, tokens, config, chain, collector, enode, now=None
):
    """Prepare coordinated registration updates in memory.

    Does not modify inputs or write files.
    """
    if chain not in config["chains"]:
        raise ValueError("Unknown blockchain")

    settings = config["chains"][chain]

    if not settings.get("enabled"):
        raise ValueError("Blockchain disabled")

    if collector in settings["collectors"]:
        raise ValueError("Collector already approved")

    if collector in tokens.get(chain, {}):
        raise ValueError("Collector already has credentials")

    new_registry = copy.deepcopy(registry)
    new_tokens = copy.deepcopy(tokens)
    new_config = copy.deepcopy(config)

    record, token = prepare_provisional_registration(
        new_registry, chain, collector, enode, now
    )

    new_registry["collectors"][chain][collector] = record
    new_tokens.setdefault(chain, {})[collector] = token

    return {
        "registry": new_registry,
        "tokens": new_tokens,
        "config": new_config,
        "token": token
    }
