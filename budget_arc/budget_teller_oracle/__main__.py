from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import load_config, load_env_file, load_oracle_config, load_teller_config
from .connect_server import run_connect_server
from .crypto import TokenCipher, generate_master_key
from .db import BudgetStore, connect, initialize_schema
from .secret_store import dpapi_available, migrate_env_master_key_to_dpapi
from .signature import load_ed25519_public_key
from .sync import sync_connection
from .teller import TellerClient
from .web import run_web
from .web_security import hash_password
from .emailer import load_email_config, send_email


def _cmd_generate_key(_: argparse.Namespace) -> int:
    print(generate_master_key())
    return 0


def _cmd_hash_password(args: argparse.Namespace) -> int:
    import getpass

    if args.password_env:
        password = os.getenv(args.password_env, "")
        if not password:
            print(f"{args.password_env} is not set")
            return 1
    else:
        password = getpass.getpass("Budget admin password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords did not match")
            return 1
    if len(password) < 12:
        print("Use at least 12 characters for the budget admin password")
        return 1
    print(hash_password(password))
    return 0


def _cmd_bootstrap_env(args: argparse.Namespace) -> int:
    env_path = Path(".env")
    if env_path.exists() and not args.force:
        print(".env already exists; use --force to overwrite")
        return 1

    master_key_source = "dpapi" if dpapi_available() else "env"
    plaintext_key = "" if dpapi_available() else generate_master_key()

    if dpapi_available():
        from .secret_store import ensure_master_key_dpapi

        ensure_master_key_dpapi()

    contents = f"""# Local-only secrets/config. Do not commit this file.
DB_USER=
DB_PASSWORD=
DB_DSN=cfadb1_low
WALLET_DIR=C:\\Users\\dough\\OneDrive\\Desktop\\sqldeveloper\\Wallet
WALLET_PASSWORD=
ORACLE_CONFIG_SOURCE=cashflowarc
CASHFLOWARC_REPO=C:\\Users\\dough\\OneDrive\\Documents\\GitHub\\CashFlowArc

BUDGET_MASTER_KEY={plaintext_key}
BUDGET_MASTER_KEY_SOURCE={master_key_source}
BUDGET_KEY_ID=local-v1

TELLER_APPLICATION_ID=
TELLER_ENVIRONMENT=development
TELLER_CERT_PATH=
TELLER_CERT_KEY_PATH=
TELLER_SIGNING_PUBLIC_KEY=
TELLER_ALLOW_UNVERIFIED_SIGNATURES=false
TELLER_INSTITUTION_ID=amex

CONNECT_HOST=127.0.0.1
CONNECT_PORT=8787
"""
    env_path.write_text(contents, encoding="utf-8")
    print("Created .env with Amex defaults and a generated encryption key")
    print("Still needed: DB_USER, DB_PASSWORD, TELLER_APPLICATION_ID, TELLER_CERT_PATH, TELLER_CERT_KEY_PATH, TELLER_SIGNING_PUBLIC_KEY")
    return 0


def _cmd_secure_local(args: argparse.Namespace) -> int:
    if not dpapi_available():
        print("Windows DPAPI is not available on this platform")
        return 1

    env_path = Path(".env")
    if not env_path.exists():
        print(".env is missing; run bootstrap-env first")
        return 1

    path, migrated = migrate_env_master_key_to_dpapi(env_path, overwrite=args.force)
    print("Local secret hardening complete")
    print(f"DPAPI master key path: {path}")
    print("BUDGET_MASTER_KEY is no longer stored in plaintext .env" if migrated else "DPAPI master key already configured")
    return 0


def _cmd_init_db(_: argparse.Namespace) -> int:
    oracle_cfg = load_oracle_config()
    conn = connect(oracle_cfg)
    try:
        created = initialize_schema(conn)
    finally:
        conn.close()
    if created:
        print("Created tables: " + ", ".join(created))
    else:
        print("Schema already initialized")
    return 0


def _cmd_check_institution(args: argparse.Namespace) -> int:
    teller = TellerClient(load_teller_config())
    institutions = teller.list_institutions()
    query = args.query.strip().lower()
    matches = [
        item
        for item in institutions
        if query in item.get("name", "").lower() or query in item.get("id", "").lower()
    ]
    print(json.dumps({"count": len(institutions), "matches": matches}, indent=2))
    return 0 if matches else 2


def _cmd_doctor(_: argparse.Namespace) -> int:
    checks: list[dict[str, str | bool]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    load_env_file()

    if os.getenv("BUDGET_MASTER_KEY") or os.getenv("BUDGET_MASTER_KEY_SOURCE", "").lower() == "dpapi":
        try:
            from .config import load_master_key

            TokenCipher(load_master_key())
            add("encryption_key", True, "BUDGET_MASTER_KEY is a valid Fernet key")
        except Exception:
            add("encryption_key", False, "BUDGET_MASTER_KEY is invalid")
    else:
        add("encryption_key", False, "BUDGET_MASTER_KEY is missing or invalid")

    teller = load_teller_config()
    if os.getenv("TELLER_APPLICATION_ID"):
        add("teller_application", True, "Teller application id configured")
    else:
        add("teller_application", False, "Set TELLER_APPLICATION_ID from the Teller Dashboard")

    if teller.environment in {"development", "production"}:
        cert_ok = bool(teller.cert_path and Path(teller.cert_path).exists())
        key_ok = bool(teller.cert_key_path and Path(teller.cert_key_path).exists())
        add("teller_cert", cert_ok, "Teller client certificate file found" if cert_ok else "Set TELLER_CERT_PATH")
        add("teller_cert_key", key_ok, "Teller private key file found" if key_ok else "Set TELLER_CERT_KEY_PATH")
        signing_ok = bool(teller.signing_public_key)
        if signing_ok:
            try:
                load_ed25519_public_key(teller.signing_public_key or "")
                add("teller_signing_key", True, "Valid ED25519 Token Signing Key configured")
            except Exception:
                add(
                    "teller_signing_key",
                    False,
                    "TELLER_SIGNING_PUBLIC_KEY is not a valid ED25519 Token Signing Key",
                )
        else:
            add(
                "teller_signing_key",
                teller.allow_unverified_signatures,
                "Set TELLER_SIGNING_PUBLIC_KEY; do not bypass for real data",
            )
    else:
        add("teller_sandbox", True, "Sandbox does not require mTLS")

    try:
        teller_client = TellerClient(teller)
        institutions = teller_client.list_institutions()
        matches = [
            item
            for item in institutions
            if item.get("id") == (teller.institution_id or "")
        ]
        supports_transactions = bool(matches and "transactions" in matches[0].get("products", []))
        add(
            "institution",
            supports_transactions,
            f"{teller.institution_id} supports transactions"
            if supports_transactions
            else f"{teller.institution_id or '<unset>'} does not support transactions",
        )
    except Exception as exc:
        add("institution", False, f"Could not check Teller institutions: {type(exc).__name__}")

    try:
        oracle = load_oracle_config()
        conn = connect(oracle)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM BUDGET_CONNECTIONS")
                cur.fetchone()
            add("oracle", True, "Oracle wallet connection and BUDGET_ tables are ready")
        finally:
            conn.close()
    except Exception as exc:
        add("oracle", False, f"Oracle check failed: {type(exc).__name__}")

    ready = all(bool(item["ok"]) for item in checks)
    print(json.dumps({"ready": ready, "checks": checks}, indent=2))
    return 0 if ready else 1


def _cmd_serve(_: argparse.Namespace) -> int:
    cfg = load_config(require_teller=True)
    run_connect_server(cfg)
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    cfg = load_config()
    conn = connect(cfg.oracle)
    try:
        store = BudgetStore(conn)
        summary = sync_connection(
            store=store,
            teller=TellerClient(cfg.teller),
            cipher=TokenCipher(cfg.master_key),
            user_id=args.user_id,
            connection_id=args.connection_id,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        conn.commit()
        print(json.dumps(summary.__dict__, indent=2))
    finally:
        conn.close()
    return 0


def _cmd_list_connections(_: argparse.Namespace) -> int:
    cfg = load_config()
    conn = connect(cfg.oracle)
    try:
        rows = BudgetStore(conn).list_connections()
        print(json.dumps(rows, indent=2))
    finally:
        conn.close()
    return 0


def _cmd_web(_: argparse.Namespace) -> int:
    run_web()
    return 0


def _cmd_test_email(args: argparse.Namespace) -> int:
    if args.env_file:
        load_env_file(args.env_file)
    config = load_email_config()
    if not config.configured:
        print("Email delivery is not configured. Set BUDGET_EMAIL_FROM and BUDGET_SMTP_HOST.")
        return 1

    send_email(
        to_email=args.to,
        subject="BudgetArc SMTP test",
        body=(
            "This is a BudgetArc SMTP relay test.\n\n"
            "If you received this message, the server can send email through the configured relay."
        ),
    )
    print(f"Sent test email to {args.to} through {config.host}:{config.port} as {config.sender}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="budget_teller_oracle")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_key = subparsers.add_parser("generate-key", help="Generate a Fernet master key")
    generate_key.set_defaults(func=_cmd_generate_key)

    password_hash = subparsers.add_parser("hash-password", help="Hash a budget web admin password")
    password_hash.add_argument("--password-env", help="Read the password from this environment variable")
    password_hash.set_defaults(func=_cmd_hash_password)

    bootstrap_env = subparsers.add_parser("bootstrap-env", help="Create a local .env for Amex setup")
    bootstrap_env.add_argument("--force", action="store_true", help="Overwrite an existing .env")
    bootstrap_env.set_defaults(func=_cmd_bootstrap_env)

    secure_local = subparsers.add_parser("secure-local", help="Move local master key into Windows DPAPI")
    secure_local.add_argument("--force", action="store_true", help="Overwrite an existing DPAPI key")
    secure_local.set_defaults(func=_cmd_secure_local)

    init_db = subparsers.add_parser("init-db", help="Create isolated BUDGET_ Oracle tables")
    init_db.set_defaults(func=_cmd_init_db)

    check = subparsers.add_parser("check-institution", help="Check Teller institution support")
    check.add_argument("query")
    check.set_defaults(func=_cmd_check_institution)

    doctor = subparsers.add_parser("doctor", help="Check readiness for the Teller Amex connection")
    doctor.set_defaults(func=_cmd_doctor)

    serve = subparsers.add_parser("serve", help="Run local Teller Connect server")
    serve.set_defaults(func=_cmd_serve)

    sync = subparsers.add_parser("sync", help="Sync an existing encrypted Teller connection")
    sync.add_argument("connection_id")
    sync.add_argument("--user-id", required=True, help="Budget user id that owns the connection")
    sync.add_argument("--start-date")
    sync.add_argument("--end-date")
    sync.set_defaults(func=_cmd_sync)

    list_connections = subparsers.add_parser("list-connections", help="List stored Teller connections")
    list_connections.set_defaults(func=_cmd_list_connections)

    web = subparsers.add_parser("web", help="Run the Mint-style budget web app")
    web.set_defaults(func=_cmd_web)

    test_email = subparsers.add_parser("test-email", help="Send a BudgetArc SMTP test email")
    test_email.add_argument("--env-file", help="Load SMTP settings from a specific env file")
    test_email.add_argument("--to", required=True, help="Recipient email address for the test message")
    test_email.set_defaults(func=_cmd_test_email)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
