#!/usr/bin/env python3
# OTB Universal Collector v1.0.0{etho,etica}

import argparse
import datetime
import json
import os
import re
import socket
import tempfile
from pathlib import Path

VERSION = "v1.0.0{etho,etica}"

NETWORKS = {
    "etica": ("ETICA", "61803"),
    "etho": ("ETHO", "1313114"),
}

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def rpc(ipc, method, params=None):
    request = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params if params is not None else [],
        "id": 1
    }).encode() + b"\n"

    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(10)
        sock.connect(ipc)
        sock.sendall(request)

        response = b""

        while b"\n" not in response:
            chunk = sock.recv(65536)
            if not chunk:
                raise RuntimeError("IPC connection closed")
            response += chunk

            if len(response) > 8 * 1024 * 1024:
                raise RuntimeError("RPC response too large")

    result = json.loads(response.split(b"\n", 1)[0])

    if result.get("error"):
        raise RuntimeError(str(result["error"]))

    return result["result"]


def hexint(value):
    if value is None:
        return None
    if isinstance(value, str):
        return int(value, 16)
    return int(value)


def main():
    parser = argparse.ArgumentParser(
        description="OTB Universal Collector " + VERSION
    )

    parser.add_argument(
        "--chain", required=True,
        choices=sorted(NETWORKS)
    )
    parser.add_argument("--collector", required=True)
    parser.add_argument("--ipc", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--advertise-ip")

    args = parser.parse_args()

    if not SAFE_NAME.fullmatch(args.collector):
        parser.error("Invalid collector name")

    network_name, expected_id = NETWORKS[args.chain]

    actual_id = str(rpc(args.ipc, "net_version"))

    if actual_id != expected_id:
        raise RuntimeError(
            "Wrong blockchain network: expected %s, got %s"
            % (expected_id, actual_id)
        )

    node = rpc(args.ipc, "admin_nodeInfo")
    peers = rpc(args.ipc, "admin_peers")

    height = hexint(rpc(args.ipc, "eth_blockNumber"))
    syncing = rpc(args.ipc, "eth_syncing")
    head = rpc(
        args.ipc, "eth_getBlockByNumber",
        ["latest", False]
    )

    if head is None:
        raise RuntimeError("Geth returned no latest block")

    enode = node.get("enode", "")

    # Optional correction of a locally advertised address.
    if args.advertise_ip and enode:
        enode = re.sub(
            r"@(?:127\.0\.0\.1|0\.0\.0\.0|localhost):",
            "@" + args.advertise_ip + ":",
            enode,
            count=1
        )

    local_node = {
        "name": args.collector,
        "id": node.get("id"),
        "enode": enode,
        "client": node.get("name"),
        "collector": True,
        "connected": True,
        "block_height": height,
        "head_hash": head.get("hash"),
        "total_difficulty": hexint(
            head.get("totalDifficulty")
        ),
        "block_timestamp": hexint(
            head.get("timestamp")
        ),
        "syncing": syncing,
        "sync_status": (
            "syncing" if syncing is not False
            else "unverified"
        ),
        "chain_verified": False
    }

    nodes = [local_node]
    head_cache = {}

    for peer in peers:
        network = peer.get("network") or {}
        protocols = peer.get("protocols") or {}

        if not isinstance(network, dict):
            network = {}

        if not isinstance(protocols, dict):
            protocols = {}

        eth = protocols.get("eth") or {}

        # Geth may report protocol handshake errors as strings.
        # Preserve the peer but treat its ETH details as unknown.
        if not isinstance(eth, dict):
            eth = {}

        peer_head = eth.get("head")
        peer_height = None

        if peer_head:
            if peer_head not in head_cache:
                try:
                    block = rpc(
                        args.ipc,
                        "eth_getBlockByHash",
                        [peer_head, False]
                    )
                    head_cache[peer_head] = (
                        hexint(block["number"])
                        if block else None
                    )
                except Exception:
                    head_cache[peer_head] = None

            peer_height = head_cache[peer_head]

        nodes.append({
            "name": peer.get("name"),
            "id": peer.get("id"),
            "enode": peer.get("enode"),
            "client": peer.get("name"),
            "network": network,
            "protocols": protocols,
            "collector": False,
            "connected": True,
            "block_height": peer_height,
            "head_hash": peer_head,
            "height_source": (
                "peer_advertised_head"
                if peer_height is not None else None
            ),
            "total_difficulty": eth.get("difficulty"),
            "syncing": None,
            "sync_status": "unverified",
            "chain_verified": False
        })

    result = {
        "network": network_name,
        "collector": args.collector,
        "timestamp": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "total_nodes": len(nodes),
        "connected_peers": len(peers),
        "collector_height": height,
        "collector_syncing": syncing,
        "collector_head_hash": head.get("hash"),
        "nodes": nodes
    }

    output = Path(args.output)

    if not output.parent.is_dir():
        raise RuntimeError(
            "Output directory does not exist: "
            + str(output.parent)
        )

    fd, temp = tempfile.mkstemp(
        prefix=".otb-",
        dir=str(output.parent)
    )

    try:
        with os.fdopen(fd, "w") as f:
            json.dump(result, f, indent=2)
            f.write("\n")

        os.chmod(temp, 0o600)
        os.replace(temp, output)

    finally:
        if os.path.exists(temp):
            os.unlink(temp)

    print("OTB Collector", VERSION)
    print("Blockchain:", network_name)
    print("Collector:", args.collector)
    print("Network ID:", actual_id)
    print("Block height:", height)
    print("Syncing:", syncing)
    print("Connected peers:", len(peers))
    print("Total nodes:", len(nodes))
    print("Saved:", output)


if __name__ == "__main__":
    main()
