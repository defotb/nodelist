#!/usr/bin/env python3
"""OTB Pending Node Explorer publisher — development version."""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import otb_registry

BASE = Path(__file__).resolve().parent
TEST = BASE / "pending-test"

INCOMING = TEST / "incoming"
OUTPUT = TEST / "feeds"
REGISTRY = TEST / "registration/collector-status.json"
CONFIG = BASE / "config/chains.json"

MAX_AGE = 180
NODE_ID = re.compile(r"^[0-9a-fA-F]{64}$")

FIELDS = (
    "id", "enode", "client", "collector", "connected",
    "name", "block_height", "head_hash",
    "height_source", "sync_status", "protocols"
)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp = tempfile.mkstemp(
        prefix=".pending-",
        dir=str(path.parent)
    )

    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, separators=(",", ":"))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.chmod(temp, 0o644)
        os.replace(temp, path)

    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def valid_observation(data, chain, collector, network):
    if not isinstance(data, dict):
        return False

    if (
        data.get("chain") != chain
        or data.get("collector") != collector
        or data.get("network") != network
    ):
        return False

    try:
        received = datetime.fromisoformat(
            data["received_at"].replace("Z", "+00:00")
        )

        if received.tzinfo is None:
            return False

        age = (
            datetime.now(timezone.utc) - received
        ).total_seconds()

        if not -300 <= age <= MAX_AGE:
            return False

        nodes = data["nodes"]

        if not isinstance(nodes, list) or not nodes:
            return False

        if len(nodes) > 500:
            return False

        if sum(
            n.get("collector") is True
            for n in nodes if isinstance(n, dict)
        ) != 1:
            return False

        ids = set()

        for node in nodes:
            if not isinstance(node, dict):
                return False

            node_id = node.get("id")

            if (
                not isinstance(node_id, str)
                or not NODE_ID.fullmatch(node_id)
            ):
                return False

            normalized = node_id.lower()

            if normalized in ids:
                return False

            ids.add(normalized)

            enode = node.get("enode")

            try:
                otb_registry.node_id_from_enode(enode)
            except ValueError:
                return False

        return True

    except (KeyError, ValueError, TypeError):
        return False


def publish_chain(chain, settings, records):
    output = OUTPUT / chain
    output.mkdir(parents=True, exist_ok=True)

    sources = []
    merged = {}
    edges = set()
    active_files = set()

    now = datetime.now(timezone.utc)

    for collector, record in records.items():
        if record.get("status") != "pending":
            continue

        try:
            expires = datetime.fromisoformat(
                record["expires_at"]
            )

            if expires.tzinfo is None or now >= expires:
                continue

        except (KeyError, ValueError, TypeError):
            continue

        path = INCOMING / chain / (collector + ".json")

        if not path.is_file():
            continue

        try:
            observation = json.loads(path.read_text())
        except (ValueError, OSError):
            continue

        if not valid_observation(
            observation, chain, collector,
            settings["network"]
        ):
            continue

        nodes = [
            {key: node[key] for key in FIELDS if key in node}
            for node in observation["nodes"]
        ]

        local = next(
            n for n in nodes if n.get("collector") is True
        )

        # The collector's observed Geth identity must match
        # the identity bound to its registration.
        try:
            observed_id = otb_registry.node_id_from_enode(
                local.get("enode")
            )
        except ValueError:
            print(chain, collector, "invalid local enode")
            continue

        if observed_id != record.get("node_id"):
            print(chain, collector, "node identity mismatch")
            continue

        connected = [
            n for n in nodes
            if not n.get("collector")
            and n.get("connected") is True
        ]

        individual = {
            "chain": chain,
            "network": settings["network"],
            "collector": collector,
            "status": "pending",
            "timestamp": observation["timestamp"],
            "total_nodes": len(nodes),
            "connected_peers": len(connected),
            "nodes": nodes
        }

        save_json(output / (collector + ".json"), individual)
        active_files.add(collector + ".json")
        sources.append(collector)

        for node in nodes:
            merged[node["id"]] = node

        for peer in connected:
            edges.add((local["id"], peer["id"]))

    combined = {
        "chain": chain,
        "network": settings["network"],
        "collector": "All pending collectors",
        "status": "pending",
        "timestamp": now.isoformat(),
        "sources": sorted(sources),
        "total_nodes": len(merged),
        "connected_peers": sum(
            1 for n in merged.values()
            if n.get("connected") is True
            and not n.get("collector")
        ),
        "nodes": list(merged.values()),
        "edges": [
            {"from": a, "to": b}
            for a, b in sorted(edges)
        ]
    }

    save_json(output / "all.json", combined)

    # Remove obsolete individual pending feeds.
    for path in output.glob("*.json"):
        if path.name == "all.json":
            continue

        if path.name not in active_files:
            path.unlink()

    print(
        chain.upper(),
        "pending collectors:", len(sources),
        "nodes:", len(merged)
    )


def main():
    if not REGISTRY.is_file():
        raise SystemExit(
            "STOP: Test registry missing — no feeds modified"
        )

    registry = otb_registry.load_registry(REGISTRY)
    config = json.loads(CONFIG.read_text())["chains"]

    for chain, settings in config.items():
        publish_chain(
            chain,
            settings,
            registry["collectors"].get(chain, {})
        )


if __name__ == "__main__":
    main()
