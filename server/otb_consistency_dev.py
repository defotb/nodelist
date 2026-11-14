#!/usr/bin/env python3
"""Cross-file registration consistency checks — development."""

def validate(tokens, config, registry):
    if not all(isinstance(x, dict) for x in
               (tokens, config, registry)):
        raise ValueError("Registration data must be objects")

    chains = config.get("chains")
    records_by_chain = registry.get("collectors")

    if not isinstance(chains, dict):
        raise ValueError("Invalid blockchain configuration")

    if not isinstance(records_by_chain, dict):
        raise ValueError("Invalid collector registry")

    if set(tokens) != set(chains):
        raise ValueError("Credential blockchain mismatch")

    if set(records_by_chain) != set(chains):
        raise ValueError("Registry blockchain mismatch")

    for chain, settings in chains.items():
        approved = settings.get("collectors")
        credentials = tokens[chain]
        records = records_by_chain[chain]

        if not isinstance(approved, list):
            raise ValueError("Invalid approved collector list")

        if not isinstance(credentials, dict):
            raise ValueError("Invalid credentials")

        if not isinstance(records, dict):
            raise ValueError("Invalid collector records")

        if len(approved) != len(set(approved)):
            raise ValueError("Duplicate approved collector")

        active = {
            name for name, record in records.items()
            if record["status"] != "revoked"
        }

        if set(credentials) != active:
            raise ValueError("Credential/registry mismatch")

        if not set(approved).issubset(records):
            raise ValueError("Approved collector missing registry")

        for name, record in records.items():
            status = record["status"]
            has_token = name in credentials
            is_approved = name in approved

            if status in ("enabled", "suspended"):
                if not has_token or not is_approved:
                    raise ValueError(
                        "Incomplete approved collector: " + name
                    )

            elif status == "pending":
                if not has_token or is_approved:
                    raise ValueError(
                        "Inconsistent pending collector: " + name
                    )

            elif status == "revoked":
                if has_token or is_approved:
                    raise ValueError(
                        "Revoked collector remains active: " + name
                    )

            else:
                raise ValueError("Invalid collector status")

            if has_token:
                token = credentials[name]
                if not isinstance(token, str) or not token:
                    raise ValueError(
                        "Invalid collector credential: " + name
                    )

    return True
