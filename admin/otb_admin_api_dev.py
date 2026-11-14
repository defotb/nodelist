#!/usr/bin/env python3
"""OTB administrator HTTP API — isolated development."""

from pathlib import Path
import threading
import fcntl
import re
import os
import json
from flask import Flask, jsonify, request, make_response, send_file

from otb_admin_auth_dev import SessionStore
from otb_admin_accounts_dev import authenticate_account
from otb_admin_limit_dev import LoginLimiter
import otb_registry_dev
from otb_admin_adapter_dev import load_engine
from otb_admin_audit_dev import append_event
from otb_admin_operations_dev import (
    open_private_directory, validate_id
)
from otb_admin_reconcile_dev import inspect_operation
from otb_admin_directory_dev import (
    open_registration_directory,
    open_engine_directory,
    open_private_member
)
from otb_admin_reconcile_dev import validate_registry_data
from otb_admin_dispatch_dev import dispatch
from otb_admin_csrf_dev import (
    create_csrf_token, verify_csrf_token
)

COOKIE = "otb_admin_session"
ORIGIN = "https://nodelist.outsidethebox.top"


def create_app(account_path, origin=ORIGIN, registration_dir=None, engine_root=None, audit_path=None, dashboard_dir=None, ledger_root=None):
    """Construct an isolated API without starting a server."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 4096

    account_path = Path(account_path)
    # Preserve path components for symlink validation.
    # resolve() would erase evidence of a symlinked parent.
    registration_dir = (
        Path(registration_dir).absolute()
        if registration_dir is not None else None
    )

    # Administrator writes require an explicit audit destination.
    audit_path = (
        Path(audit_path).absolute()
        if audit_path is not None else None
    )

    # Transaction support is opt-in. The adapter validates
    # all transaction and enrollment paths.
    admin_engine = None

    if engine_root is not None:
        engine_root = Path(engine_root).absolute()

        # Reject symlinked engine paths before load_engine()
        # resolves them into canonical paths.
        with open_engine_directory(engine_root):
            pass

        admin_engine = load_engine(engine_root)
        engine_db = admin_engine.BASE.resolve()

        if registration_dir is not None:
            if registration_dir != engine_db:
                raise ValueError(
                    "Administrator database path mismatch"
                )

        registration_dir = engine_db

    # Validate the configured path before any registration reads.
    # Opening every component without following symlinks also
    # verifies the final directory is private.
    if registration_dir is not None:
        with open_registration_directory(registration_dir):
            pass

    # An audit destination is valid only alongside an
    # explicitly selected isolated transaction engine.
    if audit_path is not None:
        if admin_engine is None:
            raise ValueError(
                "Audit destination requires isolated engine"
            )

        isolated_root = Path(engine_root).resolve(strict=True)

        if audit_path.name != "admin-audit.jsonl":
            raise ValueError("Invalid administrator audit filename")

        if audit_path.parent.resolve(strict=True) != isolated_root:
            raise ValueError(
                "Audit destination outside isolated root"
            )

        if audit_path.is_symlink():
            raise ValueError("Symlinked audit destination")

        if audit_path.exists() and not audit_path.is_file():
            raise ValueError("Invalid audit destination")

    # Keep the isolated engine attached to this Flask
    # application for subsequent development integration.
    # Coordinated writes are opt-in and initially blocked.
    # Their routes must all be integrated before enabling writes.
    if ledger_root is not None:
        if admin_engine is None or audit_path is None:
            raise ValueError(
                "Coordinated mode requires engine and audit"
            )

        ledger_root = Path(ledger_root)

        if ledger_root.name != "admin-operations":
            raise ValueError("Invalid operation directory name")

        if ledger_root.is_symlink():
            raise ValueError("Symlinked operation directory")

        isolated_root = Path(engine_root).resolve(strict=True)

        if ledger_root.parent.resolve(strict=True) != isolated_root:
            raise ValueError(
                "Operation directory outside isolated engine root"
            )

        with open_private_directory(ledger_root):
            pass

    app.extensions["otb_admin_ledger_root"] = ledger_root
    app.extensions["otb_admin_engine"] = admin_engine
    sessions = SessionStore()
    limiter = LoginLimiter()

    # Serialize the complete login decision.
    login_mutex = threading.Lock()

    @app.after_request
    def secure_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def error(status, message):
        return jsonify({"error": message}), status

    def same_origin():
        return (
            request.headers.get("Origin") == origin
            and request.headers.get("Sec-Fetch-Site", "same-origin")
                in ("same-origin", "none")
        )

    def current_session():
        token = request.cookies.get(COOKIE)
        username = sessions.authenticate(token)
        return token, username

    def audited_action(username, action, chain, collector, operation):
        """Record an attempt before executing an administrator action."""

        if ledger_root is not None:
            data = request.get_json(silent=True)
            operation_id = (
                data.get("operation_id")
                if isinstance(data, dict) else None
            )

            status, body = dispatch(
                ledger_root,
                audit_path,
                operation_id,
                username,
                action,
                chain,
                collector,
                operation
            )

            # Always return the dispatcher's HTTP response.
            # Never fall through to the legacy transaction.
            return None, (jsonify(body), status)

        try:
            append_event(
                audit_path, username, action,
                chain, collector, "attempt"
            )
        except (OSError, ValueError, TypeError):
            app.logger.error("Administrator audit attempt failed")
            return None, error(
                503, "Audit unavailable; action not started"
            )

        failure = None

        try:
            result = operation()
        except ValueError:
            result = None
            outcome = "rejected"
            failure = error(409, "Collector action rejected")
        except Exception:
            result = None
            outcome = "error"
            app.logger.error("Administrator transaction failed")
            failure = error(503, "Collector transaction unavailable")
        else:
            outcome = "success"

        try:
            append_event(
                audit_path, username, action,
                chain, collector, outcome
            )
        except (OSError, ValueError, TypeError):
            app.logger.error("Administrator audit outcome failed")
            return None, error(
                503,
                "Transaction result requires verification; "
                "audit outcome unavailable"
            )

        return result, failure

    # Development dashboard serving is explicitly opt-in.
    # Do not expose these routes through public nginx.
    if dashboard_dir is not None:
        dashboard_dir = Path(dashboard_dir).resolve(strict=True)

        files = {
            "/admin/": (
                "admin-dashboard-dev.html", "text/html"
            ),
            "/admin/admin-dashboard-dev.css": (
                "admin-dashboard-dev.css", "text/css"
            ),
            "/admin/admin-dashboard-dev.js": (
                "admin-dashboard-dev.js", "text/javascript"
            )
        }

        for filename, _ in files.values():
            target = dashboard_dir / filename
            if not target.is_file() or target.is_symlink():
                raise ValueError("Missing or unsafe dashboard asset")
            if target.resolve().parent != dashboard_dir:
                raise ValueError("Dashboard asset escapes directory")

        csp = (
            "default-src 'none'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "connect-src 'self'; "
            "img-src 'self'; "
            "base-uri 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "object-src 'none'"
        )

        def serve_dashboard(path):
            filename, content_type = files[path]
            response = make_response(send_file(
                dashboard_dir / filename,
                mimetype=content_type
            ))
            response.headers["Content-Security-Policy"] = csp
            response.headers["X-Frame-Options"] = "DENY"
            return response

        for index, path in enumerate(files):
            app.add_url_rule(
                path,
                endpoint="otb_dashboard_asset_" + str(index),
                view_func=lambda path=path: serve_dashboard(path),
                methods=["GET"]
            )

    @app.post("/admin/api/login")
    def login():
        if not same_origin():
            return error(403, "Origin rejected")

        if not request.is_json:
            return error(415, "JSON required")

        with login_mutex:
            if not limiter.allowed():
                response = make_response(
                    jsonify({"error": "Login temporarily locked"}), 429
                )
                response.headers["Retry-After"] = str(
                    limiter.retry_after()
                )
                return response

            data = request.get_json(silent=True)

            if not isinstance(data, dict):
                return error(400, "Invalid request")

            username = data.get("username")
            password = data.get("password")

            if not isinstance(username, str) or not isinstance(
                password, str
            ):
                return error(400, "Invalid request")

            if not account_path.is_file():
                return error(503, "Administrator not configured")

            try:
                authenticated = authenticate_account(
                    account_path, username, password
                )
            except (ValueError, TypeError, OSError):
                app.logger.error(
                    "Administrator credential storage unavailable"
                )
                return error(503, "Authentication unavailable")

            if not authenticated:
                limiter.record_failure()
                return error(401, "Invalid credentials")

            if not limiter.record_success():
                return error(429, "Login temporarily locked")

            old_token, _ = current_session()
            if old_token:
                sessions.revoke(old_token)

            token = sessions.create(username)

            response = make_response(
                jsonify({"status": "authenticated", "username": username})
            )

            response.set_cookie(
                COOKIE, token,
                secure=True,
                httponly=True,
                samesite="Strict",
                path="/admin/api",
                max_age=sessions.lifetime
            )

            return response

    @app.get("/admin/api/session")
    def session_status():
        token, username = current_session()

        if username is None:
            return error(401, "Authentication required")

        return jsonify({
            "authenticated": True,
            "username": username,
            "csrf_token": create_csrf_token(token)
        })

    @app.get("/admin/api/operations/<operation_id>")
    def inspect_operation_http(operation_id):
        """Read-only operation evidence; never modify registrations."""

        token, username = current_session()

        if username is None:
            return error(401, "Authentication required")

        if ledger_root is None:
            return error(404, "Endpoint unavailable")

        try:
            validate_id(operation_id)
        except (ValueError, TypeError):
            return error(400, "Invalid operation ID")

        try:
            evidence = inspect_operation(
                ledger_root,
                audit_path,
                registration_dir,
                operation_id,
                include_assessment=True
            )
        except (OSError, ValueError, TypeError, KeyError):
            app.logger.error(
                "Administrator operation inspection unavailable"
            )
            return error(503, "Operation inspection unavailable")

        allowed = {
            "operation_id", "administrator", "action",
            "chain", "collector", "ledger_state",
            "audit_events", "journal_present",
            "collector_status", "collector_last_action",
            "collector_updated_at", "requires_manual_review",
            "automatic_resolution", "assessment"
        }

        if not isinstance(evidence, dict) or set(evidence) != allowed:
            return error(503, "Invalid operation inspection result")

        if evidence["automatic_resolution"] is not False:
            return error(503, "Invalid operation inspection result")

        assessment = evidence["assessment"]

        assessment_fields = {
            "classification", "reason", "ledger_state",
            "registration_consistent", "journal_present",
            "audit_outcomes", "requires_manual_review",
            "automatic_resolution", "collector_unlock_allowed"
        }

        if (
            not isinstance(assessment, dict)
            or set(assessment) != assessment_fields
            or assessment["ledger_state"] != evidence["ledger_state"]
            or assessment["journal_present"] is not evidence["journal_present"]
            or assessment["requires_manual_review"]
                is not evidence["requires_manual_review"]
            or assessment["automatic_resolution"] is not False
            or assessment["collector_unlock_allowed"] is not False
        ):
            return error(503, "Invalid reconciliation assessment")

        return jsonify(evidence)

    @app.get("/admin/api/collectors")
    def collector_listing():
        token, username = current_session()

        if username is None:
            return error(401, "Authentication required")

        if registration_dir is None:
            return error(503, "Collector registry unavailable")

        try:
            # Open files relative to one verified registration directory.
            with open_registration_directory(registration_dir) as directory_fd:
                with open_private_member(
                    directory_fd, "enroll.lock"
                ) as lock_fd:
                    # Preserve the endpoint's existing exclusive lock.
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)

                    try:
                        try:
                            with open_private_member(
                                directory_fd,
                                "enroll-transaction.json"
                            ):
                                pass
                        except FileNotFoundError:
                            journal_present = False
                        else:
                            journal_present = True

                        if journal_present:
                            return error(
                                503, "Registration recovery required"
                            )

                        with open_private_member(
                            directory_fd,
                            "collector-status.json"
                        ) as registry_fd:
                            with os.fdopen(
                                os.dup(registry_fd), "r"
                            ) as handle:
                                registry = validate_registry_data(
                                    json.load(handle)
                                )
                    finally:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)

            collectors = []

            # Explicit allowlist: never serialize entire records.
            visible = (
                "status",
                "node_id",
                "created_at",
                "updated_at",
                "expires_at",
                "last_action"
            )

            for chain, entries in registry["collectors"].items():
                for name, record in entries.items():
                    item = {
                        "chain": chain,
                        "collector": name
                    }

                    for field in visible:
                        if field in record:
                            item[field] = record[field]

                    collectors.append(item)

            collectors.sort(
                key=lambda x: (x["chain"], x["collector"])
            )

            return jsonify({
                "collectors": collectors,
                "total": len(collectors)
            })

        except (OSError, ValueError, TypeError, KeyError):
            app.logger.error("Collector registry read failed")
            return error(503, "Collector registry unavailable")

    @app.post("/admin/api/collectors/approve")
    def approve_collector_http():
        token, username = current_session()

        if username is None:
            return error(401, "Authentication required")

        if not same_origin():
            return error(403, "Origin rejected")

        if not verify_csrf_token(
            token, request.headers.get("X-CSRF-Token")
        ):
            return error(403, "CSRF rejected")

        if admin_engine is None or audit_path is None:
            return error(503, "Administrator actions unavailable")

        if not request.is_json:
            return error(415, "JSON required")

        data = request.get_json(silent=True)

        if not isinstance(data, dict) or set(data) != (
            {"chain", "collector", "operation_id"}
            if ledger_root is not None
            else {"chain", "collector"}
        ):
            return error(400, "Invalid approval request")

        chain = data["chain"]
        collector = data["collector"]

        safe = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

        if not (
            isinstance(chain, str)
            and isinstance(collector, str)
            and safe.fullmatch(chain)
            and safe.fullmatch(collector)
        ):
            return error(400, "Invalid blockchain or collector")

        result, failure = audited_action(
            username, "approve", chain, collector,
            lambda: admin_engine.approve_collector(chain, collector)
        )

        if failure is not None:
            return failure

        return jsonify({
            "status": "approved",
            "collector": result
        })

    @app.post("/admin/api/collectors/status")
    def set_collector_status_http():
        token, username = current_session()

        if username is None:
            return error(401, "Authentication required")

        if not same_origin():
            return error(403, "Origin rejected")

        if not verify_csrf_token(
            token, request.headers.get("X-CSRF-Token")
        ):
            return error(403, "CSRF rejected")

        if admin_engine is None or audit_path is None:
            return error(503, "Administrator actions unavailable")

        if not request.is_json:
            return error(415, "JSON required")

        data = request.get_json(silent=True)

        if not isinstance(data, dict) or set(data) != (
            {"chain", "collector", "enabled", "operation_id"}
            if ledger_root is not None
            else {"chain", "collector", "enabled"}
        ):
            return error(400, "Invalid status request")

        chain = data["chain"]
        collector = data["collector"]
        enabled = data["enabled"]

        safe = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

        if not (
            isinstance(chain, str)
            and isinstance(collector, str)
            and safe.fullmatch(chain)
            and safe.fullmatch(collector)
            and isinstance(enabled, bool)
        ):
            return error(400, "Invalid status parameters")

        action = "enable" if enabled else "suspend"

        result, failure = audited_action(
            username, action, chain, collector,
            lambda: admin_engine.set_collector_enabled(
                chain, collector, enabled
            )
        )

        if failure is not None:
            return failure

        return jsonify({
            "status": "updated",
            "collector": result
        })

    def collector_removal_http(action):
        """Shared authorization and validation for removal actions."""

        token, username = current_session()

        if username is None:
            return error(401, "Authentication required")

        if not same_origin():
            return error(403, "Origin rejected")

        if not verify_csrf_token(
            token, request.headers.get("X-CSRF-Token")
        ):
            return error(403, "CSRF rejected")

        if admin_engine is None or audit_path is None:
            return error(503, "Administrator actions unavailable")

        if not request.is_json:
            return error(415, "JSON required")

        data = request.get_json(silent=True)

        if not isinstance(data, dict) or set(data) != (
            {"chain", "collector", "operation_id"}
            if ledger_root is not None
            else {"chain", "collector"}
        ):
            return error(400, "Invalid removal request")

        chain = data["chain"]
        collector = data["collector"]

        safe = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

        if not (
            isinstance(chain, str)
            and isinstance(collector, str)
            and safe.fullmatch(chain)
            and safe.fullmatch(collector)
        ):
            return error(400, "Invalid blockchain or collector")

        if action == "deny":
            operation = lambda: admin_engine.deny_collector(
                chain, collector
            )
        elif action == "revoke":
            operation = lambda: admin_engine.revoke_collector(
                chain, collector
            )
        else:
            return error(400, "Invalid administrator action")

        result, failure = audited_action(
            username, action, chain, collector, operation
        )

        if failure is not None:
            return failure

        return jsonify({
            "status": "denied" if action == "deny" else "revoked",
            "collector": result
        })

    @app.post("/admin/api/collectors/deny")
    def deny_collector_http():
        return collector_removal_http("deny")

    @app.post("/admin/api/collectors/revoke")
    def revoke_collector_http():
        return collector_removal_http("revoke")

    @app.post("/admin/api/logout")
    def logout():
        if not same_origin():
            return error(403, "Origin rejected")

        token, username = current_session()

        if username is None:
            return error(401, "Authentication required")

        supplied = request.headers.get("X-CSRF-Token")

        if not verify_csrf_token(token, supplied):
            return error(403, "CSRF rejected")

        sessions.revoke(token)

        response = make_response(jsonify({"status": "logged_out"}))

        response.delete_cookie(
            COOKIE,
            path="/admin/api",
            secure=True,
            httponly=True,
            samesite="Strict"
        )

        return response

    return app
