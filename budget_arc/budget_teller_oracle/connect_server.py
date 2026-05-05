from __future__ import annotations

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import AppConfig
from .crypto import TokenCipher
from .db import BudgetStore, connect
from .signature import verify_teller_enrollment_signature
from .sync import sync_connection
from .teller import TellerAPIError, TellerClient


class ConnectState:
    def __init__(self, config: AppConfig):
        self.config = config
        self.nonce = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        self.last_event: dict[str, Any] = {
            "type": "server_started",
            "message": "Waiting for Teller Connect enrollment",
        }

    def rotate(self) -> None:
        self.nonce = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)

    def remember(self, event_type: str, message: str, **details: Any) -> None:
        self.last_event = {
            "type": event_type,
            "message": message,
            **details,
        }


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler: BaseHTTPRequestHandler, body: str) -> None:
    encoded = body.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' https://cdn.teller.io https://*.teller.io 'unsafe-inline'; "
        "connect-src 'self' https://api.teller.io https://cdn.teller.io https://connect.teller.io https://teller.io https://*.teller.io; "
        "frame-src https://connect.teller.io https://teller.io https://*.teller.io; "
        "child-src https://connect.teller.io https://teller.io https://*.teller.io; "
        "img-src 'self' data: https://teller.io https://*.teller.io; "
        "style-src 'self' https://teller.io https://*.teller.io 'unsafe-inline'; "
        "font-src 'self' https://teller.io https://*.teller.io",
    )
    handler.end_headers()
    handler.wfile.write(encoded)


def _connect_page() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Teller Oracle Test Connection</title>
    <style>
      body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; max-width: 760px; }
      button { font-size: 1rem; padding: .75rem 1rem; cursor: pointer; }
      pre { background: #f6f8fa; padding: 1rem; overflow: auto; white-space: pre-wrap; }
      .warn { border-left: 4px solid #c97a00; padding-left: 1rem; }
    </style>
  </head>
  <body>
    <h1>Teller Oracle Test Connection</h1>
    <p class="warn">
      This local page should only be used on a trusted machine. Teller handles bank credentials;
      this app receives an access token and encrypts it before storing it in Oracle.
    </p>
    <button id="connect">Connect with Teller</button>
    <pre id="status">Loading configuration...</pre>
    <script src="https://cdn.teller.io/connect/connect.js"></script>
    <script>
      const status = document.getElementById("status");
      const button = document.getElementById("connect");

      async function main() {
        const configResponse = await fetch("/api/config", { cache: "no-store" });
        const config = await configResponse.json();
        if (!config.ok) {
          status.textContent = JSON.stringify(config, null, 2);
          button.disabled = true;
          return;
        }

        status.textContent = `Ready. Environment: ${config.environment}`;
        const tellerConnect = TellerConnect.setup({
          applicationId: config.applicationId,
          environment: config.environment,
          products: config.products,
          selectAccount: "multiple",
          nonce: config.nonce,
          institution: config.institutionId || undefined,
          onSuccess: async function(enrollment) {
            status.textContent = "Enrollment received. Encrypting token and syncing data...";
            const response = await fetch("/api/teller/enrollment", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": config.csrfToken
              },
              body: JSON.stringify({ nonce: config.nonce, enrollment })
            });
            const payload = await response.json();
            status.textContent = JSON.stringify(payload, null, 2);
          },
          onExit: function() {
            status.textContent = "Teller Connect closed without a completed enrollment.";
          }
        });

        button.addEventListener("click", function() {
          tellerConnect.open();
        });
      }

      main().catch(function(error) {
        status.textContent = "Local setup error: " + error.message;
        button.disabled = true;
      });
    </script>
  </body>
</html>
"""


def make_handler(state: ConnectState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            # Avoid logging URLs or request bodies that could accidentally include sensitive data.
            print(f"{self.address_string()} {self.command} {self.path.split('?', 1)[0]}")

        def do_GET(self) -> None:
            if self.path == "/" or self.path.startswith("/?"):
                _html_response(self, _connect_page())
                return

            if self.path == "/api/config":
                cfg = state.config
                _json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "applicationId": cfg.teller.application_id,
                        "environment": cfg.teller.environment,
                        "products": ["transactions", "balance"],
                        "nonce": state.nonce,
                        "csrfToken": state.csrf_token,
                        "institutionId": cfg.teller.institution_id,
                    },
                )
                return

            if self.path == "/api/status":
                _json_response(self, 200, {"ok": True, "lastEvent": state.last_event})
                return

            _json_response(self, 404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:
            if self.path != "/api/teller/enrollment":
                _json_response(self, 404, {"ok": False, "error": "not_found"})
                return

            expected_origin = f"http://{state.config.server.host}:{state.config.server.port}"
            origin = self.headers.get("Origin")
            if origin and origin not in {expected_origin, f"http://localhost:{state.config.server.port}"}:
                state.remember("blocked", "Rejected enrollment callback origin", origin=origin)
                _json_response(self, 403, {"ok": False, "error": "origin_check_failed"})
                return

            content_type = self.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                state.remember("blocked", "Rejected non-JSON enrollment callback")
                _json_response(self, 415, {"ok": False, "error": "json_required"})
                return

            if not secrets.compare_digest(self.headers.get("X-CSRF-Token") or "", state.csrf_token):
                state.remember("blocked", "Rejected enrollment callback CSRF token")
                _json_response(self, 403, {"ok": False, "error": "csrf_check_failed"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1_000_000:
                    state.remember("blocked", "Rejected invalid enrollment callback size", length=length)
                    _json_response(self, 413, {"ok": False, "error": "invalid_request_size"})
                    return
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                nonce = payload.get("nonce")
                if not secrets.compare_digest(nonce or "", state.nonce):
                    state.remember("blocked", "Rejected enrollment callback nonce")
                    _json_response(self, 400, {"ok": False, "error": "nonce_mismatch"})
                    return

                enrollment_payload = payload["enrollment"]
                access_token = enrollment_payload["accessToken"]
                user_id = enrollment_payload.get("user", {}).get("id")
                enrollment = enrollment_payload.get("enrollment", {})
                enrollment_id = enrollment.get("id")
                institution = enrollment.get("institution") or {}
                institution_name = institution.get("name")
                signatures = enrollment_payload.get("signatures") or []

                if not access_token or not user_id or not enrollment_id:
                    state.remember("blocked", "Rejected incomplete Teller enrollment callback")
                    _json_response(self, 400, {"ok": False, "error": "incomplete_teller_enrollment"})
                    return

                cfg = state.config
                signature_required = (
                    cfg.teller.environment != "sandbox"
                    and not cfg.teller.allow_unverified_signatures
                )
                if signature_required and not cfg.teller.signing_public_key:
                    _json_response(
                        self,
                        400,
                        {
                            "ok": False,
                            "error": "missing_teller_signing_public_key",
                            "message": "Set TELLER_SIGNING_PUBLIC_KEY for development/production.",
                        },
                    )
                    state.remember("blocked", "Missing Teller signing public key")
                    return

                if cfg.teller.signing_public_key:
                    valid_signature = verify_teller_enrollment_signature(
                        signing_public_key=cfg.teller.signing_public_key,
                        signatures=signatures,
                        nonce=nonce,
                        access_token=access_token,
                        user_id=user_id,
                        enrollment_id=enrollment_id,
                        environment=cfg.teller.environment,
                    )
                    if not valid_signature:
                        state.remember("blocked", "Rejected invalid Teller enrollment signature")
                        _json_response(self, 400, {"ok": False, "error": "invalid_teller_signature"})
                        return
                elif signature_required:
                    state.remember("blocked", "Rejected unsigned Teller enrollment callback")
                    _json_response(self, 400, {"ok": False, "error": "signature_required"})
                    return

                cipher = TokenCipher(cfg.master_key)
                encrypted_token = cipher.encrypt(access_token)
                teller = TellerClient(cfg.teller)

                conn = connect(cfg.oracle)
                try:
                    store = BudgetStore(conn)
                    connection_id = store.upsert_connection(
                        environment=cfg.teller.environment,
                        provider_user_id=user_id,
                        provider_enrollment_id=enrollment_id,
                        institution_name=institution_name,
                        access_token_cipher=encrypted_token,
                        token_key_id=cfg.key_id,
                        metadata=enrollment_payload,
                    )
                    conn.commit()
                    summary = sync_connection(
                        store=store,
                        teller=teller,
                        cipher=cipher,
                        connection_id=connection_id,
                    )
                    conn.commit()
                finally:
                    conn.close()

                state.rotate()
                state.remember(
                    "sync_success",
                    "Stored encrypted Teller token and synced account data",
                    accountsSynced=summary.accounts,
                    transactionsSynced=summary.transactions,
                    institution=institution_name,
                )
                _json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "connectionId": summary.connection_id,
                        "accountsSynced": summary.accounts,
                        "transactionsSynced": summary.transactions,
                    },
                )
            except Exception as exc:
                details: dict[str, Any] = {"error": type(exc).__name__}
                if isinstance(exc, TellerAPIError):
                    details.update(
                        {
                            "status": exc.status,
                            "path": exc.path,
                            "code": exc.code,
                            "tellerMessage": exc.teller_message,
                        }
                    )
                state.remember(
                    "sync_error",
                    "Enrollment callback failed before sync completed",
                    **details,
                )
                payload = {"ok": False, "error": type(exc).__name__, "message": str(exc)[:500]}
                if isinstance(exc, TellerAPIError):
                    payload.update(
                        {
                            "status": exc.status,
                            "path": exc.path,
                            "code": exc.code,
                            "tellerMessage": exc.teller_message,
                        }
                    )
                _json_response(self, 500, payload)

    return Handler


def run_connect_server(config: AppConfig) -> None:
    if config.server.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("CONNECT_HOST must remain loopback for this test harness")

    state = ConnectState(config)
    server = ThreadingHTTPServer((config.server.host, config.server.port), make_handler(state))
    print(f"Serving Teller Connect locally at http://{config.server.host}:{config.server.port}")
    server.serve_forever()
