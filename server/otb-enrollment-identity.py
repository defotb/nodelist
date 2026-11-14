#!/usr/bin/env python3
"""Extract verified collector identity from an OTB observation."""

import json
from pathlib import Path

import otb_registry


def extract_identity(path, chain, collector, network):
    data = json.loads(Path(path).read_text())

    if data.get("network") != network:
        raise ValueError("Observation network mismatch")

    if data.get("collector") != collector:
        raise ValueError("Observation collector mismatch")

    nodes = data.get("nodes")

    if not isinstance(nodes, list):
        raise ValueError("Invalid observation nodes")

    local = [
        node for node in nodes
        if isinstance(node, dict)
        and node.get("collector") is True
    ]

    if len(local) != 1:
        raise ValueError(
            "Exactly one local collector node required"
        )

    enode = local[0].get("enode")

    # Existing registry library validates the 128-character
    # public key and enode format.
    node_id = otb_registry.node_id_from_enode(enode)

    return {
        "chain": chain,
        "collector": collector,
        "enode": enode,
        "node_id": node_id
    }


if __name__ == "__main__":
    print("OTB enrollment identity helper")
    print("Import extract_identity() to validate an observation.")
