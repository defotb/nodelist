#!/usr/bin/env python3
# OTB Universal Uploader v1.0.0{etho,etica}

import argparse
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "v1.0.0{etho,etica}"

NETWORKS = {
    "etica": "ETICA",
    "etho": "ETHO"
}

DEFAULT_URL = (
    "https://nodelist.outsidethebox.top"
    "/api/v1/observations"
)

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def main():
    parser = argparse.ArgumentParser(
        description="OTB Universal Uploader " + VERSION
    )

    parser.add_argument(
        "--chain",
        required=True,
        choices=sorted(NETWORKS)
    )
    parser.add_argument("--collector", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--token-file")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate observation without uploading"
    )

    args = parser.parse_args()

    if not SAFE_NAME.fullmatch(args.collector):
        parser.error("Invalid collector name")

    if not args.url.startswith("https://"):
        parser.error("HTTPS is required")

    path = Path(args.input)
    raw = path.read_bytes()

    if not 0 < len(raw) <= 262144:
        raise RuntimeError("Invalid observation size")

    data = json.loads(raw)

    if not isinstance(data, dict):
        raise RuntimeError("Observation must be a JSON object")

    if data.get("network") != NETWORKS[args.chain]:
        raise RuntimeError("Incorrect blockchain network")

    if data.get("collector") != args.collector:
        raise RuntimeError("Collector identity mismatch")

    nodes = data.get("nodes")

    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 500:
        raise RuntimeError("Invalid node list")

    if not any(
        isinstance(node, dict)
        and node.get("collector") is True
        for node in nodes
    ):
        raise RuntimeError("Missing local collector node")

    print("OTB Uploader", VERSION)
    print("Blockchain:", args.chain)
    print("Collector:", args.collector)
    print("Nodes:", len(nodes))
    print("Observation size:", len(raw), "bytes")

    if args.check_only:
        print("Validation passed. Nothing uploaded.")
        return

    if not args.token_file:
        parser.error("--token-file is required for uploading")

    token_path = Path(args.token_file)

    if token_path.is_symlink():
        raise RuntimeError("Token file must not be a symlink")

    mode = stat.S_IMODE(token_path.stat().st_mode)

    if mode & 0o077:
        raise RuntimeError(
            "Token file permissions are too open"
        )

    token = token_path.read_text().strip()

    if not token:
        raise RuntimeError("Token file is empty")

    request = urllib.request.Request(
        args.url,
        data=raw,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request, timeout=20
        ) as response:
            result = json.load(response)
            status = response.status

    except urllib.error.HTTPError as exc:
        print(
            "Upload rejected. HTTP:",
            exc.code,
            file=sys.stderr
        )
        sys.exit(1)

    except urllib.error.URLError as exc:
        print(
            "Upload connection failed:",
            exc.reason,
            file=sys.stderr
        )
        sys.exit(1)

    print("Upload HTTP:", status)
    print("Server response:", result.get("message"))

    if status != 200:
        sys.exit(1)


if __name__ == "__main__":
    main()
