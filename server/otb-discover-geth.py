#!/usr/bin/env python3
# OTB Collector v0.1.0{etho,etica}
# Read-only Geth service discovery.

import json
import re
import shlex
import socket
import subprocess
from pathlib import Path

VERSION = "v0.1.0{etho,etica}"


def command(*args):
    return subprocess.check_output(
        args, text=True, stderr=subprocess.DEVNULL
    ).strip()


def option(args, name):
    for i, arg in enumerate(args):
        if arg == name and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return None


def rpc(ipc, method):
    request = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": [],
        "id": 1
    }).encode() + b"\n"

    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(3)
        sock.connect(ipc)
        sock.sendall(request)

        response = b""
        while b"\n" not in response:
            chunk = sock.recv(65536)
            if not chunk:
                raise RuntimeError("Connection closed")
            response += chunk
            if len(response) > 1048576:
                raise RuntimeError("Response too large")

    result = json.loads(response.split(b"\n", 1)[0])
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    return result.get("result")


def discover():
    units = command(
        "systemctl", "list-unit-files",
        "--type=service", "--no-legend", "--no-pager"
    )

    for line in units.splitlines():
        fields = line.split()
        if not fields:
            continue

        service = fields[0]

        if not re.search(r"geth", service, re.I):
            continue

        try:
            state = command(
                "systemctl", "show", service,
                "-p", "ActiveState", "--value"
            )

            raw = command(
                "systemctl", "show", service,
                "-p", "ExecStart", "--value"
            )

            match = re.search(
                r"argv\[\]=(.*?)(?:\s;\signore_errors=|$)",
                raw
            )

            if not match:
                continue

            args = shlex.split(match.group(1))

            datadir = option(args, "--datadir")
            network_id = option(args, "--networkid")

            if "--etica" in args or any(
                "geth-etica" in Path(a).name for a in args[:1]
            ):
                chain = "etica"
            elif network_id == "1313114":
                chain = "etho"
            else:
                chain = "unknown"

            ipc = option(args, "--ipcpath")

            if not ipc and datadir:
                ipc = str(Path(datadir) / "geth.ipc")
            elif ipc and not Path(ipc).is_absolute() and datadir:
                ipc = str(Path(datadir) / ipc)

            if "--ipcdisable" in args:
                ipc = None

            yield {
                "service": service,
                "state": state,
                "chain": chain,
                "network_id": network_id,
                "datadir": datadir,
                "ipc": ipc
            }

        except Exception as exc:
            print("Discovery error:", service, str(exc))


print("OTB Geth Discovery", VERSION)
print()

found = list(discover())

for index, item in enumerate(found, 1):
    print("[%d] %s" % (index, item["service"]))
    print("    Chain:   ", item["chain"])
    print("    State:   ", item["state"])
    print("    Datadir: ", item["datadir"])
    print("    IPC:     ", item["ipc"])

    ipc = item["ipc"]

    if ipc:
        try:
            actual_network = rpc(ipc, "net_version")
            print("    RPC network ID:", actual_network)

            if item["network_id"] and (
                str(actual_network) != str(item["network_id"])
            ):
                print("    WARNING: network ID mismatch")

        except Exception as exc:
            print("    IPC check:", str(exc))
    else:
        print("    IPC check: unavailable")

    print()

print("Discovered Geth services:", len(found))
