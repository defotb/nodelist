#!/usr/bin/env python3

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

VERSION = "v0.1.0{etho,etica}"

BASE = Path(os.environ.get("OTB_BASE", "/home/def/otb-node-directory"))
CONFIG = BASE / "config/chains.json"
TOKENS = BASE / "private/tokens.json"
INVITES = BASE / "private/invitations.json"
LOCK = BASE / "private/enroll.lock"
JOURNAL = BASE / "private/enroll-transaction.json"

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def save_json(path, data):
    fd, temp = tempfile.mkstemp(
        prefix=".enroll-",
        dir=str(path.parent)
    )

    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.chmod(temp, 0o600)
        os.replace(temp, path)

        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    parser = argparse.ArgumentParser(
        description="OTB Enrollment Administrator " + VERSION
    )

    parser.add_argument(
        "chain",
        choices=["etica", "etho"]
    )

    parser.add_argument("collector")

    parser.add_argument(
        "--minutes",
        type=int,
        default=15
    )

    args = parser.parse_args()

    if not SAFE_NAME.fullmatch(args.collector):
        parser.error("Invalid collector name")

    if not 1 <= args.minutes <= 120:
        parser.error("Expiration must be 1-120 minutes")

    with LOCK.open("a+") as lock:
        os.chmod(LOCK, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)

        if JOURNAL.exists():
            parser.error(
                "Pending enrollment transaction; "
                "restart enrollment server to recover"
            )

        config = load_json(CONFIG, {})["chains"]
        tokens = load_json(TOKENS, {})

        if args.chain not in config:
            parser.error("Unknown blockchain")

        if not config[args.chain].get("enabled"):
            parser.error("Blockchain disabled")

        if (
            args.collector in tokens.get(args.chain, {})
            or args.collector in
            config[args.chain].get("collectors", [])
        ):
            parser.error("Collector already registered")

        invitations = load_json(INVITES, {})

        now = datetime.now(timezone.utc)

        invitations = {
            key: value
            for key, value in invitations.items()
            if datetime.fromisoformat(
                value["expires_at"]
            ) > now
        }

        code = secrets.token_urlsafe(32)
        code_hash = hashlib.sha256(
            code.encode()
        ).hexdigest()

        expires = now + timedelta(
            minutes=args.minutes
        )

        invitations[code_hash] = {
            "chain": args.chain,
            "collector": args.collector,
            "expires_at": expires.isoformat()
        }

        save_json(INVITES, invitations)

    print()
    print("OTB Collector Enrollment", VERSION)
    print("Blockchain:", args.chain)
    print("Collector:", args.collector)
    print("Expires:", expires.isoformat())
    print()
    print("ONE-TIME ENROLLMENT CODE:")
    print(code)
    print()
    print("Keep this code private.")


if __name__ == "__main__":
    main()
