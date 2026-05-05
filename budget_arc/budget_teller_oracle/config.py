from __future__ import annotations

import os
import ast
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class OracleConfig:
    user: str
    password: str
    dsn: str
    wallet_dir: str
    wallet_password: str | None


@dataclass(frozen=True)
class TellerConfig:
    application_id: str
    environment: str
    api_version: str | None
    cert_path: str | None
    cert_key_path: str | None
    signing_public_key: str | None
    allow_unverified_signatures: bool
    institution_id: str | None


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int


@dataclass(frozen=True)
class AppConfig:
    oracle: OracleConfig
    teller: TellerConfig
    server: ServerConfig
    master_key: str
    key_id: str


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _cashflowarc_oracle_defaults() -> dict[str, str]:
    repo = Path(
        os.getenv(
            "CASHFLOWARC_REPO",
            r"C:\Users\dough\OneDrive\Documents\GitHub\CashFlowArc",
        )
    )
    source_file = repo / "getData" / "getTickerData.py"
    if not source_file.exists():
        return {}

    module = ast.parse(source_file.read_text(encoding="utf-8", errors="replace"))
    defaults: dict[str, str] = {}
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id not in {"DB_USER", "DB_PASSWORD", "DB_DSN"}:
                continue
            value_node = node.value
            if (
                isinstance(value_node, ast.Call)
                and isinstance(value_node.func, ast.Attribute)
                and value_node.func.attr == "getenv"
            ):
                env_name = ast.literal_eval(value_node.args[0]) if value_node.args else target.id
                default = (
                    ast.literal_eval(value_node.args[1])
                    if len(value_node.args) > 1 and isinstance(value_node.args[1], ast.Constant)
                    else None
                )
                value = os.getenv(env_name) or default
                if value:
                    defaults[target.id] = value
            elif isinstance(value_node, ast.Constant) and value_node.value:
                defaults[target.id] = str(value_node.value)
    return defaults


def load_oracle_config() -> OracleConfig:
    load_env_file()

    cashflowarc_defaults = (
        _cashflowarc_oracle_defaults()
        if os.getenv("ORACLE_CONFIG_SOURCE", "").strip().lower() == "cashflowarc"
        else {}
    )

    oracle_user = os.getenv("DB_USER") or cashflowarc_defaults.get("DB_USER")
    oracle_password = os.getenv("DB_PASSWORD") or cashflowarc_defaults.get("DB_PASSWORD")
    oracle_dsn = os.getenv("DB_DSN") or cashflowarc_defaults.get("DB_DSN") or "cfadb1_low"

    if not oracle_user:
        raise RuntimeError("Missing required environment variable: DB_USER")
    if not oracle_password:
        raise RuntimeError("Missing required environment variable: DB_PASSWORD")

    wallet_password = os.getenv("WALLET_PASSWORD") or oracle_password

    return OracleConfig(
        user=oracle_user,
        password=oracle_password,
        dsn=oracle_dsn,
        wallet_dir=require_env("WALLET_DIR"),
        wallet_password=wallet_password,
    )


def load_teller_config(require_app_id: bool = False) -> TellerConfig:
    load_env_file()

    application_id = os.getenv("TELLER_APPLICATION_ID", "")
    if require_app_id and not application_id:
        raise RuntimeError("Missing required environment variable: TELLER_APPLICATION_ID")

    environment = os.getenv("TELLER_ENVIRONMENT", "sandbox").strip().lower()
    if environment not in {"sandbox", "development", "production"}:
        raise RuntimeError("TELLER_ENVIRONMENT must be sandbox, development, or production")

    return TellerConfig(
        application_id=application_id,
        environment=environment,
        api_version=os.getenv("TELLER_API_VERSION") or None,
        cert_path=os.getenv("TELLER_CERT_PATH") or None,
        cert_key_path=os.getenv("TELLER_CERT_KEY_PATH") or None,
        signing_public_key=os.getenv("TELLER_SIGNING_PUBLIC_KEY") or None,
        allow_unverified_signatures=_bool_env("TELLER_ALLOW_UNVERIFIED_SIGNATURES", False),
        institution_id=os.getenv("TELLER_INSTITUTION_ID") or None,
    )


def load_server_config() -> ServerConfig:
    load_env_file()
    return ServerConfig(
        host=os.getenv("CONNECT_HOST", "127.0.0.1"),
        port=int(os.getenv("CONNECT_PORT", "8787")),
    )


def load_master_key() -> str:
    load_env_file()
    explicit_key = os.getenv("BUDGET_MASTER_KEY")
    if explicit_key:
        return explicit_key

    source = os.getenv("BUDGET_MASTER_KEY_SOURCE", "dpapi" if os.name == "nt" else "env")
    if source.strip().lower() == "dpapi":
        from .secret_store import load_master_key_dpapi

        return load_master_key_dpapi()

    raise RuntimeError("Missing required environment variable: BUDGET_MASTER_KEY")


def load_config(require_teller: bool = False) -> AppConfig:
    load_env_file()

    return AppConfig(
        oracle=load_oracle_config(),
        teller=load_teller_config(require_app_id=require_teller),
        server=load_server_config(),
        master_key=load_master_key(),
        key_id=os.getenv("BUDGET_KEY_ID", "local-v1"),
    )
