#!/usr/bin/env python3
# OTB Universal Collector Installer v1.0.1{etho,etica}

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

VERSION = "v1.0.1{etho,etica}"

NETWORKS = {
    "etica": "61803",
    "etho": "1313114",
}

RPC_CHECK = r'''
import json
import socket
import sys

ipc = sys.argv[1]

request = json.dumps({
    "jsonrpc": "2.0",
    "method": "net_version",
    "params": [],
    "id": 1
}).encode() + b"\n"

with socket.socket(socket.AF_UNIX) as s:
    s.settimeout(5)
    s.connect(ipc)
    s.sendall(request)

    response = b""
    while b"\n" not in response:
        chunk = s.recv(4096)
        if not chunk:
            raise RuntimeError("IPC closed")
        response += chunk

result = json.loads(response.split(b"\n", 1)[0])

if result.get("error"):
    raise RuntimeError(str(result["error"]))

print(result["result"])
'''


def systemctl(*args):
    return subprocess.check_output(
        ["systemctl", *args],
        text=True,
        stderr=subprocess.DEVNULL
    ).strip()


def option(args, name):
    for i, arg in enumerate(args):
        if arg == name and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return None


def identify_service(service):
    raw = systemctl(
        "show", service,
        "-p", "ExecStart", "--value"
    )

    match = re.search(
        r"argv\[\]=(.*?)(?:\s;\signore_errors=|$)",
        raw
    )

    if not match:
        return None

    args = shlex.split(match.group(1))

    if not args:
        return None

    executable = Path(args[0]).name

    if "geth" not in executable.lower():
        return None

    state = systemctl(
        "show", service,
        "-p", "ActiveState", "--value"
    )

    user = systemctl(
        "show", service,
        "-p", "User", "--value"
    ) or "root"

    group = systemctl(
        "show", service,
        "-p", "Group", "--value"
    )

    datadir = option(args, "--datadir")
    network = option(args, "--networkid")

    ipc = option(args, "--ipcpath")

    if "--ipcdisable" in args:
        ipc = None
    elif ipc and not Path(ipc).is_absolute():
        if datadir:
            ipc = str(Path(datadir) / ipc)
    elif not ipc and datadir:
        ipc = str(Path(datadir) / "geth.ipc")

    if "--etica" in args or "geth-etica" in executable:
        chain = "etica"
    elif network == NETWORKS["etho"]:
        chain = "etho"
    else:
        chain = "unknown"

    return {
        "service": service,
        "state": state,
        "user": user,
        "group": group,
        "chain": chain,
        "datadir": datadir,
        "ipc": ipc,
        "configured_network": network
    }


def check_ipc(item):
    ipc = item["ipc"]

    if not ipc:
        return None, "No IPC configured"

    cmd = [
        sys.executable,
        "-c",
        RPC_CHECK,
        ipc
    ]

    if os.geteuid() == 0 and item["user"] != "root":
        cmd = [
            "runuser",
            "-u", item["user"],
            "--"
        ] + cmd

    try:
        result = subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.PIPE,
            timeout=10
        ).strip()

        return result, None

    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip().splitlines()
        return None, message[-1] if message else "IPC failed"

    except Exception as exc:
        return None, str(exc)


def discover():
    units = systemctl(
        "list-unit-files",
        "--type=service",
        "--no-legend",
        "--no-pager"
    )

    found = []

    for line in units.splitlines():
        fields = line.split()

        if not fields:
            continue

        service = fields[0]

        if "geth" not in service.lower():
            continue

        try:
            item = identify_service(service)

            if item:
                item["actual_network"], item["error"] = (
                    check_ipc(item)
                )

                for chain, network_id in NETWORKS.items():
                    if item["actual_network"] == network_id:
                        item["chain"] = chain

                found.append(item)

        except Exception as exc:
            print("Discovery warning:", service, exc)

    return sorted(
        found,
        key=lambda x: (
            x["chain"],
            x["service"]
        )
    )



def installation_plan():
    import pwd

    if os.geteuid() != 0:
        raise SystemExit("Run with sudo")

    found = []

    for item in discover():
        expected = NETWORKS.get(item["chain"])

        if (
            item["state"] == "active"
            and expected is not None
            and item["actual_network"] == expected
        ):
            found.append(item)

    found.sort(key=lambda x: (x["chain"], x["service"]))

    if not found:
        raise SystemExit("No verified Geth services found")

    print("\nAvailable Geth services:\n")

    for index, item in enumerate(found, 1):
        print(
            "[%d] %s (%s, user=%s)"
            % (
                index,
                item["service"],
                item["chain"],
                item["user"]
            )
        )
        print("    IPC:", item["ipc"])

    choice = input("\nSelect service number: ").strip()

    if not choice.isdigit():
        raise SystemExit("Invalid selection")

    index = int(choice) - 1

    if not 0 <= index < len(found):
        raise SystemExit("Selection out of range")

    item = found[index]

    collector = input(
        "Collector identity: "
    ).strip()

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", collector):
        raise SystemExit("Invalid collector identity")

    if collector in (".", ".."):
        raise SystemExit("Invalid collector identity")

    identity = item["chain"] + "-" + collector
    service_name = "otb-collector-" + identity

    config = Path("/etc/otb-collector") / (identity + ".json")
    data = Path("/var/lib/otb-collector") / identity

    if config.exists() or data.exists():
        raise SystemExit("STOP: Installation already exists")

    unit = Path("/etc/systemd/system") / (
        service_name + ".service"
    )

    if unit.exists():
        raise SystemExit("STOP: Service already exists")

    account = pwd.getpwnam(item["user"])

    print("\n===== PROPOSED INSTALLATION =====")
    print("Blockchain:      ", item["chain"])
    print("Collector:       ", collector)
    print("Geth service:    ", item["service"])
    print("Linux account:   ", item["user"])
    print("Primary group ID:", account.pw_gid)
    print("IPC socket:      ", item["ipc"])
    print("Network ID:      ", item["actual_network"])
    print("Configuration:   ", config)
    print("Data directory:  ", data)
    print("Systemd service: ", service_name + ".service")
    print("Systemd timer:   ", service_name + ".timer")
    print("Interval:        60 seconds")
    print("\nPLAN ONLY — nothing installed or registered")

    return {
        "service": item["service"],
        "chain": item["chain"],
        "collector": collector,
        "user": item["user"],
        "group_id": account.pw_gid,
        "ipc": item["ipc"],
        "network_id": item["actual_network"],
        "identity": identity,
        "config": str(config),
        "data": str(data),
        "unit": str(unit),
        "timer": str(
            Path("/etc/systemd/system") /
            (service_name + ".timer")
        )
    }



def main():
    parser = argparse.ArgumentParser(
        description="OTB Installer " + VERSION
    )

    mode = parser.add_mutually_exclusive_group(required=True)

    mode.add_argument(
        "--probe",
        action="store_true",
        help="Discover Geth services without installing"
    )

    mode.add_argument(
        "--plan",
        action="store_true",
        help="Interactively plan an installation"
    )

    mode.add_argument(
        "--preflight",
        action="store_true",
        help="Check installation readiness without making changes"
    )

    mode.add_argument(
        "--install",
        action="store_true",
        help="Install and enroll a new collector"
    )

    mode.add_argument(
        "--resume",
        action="store_true",
        help="Finish an installation using an existing token"
    )

    mode.add_argument(
        "--list",
        action="store_true",
        help="List locally installed OTB collectors"
    )

    mode.add_argument(
        "--validate",
        action="store_true",
        help="Validate ownership of installed collectors"
    )

    mode.add_argument(
        "--uninstall",
        action="store_true",
        help="Selectively uninstall managed collectors"
    )

    mode.add_argument(
        "--uninstall-preview",
        action="store_true",
        help="Preview selective collector removal"
    )

    args = parser.parse_args()

    if args.plan:
        installation_plan()
        return

    if args.preflight:
        plan = installation_plan()
        installation_preflight(plan)
        return

    if args.install:
        install_collector()
        return

    if args.resume:
        resume_collector()
        return

    if args.list:
        list_collectors()
        return

    if args.uninstall_preview:
        uninstall_preview()
        return

    if args.uninstall:
        uninstall_collectors()
        return

    if args.validate:
        validate_installed_collectors()
        return

    print("OTB Universal Collector Installer", VERSION)
    print("Mode: Read-only discovery")
    print()

    found = discover()

    for i, item in enumerate(found, 1):
        expected = NETWORKS.get(item["chain"])

        verified = (
            item["state"] == "active"
            and expected is not None
            and item["actual_network"] == expected
        )

        print("[%d] %s" % (i, item["service"]))
        print("    Blockchain:", item["chain"])
        print("    State:", item["state"])
        print("    Linux user:", item["user"])
        print("    Datadir:", item["datadir"])
        print("    IPC:", item["ipc"])
        print("    Network ID:", item["actual_network"])
        print("    Verified:", verified)

        if item["error"]:
            print("    IPC error:", item["error"])

        print()

    print("Discovered services:", len(found))
    print(
        "Verified services:",
        sum(
            item["state"] == "active"
            and item["actual_network"]
                == NETWORKS.get(item["chain"])
            for item in found
        )
    )





def installation_preflight(plan):
    import pwd

    print("\n===== INSTALLATION PREFLIGHT =====")

    shared = Path("/usr/local/lib/otb-collector")
    needs_setup = False

    if shared.is_symlink() or (
        shared.exists() and not shared.is_dir()
    ):
        raise SystemExit("STOP: Unsafe shared software directory")

    for name in (
        "otb-collect.py",
        "otb-push.py",
        "otb-run.py"
    ):
        path = shared / name

        if path.is_symlink() or (
            path.exists() and not path.is_file()
        ):
            raise SystemExit(
                "STOP: Unsafe shared collector: " + str(path)
            )

        if path.is_file():
            print("Software:", name, "present")
        else:
            needs_setup = True
            print("Software:", name, "WILL INSTALL")

    account = pwd.getpwnam(plan["user"])

    if not Path(plan["ipc"]).exists():
        raise SystemExit("STOP: Geth IPC socket missing")

    for name in ("config", "data", "unit", "timer"):
        path = Path(plan[name])

        if path.exists() or path.is_symlink():
            raise SystemExit(
                "STOP: Installation path already exists: "
                + str(path)
            )

    if plan["network_id"] != NETWORKS[plan["chain"]]:
        raise SystemExit("STOP: Blockchain network mismatch")

    for directory in (
        Path("/usr/local/lib/otb-collector"),
        Path("/etc/otb-collector"),
        Path("/var/lib/otb-collector"),
    ):
        if directory.is_symlink() or (
            directory.exists() and not directory.is_dir()
        ):
            raise SystemExit(
                "STOP: Unsafe installation directory: " + str(directory)
            )

        if directory.is_dir():
            print("Directory:", directory, "present")
        else:
            needs_setup = True
            print("Directory:", directory, "WILL CREATE")

    print("Geth user:", account.pw_name)
    print("Network:", plan["network_id"], "OK")
    print("Installation paths: available")
    if needs_setup:
        print("Preflight: READY FOR AUTOMATIC SETUP")
    else:
        print("Preflight: PASSED")

    print("No files created; no invitation redeemed.")





def prepare_shared_prerequisites():
    """Prepare missing shared components before collector enrollment."""
    import hashlib
    import stat
    import tempfile
    import urllib.request

    shared = Path("/usr/local/lib/otb-collector")
    config_root = Path("/etc/otb-collector")
    data_root = Path("/var/lib/otb-collector")

    base_url = (
        "https://nodelist.outsidethebox.top/downloads/"
    )

    checksums = {
        "otb-collect.py":
            "41bb654e4c53ffbd5db8ae51440348061752efcf6aeadeff6f3355e509489e06",
        "otb-push.py":
            "91ed5ca9128feed9639beb29531fb32338f7728081f33d32bf19372ecc76ed4b",
        "otb-run.py":
            "f682561f49cafafe248acf300706a52a09c4b50bda25fd501bf82597a742f77e",
    }

    if os.geteuid() != 0:
        raise RuntimeError("Prerequisite setup requires root")

    print("\n===== AUTOMATIC PREREQUISITE SETUP =====")

    # Reject unsafe directory types before creating anything.
    for directory in (shared, config_root, data_root):
        if directory.is_symlink() or (
            directory.exists() and not directory.is_dir()
        ):
            raise RuntimeError(
                "Unsafe prerequisite directory: " + str(directory)
            )

    for name in checksums:
        path = shared / name
        if path.is_symlink() or (
            path.exists() and not path.is_file()
        ):
            raise RuntimeError(
                "Unsafe shared component: " + str(path)
            )

    # Download and verify missing files before installing any.
    staged = {}

    try:
        for name, expected in checksums.items():
            target = shared / name

            if target.exists():
                actual = hashlib.sha256(
                    target.read_bytes()
                ).hexdigest()

                if actual != expected:
                    raise RuntimeError(
                        "Existing shared component checksum mismatch: "
                        + str(target)
                    )

                print("Existing shared component verified:", name)
                continue

            print("Downloading:", name)

            with urllib.request.urlopen(
                base_url + name, timeout=20
            ) as response:
                content = response.read(1024 * 1024 + 1)

            if len(content) > 1024 * 1024:
                raise RuntimeError("Download too large: " + name)

            actual = hashlib.sha256(content).hexdigest()

            if actual != expected:
                raise RuntimeError(
                    "SHA256 verification failed: " + name
                )

            compile(content, name, "exec")
            staged[name] = content

            print("SHA256 verified:", name)

        # Only create directories after downloads have passed.
        for directory in (shared, config_root, data_root):
            if not directory.exists():
                directory.mkdir(mode=0o755)
                os.chown(directory, 0, 0)
                os.chmod(directory, 0o755)
                print("Created directory:", directory)

        # Atomically create files; never overwrite an existing file.
        for name, content in staged.items():
            target = shared / name

            fd, temporary = tempfile.mkstemp(
                prefix=".otb-install-",
                dir=str(shared)
            )

            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())

                os.chown(temporary, 0, 0)
                os.chmod(temporary, 0o755)

                # Atomic no-overwrite creation on the same filesystem.
                os.link(temporary, target, follow_symlinks=False)

                print("Installed shared component:", name)

            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

        for name in checksums:
            path = shared / name

            if path.is_symlink() or not path.is_file():
                raise RuntimeError(
                    "Missing or unsafe component: " + name
                )

        print("Automatic prerequisite setup: COMPLETE")

    finally:
        staged.clear()


def prepare_collector(plan):
    import pwd
    import shutil

    account = pwd.getpwnam(plan["user"])
    data = Path(plan["data"])
    output = data / "observation.json"
    config = Path(plan["config"])
    token = data / "token"

    if data.exists() or config.exists():
        raise RuntimeError("Collector installation already exists")

    # Private data directory owned by the Geth service account.
    data.mkdir(mode=0o700)
    os.chown(data, account.pw_uid, account.pw_gid)

    settings = {
        "chain": plan["chain"],
        "collector": plan["collector"],
        "ipc": plan["ipc"],
        "output": str(output),
        "token_file": str(token)
    }

    # Config contains paths and identity, never the token itself.
    fd = os.open(
        str(config),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o644
    )

    with os.fdopen(fd, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    os.chmod(config, 0o644)

    print("\n===== LOCAL COLLECTOR TEST =====", flush=True)

    runner = [
        sys.executable,
        "/usr/local/lib/otb-collector/otb-run.py",
        "--config", str(config),
        "--check-only"
    ]

    if plan["user"] != "root":
        runner = [
            "runuser",
            "-u", plan["user"],
            "--"
        ] + runner

    try:
        subprocess.run(runner, check=True)

    except Exception:
        print("Local collector test failed.")
        print("No invitation has been redeemed.")

        # Clean up only files created by this preparation.
        if config.exists():
            config.unlink()

        if data.exists():
            shutil.rmtree(data)

        raise

    print("\nLocal collector preparation: PASSED")
    print("Private directory:", data)
    print("Configuration:", config)
    print("Observation:", output)
    print("Token: not issued")
    print("Systemd units: not installed")

    return settings






def enroll_collector(plan):
    import getpass
    import pwd
    import urllib.error
    import urllib.request

    url = "https://nodelist.outsidethebox.top/api/v1/enroll"
    token_path = Path(plan["data"]) / "token"

    if not token_path.parent.is_dir():
        raise RuntimeError("Collector directory missing")

    if token_path.exists() or token_path.is_symlink():
        raise RuntimeError("Token file already exists")

    print("\n===== COLLECTOR ENROLLMENT =====")
    print("Blockchain:", plan["chain"])
    print("Collector:", plan["collector"])

    code = getpass.getpass(
        "One-time enrollment code: "
    ).strip()

    if not code:
        raise RuntimeError("Enrollment code required")

    request = urllib.request.Request(
        url,
        data=json.dumps({"code": code}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            "Enrollment rejected: HTTP " + str(exc.code)
        ) from exc

    if (
        result.get("status") != "registered"
        or result.get("chain") != plan["chain"]
        or result.get("collector") != plan["collector"]
    ):
        raise RuntimeError(
            "Enrollment response did not match requested collector"
        )

    token = result.get("token")

    if not isinstance(token, str) or len(token) < 32:
        raise RuntimeError("Invalid enrollment token")

    account = pwd.getpwnam(plan["user"])

    fd = os.open(
        str(token_path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600
    )

    try:
        os.fchown(fd, account.pw_uid, account.pw_gid)
        os.fchmod(fd, 0o600)

        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
            f.flush()
            os.fsync(f.fileno())

    except Exception:
        token_path.unlink(missing_ok=True)
        raise

    print("Enrollment successful.")
    print("Token stored securely:", token_path)
    print("Token contents: hidden")

    return str(token_path)




def create_systemd_units(plan):
    unit = Path(plan["unit"])
    timer = Path(plan["timer"])

    if unit.exists() or timer.exists():
        raise RuntimeError("Systemd unit already exists")

    service_name = unit.name

    service_text = f"""[Unit]
Description=OTB Node Collector - {plan['chain']}/{plan['collector']}
After=network-online.target {plan['service']}
Wants=network-online.target

[Service]
Type=oneshot
User={plan['user']}
WorkingDirectory={plan['data']}
ExecStart=/usr/bin/python3 /usr/local/lib/otb-collector/otb-run.py --config {plan['config']}
UMask=0077
NoNewPrivileges=true
"""

    timer_text = f"""[Unit]
Description=OTB Node Collector Timer - {plan['chain']}/{plan['collector']}

[Timer]
OnBootSec=30s
OnUnitInactiveSec=60s
Unit={service_name}

[Install]
WantedBy=timers.target
"""

    # Exclusive creation: never overwrite existing units.
    created = []

    try:
        for path, content in (
            (unit, service_text),
            (timer, timer_text)
        ):
            fd = os.open(
                str(path),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644
            )

            created.append(path)

            with os.fdopen(fd, "w") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

        print("\n===== SYSTEMD UNITS CREATED =====")
        print("Service:", unit)
        print("Timer:", timer)

    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise





def install_collector():
    if os.geteuid() != 0:
        raise SystemExit("Installation requires sudo")

    plan = installation_plan()
    installation_preflight(plan)

    print("\n===== INSTALLATION CONFIRMATION =====")
    print("Blockchain:", plan["chain"])
    print("Collector:", plan["collector"])
    print("Geth service:", plan["service"])

    answer = input(
        "Prepare this collector? [yes/NO]: "
    ).strip().lower()

    if answer != "yes":
        print("Installation cancelled.")
        return

    # Prepare missing dependencies only after confirmation.
    # No enrollment invitation has been consumed yet.
    prepare_shared_prerequisites()

    # Recheck installation paths and Geth before proceeding.
    installation_preflight(plan)

    # Test collection before consuming the invitation.
    prepare_collector(plan)

    print("\nLocal collection test passed.")
    print("The next step registers this collector centrally.")
    print("An invitation will be consumed if accepted.")

    answer = input(
        "Proceed with enrollment? [yes/NO]: "
    ).strip().lower()

    if answer != "yes":
        print("Enrollment cancelled.")
        print("Local preparation remains at:", plan["data"])
        return

    try:
        enroll_collector(plan)

        # Registration succeeded: preserve the local
        # configuration and token on subsequent failures.
        create_systemd_units(plan)

        subprocess.run(
            ["systemctl", "daemon-reload"],
            check=True
        )

        service = Path(plan["unit"]).name
        timer = Path(plan["timer"]).name

        print("\n===== FIRST UPLOAD TEST =====")
        subprocess.run(
            ["systemctl", "start", service],
            check=True
        )

        print("First authenticated upload: PASSED")

        subprocess.run(
            ["systemctl", "enable", "--now", timer],
            check=True
        )

        print("\n===== INSTALLATION COMPLETE =====")
        print("Collector:", plan["chain"] + "/" + plan["collector"])
        print("Service:", service)
        print("Timer:", timer)
        print("Status: enabled and running")

    except Exception:
        print("\nINSTALLATION INCOMPLETE")
        print("Local files have been preserved.")
        print("Do not redeem another invitation yet.")
        print("Configuration:", plan["config"])
        print("Data directory:", plan["data"])
        print("Check the failure before retrying.")
        raise





def resume_collector():
    import pwd
    import stat

    if os.geteuid() != 0:
        raise SystemExit("Recovery requires sudo")

    print("\n===== RESUME COLLECTOR INSTALLATION =====")
    chain = input("Blockchain (etho/etica): ").strip()
    collector = input("Collector identity: ").strip()

    if chain not in NETWORKS:
        raise SystemExit("Invalid blockchain")

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", collector):
        raise SystemExit("Invalid collector identity")

    if collector in (".", ".."):
        raise SystemExit("Invalid collector identity")

    identity = chain + "-" + collector
    config = Path("/etc/otb-collector") / (identity + ".json")
    data = Path("/var/lib/otb-collector") / identity
    token = data / "token"

    if not config.is_file() or not token.is_file():
        raise SystemExit(
            "STOP: Existing configuration or token missing. "
            "Do not redeem another invitation."
        )

    if config.is_symlink() or data.is_symlink() or token.is_symlink():
        raise SystemExit("STOP: Unexpected symbolic link")

    settings = json.loads(config.read_text())

    if (settings.get("chain") != chain
            or settings.get("collector") != collector
            or settings.get("token_file") != str(token)
            or settings.get("output") != str(data / "observation.json")):
        raise SystemExit("STOP: Configuration mismatch")

    account = pwd.getpwuid(data.stat().st_uid)

    if (token.stat().st_uid != account.pw_uid
            or stat.S_IMODE(token.stat().st_mode) != 0o600
            or stat.S_IMODE(data.stat().st_mode) != 0o700):
        raise SystemExit("STOP: Credential permissions mismatch")

    if len(token.read_text().strip()) < 32:
        raise SystemExit("STOP: Credential is invalid")

    item = {
        "user": account.pw_name,
        "ipc": settings["ipc"]
    }
    network, error = check_ipc(item)

    if network != NETWORKS[chain]:
        raise SystemExit("STOP: Geth IPC verification failed: " + str(error))

    matches = [
        item for item in discover()
        if item["chain"] == chain
        and item["user"] == account.pw_name
        and item["ipc"] == settings["ipc"]
        and item["actual_network"] == NETWORKS[chain]
        and item["state"] == "active"
    ]

    if len(matches) != 1:
        raise SystemExit(
            "STOP: Cannot uniquely identify the original Geth service"
        )

    geth_service = matches[0]["service"]

    name = "otb-collector-" + identity
    unit = Path("/etc/systemd/system") / (name + ".service")
    timer = Path("/etc/systemd/system") / (name + ".timer")

    if unit.is_symlink() or timer.is_symlink():
        raise SystemExit("STOP: Unsafe systemd unit symlink")

    if unit.exists() != timer.exists():
        raise SystemExit("STOP: Partial systemd unit installation")

    if unit.exists():
        content = unit.read_text()
        expected = (
            "ExecStart=/usr/bin/python3 "
            "/usr/local/lib/otb-collector/otb-run.py "
            "--config " + str(config)
        )
        if (expected not in content
                or "User=" + account.pw_name + "\n" not in content
                or "Unit=" + unit.name not in timer.read_text()):
            raise SystemExit("STOP: Existing systemd units differ")
    # Existing token, Geth service and any installed
    # systemd units have now been verified.
    # Restore shared prerequisites before changing systemd.
    prepare_shared_prerequisites()

    if not unit.exists():
        plan = {
            "chain": chain,
            "collector": collector,
            "user": account.pw_name,
            "data": str(data),
            "config": str(config),
            "unit": str(unit),
            "timer": str(timer),
            "service": geth_service
        }
        create_systemd_units(plan)

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "start", unit.name], check=True)
    subprocess.run(
        ["systemctl", "enable", "--now", timer.name],
        check=True
    )

    print("\nRECOVERY COMPLETE")
    print("Collector:", identity)
    print("Service:", unit.name)
    print("Timer:", timer.name)
    print("Existing token retained; no invitation redeemed.")





def list_collectors():
    import stat

    base = Path("/etc/otb-collector")
    data_root = Path("/var/lib/otb-collector")
    unit_root = Path("/etc/systemd/system")

    print("\n===== INSTALLED OTB COLLECTORS =====")

    if not base.is_dir():
        print("No collector configuration directory found.")
        return

    found = 0

    for config in sorted(base.glob("*.json")):
        if config.is_symlink():
            print("SKIPPED symbolic link:", config.name)
            continue

        try:
            settings = json.loads(config.read_text())

            chain = settings["chain"]
            collector = settings["collector"]

            if chain not in NETWORKS:
                print("Unknown chain:", config.name)
                continue

            if not re.fullmatch(
                r"[A-Za-z0-9_.-]+", collector
            ) or collector in (".", ".."):
                print("Invalid collector:", config.name)
                continue

            identity = chain + "-" + collector

            if config.name != identity + ".json":
                print("Configuration filename mismatch:", config.name)
                continue

            data = data_root / identity

            service = unit_root / (
                "otb-collector-" + identity + ".service"
            )

            timer = unit_root / (
                "otb-collector-" + identity + ".timer"
            )

            found += 1

            print()
            print("[%d] %s" % (found, identity))
            print("    Blockchain:", chain)
            print("    Collector:", collector)
            print("    Configuration:", config)
            print("    Data directory:", data)
            print("    Data present:", data.is_dir())
            print("    Token present:", (data / "token").is_file())
            print("    Service present:", service.is_file())
            print("    Timer present:", timer.is_file())

        except Exception as exc:
            print("Inventory warning:", config.name, str(exc))

    print("\nInstalled configurations:", found)
    print("Read-only inventory — nothing removed.")





def uninstall_preview():
    base = Path("/etc/otb-collector")
    data_root = Path("/var/lib/otb-collector")
    unit_root = Path("/etc/systemd/system")

    found = []

    for config in sorted(base.glob("*.json")):
        if config.is_symlink():
            continue

        try:
            settings = json.loads(config.read_text())
            chain = settings["chain"]
            collector = settings["collector"]

            if chain not in NETWORKS:
                print("Skipped unknown blockchain:", config.name)
                continue

            if not re.fullmatch(r"[A-Za-z0-9_.-]+", collector):
                continue
            if collector in (".", ".."):
                continue

            identity = chain + "-" + collector

            if config.name != identity + ".json":
                continue

            data = data_root / identity
            service = unit_root / (
                "otb-collector-" + identity + ".service"
            )
            timer = unit_root / (
                "otb-collector-" + identity + ".timer"
            )

            found.append({
                "identity": identity,
                "chain": chain,
                "config": config,
                "data": data,
                "service": service,
                "timer": timer
            })

        except Exception as exc:
            print("Skipped:", config.name, str(exc))

    if not found:
        print("No managed collectors found.")
        return

    print("\n===== OTB COLLECTOR UNINSTALL PREVIEW =====\n")

    for index, item in enumerate(found, 1):
        print(
            "[%d] %s" % (index, item["identity"])
        )

    print("[A] All collectors")
    print("[Q] Cancel")

    selection = input(
        "\nSelect collector number(s), e.g. 1,2 or A: "
    ).strip().lower()

    if selection == "q" or not selection:
        print("Cancelled.")
        return

    if selection == "a":
        selected = found
    else:
        try:
            indexes = {
                int(value.strip()) - 1
                for value in selection.split(",")
            }
        except ValueError:
            raise SystemExit("Invalid selection")

        if not indexes or any(
            index < 0 or index >= len(found)
            for index in indexes
        ):
            raise SystemExit("Selection out of range")

        selected = [
            found[index] for index in sorted(indexes)
        ]

    print("\n===== PROPOSED REMOVAL =====")

    for item in selected:
        print("\nCollector:", item["identity"])
        print("Blockchain:", item["chain"])
        print("Systemd service:", item["service"])
        print("Systemd timer:", item["timer"])
        print("Configuration:", item["config"])
        print("Private data:", item["data"])
        print("Central token revocation: required")

    remaining = [
        item["identity"]
        for item in found
        if item not in selected
    ]

    print("\nCollectors to remove:", len(selected))
    print("Collectors to retain:", len(remaining))

    for identity in remaining:
        print("  KEEP:", identity)

    print("\nPREVIEW ONLY — NOTHING REMOVED")
    print("Geth services and blockchain data are untouched.")




def validate_managed_collector(item):
    """Validate ownership before permitting collector removal."""
    import configparser
    import pwd
    import stat

    # Reject redirected managed-resource directories.
    for directory in (
        Path("/etc/otb-collector"),
        Path("/var/lib/otb-collector"),
        Path("/etc/systemd/system"),
    ):
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError(
                "Unsafe managed-resource directory: " + str(directory)
            )

    identity = item["identity"]
    chain = item["chain"]
    config = Path(item["config"])
    data = Path(item["data"])
    service = Path(item["service"])
    timer = Path(item["timer"])

    if chain not in NETWORKS:
        raise RuntimeError("Unsupported blockchain")

    collector = identity[len(chain) + 1:]

    if (
        not identity.startswith(chain + "-")
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", collector)
        or collector in (".", "..")
    ):
        raise RuntimeError("Invalid collector identity")

    expected_config = Path("/etc/otb-collector") / (identity + ".json")
    expected_data = Path("/var/lib/otb-collector") / identity
    expected_service = Path("/etc/systemd/system") / (
        "otb-collector-" + identity + ".service"
    )
    expected_timer = Path("/etc/systemd/system") / (
        "otb-collector-" + identity + ".timer"
    )

    if (
        config != expected_config
        or data != expected_data
        or service != expected_service
        or timer != expected_timer
    ):
        raise RuntimeError("Unexpected collector paths")

    # Never follow symbolic links in managed resources.
    for path in (
        config, data, service, timer,
        data / "token", data / "observation.json"
    ):
        if path.is_symlink():
            raise RuntimeError("Symbolic link rejected: " + str(path))

    for path in (config, service, timer):
        if not path.is_file():
            raise RuntimeError("Missing managed file: " + str(path))

    if not data.is_dir():
        raise RuntimeError("Missing private data directory")

    settings = json.loads(config.read_text())

    if (
        settings.get("chain") != chain
        or settings.get("collector") != collector
        or settings.get("output") != str(data / "observation.json")
        or settings.get("token_file") != str(data / "token")
    ):
        raise RuntimeError("Collector configuration mismatch")

    ipc = settings.get("ipc")

    if not isinstance(ipc, str) or not ipc.startswith("/"):
        raise RuntimeError("Invalid Geth IPC path")

    if not (data / "token").is_file():
        raise RuntimeError("Missing authentication token")

    unit = configparser.ConfigParser(interpolation=None)
    unit.read(service)

    if (
        unit.get("Service", "Type", fallback="") != "oneshot"
        or unit.get("Service", "WorkingDirectory", fallback="")
            != str(data)
        or unit.get("Service", "ExecStart", fallback="")
            != (
                "/usr/bin/python3 "
                "/usr/local/lib/otb-collector/otb-run.py "
                "--config " + str(config)
            )
    ):
        raise RuntimeError("Service ownership mismatch")

    user = unit.get("Service", "User", fallback="")

    if not user:
        raise RuntimeError("Service account missing")

    account = pwd.getpwnam(user)

    if data.stat().st_uid != account.pw_uid:
        raise RuntimeError("Private directory owner mismatch")

    if (data / "token").stat().st_uid != account.pw_uid:
        raise RuntimeError("Token owner mismatch")

    if stat.S_IMODE((data / "token").stat().st_mode) != 0o600:
        raise RuntimeError("Token permissions mismatch")

    timer_config = configparser.ConfigParser(interpolation=None)
    timer_config.read(timer)

    if timer_config.get("Timer", "Unit", fallback="") != service.name:
        raise RuntimeError("Timer ownership mismatch")

    # Never recursively remove unrecognized private files.
    allowed = {"token", "observation.json"}

    for entry in data.iterdir():
        if entry.name not in allowed:
            raise RuntimeError(
                "Unexpected private file: " + str(entry)
            )

        if entry.is_symlink() or not entry.is_file():
            raise RuntimeError(
                "Unsafe private file: " + str(entry)
            )

    return {
        "chain": chain,
        "collector": collector,
        "identity": identity,
        "config": config,
        "data": data,
        "service": service,
        "timer": timer,
        "user": user,
        "ipc": ipc
    }



def validate_installed_collectors():
    base = Path("/etc/otb-collector")

    print("\n===== OTB COLLECTOR OWNERSHIP VALIDATION =====")

    if not base.is_dir():
        print("No installed collectors found.")
        return

    passed = 0
    failed = 0

    for config in sorted(base.glob("*.json")):
        try:
            if config.is_symlink():
                raise RuntimeError("Configuration is a symbolic link")

            settings = json.loads(config.read_text())
            chain = settings["chain"]
            collector = settings["collector"]

            if chain not in NETWORKS:
                raise RuntimeError("Unsupported blockchain")

            if not re.fullmatch(r"[A-Za-z0-9_.-]+", collector):
                raise RuntimeError("Invalid collector identity")

            identity = chain + "-" + collector

            item = {
                "identity": identity,
                "chain": chain,
                "config": config,
                "data": Path("/var/lib/otb-collector") / identity,
                "service": Path("/etc/systemd/system") /
                    ("otb-collector-" + identity + ".service"),
                "timer": Path("/etc/systemd/system") /
                    ("otb-collector-" + identity + ".timer")
            }

            result = validate_managed_collector(item)

            print(
                "PASS:",
                result["identity"],
                "user=" + result["user"],
                "ipc=" + result["ipc"]
            )
            passed += 1

        except Exception as exc:
            print("FAIL:", config.name, str(exc))
            failed += 1

    print("\nValidated:", passed)
    print("Rejected:", failed)
    print("READ-ONLY — no changes made.")



def revoke_collector_registration(item):
    """Revoke one collector using its existing credential."""
    import urllib.error
    import urllib.request

    marker = (
        Path("/var/lib/otb-collector")
        / (".uninstall-" + item["identity"] + ".json")
    )

    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("Uninstall transaction missing")

    state = json.loads(marker.read_text())

    if (
        state.get("chain") != item["chain"]
        or state.get("collector") != item["collector"]
        or state.get("identity") != item["identity"]
        or state.get("phase") != "revocation_requested"
    ):
        raise RuntimeError("Uninstall transaction mismatch")

    transaction_id = state.get("transaction_id")

    if (
        not isinstance(transaction_id, str)
        or not re.fullmatch(r"[0-9a-f]{32}", transaction_id)
    ):
        raise RuntimeError("Invalid uninstall transaction ID")

    token_path = item["data"] / "token"
    token = token_path.read_text().strip()

    if not token:
        raise RuntimeError("Collector token is empty")

    url = "https://nodelist.outsidethebox.top/api/v1/unenroll"

    payload = json.dumps({
        "chain": item["chain"],
        "collector": item["collector"],
        "transaction_id": transaction_id
    }).encode()

    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request, timeout=15
        ) as response:
            status = response.status
            result = json.load(response)

    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            "Central revocation rejected: HTTP " + str(exc.code)
        ) from exc

    if (
        status != 200
        or result.get("status") != "deregistered"
        or result.get("chain") != item["chain"]
        or result.get("collector") != item["collector"]
        or result.get("transaction_id") != transaction_id
    ):
        raise RuntimeError("Unexpected central revocation response")

    print(
        "Central registration revoked:",
        item["chain"] + "/" + item["collector"]
    )

    if result.get("publication") == "pending":
        print("Public combined feed refresh: pending")

    return result



def remove_local_collector_files(item):
    """Remove only validated OTB collector resources."""

    # Revalidate before performing any deletion.
    item = validate_managed_collector(item)

    data = item["data"]
    config = item["config"]
    service = item["service"]
    timer = item["timer"]

    token = data / "token"
    observation = data / "observation.json"

    allowed = {"token", "observation.json"}

    # Never recursively delete a directory.
    for entry in data.iterdir():
        if entry.name not in allowed:
            raise RuntimeError(
                "Unexpected file prevents removal: " + str(entry)
            )

        if entry.is_symlink() or not entry.is_file():
            raise RuntimeError(
                "Unsafe private file prevents removal: " + str(entry)
            )

    # Remove only individually validated paths.
    for path in (observation, token, config, timer, service):
        if path.is_symlink():
            raise RuntimeError(
                "Symbolic link prevents removal: " + str(path)
            )

    for path in (observation, token, config, timer, service):
        if path.exists():
            if not path.is_file():
                raise RuntimeError(
                    "Not a regular file: " + str(path)
                )

            path.unlink()
            print("Removed:", path)

    # Will fail safely if anything unexpected remains.
    data.rmdir()

    print("Removed private directory:", data)
    print("Local collector files removed:", item["identity"])



def create_uninstall_transaction(item):
    """Record a validated removal before contacting the server."""
    import stat
    import secrets

    item = validate_managed_collector(item)

    root = Path("/var/lib/otb-collector")

    marker = root / (
        ".uninstall-" + item["identity"] + ".json"
    )

    if marker.exists() or marker.is_symlink():
        raise RuntimeError(
            "Existing uninstall transaction: " + str(marker)
        )

    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("Unsafe collector storage directory")

    if root.stat().st_uid != 0:
        raise RuntimeError("Collector storage root is not root-owned")

    transaction = {
        "version": 1,
        "chain": item["chain"],
        "collector": item["collector"],
        "identity": item["identity"],
        "transaction_id": secrets.token_hex(16),
        "phase": "prepared",
        "central_revocation": "not_requested"
    }

    fd = os.open(
        str(marker),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600
    )

    try:
        with os.fdopen(fd, "w") as f:
            json.dump(transaction, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.chmod(marker, 0o600)

        dir_fd = os.open(str(root), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    except Exception:
        marker.unlink(missing_ok=True)
        raise

    print("Uninstall transaction prepared:", marker)

    return marker



def update_uninstall_transaction(marker, expected_phase, new_phase):
    """Atomically advance an uninstall transaction."""
    import stat
    import tempfile

    marker = Path(marker)

    transitions = {
        "prepared": "revocation_requested",
        "revocation_requested": "revoked",
        "revoked": "local_cleanup_complete"
    }

    if transitions.get(expected_phase) != new_phase:
        raise RuntimeError("Invalid uninstall state transition")

    root = Path("/var/lib/otb-collector")

    if marker.parent != root:
        raise RuntimeError("Unexpected transaction location")

    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("Unsafe or missing transaction marker")

    if marker.stat().st_uid != 0:
        raise RuntimeError("Transaction marker is not root-owned")

    if stat.S_IMODE(marker.stat().st_mode) != 0o600:
        raise RuntimeError("Invalid transaction permissions")

    state = json.loads(marker.read_text())

    if state.get("version") != 1:
        raise RuntimeError("Unknown transaction version")

    chain = state.get("chain")
    collector = state.get("collector")

    if (
        chain not in NETWORKS
        or not isinstance(collector, str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", collector)
        or collector in (".", "..")
    ):
        raise RuntimeError("Invalid transaction identity")

    identity = chain + "-" + collector

    if (
        state.get("identity") != identity
        or marker.name != ".uninstall-" + identity + ".json"
    ):
        raise RuntimeError("Transaction identity mismatch")

    if state.get("phase") != expected_phase:
        raise RuntimeError("Unexpected current transaction phase")

    state["phase"] = new_phase

    state["central_revocation"] = {
        "prepared": "not_requested",
        "revocation_requested": "unconfirmed",
        "revoked": "confirmed",
        "local_cleanup_complete": "confirmed"
    }[new_phase]

    fd, temporary = tempfile.mkstemp(
        prefix=".uninstall-update-",
        dir=str(root)
    )

    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.chmod(temporary, 0o600)
        os.replace(temporary, marker)

        directory_fd = os.open(str(root), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    print("Uninstall transaction phase:", new_phase)
    return state



def recover_local_uninstall(marker):
    """Finish local cleanup after confirmed central revocation."""
    import stat

    marker = Path(marker)
    root = Path("/var/lib/otb-collector")

    # Reject redirected managed-resource directories.
    for directory in (
        Path("/etc/otb-collector"),
        Path("/var/lib/otb-collector"),
        Path("/etc/systemd/system"),
    ):
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError(
                "Unsafe managed-resource directory: " + str(directory)
            )


    if marker.parent != root:
        raise RuntimeError("Unexpected transaction location")

    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("Missing or unsafe uninstall marker")

    if marker.stat().st_uid != 0:
        raise RuntimeError("Uninstall marker owner mismatch")

    if stat.S_IMODE(marker.stat().st_mode) != 0o600:
        raise RuntimeError("Uninstall marker permissions mismatch")

    state = json.loads(marker.read_text())

    if (
        state.get("version") != 1
        or state.get("phase") != "revoked"
        or state.get("central_revocation") != "confirmed"
    ):
        raise RuntimeError("Central revocation not confirmed")

    chain = state.get("chain")
    collector = state.get("collector")
    txid = state.get("transaction_id")

    if (
        chain not in NETWORKS
        or not isinstance(collector, str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", collector)
        or collector in (".", "..")
        or not isinstance(txid, str)
        or not re.fullmatch(r"[0-9a-f]{32}", txid)
    ):
        raise RuntimeError("Invalid transaction identity")

    identity = chain + "-" + collector

    if (
        state.get("identity") != identity
        or marker.name != ".uninstall-" + identity + ".json"
    ):
        raise RuntimeError("Transaction identity mismatch")

    config = Path("/etc/otb-collector") / (identity + ".json")
    data = root / identity
    service = Path("/etc/systemd/system") / (
        "otb-collector-" + identity + ".service"
    )
    timer = Path("/etc/systemd/system") / (
        "otb-collector-" + identity + ".timer"
    )

    # Remove the service definition last so its account
    # remains available for ownership checks during recovery.
    expected = (
        config,
        data / "token",
        data / "observation.json",
        timer,
        service
    )

    for path in (config, data, service, timer) + expected:
        if path.is_symlink():
            raise RuntimeError("Symbolic link rejected: " + str(path))

    if data.exists():
        if not data.is_dir():
            raise RuntimeError("Invalid private data directory")

        allowed = {"token", "observation.json"}

        for entry in data.iterdir():
            if entry.name not in allowed:
                raise RuntimeError(
                    "Unexpected private file: " + str(entry)
                )

            if entry.is_symlink() or not entry.is_file():
                raise RuntimeError(
                    "Unsafe private file: " + str(entry)
                )

    # Inspect all remaining files before deleting any.
    for path in expected:
        if path.exists() and not path.is_file():
            raise RuntimeError("Unexpected file type: " + str(path))

    import configparser

    service_name = service.name
    timer_name = timer.name

    # Never remove units that are still active.
    for unit_name in (timer_name, service_name):
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit_name],
            check=False
        )

        if result.returncode == 0:
            raise RuntimeError(
                "Stop collector unit before cleanup: " + unit_name
            )

        if result.returncode not in (3, 4):
            raise RuntimeError(
                "Cannot verify inactive unit: " + unit_name
            )

    # The selected timer must not be scheduled to restart.
    enabled = subprocess.run(
        ["systemctl", "is-enabled", timer_name],
        capture_output=True,
        text=True,
        check=False
    )

    timer_state = enabled.stdout.strip()

    if timer_state not in ("disabled", "masked", "not-found"):
        raise RuntimeError(
            "Collector timer is not confirmed disabled: "
            + timer_name + " (" + timer_state + ")"
        )

    if service.exists():
        unit = configparser.ConfigParser(interpolation=None)
        unit.read(service)

        expected_exec = (
            "/usr/bin/python3 "
            "/usr/local/lib/otb-collector/otb-run.py "
            "--config " + str(config)
        )

        if (
            unit.get("Service", "Type", fallback="") != "oneshot"
            or unit.get("Service", "WorkingDirectory", fallback="")
                != str(data)
            or unit.get("Service", "ExecStart", fallback="")
                != expected_exec
            or not unit.get("Service", "User", fallback="")
            or unit.get("Unit", "Description", fallback="")
                != "OTB Node Collector - " + chain + "/" + collector
        ):
            raise RuntimeError("Service ownership mismatch")

    if timer.exists():
        timer_config = configparser.ConfigParser(interpolation=None)
        timer_config.read(timer)

        if (
            timer_config.get("Timer", "Unit", fallback="")
                != service_name
            or timer_config.get("Unit", "Description", fallback="")
                != "OTB Node Collector Timer - " + chain + "/" + collector
        ):
            raise RuntimeError("Timer ownership mismatch")

    # Validate any surviving collector configuration.
    if config.exists():
        settings = json.loads(config.read_text())

        if (
            settings.get("chain") != chain
            or settings.get("collector") != collector
            or settings.get("output")
                != str(data / "observation.json")
            or settings.get("token_file")
                != str(data / "token")
        ):
            raise RuntimeError(
                "Collector configuration ownership mismatch"
            )

        ipc = settings.get("ipc")

        if (
            not isinstance(ipc, str)
            or not ipc.startswith("/")
        ):
            raise RuntimeError("Invalid collector IPC path")

    # Verify the surviving service account owns private data.
    if service.exists() and data.exists():
        import pwd

        account = pwd.getpwnam(
            unit.get("Service", "User")
        )

        if data.stat().st_uid != account.pw_uid:
            raise RuntimeError(
                "Private directory owner mismatch"
            )

        token = data / "token"

        if token.exists() and token.stat().st_uid != account.pw_uid:
            raise RuntimeError("Token owner mismatch")

    # Without the service definition, we cannot establish
    # ownership of private files left by an interrupted cleanup.
    if not service.exists() and data.exists():
        if any(data.iterdir()):
            raise RuntimeError(
                "Cannot verify private-file ownership without "
                "the collector service definition"
            )

    # Delete only explicitly named OTB collector files.
    for path in expected:
        if path.exists():
            path.unlink()
            print("Removed:", path)

    if data.exists():
        data.rmdir()
        print("Removed private directory:", data)

    print("Local cleanup completed:", identity)



def finalize_uninstall_transaction(marker):
    """Remove a completed uninstall transaction marker."""
    import stat

    marker = Path(marker)
    root = Path("/var/lib/otb-collector")

    if marker.parent != root:
        raise RuntimeError("Invalid transaction location")

    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("Unsafe transaction directory")

    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("Invalid transaction marker")

    info = marker.stat()

    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise RuntimeError("Unsafe transaction ownership")

    state = json.loads(marker.read_text())

    chain = state.get("chain")
    collector = state.get("collector")
    txid = state.get("transaction_id")

    if (
        chain not in NETWORKS
        or not isinstance(collector, str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", collector)
        or collector in (".", "..")
        or not isinstance(txid, str)
        or not re.fullmatch(r"[0-9a-f]{32}", txid)
    ):
        raise RuntimeError("Invalid transaction identity")

    identity = chain + "-" + collector

    if (
        state.get("version") != 1
        or state.get("identity") != identity
        or marker.name != ".uninstall-" + identity + ".json"
        or state.get("phase") != "local_cleanup_complete"
        or state.get("central_revocation") != "confirmed"
    ):
        raise RuntimeError("Uninstall transaction is not complete")

    paths = (
        Path("/etc/otb-collector") / (identity + ".json"),
        root / identity,
        Path("/etc/systemd/system") /
            ("otb-collector-" + identity + ".service"),
        Path("/etc/systemd/system") /
            ("otb-collector-" + identity + ".timer")
    )

    for path in paths:
        if path.exists() or path.is_symlink():
            raise RuntimeError(
                "Collector resource still exists: " + str(path)
            )

    marker.unlink()

    fd = os.open(str(root), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

    print("Uninstall transaction finalized:", identity)



def execute_collector_uninstall(item):
    """Execute or resume one collector's confirmed uninstall."""
    import stat

    if os.geteuid() != 0:
        raise RuntimeError("Uninstall requires root")

    identity = item["identity"]
    chain = item["chain"]

    if chain not in NETWORKS:
        raise RuntimeError("Unsupported blockchain")

    if not identity.startswith(chain + "-"):
        raise RuntimeError("Invalid collector identity")

    collector = identity[len(chain) + 1:]

    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+", collector)
        or collector in (".", "..")
    ):
        raise RuntimeError("Invalid collector identity")

    item = dict(item)
    item["collector"] = collector

    root = Path("/var/lib/otb-collector")
    marker = root / (".uninstall-" + identity + ".json")

    if marker.is_symlink():
        raise RuntimeError("Unsafe uninstall marker")

    # New uninstall: validate the complete installation.
    if not marker.exists():
        item = validate_managed_collector(item)
        marker = create_uninstall_transaction(item)

    # Existing uninstall: verify the transaction before resuming.
    if not marker.is_file():
        raise RuntimeError("Missing uninstall transaction")

    if (
        marker.stat().st_uid != 0
        or stat.S_IMODE(marker.stat().st_mode) != 0o600
    ):
        raise RuntimeError("Unsafe transaction permissions")

    state = json.loads(marker.read_text())

    if (
        state.get("version") != 1
        or state.get("identity") != identity
        or state.get("chain") != item["chain"]
        or state.get("collector") != item["collector"]
        or not isinstance(state.get("transaction_id"), str)
        or not re.fullmatch(
            r"[0-9a-f]{32}", state["transaction_id"]
        )
    ):
        raise RuntimeError("Uninstall transaction mismatch")

    phase = state.get("phase")

    print("\n===== UNINSTALL TRANSACTION =====")
    print("Collector:", identity)
    print("Current phase:", phase)

    if phase == "prepared":
        # Check ownership again before touching systemd.
        validate_managed_collector(item)

        timer = item["timer"].name
        service = item["service"].name

        print("Disabling timer:", timer)
        subprocess.run(
            ["systemctl", "disable", "--now", timer],
            check=True
        )

        print("Stopping collector service:", service)
        subprocess.run(
            ["systemctl", "stop", service],
            check=True
        )

        # Mark the network operation as potentially initiated
        # before sending any credentials to the server.
        update_uninstall_transaction(
            marker, "prepared", "revocation_requested"
        )
        phase = "revocation_requested"

    if phase == "revocation_requested":
        # A resumed uninstall must not revoke credentials
        # while its collector is running or scheduled.
        timer = item["timer"].name
        service = item["service"].name

        for name in (timer, service):
            result = subprocess.run(
                ["systemctl", "is-active", "--quiet", name],
                check=False
            )

            if result.returncode not in (3, 4):
                raise RuntimeError(
                    "Collector unit must be inactive: " + name
                )

        enabled = subprocess.run(
            ["systemctl", "is-enabled", timer],
            capture_output=True,
            text=True,
            check=False
        )

        if enabled.stdout.strip() not in (
            "disabled", "masked", "not-found"
        ):
            raise RuntimeError(
                "Collector timer must be disabled: " + timer
            )

        # An interrupted request is retried using the same
        # transaction ID and authentication token.
        revoke_collector_registration(item)

        update_uninstall_transaction(
            marker, "revocation_requested", "revoked"
        )
        phase = "revoked"

    if phase == "revoked":
        recover_local_uninstall(marker)

        subprocess.run(
            ["systemctl", "daemon-reload"],
            check=True
        )

        update_uninstall_transaction(
            marker, "revoked", "local_cleanup_complete"
        )
        phase = "local_cleanup_complete"

    if phase == "local_cleanup_complete":
        # Also handles a crash after the state changed,
        # but before the marker was removed.
        subprocess.run(
            ["systemctl", "daemon-reload"],
            check=True
        )

        finalize_uninstall_transaction(marker)

        print("\nUNINSTALL COMPLETE:", identity)
        print("Geth and blockchain data were not removed.")
        return

    raise RuntimeError("Unknown uninstall phase: " + str(phase))



def uninstall_collectors():
    """Select and confirm individual managed collector removals."""
    import stat

    if os.geteuid() != 0:
        raise SystemExit("Uninstall requires sudo")

    config_root = Path("/etc/otb-collector")
    data_root = Path("/var/lib/otb-collector")
    unit_root = Path("/etc/systemd/system")

    found = {}

    def make_item(chain, collector):
        identity = chain + "-" + collector

        return {
            "identity": identity,
            "chain": chain,
            "collector": collector,
            "config": config_root / (identity + ".json"),
            "data": data_root / identity,
            "service": unit_root / (
                "otb-collector-" + identity + ".service"
            ),
            "timer": unit_root / (
                "otb-collector-" + identity + ".timer"
            )
        }

    if config_root.is_dir():
        for config in sorted(config_root.glob("*.json")):
            try:
                if config.is_symlink():
                    raise RuntimeError("Symbolic link")

                settings = json.loads(config.read_text())
                chain = settings["chain"]
                collector = settings["collector"]

                if chain not in NETWORKS:
                    raise RuntimeError("Unsupported chain")

                if (
                    not isinstance(collector, str)
                    or not re.fullmatch(
                        r"[A-Za-z0-9_.-]+", collector
                    )
                    or collector in (".", "..")
                ):
                    raise RuntimeError("Invalid collector")

                item = make_item(chain, collector)

                if config != item["config"]:
                    raise RuntimeError("Configuration filename mismatch")

                found[item["identity"]] = item

            except Exception as exc:
                raise RuntimeError(
                    "Unsafe collector configuration "
                    + str(config) + ": " + str(exc)
                )

    if data_root.is_dir():
        for marker in sorted(data_root.glob(".uninstall-*.json")):
            if marker.is_symlink() or not marker.is_file():
                raise RuntimeError(
                    "Unsafe transaction marker: " + str(marker)
                )

            info = marker.stat()

            if (
                info.st_uid != 0
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise RuntimeError(
                    "Unsafe transaction ownership: " + str(marker)
                )

            state = json.loads(marker.read_text())
            chain = state.get("chain")
            collector = state.get("collector")

            if (
                chain not in NETWORKS
                or not isinstance(collector, str)
                or not re.fullmatch(
                    r"[A-Za-z0-9_.-]+", collector
                )
                or collector in (".", "..")
            ):
                raise RuntimeError("Invalid transaction identity")

            item = make_item(chain, collector)

            if (
                state.get("version") != 1
                or state.get("identity") != item["identity"]
                or marker.name != (
                    ".uninstall-" + item["identity"] + ".json"
                )
                or state.get("phase") not in (
                    "prepared",
                    "revocation_requested",
                    "revoked",
                    "local_cleanup_complete"
                )
                or not isinstance(
                    state.get("transaction_id"), str
                )
                or not re.fullmatch(
                    r"[0-9a-f]{32}",
                    state["transaction_id"]
                )
            ):
                raise RuntimeError("Invalid transaction marker")

            found[item["identity"]] = item

    if not found:
        print("No OTB collector installations found.")
        return

    items = [found[name] for name in sorted(found)]

    print("\n===== SELECTIVE COLLECTOR UNINSTALL =====")

    for index, item in enumerate(items, 1):
        marker = data_root / (
            ".uninstall-" + item["identity"] + ".json"
        )

        if marker.exists():
            phase = json.loads(marker.read_text())["phase"]
            status = "RESUME: " + phase
        else:
            status = "INSTALLED"

        print("[%d] %s [%s]" % (
            index, item["identity"], status
        ))

    print("[A] All listed collectors")
    print("[Q] Cancel")

    choice = input(
        "\nSelect collector number(s), e.g. 1,2 or A: "
    ).strip().lower()

    if choice in ("", "q"):
        print("Cancelled.")
        return

    if choice == "a":
        selected = items
    else:
        try:
            indexes = sorted({
                int(value.strip()) - 1
                for value in choice.split(",")
            })
        except ValueError:
            raise SystemExit("Invalid selection")

        if not indexes or any(
            index < 0 or index >= len(items)
            for index in indexes
        ):
            raise SystemExit("Selection out of range")

        selected = [items[index] for index in indexes]

    print("\n===== FINAL REMOVAL PLAN =====")

    for item in selected:
        marker = data_root / (
            ".uninstall-" + item["identity"] + ".json"
        )

        if not marker.exists():
            validate_managed_collector(item)

        print("\nCollector:", item["identity"])
        print("Service:", item["service"])
        print("Timer:", item["timer"])
        print("Configuration:", item["config"])
        print("Private data:", item["data"])
        print("Central registration: revoke or confirm revocation")

    print("\nGeth services and blockchain data will be preserved.")

    confirmation = input(
        "\nType UNINSTALL to confirm removal: "
    ).strip()

    if confirmation != "UNINSTALL":
        print("Cancelled. No changes made.")
        return

    for item in selected:
        print("\nProcessing:", item["identity"])

        try:
            execute_collector_uninstall(item)
        except Exception as exc:
            print("UNINSTALL INCOMPLETE:", item["identity"])
            print("Reason:", exc)
            print("Transaction preserved for recovery.")
            raise SystemExit(1)


if __name__ == "__main__":
    main()
