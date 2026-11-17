#!/usr/bin/env python3
"""Run the preserved original OTB publisher bytecode."""
import importlib.util
import marshal
from pathlib import Path

source = Path(__file__).resolve()
cache = source.parent / "otb-bytecode-recovery/live-publisher.pyc"
data = cache.read_bytes()

if data[:4] != importlib.util.MAGIC_NUMBER:
    raise RuntimeError("Publisher bytecode version mismatch")

code = marshal.loads(data[16:])

exec(code, {
    "__name__": "__main__",
    "__file__": str(source),
    "__package__": None,
    "__cached__": str(cache),
    "__builtins__": __builtins__,
})


# Preserve the original publisher's processing and enrich only
# the authenticated collector nodes with installer version metadata.
def publish_collector_versions():
    import json
    import os
    import re
    import tempfile

    base = Path("/home/def/otb-node-directory")
    incoming = base / "incoming"
    output = Path("/var/www/nodelist.outsidethebox.top/feeds")

    valid_version = re.compile(
        r"v[0-9]+\.[0-9]+\.[0-9]+(?:-beta)?"
    )

    for chain in ("etho", "etica"):
        feed_path = output / chain / "all.json"

        if not feed_path.is_file():
            continue

        feed = json.loads(feed_path.read_text())
        active = set(feed.get("sources", []))
        versions = {}

        for collector in active:
            if not isinstance(collector, str):
                continue
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", collector):
                continue
            if collector in (".", ".."):
                continue

            source_path = incoming / chain / (collector + ".json")

            if not source_path.is_file() or source_path.is_symlink():
                continue

            observation = json.loads(source_path.read_text())

            if observation.get("collector") != collector:
                continue

            for node in observation.get("nodes", []):
                if not isinstance(node, dict):
                    continue
                if node.get("collector") is not True:
                    continue

                version = node.get("collector_app_version")

                if (
                    isinstance(version, str)
                    and valid_version.fullmatch(version)
                    and isinstance(node.get("id"), str)
                ):
                    versions[node["id"]] = version

        for target in [feed_path] + [
            output / chain / (name + ".json")
            for name in active
            if isinstance(name, str)
            and re.fullmatch(r"[A-Za-z0-9_.-]+", name)
            and name not in (".", "..")
        ]:
            if not target.is_file() or target.is_symlink():
                continue

            data = json.loads(target.read_text())
            changed = False

            for node in data.get("nodes", []):
                if not isinstance(node, dict):
                    continue

                version = versions.get(node.get("id"))

                if node.get("collector") is True and version:
                    if node.get("collector_app_version") != version:
                        node["collector_app_version"] = version
                        changed = True

            if not changed:
                continue

            fd, temporary = tempfile.mkstemp(
                prefix=".version-",
                dir=str(target.parent)
            )

            try:
                with os.fdopen(fd, "w") as handle:
                    json.dump(data, handle, separators=(",", ":"))
                    handle.write("\n")
                os.chmod(temporary, 0o640)
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

            print("Collector versions published:", target)


publish_collector_versions()
