#!/usr/bin/env python3
"""Private OTB Administrator v2.1.0-dev browser preview."""

from pathlib import Path
from otb_admin_api_dev import create_app

PROJECT = Path("/home/def/otb-node-directory")

app = create_app(
    account_path=PROJECT / "admin-private/accounts.json",
    origin="https://nodelist.outsidethebox.top",
    # Live production collector registry, read-only.
    registration_dir=PROJECT / "private",
    engine_root=None,
    audit_path=None,
    ledger_root=None,
    dashboard_dir=PROJECT
)


from flask import request, jsonify

@app.before_request
def production_readonly_guard():
    if (
        request.method == "POST"
        and request.path not in (
            "/admin/api/login",
            "/admin/api/logout"
        )
    ):
        return jsonify({
            "error": "Production management is not yet enabled"
        }), 503


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8790,
        debug=False,
        use_reloader=False
    )
