#!/usr/bin/env python3
"""Publish safe, public blockchain and collector configuration."""

import json
import os
import re
import tempfile
from pathlib import Path

BASE = Path("/home/def/otb-node-directory")
SOURCE = BASE / "config/chains.json"
TARGET = Path("/var/www/nodelist.outsidethebox.top/feeds/chains.json")

config = json.loads(SOURCE.read_text())
public = {"chains": {}}

valid_id = re.compile(r"^[A-Za-z0-9._-]+$")

for chain_id, chain in config["chains"].items():
    if not chain.get("enabled", False):
        continue

    if not valid_id.fullmatch(chain_id):
        raise SystemExit("Invalid blockchain ID: " + chain_id)

    collectors = chain["collectors"]

    if not isinstance(collectors, list):
        raise SystemExit("Invalid collectors for: " + chain_id)

    for collector in collectors:
        if not isinstance(collector, str) or not valid_id.fullmatch(collector):
            raise SystemExit("Invalid collector ID")

    public["chains"][chain_id] = {
        "name": chain["name"],
        "collectors": collectors
    }

if not public["chains"]:
    raise SystemExit("No enabled blockchains; unchanged")

fd, temporary = tempfile.mkstemp(
    prefix=".chains-",
    dir=str(TARGET.parent)
)

try:
    with os.fdopen(fd, "w") as f:
        json.dump(public, f, indent=2)
        f.write("\n")

    os.chmod(temporary, 0o644)
    os.replace(temporary, TARGET)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)

print("Public blockchain configuration published")
for chain_id, chain in public["chains"].items():
    print(chain_id, ":", len(chain["collectors"]), "collectors")
