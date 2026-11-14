#!/usr/bin/env python3
# OTB Universal Collector Runner v1.0.0{etho,etica}

import argparse
import json
import subprocess
import sys
from pathlib import Path

VERSION = "v1.0.0{etho,etica}"

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(
        description="OTB Collector Runner " + VERSION
    )

    parser.add_argument("--config", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text())

    chain = config["chain"]
    collector = config["collector"]
    ipc = config["ipc"]
    output = config["output"]

    print("OTB Collector Runner", VERSION, flush=True)
    print("Chain:", chain, flush=True)
    print("Collector:", collector, flush=True)

    collect = [
        sys.executable,
        str(HERE / "otb-collect.py"),
        "--chain", chain,
        "--collector", collector,
        "--ipc", ipc,
        "--output", output
    ]

    if config.get("advertise_ip"):
        collect.extend([
            "--advertise-ip",
            config["advertise_ip"]
        ])

    subprocess.run(collect, check=True)

    push = [
        sys.executable,
        str(HERE / "otb-push.py"),
        "--chain", chain,
        "--collector", collector,
        "--input", output
    ]

    if args.check_only:
        push.append("--check-only")
    else:
        push.extend([
            "--token-file",
            config["token_file"]
        ])

    subprocess.run(push, check=True)

    print("Collector cycle completed.", flush=True)


if __name__ == "__main__":
    main()
