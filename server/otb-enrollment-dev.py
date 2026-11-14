#!/usr/bin/env python3

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile

import otb_registry_dev as otb_registry
import otb_consistency_dev
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

VERSION = "v1.0.0{etho,etica}"

BASE = (
    Path(__file__).resolve().parent / "pending-test"
).resolve()
REGISTRATION = BASE / "registration"

CONFIG = REGISTRATION / "chains.json"
TOKENS = REGISTRATION / "tokens.json"
INVITES = REGISTRATION / "invitations.json"
LOCK = REGISTRATION / "enroll.lock"
JOURNAL = REGISTRATION / "enroll-transaction.json"
RECEIPTS = REGISTRATION / "uninstall-receipts.json"
STATUS = REGISTRATION / "collector-status.json"

WEB = BASE / "approved-feeds"

HOST = "127.0.0.1"
PORT = 18769
MAX_SIZE = 4096

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, data):
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




def sync_directory(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def recover_pending():
    if not JOURNAL.exists():
        return

    transaction = read_json(JOURNAL)

    for key in ("tokens", "config", "invitations"):
        if key not in transaction:
            raise RuntimeError("Incomplete transaction journal")

    removal = transaction.get("removal")

    if removal is not None:
        if not isinstance(removal, dict):
            raise RuntimeError("Invalid removal journal")

        chain = removal.get("chain")
        collector = removal.get("collector")
        scope = removal.get("scope", "approved")

        if scope not in ("approved", "pending"):
            raise RuntimeError("Invalid removal scope")

        if (
            not isinstance(chain, str)
            or not isinstance(collector, str)
            or not SAFE_NAME.fullmatch(chain)
            or not SAFE_NAME.fullmatch(collector)
            or chain in (".", "..")
            or collector in (".", "..")
        ):
            raise RuntimeError("Invalid removal journal")

    receipts = transaction.get("receipts")

    if receipts is not None and not isinstance(receipts, dict):
        raise RuntimeError("Invalid receipt journal")

    registry = transaction.get("registry")

    if registry is not None:
        if not isinstance(registry, dict):
            raise RuntimeError("Invalid collector-status journal")

        # Validate a temporary copy without touching live status.
        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                prefix=".validate-registry-",
                suffix=".json",
                dir=str(REGISTRATION),
                delete=False
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(registry, handle)
                handle.flush()
                os.fsync(handle.fileno())

            otb_registry.load_registry(temporary_path)

            otb_consistency_dev.validate(
                transaction["tokens"],
                transaction["config"],
                registry
            )

        except (ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError(
                "Invalid collector-status journal"
            ) from exc

        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    write_json(TOKENS, transaction["tokens"])
    write_json(CONFIG, transaction["config"])
    write_json(INVITES, transaction["invitations"])

    if registry is not None:
        write_json(STATUS, registry)

    if receipts is not None:
        write_json(RECEIPTS, receipts)

    if removal is not None:
        if scope == "pending":
            incoming_dir = BASE / "incoming" / chain
            public_dir = BASE / "feeds" / chain
        else:
            incoming_dir = BASE / "approved-incoming" / chain
            public_dir = WEB / chain

        for directory in (incoming_dir, public_dir):
            target = directory / (collector + ".json")

            if directory.is_dir():
                target.unlink(missing_ok=True)
                sync_directory(directory)

    JOURNAL.unlink()
    sync_directory(JOURNAL.parent)

    print("Recovered pending transaction", flush=True)


class Handler(BaseHTTPRequestHandler):

    def reply(self, status, data):
        body = json.dumps(data).encode()

        self.send_response(status)
        self.send_header(
            "Content-Type", "application/json"
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/health":
            return self.reply(
                404, {"error": "Not found"}
            )

        return self.reply(200, {
            "status": "ready",
            "version": VERSION
        })

    def do_POST(self):
        if self.path == "/api/v1/unenroll":
            return self.do_unenroll()

        if self.path != "/api/v1/enroll":
            return self.reply(
                404, {"error": "Not found"}
            )

        try:
            size = int(
                self.headers.get("Content-Length", "0")
            )

            if not 1 <= size <= MAX_SIZE:
                return self.reply(
                    413, {"error": "Invalid request size"}
                )

            if self.headers.get(
                "Content-Type", ""
            ).split(";")[0].strip().lower() != "application/json":
                return self.reply(
                    415, {"error": "JSON required"}
                )

            data = json.loads(self.rfile.read(size))

            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")

            code = data.get("code")

            if (
                not isinstance(code, str)
                or not 20 <= len(code) <= 256
            ):
                return self.reply(
                    403, {"error": "Invalid invitation"}
                )

            code_hash = hashlib.sha256(
                code.encode()
            ).hexdigest()

            with LOCK.open("a+") as lock:
                os.chmod(LOCK, 0o600)
                fcntl.flock(lock, fcntl.LOCK_EX)

                recover_pending()
                invitations = read_json(INVITES)
                invitation = invitations.get(code_hash)

                if invitation is None:
                    return self.reply(
                        403, {"error": "Invalid invitation"}
                    )

                expires = datetime.fromisoformat(
                    invitation["expires_at"]
                )

                if (
                    expires.tzinfo is None
                    or datetime.now(timezone.utc) >= expires
                ):
                    return self.reply(
                        403, {"error": "Invitation expired"}
                    )

                chain = invitation["chain"]
                collector = invitation["collector"]

                if not SAFE_NAME.fullmatch(collector):
                    raise ValueError(
                        "Invalid collector identity"
                    )

                config = read_json(CONFIG)
                tokens = read_json(TOKENS)
                registry = otb_registry.load_registry(STATUS)

                chains = config["chains"]

                if (
                    chain not in chains
                    or not chains[chain].get("enabled")
                ):
                    return self.reply(
                        403, {"error": "Blockchain unavailable"}
                    )

                if (
                    collector in tokens.get(chain, {})
                    or collector in
                    chains[chain].get("collectors", [])
                    or collector in
                    registry["collectors"].get(chain, {})
                ):
                    return self.reply(
                        409, {"error": "Collector already registered"}
                    )

                # Unique credential for this chain/collector.
                token = secrets.token_urlsafe(48)

                tokens.setdefault(chain, {})
                tokens[chain][collector] = token

                chains[chain]["collectors"].append(
                    collector
                )

                now = datetime.now(timezone.utc).isoformat()

                registry["collectors"][chain][collector] = {
                    "status": "enabled",
                    "node_id": None,
                    "updated_at": now,
                    "last_action": "invitation_enrollment"
                }

                del invitations[code_hash]

                # All changes are made under one file lock.
                # Each file is written by atomic replacement.
                #
                # This is not a transaction across three
                # files: interrupted writes require recovery
                # before another enrollment is attempted.

                transaction = {
                    "tokens": tokens,
                    "config": config,
                    "invitations": invitations,
                    "registry": registry
                }

                otb_consistency_dev.validate(
                    tokens, config, registry
                )

                write_json(JOURNAL, transaction)
                recover_pending()

            print(
                "Registered collector:",
                chain, collector,
                flush=True
            )

            return self.reply(200, {
                "status": "registered",
                "chain": chain,
                "collector": collector,
                "token": token
            })

        except (ValueError, KeyError, TypeError):
            return self.reply(
                400, {"error": "Invalid enrollment request"}
            )

        except Exception:
            self.log_error("Enrollment processing failed")
            return self.reply(
                500, {"error": "Internal server error"}
            )


    def do_unenroll(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))

            if not 1 <= size <= MAX_SIZE:
                return self.reply(
                    413, {"error": "Invalid request size"}
                )

            content_type = self.headers.get(
                "Content-Type", ""
            ).split(";")[0].strip().lower()

            if content_type != "application/json":
                return self.reply(
                    415, {"error": "JSON required"}
                )

            data = json.loads(self.rfile.read(size))

            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")

            chain = data.get("chain")
            collector = data.get("collector")
            transaction_id = data.get("transaction_id")

            if (
                not isinstance(chain, str)
                or not isinstance(collector, str)
                or not SAFE_NAME.fullmatch(chain)
                or not SAFE_NAME.fullmatch(collector)
                or chain in (".", "..")
                or collector in (".", "..")
                or not isinstance(transaction_id, str)
                or not re.fullmatch(
                    r"[0-9a-f]{32}", transaction_id
                )
            ):
                raise ValueError("Invalid removal identity or transaction")

            auth = self.headers.get("Authorization", "")
            supplied = (
                auth[7:] if auth.startswith("Bearer ") else ""
            )

            if not supplied:
                return self.reply(
                    401, {"error": "Unauthorized"}
                )

            fingerprint = hashlib.sha256(
                supplied.encode()
            ).hexdigest()

            with LOCK.open("a+") as lock:
                os.chmod(LOCK, 0o600)
                fcntl.flock(lock, fcntl.LOCK_EX)

                recover_pending()

                receipts = (
                    read_json(RECEIPTS)
                    if RECEIPTS.exists()
                    else {}
                )

                if not isinstance(receipts, dict):
                    raise RuntimeError("Invalid receipts database")

                previous = receipts.get(transaction_id)

                if previous is not None:
                    if (
                        not isinstance(previous, dict)
                        or previous.get("chain") != chain
                        or previous.get("collector") != collector
                        or not isinstance(
                            previous.get("token_fingerprint"), str
                        )
                        or not hmac.compare_digest(
                            previous["token_fingerprint"],
                            fingerprint
                        )
                    ):
                        return self.reply(
                            409, {"error": "Transaction mismatch"}
                        )

                    return self.reply(200, {
                        "status": "deregistered",
                        "chain": chain,
                        "collector": collector,
                        "transaction_id": transaction_id,
                        "replayed": True,
                        "publication": "pending"
                    })

                tokens = read_json(TOKENS)
                config = read_json(CONFIG)
                invitations = read_json(INVITES)
                registry = otb_registry.load_registry(STATUS)

                expected = tokens.get(chain, {}).get(collector)

                if (
                    not isinstance(expected, str)
                    or not hmac.compare_digest(
                        expected, supplied
                    )
                ):
                    return self.reply(
                        401, {"error": "Unauthorized"}
                    )

                chains = config["chains"]

                if chain not in chains:
                    return self.reply(
                        409, {"error": "Registry mismatch"}
                    )

                record = registry["collectors"].get(
                    chain, {}
                ).get(collector)

                if record is None:
                    return self.reply(
                        409, {"error": "Status registry mismatch"}
                    )

                current_status = record.get("status")
                approved = collector in chains[chain].get(
                    "collectors", []
                )

                if current_status in ("enabled", "suspended"):
                    if not approved:
                        return self.reply(
                            409, {"error": "Registry mismatch"}
                        )
                    removal_scope = "approved"

                elif current_status == "pending":
                    if approved:
                        return self.reply(
                            409, {"error": "Registry mismatch"}
                        )
                    removal_scope = "pending"

                else:
                    return self.reply(
                        409, {"error": "Status registry mismatch"}
                    )

                # Keep the collector name and enode identity
                # reserved after uninstallation.
                now = datetime.now(timezone.utc).isoformat()

                record["status"] = "revoked"
                record["updated_at"] = now
                record["last_action"] = "collector_uninstalled"

                del tokens[chain][collector]

                if removal_scope == "approved":
                    chains[chain]["collectors"].remove(collector)

                receipts[transaction_id] = {
                    "chain": chain,
                    "collector": collector,
                    "token_fingerprint": fingerprint
                }

                transaction = {
                    "tokens": tokens,
                    "config": config,
                    "invitations": invitations,
                    "registry": registry,
                    "receipts": receipts,
                    "removal": {
                        "chain": chain,
                        "collector": collector,
                        "scope": removal_scope
                    }
                }

                otb_consistency_dev.validate(
                    tokens, config, registry
                )

                write_json(JOURNAL, transaction)
                recover_pending()

            print(
                "Deregistered collector:",
                chain, collector,
                flush=True
            )

            return self.reply(200, {
                "status": "deregistered",
                "chain": chain,
                "collector": collector,
                "transaction_id": transaction_id,
                "replayed": False,
                "publication": "pending"
            })

        except (ValueError, KeyError, TypeError):
            return self.reply(
                400, {"error": "Invalid removal request"}
            )

        except Exception:
            self.log_error("Deregistration processing failed")
            return self.reply(
                500, {"error": "Internal server error"}
            )


if __name__ == "__main__":
    print(
        "OTB Enrollment Server",
        VERSION,
        flush=True
    )
    print(
        "Listening on %s:%s" % (HOST, PORT),
        flush=True
    )

    with LOCK.open("a+") as lock:
        os.chmod(LOCK, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        recover_pending()

    HTTPServer((HOST, PORT), Handler).serve_forever()
