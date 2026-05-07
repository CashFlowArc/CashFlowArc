from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from decimal import Decimal
from functools import wraps
from typing import Any, Callable
from urllib.parse import urlparse

from flask import (
    Blueprint,
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import AppConfig, load_config, load_env_file
from .crypto import TokenCipher
from .db import BudgetStore, connect
from .emailer import load_email_config, send_password_reset_email, send_verification_email
from .signature import verify_teller_enrollment_signature
from .sync import sync_connection
from .teller import TellerAPIError, TellerClient
from .web_security import hash_password, verify_password


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INSTITUTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
CONNECTION_ID_RE = re.compile(r"^[A-Fa-f0-9]{64}$")


@dataclass(frozen=True)
class WebConfig:
    base_path: str
    host: str
    port: int
    require_auth: bool
    admin_username: str
    admin_password_hash: str | None
    cookie_secure: bool
    external_origin: str | None
    session_days: int


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return min(max(parsed, minimum), maximum)


def load_web_config() -> WebConfig:
    load_env_file()
    base_path = os.getenv("BUDGET_BASE_PATH", "/budget").strip() or "/budget"
    if not base_path.startswith("/"):
        base_path = "/" + base_path
    if len(base_path) > 1:
        base_path = base_path.rstrip("/")

    return WebConfig(
        base_path=base_path,
        host=os.getenv("BUDGET_WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("BUDGET_WEB_PORT", "8788")),
        require_auth=_bool_env("BUDGET_REQUIRE_AUTH", True),
        admin_username=os.getenv("BUDGET_ADMIN_USERNAME", "admin"),
        admin_password_hash=os.getenv("BUDGET_ADMIN_PASSWORD_HASH") or None,
        cookie_secure=_bool_env("BUDGET_COOKIE_SECURE", False),
        external_origin=(os.getenv("BUDGET_EXTERNAL_ORIGIN") or "").rstrip("/") or None,
        session_days=_int_env("BUDGET_SESSION_DAYS", 30, minimum=1, maximum=90),
    )


class WebState:
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
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
        self.last_event = {"type": event_type, "message": message, **details}


def _money(value: Any) -> str:
    if value is None:
        return "$0.00"
    amount = Decimal(str(value))
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    return f"{sign}${amount:,.2f}"


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _attach_bar_percent(rows: list[dict[str, Any]], value_key: str) -> list[dict[str, Any]]:
    max_value = max([_decimal(row.get(value_key)) for row in rows] or [Decimal("1")])
    if max_value <= 0:
        max_value = Decimal("1")
    for row in rows:
        value = _decimal(row.get(value_key))
        row["bar_pct"] = float((value / max_value) * Decimal("100"))
    return rows


def _date(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%b %-d, %Y") if os.name != "nt" else value.strftime("%b %#d, %Y")
    return str(value)


def _datetime_label(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        month = value.strftime("%b")
        day = value.strftime("%d").lstrip("0") or "0"
        year = value.strftime("%Y")
        time_text = value.strftime("%I:%M %p").lstrip("0")
        return f"{month} {day}, {year} {time_text}"
    return str(value)


def _category_display(row: dict[str, Any]) -> str:
    name = str(row.get("name") or row.get("category") or row.get("category_name") or "Uncategorized")
    parent_name = row.get("parent_name")
    return f"{parent_name} / {name}" if parent_name else name


def _ensure_category_from_input(
    store: BudgetStore,
    *,
    user_id: str,
    value: str | None,
    category_type: str = "expense",
) -> str | None:
    clean_value = (value or "").strip()
    if not clean_value:
        return None
    if "/" not in clean_value:
        return store.ensure_category(user_id=user_id, name=clean_value, category_type=category_type)

    parent_name, child_name = [part.strip() for part in clean_value.split("/", 1)]
    if not parent_name or not child_name:
        return store.ensure_category(user_id=user_id, name=clean_value, category_type=category_type)
    parent_id = store.ensure_category(user_id=user_id, name=parent_name, category_type=category_type)
    return store.ensure_category(
        user_id=user_id,
        name=child_name,
        category_type=category_type,
        parent_category_id=parent_id,
    )


def _iso_date(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _valid_email(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch(value))


def _valid_password(value: str) -> bool:
    return len(value) >= 12


def _selected_institution_id() -> str | None:
    raw = (request.args.get("institution_id") or "").strip()
    if not raw:
        return None
    if not INSTITUTION_ID_RE.fullmatch(raw):
        raise ValueError("Invalid institution id")
    return raw


def _selected_connection_id() -> str | None:
    raw = (request.args.get("connection_id") or "").strip()
    if not raw:
        return None
    if not CONNECTION_ID_RE.fullmatch(raw):
        raise ValueError("Invalid connection id")
    return raw.lower()


def _normalized_origin(value: str | None) -> str | None:
    raw = (value or "").strip().rstrip("/")
    if not raw:
        return None

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.hostname:
        return None

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    port = parsed.port
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    port_part = "" if port is None or default_port else f":{port}"
    return f"{scheme}://{hostname}{port_part}"


def _month_end(start: dt.date) -> dt.date:
    if start.month == 12:
        return dt.date(start.year + 1, 1, 1)
    return dt.date(start.year, start.month + 1, 1)


def _parse_month(value: str | None) -> dt.date | None:
    if not value:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        return None
    try:
        return dt.date.fromisoformat(f"{value}-01")
    except ValueError:
        return None


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _parse_money(value: str | None) -> Decimal | None:
    cleaned = (value or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def _month_bounds(month_value: str | None = None) -> tuple[dt.date, dt.date]:
    start = _parse_month(month_value) or dt.date.today().replace(day=1)
    return start, _month_end(start)


def _selected_month_bounds() -> tuple[dt.date, dt.date, str]:
    start, end = _month_bounds(request.args.get("month"))
    return start, end, start.strftime("%Y-%m")


def _previous_month_bounds(start: dt.date | None = None) -> tuple[dt.date, dt.date]:
    if start is None:
        start, _ = _month_bounds()
    previous_end = start
    previous_start = (start - dt.timedelta(days=1)).replace(day=1)
    return previous_start, previous_end


def _teller_sync_error_message(exc: TellerAPIError) -> str:
    if exc.code and exc.teller_message:
        detail = f"{exc.code}: {exc.teller_message}"
    else:
        detail = exc.teller_message or exc.code or f"HTTP {exc.status}"
    if exc.code and exc.code.startswith("enrollment.disconnected.user_action"):
        return (
            "Sync failed: Teller needs you to reconnect this institution or complete MFA. "
            "Open Accounts, choose Repair for this institution, complete the Teller prompts, then try Sync again. "
            f"Teller reported: {detail}"
        )
    return f"Sync failed: Teller API HTTP {exc.status}: {detail}"


def _teller_requires_reconnect(exc: TellerAPIError) -> bool:
    return bool(exc.code and exc.code.startswith("enrollment.disconnected"))


def _teller_error_code(exc: TellerAPIError) -> str:
    return exc.code or type(exc).__name__


def _connection_warning_label(connection: dict[str, Any]) -> str | None:
    if connection.get("status") != "RECONNECT_REQUIRED":
        return None
    error_code = str(connection.get("last_error_code") or "")
    error_message = str(connection.get("last_error_message") or "")
    error_text = f"{error_code} {error_message}".lower()
    if "mfa_required" in error_text:
        return "MFA required"
    if error_code.startswith("enrollment.disconnected"):
        return "Reconnect required"
    return "Repair required"


def _net_worth_period(value: str | None) -> tuple[str, str, dt.date | None, dt.date]:
    today = dt.date.today()
    key = (value or "month").strip().lower()
    options = {
        "month": ("Current month", today.replace(day=1)),
        "90d": ("Last 90 days", today - dt.timedelta(days=89)),
        "year": ("Past year", today - dt.timedelta(days=365)),
        "all": ("All time", None),
    }
    if key not in options:
        key = "month"
    label, start = options[key]
    return key, label, start, today


def _is_liability_account(account_type: str | None, account_subtype: str | None) -> bool:
    type_value = (account_type or "").strip().lower()
    subtype_value = (account_subtype or "").strip().lower()
    return type_value in {"credit", "loan"} or subtype_value in {
        "credit_card",
        "line_of_credit",
        "loan",
        "mortgage",
        "student",
        "student_loan",
        "auto",
        "auto_loan",
    }


def _signed_net_worth_balance(
    balance: Any,
    account_type: str | None,
    account_subtype: str | None,
) -> Decimal:
    amount = _decimal(balance)
    return -amount if _is_liability_account(account_type, account_subtype) else amount


def _account_balance_from_raw(raw_json: Any) -> Decimal | None:
    if raw_json is None:
        return None
    text = raw_json.read() if hasattr(raw_json, "read") else str(raw_json)
    if not text:
        return None
    try:
        account = json.loads(text)
    except json.JSONDecodeError:
        return None
    balances = account.get("balances") or {}
    if not isinstance(balances, dict):
        return None
    value = balances.get("ledger")
    if value is None:
        value = balances.get("available")
    if value is None:
        return None
    try:
        return _decimal(value)
    except Exception:
        return None


def _account_group_label(account_type: str | None, account_subtype: str | None) -> str:
    type_value = (account_type or "").strip().lower()
    subtype_value = (account_subtype or "").strip().lower()
    if type_value in {"depository", "bank"} or subtype_value in {"checking", "savings", "money_market"}:
        return "Cash"
    if type_value == "credit" or subtype_value in {"credit_card", "line_of_credit"}:
        return "Credit Cards"
    if type_value == "loan" or subtype_value in {"loan", "mortgage", "student", "student_loan", "auto", "auto_loan"}:
        return "Loans"
    if type_value in {"investment", "brokerage"} or subtype_value in {"brokerage", "ira", "401k"}:
        return "Investments"
    if type_value in {"property", "asset"} or subtype_value in {"vehicle", "home", "real_estate"}:
        return "Property"
    return "Other Accounts"


def _dashboard_account_groups(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Decimal]:
    order = ["Cash", "Credit Cards", "Loans", "Investments", "Property", "Other Accounts"]
    groups: dict[str, dict[str, Any]] = {}
    net_worth = Decimal("0")

    for row in rows:
        balance = _decimal(row.get("running_balance")) if row.get("running_balance") is not None else None
        if balance is None:
            balance = _account_balance_from_raw(row.get("raw_json"))
        signed_balance = _signed_net_worth_balance(
            balance,
            row.get("account_type"),
            row.get("account_subtype"),
        )
        net_worth += signed_balance

        label = _account_group_label(row.get("account_type"), row.get("account_subtype"))
        group = groups.setdefault(label, {"label": label, "total": Decimal("0"), "accounts": []})
        group["total"] += signed_balance
        group["accounts"].append(
            {
                "provider_account_id": row.get("provider_account_id"),
                "account_name": row.get("account_name") or "Account",
                "institution_name": row.get("institution_name") or "Institution",
                "account_type": row.get("account_type"),
                "account_subtype": row.get("account_subtype"),
                "last_four": row.get("last_four"),
                "status": row.get("status"),
                "last_transaction_date": row.get("last_transaction_date"),
                "balance": signed_balance,
            }
        )

    grouped_rows = [groups[label] for label in order if label in groups]
    for group in grouped_rows:
        group["accounts"].sort(key=lambda account: abs(_decimal(account["balance"])), reverse=True)
    return grouped_rows, net_worth


def _net_worth_svg(series: list[dict[str, Any]]) -> dict[str, Any]:
    width = Decimal("720")
    height = Decimal("190")
    left = Decimal("96")
    right = Decimal("14")
    top = Decimal("12")
    bottom = Decimal("24")
    chart_width = width - left - right
    chart_height = height - top - bottom

    values = [_decimal(row["net_worth"]) for row in series]
    if not values:
        return {"points": "", "area_points": "", "ticks": []}

    minimum = min(values)
    maximum = max(values)
    minimum = min(minimum, Decimal("0"))
    maximum = max(maximum, Decimal("0"))
    if minimum == maximum:
        padding = max(abs(maximum) * Decimal("0.08"), Decimal("100"))
        minimum -= padding
        maximum += padding
    value_range = maximum - minimum
    point_count = max(len(series) - 1, 1)

    points: list[str] = []
    for index, value in enumerate(values):
        x = left + (chart_width * Decimal(index) / Decimal(point_count))
        y = top + ((maximum - value) * chart_height / value_range)
        points.append(f"{float(x):.2f},{float(y):.2f}")

    first_x = float(left)
    last_x = float(left + chart_width)
    base_y = float(top + chart_height)
    area_points = f"{first_x:.2f},{base_y:.2f} {' '.join(points)} {last_x:.2f},{base_y:.2f}"

    def tick_y(value: Decimal) -> Decimal:
        return top + ((maximum - value) * chart_height / value_range)

    ticks = []
    for tick in range(5):
        ratio = Decimal(tick) / Decimal("4")
        value = maximum - (value_range * ratio)
        ticks.append({"y": float(top + (chart_height * ratio)), "label": _money(value), "is_zero": value == 0})
    if not any(tick["is_zero"] for tick in ticks):
        ticks.append({"y": float(tick_y(Decimal("0"))), "label": _money(0), "is_zero": True})
        ticks.sort(key=lambda tick: tick["y"])

    return {"points": " ".join(points), "area_points": area_points, "ticks": ticks}


def _build_net_worth_series(
    account_rows: list[dict[str, Any]],
    transaction_rows: list[dict[str, Any]],
    *,
    start_date: dt.date | None,
    end_date: dt.date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dated_transactions = []
    latest_transaction_by_account: dict[str, dt.date] = {}
    for row in transaction_rows:
        row_date = row.get("transaction_date")
        if hasattr(row_date, "date"):
            row_date = row_date.date()
        if row_date:
            dated_row = dict(row)
            dated_row["transaction_date"] = row_date
            dated_transactions.append(dated_row)
            account_id = str(row.get("provider_account_id"))
            if account_id and (
                account_id not in latest_transaction_by_account
                or row_date > latest_transaction_by_account[account_id]
            ):
                latest_transaction_by_account[account_id] = row_date

    balances: dict[str, dict[str, Any]] = {}
    for row in account_rows:
        account_id = str(row.get("provider_account_id") or "")
        if not account_id:
            continue
        balance = _account_balance_from_raw(row.get("raw_json"))
        if balance is None:
            continue
        balances[account_id] = {
            "provider_account_id": account_id,
            "account_name": row.get("account_name") or "Account",
            "institution_name": row.get("institution_name") or "Institution",
            "account_type": row.get("account_type"),
            "account_subtype": row.get("account_subtype"),
            "running_balance": balance,
            "last_transaction_date": latest_transaction_by_account.get(account_id),
        }

    if not balances:
        latest_running_rows: dict[str, dict[str, Any]] = {}
        for row in dated_transactions:
            if row.get("running_balance") is None:
                continue
            account_id = str(row.get("provider_account_id") or "")
            if not account_id:
                continue
            existing = latest_running_rows.get(account_id)
            if not existing or row["transaction_date"] >= existing["transaction_date"]:
                latest_running_rows[account_id] = row
        for account_id, row in latest_running_rows.items():
            balances[account_id] = {
                "provider_account_id": account_id,
                "account_name": row.get("account_name") or "Account",
                "institution_name": row.get("institution_name") or "Institution",
                "account_type": row.get("account_type"),
                "account_subtype": row.get("account_subtype"),
                "running_balance": _decimal(row.get("running_balance")),
                "last_transaction_date": latest_transaction_by_account.get(account_id),
            }

    if not balances:
        return [], []

    first_data_date = min([row["transaction_date"] for row in dated_transactions] or [end_date])
    start = start_date or first_data_date
    if start > end_date:
        start = end_date

    balances_by_account = {account_id: _decimal(row["running_balance"]) for account_id, row in balances.items()}
    transactions_by_day: dict[dt.date, list[dict[str, Any]]] = {}
    for row in dated_transactions:
        row_date = row["transaction_date"]
        if start <= row_date <= end_date and row.get("amount") is not None:
            transactions_by_day.setdefault(row_date, []).append(row)

    reversed_series: list[dict[str, Any]] = []
    day = end_date
    while day >= start:
        assets = Decimal("0")
        liabilities = Decimal("0")
        for account_id, balance in balances_by_account.items():
            row = balances[account_id]
            if _is_liability_account(row.get("account_type"), row.get("account_subtype")):
                liabilities += balance
            else:
                assets += balance

        net_worth = assets - liabilities
        if balances:
            reversed_series.append(
                {
                    "date": day,
                    "assets": assets,
                    "liabilities": liabilities,
                    "net_worth": net_worth,
                }
            )
        for row in transactions_by_day.get(day, []):
            account_id = str(row.get("provider_account_id") or "")
            if account_id in balances_by_account:
                balances_by_account[account_id] -= _decimal(row.get("amount"))
        day -= dt.timedelta(days=1)

    series = list(reversed(reversed_series))

    latest_rows = sorted(
        balances.values(),
        key=lambda row: abs(_signed_net_worth_balance(row["running_balance"], row.get("account_type"), row.get("account_subtype"))),
        reverse=True,
    )
    accounts = [
        {
            "account_name": row.get("account_name") or "Account",
            "institution_name": row.get("institution_name") or "Institution",
            "account_type": row.get("account_type"),
            "account_subtype": row.get("account_subtype"),
            "running_balance": row.get("running_balance"),
            "net_worth_balance": _signed_net_worth_balance(
                row.get("running_balance"),
                row.get("account_type"),
                row.get("account_subtype"),
            ),
            "last_transaction_date": row.get("last_transaction_date"),
            "is_liability": _is_liability_account(row.get("account_type"), row.get("account_subtype")),
        }
        for row in latest_rows
    ]
    return series, accounts


def _query_all(sql: str, **params: Any) -> list[dict[str, Any]]:
    cfg = load_config()
    conn = connect(cfg.oracle)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [col[0].lower() for col in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _query_one(sql: str, **params: Any) -> dict[str, Any] | None:
    rows = _query_all(sql, **params)
    return rows[0] if rows else None


def _ensure_user_category_catalog(user_id: str) -> int:
    cfg = load_config()
    conn = connect(cfg.oracle)
    try:
        store = BudgetStore(conn)
        count = store.sync_user_categories_from_transactions(user_id=user_id)
        if count:
            conn.commit()
        return count
    finally:
        conn.close()


def _dashboard_alert_id(user_id: str, alert_key: str) -> str:
    return hashlib.sha256(f"{user_id}:dashboard-alert:{alert_key}".encode("utf-8")).hexdigest()


def _sync_dashboard_notifications(
    *,
    user_id: str,
    month_key: str,
    key_prefix: str,
    generated_items: list[dict[str, str]],
) -> list[dict[str, Any]]:
    cfg = load_config()
    conn = connect(cfg.oracle)
    try:
        rows: list[dict[str, Any]] = []
        with conn.cursor() as cur:
            for item in generated_items:
                alert_key = f"{key_prefix}:{item['key']}"
                cur.execute(
                    """
                    MERGE INTO BUDGET_ALERTS target
                    USING (
                        SELECT
                            :alert_id AS ALERT_ID,
                            :user_id AS USER_ID,
                            :month_key AS MONTH_KEY,
                            :alert_key AS ALERT_KEY,
                            :icon_type AS ICON_TYPE,
                            :message AS MESSAGE,
                            :target_path AS TARGET_PATH
                        FROM dual
                    ) source
                    ON (target.ALERT_ID = source.ALERT_ID)
                    WHEN MATCHED THEN UPDATE SET
                        target.ICON_TYPE = source.ICON_TYPE,
                        target.MESSAGE = source.MESSAGE,
                        target.TARGET_PATH = source.TARGET_PATH,
                        target.UPDATED_AT = SYSTIMESTAMP
                    WHERE target.STATUS <> 'DELETED'
                    WHEN NOT MATCHED THEN INSERT (
                        ALERT_ID, USER_ID, MONTH_KEY, ALERT_KEY, ICON_TYPE, MESSAGE, TARGET_PATH
                    ) VALUES (
                        source.ALERT_ID, source.USER_ID, source.MONTH_KEY, source.ALERT_KEY,
                        source.ICON_TYPE, source.MESSAGE, source.TARGET_PATH
                    )
                    """,
                    alert_id=_dashboard_alert_id(user_id, alert_key),
                    user_id=user_id,
                    month_key=month_key,
                    alert_key=alert_key,
                    icon_type=item["icon_type"],
                    message=item["message"][:1024],
                    target_path=item["target_path"][:1024],
                )

            cur.execute(
                """
                SELECT ALERT_ID, ALERT_KEY, MONTH_KEY, ICON_TYPE, MESSAGE, TARGET_PATH, CREATED_AT
                FROM BUDGET_ALERTS
                WHERE USER_ID = :user_id
                  AND MONTH_KEY = :month_key
                  AND ALERT_KEY LIKE :key_pattern
                  AND STATUS = 'ACTIVE'
                ORDER BY CREATED_AT, ALERT_KEY
                """,
                user_id=user_id,
                month_key=month_key,
                key_pattern=f"{key_prefix}:%",
            )
            columns = [col[0].lower() for col in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        conn.commit()
        return rows
    finally:
        conn.close()


def _delete_dashboard_alert(*, user_id: str, alert_id: str) -> int:
    cfg = load_config()
    conn = connect(cfg.oracle)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE BUDGET_ALERTS
                SET STATUS = 'DELETED',
                    DELETED_AT = SYSTIMESTAMP,
                    UPDATED_AT = SYSTIMESTAMP
                WHERE USER_ID = :user_id
                  AND ALERT_ID = :alert_id
                  AND STATUS <> 'DELETED'
                """,
                user_id=user_id,
                alert_id=alert_id,
            )
            rowcount = cur.rowcount
        conn.commit()
        return rowcount
    finally:
        conn.close()


def _execute_sync(
    connection_id: str,
    *,
    user_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    conn = connect(cfg.oracle)
    try:
        store = BudgetStore(conn)
        summary = sync_connection(
            store=store,
            teller=TellerClient(cfg.teller),
            cipher=TokenCipher(cfg.master_key),
            user_id=user_id,
            connection_id=connection_id,
            start_date=start_date,
            end_date=end_date,
        )
        conn.commit()
        return summary.__dict__
    finally:
        conn.close()


def create_app() -> Flask:
    app_config = load_config(require_teller=False)
    web_config = load_web_config()
    institution_cache: dict[str, Any] = {"loaded_at": None, "items": []}
    app = Flask(__name__, static_folder=None)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.secret_key = secrets.token_urlsafe(32) if not app_config.master_key else app_config.master_key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=web_config.cookie_secure,
        PERMANENT_SESSION_LIFETIME=dt.timedelta(days=web_config.session_days),
        SESSION_REFRESH_EACH_REQUEST=True,
        MAX_CONTENT_LENGTH=1_000_000,
    )

    state = WebState(app_config)
    budget = Blueprint(
        "budget",
        __name__,
        url_prefix=web_config.base_path,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )

    def absolute_budget_url(endpoint: str, **values: Any) -> str:
        path = url_for(endpoint, **values)
        origin = web_config.external_origin or request.host_url.rstrip("/")
        return origin + path

    def send_or_log_email(send_func: Callable[[], None]) -> None:
        try:
            send_func()
        except Exception as exc:
            app.logger.warning("BudgetArc email delivery failed: %s", type(exc).__name__)

    def current_user() -> dict[str, Any] | None:
        role = session.get("auth_role")
        if role == "admin":
            return {
                "role": "admin",
                "email": web_config.admin_username,
                "display_name": "Budget administrator",
                "user_id": None,
            }
        if role == "user" and session.get("user_id"):
            return {
                "role": "user",
                "email": session.get("user_email"),
                "display_name": session.get("display_name") or session.get("user_email"),
                "user_id": session.get("user_id"),
            }
        return None

    def is_authenticated() -> bool:
        if not web_config.require_auth:
            return True
        return current_user() is not None

    def is_admin() -> bool:
        return bool(current_user() and current_user()["role"] == "admin")

    def current_user_id() -> str:
        user = current_user()
        if not user or user["role"] != "user" or not user["user_id"]:
            raise PermissionError("A budget user login is required")
        return str(user["user_id"])

    def csrf_token() -> str:
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if is_authenticated():
                return view(*args, **kwargs)
            return redirect(url_for("budget.login", next=request.full_path))

        return wrapper

    def user_required(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            user = current_user()
            if not user:
                return redirect(url_for("budget.login", next=request.full_path))
            if user["role"] != "user":
                return redirect(url_for("budget.admin_users"))
            return view(*args, **kwargs)

        return wrapper

    def admin_required(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            user = current_user()
            if not user:
                return redirect(url_for("budget.login", next=request.full_path))
            if user["role"] != "admin":
                return redirect(url_for("budget.dashboard"))
            return view(*args, **kwargs)

        return wrapper

    def require_csrf() -> None:
        expected = session.get("csrf_token")
        provided = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not expected or not provided or not secrets.compare_digest(expected, provided):
            raise PermissionError("CSRF check failed")

    def cached_teller_institutions() -> list[dict[str, Any]]:
        loaded_at = institution_cache.get("loaded_at")
        now = dt.datetime.now(dt.timezone.utc)
        if loaded_at and now - loaded_at < dt.timedelta(hours=12):
            return list(institution_cache.get("items") or [])

        items = TellerClient(app_config.teller).list_institutions()
        institution_cache["loaded_at"] = now
        institution_cache["items"] = items
        return list(items)

    def public_institution_payload(institution: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": institution.get("id"),
            "name": institution.get("name"),
            "products": institution.get("products") or [],
        }

    def mark_budget_data_changed() -> str:
        version = f"{int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)}-{secrets.token_urlsafe(8)}"
        session["budget_data_version"] = version
        return version

    @app.after_request
    def add_security_headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        referrer_policy = (
            "strict-origin-when-cross-origin"
            if request.endpoint == "budget.connect_page"
            else "no-referrer"
        )
        response.headers.setdefault("Referrer-Policy", referrer_policy)
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://teller.io https://cdn.teller.io https://*.teller.io 'unsafe-inline'; "
            "connect-src 'self' https://teller.io https://api.teller.io https://cdn.teller.io https://connect.teller.io https://*.teller.io; "
            "frame-src https://teller.io https://connect.teller.io https://*.teller.io; "
            "child-src https://teller.io https://connect.teller.io https://*.teller.io; "
            "img-src 'self' data: https://teller.io https://*.teller.io; "
            "style-src 'self' https://teller.io https://*.teller.io 'unsafe-inline'; "
            "font-src 'self' https://teller.io https://*.teller.io",
        )
        if request.endpoint and request.endpoint.startswith("budget.") and response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {
            "base_path": web_config.base_path,
            "csrf_token": csrf_token,
            "format_money": _money,
            "format_date": _date,
            "iso_date": _iso_date,
            "is_authenticated": is_authenticated(),
            "is_admin": is_admin(),
            "current_user": current_user(),
            "budget_data_version": session.get("budget_data_version", ""),
        }

    @budget.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        setup_missing = web_config.require_auth and not web_config.admin_password_hash
        if request.method == "POST" and not setup_missing:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if (
                secrets.compare_digest(username, web_config.admin_username)
                and web_config.admin_password_hash
                and verify_password(password, web_config.admin_password_hash)
            ):
                session.clear()
                session.permanent = True
                session["auth_role"] = "admin"
                csrf_token()
                return redirect(url_for("budget.admin_users"))

            email = _normalize_email(username)
            if _valid_email(email):
                cfg = load_config(require_teller=False)
                conn = connect(cfg.oracle)
                try:
                    store = BudgetStore(conn)
                    user = store.get_user_by_email(email)
                    if (
                        user
                        and user["status"] == "ACTIVE"
                        and verify_password(password, user["password_hash"])
                    ):
                        store.mark_user_login(user["user_id"])
                        conn.commit()
                        session.clear()
                        session.permanent = True
                        session["auth_role"] = "user"
                        session["user_id"] = user["user_id"]
                        session["user_email"] = user["email"]
                        session["display_name"] = user["display_name"] or user["email"]
                        csrf_token()
                        next_url = request.args.get("next") or url_for("budget.dashboard")
                        return redirect(next_url)
                finally:
                    conn.close()
            flash("Invalid username or password.", "error")
        return render_template("login.html", setup_missing=setup_missing, web_config=web_config)

    @budget.route("/register", methods=["GET", "POST"])
    def register() -> Any:
        setup_missing = web_config.require_auth and not web_config.admin_password_hash
        if request.method == "POST" and not setup_missing:
            require_csrf()
            email = _normalize_email(request.form.get("email", ""))
            display_name = request.form.get("display_name", "").strip() or None
            if not _valid_email(email):
                flash("Enter a valid email address.", "error")
                return render_template("register.html", setup_missing=setup_missing)

            token: str | None = None
            cfg = load_config(require_teller=False)
            conn = connect(cfg.oracle)
            try:
                store = BudgetStore(conn)
                user = store.get_user_by_email(email)
                if not user:
                    user_id = store.create_pending_user(email=email, display_name=display_name)
                    token = store.create_email_token(
                        user_id=user_id,
                        email=email,
                        purpose="verify_email",
                        expires_minutes=24 * 60,
                    )
                elif user["status"] == "PENDING":
                    token = store.create_email_token(
                        user_id=user["user_id"],
                        email=user["email"],
                        purpose="verify_email",
                        expires_minutes=24 * 60,
                    )
                conn.commit()
            finally:
                conn.close()

            if token:
                verify_url = absolute_budget_url("budget.verify_email", token=token)
                send_or_log_email(lambda: send_verification_email(to_email=email, verify_url=verify_url))
            flash("If this email can be registered, check your inbox for a verification link.", "success")
            return redirect(url_for("budget.login"))
        return render_template("register.html", setup_missing=setup_missing)

    @budget.route("/verify/<token>", methods=["GET", "POST"])
    def verify_email(token: str) -> Any:
        setup_missing = web_config.require_auth and not web_config.admin_password_hash
        if setup_missing:
            return redirect(url_for("budget.login"))

        cfg = load_config(require_teller=False)
        conn = connect(cfg.oracle)
        try:
            store = BudgetStore(conn)
            token_record = store.get_valid_email_token(token=token, purpose="verify_email")
            if not token_record or token_record["status"] == "DISABLED":
                return render_template("set_password.html", token_valid=False, mode="verify")

            if request.method == "POST":
                require_csrf()
                password = request.form.get("password", "")
                confirm = request.form.get("confirm_password", "")
                if password != confirm:
                    flash("Passwords did not match.", "error")
                elif not _valid_password(password):
                    flash("Use at least 12 characters for your password.", "error")
                else:
                    store.activate_user_with_password(
                        user_id=token_record["user_id"],
                        password_hash=hash_password(password),
                    )
                    store.consume_email_token(token_hash=token_record["token_hash"])
                    conn.commit()
                    flash("Your email is verified. Sign in with your new password.", "success")
                    return redirect(url_for("budget.login"))
        finally:
            conn.close()
        return render_template("set_password.html", token_valid=True, mode="verify", email=token_record["user_email"])

    @budget.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password() -> Any:
        setup_missing = web_config.require_auth and not web_config.admin_password_hash
        if request.method == "POST" and not setup_missing:
            require_csrf()
            email = _normalize_email(request.form.get("email", ""))
            token: str | None = None
            if _valid_email(email):
                cfg = load_config(require_teller=False)
                conn = connect(cfg.oracle)
                try:
                    store = BudgetStore(conn)
                    user = store.get_user_by_email(email)
                    if user and user["status"] == "ACTIVE":
                        token = store.create_email_token(
                            user_id=user["user_id"],
                            email=user["email"],
                            purpose="reset_password",
                            expires_minutes=60,
                        )
                    conn.commit()
                finally:
                    conn.close()

            if token:
                reset_url = absolute_budget_url("budget.reset_password", token=token)
                send_or_log_email(lambda: send_password_reset_email(to_email=email, reset_url=reset_url))
            flash("If an active account exists for that email, a reset link has been sent.", "success")
            return redirect(url_for("budget.login"))
        return render_template("forgot_password.html", setup_missing=setup_missing)

    @budget.route("/reset-password/<token>", methods=["GET", "POST"])
    def reset_password(token: str) -> Any:
        setup_missing = web_config.require_auth and not web_config.admin_password_hash
        if setup_missing:
            return redirect(url_for("budget.login"))

        cfg = load_config(require_teller=False)
        conn = connect(cfg.oracle)
        try:
            store = BudgetStore(conn)
            token_record = store.get_valid_email_token(token=token, purpose="reset_password")
            if not token_record or token_record["status"] != "ACTIVE":
                return render_template("set_password.html", token_valid=False, mode="reset")

            if request.method == "POST":
                require_csrf()
                password = request.form.get("password", "")
                confirm = request.form.get("confirm_password", "")
                if password != confirm:
                    flash("Passwords did not match.", "error")
                elif not _valid_password(password):
                    flash("Use at least 12 characters for your password.", "error")
                else:
                    store.set_user_password(
                        user_id=token_record["user_id"],
                        password_hash=hash_password(password),
                    )
                    store.consume_email_token(token_hash=token_record["token_hash"])
                    conn.commit()
                    flash("Your password has been reset. Sign in with the new password.", "success")
                    return redirect(url_for("budget.login"))
        finally:
            conn.close()
        return render_template("set_password.html", token_valid=True, mode="reset", email=token_record["user_email"])

    @budget.route("/logout", methods=["POST"])
    @login_required
    def logout() -> Any:
        require_csrf()
        session.clear()
        return redirect(url_for("budget.login"))

    @budget.route("/")
    @user_required
    def dashboard() -> Any:
        user_id = current_user_id()
        _ensure_user_category_catalog(user_id)
        month_start, month_end, selected_month = _selected_month_bounds()
        summary = _query_one(
            """
            SELECT
                COUNT(*) AS transaction_count,
                SUM(CASE WHEN t.AMOUNT > 0 THEN t.AMOUNT ELSE 0 END) AS spend_total,
                SUM(CASE WHEN t.AMOUNT < 0 THEN ABS(t.AMOUNT) ELSE 0 END) AS payment_total
            FROM BUDGET_TRANSACTIONS t
            LEFT JOIN BUDGET_TRANSACTION_EDITS e
              ON e.USER_ID = t.USER_ID
             AND e.PROVIDER = t.PROVIDER
             AND e.PROVIDER_TRANSACTION_ID = t.PROVIDER_TRANSACTION_ID
            WHERE t.PROVIDER = 'teller'
              AND t.USER_ID = :user_id
              AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) >= :month_start
              AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) < :month_end
              AND NVL(e.EXCLUDED_FROM_BUDGET, 0) = 0
            """,
            user_id=user_id,
            month_start=month_start,
            month_end=month_end,
        ) or {}
        accounts = _query_one(
            """
            SELECT COUNT(*) AS account_count
            FROM BUDGET_ACCOUNTS
            WHERE PROVIDER = 'teller'
              AND USER_ID = :user_id
            """,
            user_id=user_id,
        ) or {}
        account_rows = _query_all(
            """
            WITH latest_balances AS (
                SELECT PROVIDER, PROVIDER_ACCOUNT_ID, USER_ID, RUNNING_BALANCE
                FROM (
                    SELECT
                        t.PROVIDER,
                        t.PROVIDER_ACCOUNT_ID,
                        t.USER_ID,
                        t.RUNNING_BALANCE,
                        ROW_NUMBER() OVER (
                            PARTITION BY t.PROVIDER, t.PROVIDER_ACCOUNT_ID, t.USER_ID
                            ORDER BY t.TRANSACTION_DATE DESC, t.UPDATED_AT DESC, t.PROVIDER_TRANSACTION_ID DESC
                        ) AS RN
                    FROM BUDGET_TRANSACTIONS t
                    WHERE t.PROVIDER = 'teller'
                      AND t.USER_ID = :user_id
                      AND t.TRANSACTION_DATE < :month_end
                      AND t.RUNNING_BALANCE IS NOT NULL
                )
                WHERE RN = 1
            ),
            last_transactions AS (
                SELECT PROVIDER, PROVIDER_ACCOUNT_ID, USER_ID, MAX(TRANSACTION_DATE) AS LAST_TRANSACTION_DATE
                FROM BUDGET_TRANSACTIONS
                WHERE PROVIDER = 'teller'
                  AND USER_ID = :user_id
                  AND TRANSACTION_DATE < :month_end
                GROUP BY PROVIDER, PROVIDER_ACCOUNT_ID, USER_ID
            )
            SELECT
                a.PROVIDER_ACCOUNT_ID,
                a.ACCOUNT_NAME,
                a.ACCOUNT_TYPE,
                a.ACCOUNT_SUBTYPE,
                a.LAST_FOUR,
                a.STATUS,
                a.INSTITUTION_NAME,
                DBMS_LOB.SUBSTR(a.RAW_JSON, 32767, 1) AS RAW_JSON,
                lt.LAST_TRANSACTION_DATE,
                lb.RUNNING_BALANCE
            FROM BUDGET_ACCOUNTS a
            LEFT JOIN latest_balances lb
              ON lb.PROVIDER = a.PROVIDER
             AND lb.PROVIDER_ACCOUNT_ID = a.PROVIDER_ACCOUNT_ID
             AND lb.USER_ID = a.USER_ID
            LEFT JOIN last_transactions lt
              ON lt.PROVIDER = a.PROVIDER
             AND lt.PROVIDER_ACCOUNT_ID = a.PROVIDER_ACCOUNT_ID
             AND lt.USER_ID = a.USER_ID
            WHERE a.PROVIDER = 'teller'
              AND a.USER_ID = :user_id
            ORDER BY a.INSTITUTION_NAME, a.ACCOUNT_NAME
            """,
            user_id=user_id,
            month_end=month_end,
        )
        account_groups, _ = _dashboard_account_groups(account_rows)
        recent_transactions = _query_all(
            """
            SELECT
                NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) AS TRANSACTION_DATE,
                t.AMOUNT,
                t.STATUS,
                COALESCE(edited_c.NAME, raw_c.NAME, NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized') AS CATEGORY,
                t.DESCRIPTION,
                COALESCE(e.EDITED_MERCHANT_NAME, m.DISPLAY_NAME, t.COUNTERPARTY_NAME, t.DESCRIPTION) AS COUNTERPARTY_NAME,
                t.TRANSACTION_TYPE
            FROM BUDGET_TRANSACTIONS t
            LEFT JOIN BUDGET_TRANSACTION_EDITS e
              ON e.USER_ID = t.USER_ID
             AND e.PROVIDER = t.PROVIDER
             AND e.PROVIDER_TRANSACTION_ID = t.PROVIDER_TRANSACTION_ID
            LEFT JOIN BUDGET_CATEGORIES edited_c
              ON edited_c.USER_ID = t.USER_ID
             AND edited_c.CATEGORY_ID = e.CATEGORY_ID
            LEFT JOIN BUDGET_CATEGORY_ALIASES raw_alias
              ON raw_alias.USER_ID = t.USER_ID
             AND raw_alias.SOURCE_PROVIDER = t.PROVIDER
             AND raw_alias.STATUS = 'ACTIVE'
             AND LOWER(raw_alias.RAW_NAME) = LOWER(NVL(NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized'))
            LEFT JOIN BUDGET_CATEGORIES raw_c
              ON raw_c.USER_ID = t.USER_ID
             AND raw_c.CATEGORY_ID = raw_alias.CATEGORY_ID
            LEFT JOIN BUDGET_MERCHANTS m
              ON m.USER_ID = t.USER_ID
             AND m.MERCHANT_ID = e.MERCHANT_ID
            WHERE t.PROVIDER = 'teller'
              AND t.USER_ID = :user_id
              AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) >= :month_start
              AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) < :month_end
            ORDER BY NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) DESC, t.UPDATED_AT DESC
            FETCH FIRST 12 ROWS ONLY
            """,
            user_id=user_id,
            month_start=month_start,
            month_end=month_end,
        )
        categories = _query_all(
            """
            SELECT COALESCE(edited_c.NAME, raw_c.NAME, NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized') AS CATEGORY,
                   SUM(CASE WHEN t.AMOUNT > 0 THEN t.AMOUNT ELSE 0 END) AS SPEND_TOTAL,
                   COUNT(*) AS TRANSACTION_COUNT
            FROM BUDGET_TRANSACTIONS t
            LEFT JOIN BUDGET_TRANSACTION_EDITS e
              ON e.USER_ID = t.USER_ID
             AND e.PROVIDER = t.PROVIDER
             AND e.PROVIDER_TRANSACTION_ID = t.PROVIDER_TRANSACTION_ID
            LEFT JOIN BUDGET_CATEGORIES edited_c
              ON edited_c.USER_ID = t.USER_ID
             AND edited_c.CATEGORY_ID = e.CATEGORY_ID
            LEFT JOIN BUDGET_CATEGORY_ALIASES raw_alias
              ON raw_alias.USER_ID = t.USER_ID
             AND raw_alias.SOURCE_PROVIDER = t.PROVIDER
             AND raw_alias.STATUS = 'ACTIVE'
             AND LOWER(raw_alias.RAW_NAME) = LOWER(NVL(NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized'))
            LEFT JOIN BUDGET_CATEGORIES raw_c
              ON raw_c.USER_ID = t.USER_ID
             AND raw_c.CATEGORY_ID = raw_alias.CATEGORY_ID
            WHERE t.PROVIDER = 'teller'
              AND t.USER_ID = :user_id
              AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) >= :month_start
              AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) < :month_end
              AND NVL(e.EXCLUDED_FROM_BUDGET, 0) = 0
            GROUP BY COALESCE(edited_c.NAME, raw_c.NAME, NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized')
            ORDER BY SPEND_TOTAL DESC NULLS LAST
            FETCH FIRST 8 ROWS ONLY
            """,
            user_id=user_id,
            month_start=month_start,
            month_end=month_end,
        )
        categories = _attach_bar_percent(categories, "spend_total")
        all_time_summary = _query_one(
            """
            SELECT COUNT(*) AS transaction_count
            FROM BUDGET_TRANSACTIONS t
            LEFT JOIN BUDGET_TRANSACTION_EDITS e
              ON e.USER_ID = t.USER_ID
             AND e.PROVIDER = t.PROVIDER
             AND e.PROVIDER_TRANSACTION_ID = t.PROVIDER_TRANSACTION_ID
            WHERE t.PROVIDER = 'teller'
              AND t.USER_ID = :user_id
              AND NVL(e.REVIEWED_STATUS, 'new') = 'new'
            """,
            user_id=user_id,
        ) or {}
        all_time_categories = _query_all(
            """
            SELECT COALESCE(edited_c.NAME, raw_c.NAME, NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized') AS CATEGORY,
                   SUM(CASE WHEN t.AMOUNT > 0 THEN t.AMOUNT ELSE 0 END) AS SPEND_TOTAL,
                   COUNT(*) AS TRANSACTION_COUNT
            FROM BUDGET_TRANSACTIONS t
            LEFT JOIN BUDGET_TRANSACTION_EDITS e
              ON e.USER_ID = t.USER_ID
             AND e.PROVIDER = t.PROVIDER
             AND e.PROVIDER_TRANSACTION_ID = t.PROVIDER_TRANSACTION_ID
            LEFT JOIN BUDGET_CATEGORIES edited_c
              ON edited_c.USER_ID = t.USER_ID
             AND edited_c.CATEGORY_ID = e.CATEGORY_ID
            LEFT JOIN BUDGET_CATEGORY_ALIASES raw_alias
              ON raw_alias.USER_ID = t.USER_ID
             AND raw_alias.SOURCE_PROVIDER = t.PROVIDER
             AND raw_alias.STATUS = 'ACTIVE'
             AND LOWER(raw_alias.RAW_NAME) = LOWER(NVL(NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized'))
            LEFT JOIN BUDGET_CATEGORIES raw_c
              ON raw_c.USER_ID = t.USER_ID
             AND raw_c.CATEGORY_ID = raw_alias.CATEGORY_ID
            WHERE t.PROVIDER = 'teller'
              AND t.USER_ID = :user_id
              AND NVL(e.EXCLUDED_FROM_BUDGET, 0) = 0
            GROUP BY COALESCE(edited_c.NAME, raw_c.NAME, NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized')
            HAVING SUM(CASE WHEN t.AMOUNT > 0 THEN t.AMOUNT ELSE 0 END) > 0
            ORDER BY SPEND_TOTAL DESC NULLS LAST
            FETCH FIRST 1 ROWS ONLY
            """,
            user_id=user_id,
        )
        generated_alerts = [
            {
                "key": "connected-accounts",
                "icon_type": "notice",
                "message": f"You have {accounts.get('account_count') or 0} connected accounts in BudgetArc.",
                "target_path": url_for("budget.accounts"),
            },
        ]
        if all_time_categories:
            top_category = all_time_categories[0]
            generated_alerts.append(
                {
                    "key": "largest-category",
                    "icon_type": "warning",
                    "message": (
                        "Your largest overall category is "
                        f"{str(top_category['category']).title()} at {_money(top_category.get('spend_total'))}."
                    ),
                    "target_path": url_for("budget.budgets", month=selected_month),
                }
            )
        if all_time_summary.get("transaction_count"):
            generated_alerts.append(
                {
                    "key": "transactions-review",
                    "icon_type": "ledger",
                    "message": f"{all_time_summary.get('transaction_count') or 0} transactions are available for review.",
                    "target_path": url_for("budget.transactions", month=selected_month),
                }
            )
        generated_advice = [
            {
                "key": "check-largest-categories",
                "icon_type": "advice",
                "message": "Check the largest categories before the month closes.",
                "target_path": url_for("budget.budgets", month=selected_month),
            }
        ]
        alerts = _sync_dashboard_notifications(
            user_id=user_id,
            month_key="ALL",
            key_prefix="alert",
            generated_items=generated_alerts,
        )
        advice_items = _sync_dashboard_notifications(
            user_id=user_id,
            month_key="ALL",
            key_prefix="advice",
            generated_items=generated_advice,
        )
        return render_template(
            "dashboard.html",
            summary=summary,
            accounts=accounts,
            account_groups=account_groups,
            recent_transactions=recent_transactions,
            categories=categories,
            alerts=alerts,
            advice_items=advice_items,
            month_start=month_start,
            selected_month=selected_month,
        )

    @budget.route("/actions/delete-alert/<alert_id>", methods=["POST"])
    @user_required
    def delete_alert_action(alert_id: str) -> Any:
        require_csrf()
        selected_month = (_parse_month(request.form.get("month")) or dt.date.today().replace(day=1)).strftime("%Y-%m")
        if not re.fullmatch(r"[a-f0-9]{64}", alert_id):
            flash("Alert could not be deleted.", "error")
            return redirect(url_for("budget.dashboard", month=selected_month))

        deleted_count = _delete_dashboard_alert(user_id=current_user_id(), alert_id=alert_id)
        if not deleted_count:
            flash("Alert was already removed.", "error")
        return redirect(url_for("budget.dashboard", month=selected_month))

    @budget.route("/transactions")
    @user_required
    def transactions() -> Any:
        user_id = current_user_id()
        _ensure_user_category_catalog(user_id)
        month_start, month_end, selected_month = _selected_month_bounds()
        search = request.args.get("q", "").strip()
        status = request.args.get("status", "").strip()
        review = request.args.get("review", "").strip()
        account_id = request.args.get("account", "").strip()
        institution_id = request.args.get("institution", "").strip()
        category_id = request.args.get("category", "").strip()
        params: dict[str, Any] = {"user_id": user_id, "month_start": month_start, "month_end": month_end}
        effective_date = "NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE)"
        effective_merchant = "COALESCE(e.EDITED_MERCHANT_NAME, m.DISPLAY_NAME, t.COUNTERPARTY_NAME, t.DESCRIPTION)"
        effective_category = "COALESCE(edited_c.NAME, raw_c.NAME, NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized')"
        effective_category_id = "COALESCE(e.CATEGORY_ID, raw_c.CATEGORY_ID)"
        effective_review = "NVL(e.REVIEWED_STATUS, 'new')"
        clauses = [
            "t.PROVIDER = 'teller'",
            "t.USER_ID = :user_id",
            f"{effective_date} >= :month_start",
            f"{effective_date} < :month_end",
        ]
        if search:
            clauses.append(
                f"(LOWER(t.DESCRIPTION) LIKE :search OR LOWER({effective_merchant}) LIKE :search "
                f"OR LOWER({effective_category}) LIKE :search)"
            )
            params["search"] = f"%{search.lower()}%"
        if status:
            clauses.append("t.STATUS = :status")
            params["status"] = status
        if review:
            clauses.append(f"{effective_review} = :review")
            params["review"] = review
        if category_id:
            clauses.append(f"{effective_category_id} = :category_id")
            params["category_id"] = category_id
        if account_id:
            clauses.append("t.PROVIDER_ACCOUNT_ID = :account_id")
            params["account_id"] = account_id
        if institution_id:
            clauses.append("NVL(t.INSTITUTION_ID, a.INSTITUTION_ID) = :institution_id")
            params["institution_id"] = institution_id

        rows = _query_all(
            f"""
            SELECT
                {effective_date} AS TRANSACTION_DATE,
                t.AMOUNT,
                t.CURRENCY_CODE,
                t.STATUS,
                {effective_category} AS CATEGORY,
                {effective_merchant} AS MERCHANT_NAME,
                t.CATEGORY AS ORIGINAL_CATEGORY,
                t.COUNTERPARTY_NAME AS ORIGINAL_COUNTERPARTY_NAME,
                t.DESCRIPTION,
                t.TRANSACTION_TYPE,
                a.ACCOUNT_NAME,
                NVL(t.INSTITUTION_ID, a.INSTITUTION_ID) AS INSTITUTION_ID,
                NVL(t.INSTITUTION_NAME, a.INSTITUTION_NAME) AS INSTITUTION_NAME,
                t.PROVIDER_TRANSACTION_ID,
                t.PROVIDER_ACCOUNT_ID,
                t.TRANSACTION_DATE AS ORIGINAL_TRANSACTION_DATE,
                e.EDITED_TRANSACTION_DATE,
                e.EDITED_MERCHANT_NAME,
                e.REVIEWED_STATUS,
                NVL(e.EXCLUDED_FROM_BUDGET, 0) AS EXCLUDED_FROM_BUDGET,
                NVL(e.EXCLUDED_FROM_CASH_FLOW, 0) AS EXCLUDED_FROM_CASH_FLOW,
                e.NOTES,
                CASE WHEN e.EDIT_ID IS NULL THEN 0 ELSE 1 END AS HAS_USER_EDIT
            FROM BUDGET_TRANSACTIONS t
            LEFT JOIN BUDGET_ACCOUNTS a
              ON a.PROVIDER = t.PROVIDER
             AND a.PROVIDER_ACCOUNT_ID = t.PROVIDER_ACCOUNT_ID
             AND a.USER_ID = t.USER_ID
            LEFT JOIN BUDGET_TRANSACTION_EDITS e
              ON e.USER_ID = t.USER_ID
             AND e.PROVIDER = t.PROVIDER
             AND e.PROVIDER_TRANSACTION_ID = t.PROVIDER_TRANSACTION_ID
            LEFT JOIN BUDGET_CATEGORIES edited_c
              ON edited_c.USER_ID = t.USER_ID
             AND edited_c.CATEGORY_ID = e.CATEGORY_ID
            LEFT JOIN BUDGET_CATEGORY_ALIASES raw_alias
              ON raw_alias.USER_ID = t.USER_ID
             AND raw_alias.SOURCE_PROVIDER = t.PROVIDER
             AND raw_alias.STATUS = 'ACTIVE'
             AND LOWER(raw_alias.RAW_NAME) = LOWER(NVL(NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized'))
            LEFT JOIN BUDGET_CATEGORIES raw_c
              ON raw_c.USER_ID = t.USER_ID
             AND raw_c.CATEGORY_ID = raw_alias.CATEGORY_ID
            LEFT JOIN BUDGET_MERCHANTS m
              ON m.USER_ID = t.USER_ID
             AND m.MERCHANT_ID = e.MERCHANT_ID
            WHERE {" AND ".join(clauses)}
            ORDER BY {effective_date} DESC, t.UPDATED_AT DESC
            FETCH FIRST 250 ROWS ONLY
            """,
            **params,
        )
        accounts = _query_all(
            """
            SELECT PROVIDER_ACCOUNT_ID, ACCOUNT_NAME, LAST_FOUR
            FROM BUDGET_ACCOUNTS
            WHERE PROVIDER = 'teller'
              AND USER_ID = :user_id
            ORDER BY ACCOUNT_NAME
            """,
            user_id=user_id,
        )
        institutions = _query_all(
            """
            SELECT DISTINCT INSTITUTION_ID, INSTITUTION_NAME
            FROM BUDGET_ACCOUNTS
            WHERE PROVIDER = 'teller'
              AND USER_ID = :user_id
              AND INSTITUTION_ID IS NOT NULL
            ORDER BY INSTITUTION_NAME
            """,
            user_id=user_id,
        )
        categories = _query_all(
            """
            SELECT
                c.CATEGORY_ID,
                c.NAME AS CATEGORY_NAME,
                p.NAME AS PARENT_NAME
            FROM BUDGET_CATEGORIES c
            LEFT JOIN BUDGET_CATEGORIES p
              ON p.USER_ID = c.USER_ID
             AND p.CATEGORY_ID = c.PARENT_CATEGORY_ID
            WHERE c.USER_ID = :user_id
              AND c.STATUS = 'ACTIVE'
            ORDER BY LOWER(NVL(p.NAME, c.NAME)), c.PARENT_CATEGORY_ID NULLS FIRST, LOWER(c.NAME)
            """,
            user_id=user_id,
        )
        for category in categories:
            category["category_display"] = _category_display(category)
        merchants = _query_all(
            """
            SELECT DISTINCT MERCHANT_NAME
            FROM (
                SELECT DISPLAY_NAME AS MERCHANT_NAME
                FROM BUDGET_MERCHANTS
                WHERE USER_ID = :user_id
                  AND STATUS = 'ACTIVE'
                UNION ALL
                SELECT COUNTERPARTY_NAME AS MERCHANT_NAME
                FROM BUDGET_TRANSACTIONS
                WHERE PROVIDER = 'teller'
                  AND USER_ID = :user_id
                  AND COUNTERPARTY_NAME IS NOT NULL
            )
            WHERE MERCHANT_NAME IS NOT NULL
            ORDER BY MERCHANT_NAME
            FETCH FIRST 200 ROWS ONLY
            """,
            user_id=user_id,
        )
        return render_template(
            "transactions.html",
            transactions=rows,
            accounts=accounts,
            institutions=institutions,
            categories=categories,
            merchants=merchants,
            filters={
                "q": search,
                "status": status,
                "review": review,
                "category": category_id,
                "account": account_id,
                "institution": institution_id,
                "month": selected_month,
            },
            month_start=month_start,
        )

    @budget.route("/actions/transactions/<provider_transaction_id>/edit", methods=["POST"])
    @user_required
    def edit_transaction_action(provider_transaction_id: str) -> Any:
        require_csrf()
        user_id = current_user_id()
        return_args = {
            "month": request.form.get("month") or None,
            "q": request.form.get("q") or None,
            "status": request.form.get("status") or None,
            "review": request.form.get("review") or None,
            "category": request.form.get("category") or None,
            "account": request.form.get("account") or None,
            "institution": request.form.get("institution") or None,
        }
        clean_return_args = {key: value for key, value in return_args.items() if value}
        edited_date = _parse_date(request.form.get("transaction_date"))
        if request.form.get("transaction_date") and not edited_date:
            flash("Enter a valid transaction date.", "error")
            return redirect(url_for("budget.transactions", **clean_return_args))
        reviewed_status = request.form.get("reviewed_status", "").strip() or "new"
        if reviewed_status not in {"new", "reviewed", "ignored"}:
            reviewed_status = "new"

        conn = connect(app_config.oracle)
        try:
            store = BudgetStore(conn)
            if not store.transaction_belongs_to_user(
                user_id=user_id,
                provider_transaction_id=provider_transaction_id,
            ):
                flash("That transaction was not found for your user.", "error")
                return redirect(url_for("budget.transactions", **clean_return_args))
            merchant_name = request.form.get("merchant_name", "").strip()
            category_name = request.form.get("category_name", "").strip()
            merchant_id = store.ensure_merchant(user_id=user_id, display_name=merchant_name)
            category_id = _ensure_category_from_input(store, user_id=user_id, value=category_name)
            store.save_transaction_edit(
                user_id=user_id,
                provider_transaction_id=provider_transaction_id,
                edited_transaction_date=edited_date,
                merchant_id=merchant_id,
                edited_merchant_name=merchant_name or None,
                category_id=category_id,
                reviewed_status=reviewed_status,
                excluded_from_budget=1 if request.form.get("excluded_from_budget") else 0,
                excluded_from_cash_flow=1 if request.form.get("excluded_from_cash_flow") else 0,
                notes=request.form.get("notes"),
            )
            conn.commit()
        finally:
            conn.close()

        data_version = mark_budget_data_changed()
        if request.form.get("autosave") == "1" or request.headers.get("X-Requested-With") == "fetch":
            return ("", 204)
        clean_return_args["data_version"] = data_version
        flash("Transaction edits saved without changing the Teller original.", "success")
        return redirect(url_for("budget.transactions", **clean_return_args))

    @budget.route("/actions/transactions/review-listed", methods=["POST"])
    @user_required
    def review_listed_transactions_action() -> Any:
        require_csrf()
        user_id = current_user_id()
        return_args = {
            "month": request.form.get("month") or None,
            "q": request.form.get("q") or None,
            "status": request.form.get("status") or None,
            "review": request.form.get("review") or None,
            "category": request.form.get("category") or None,
            "account": request.form.get("account") or None,
            "institution": request.form.get("institution") or None,
        }
        clean_return_args = {key: value for key, value in return_args.items() if value}
        provider_transaction_ids = request.form.getlist("transaction_id")
        if not provider_transaction_ids:
            flash("No listed transactions were available to review.", "error")
            return redirect(url_for("budget.transactions", **clean_return_args))

        conn = connect(app_config.oracle)
        try:
            store = BudgetStore(conn)
            reviewed_count = store.mark_transactions_reviewed(
                user_id=user_id,
                provider_transaction_ids=provider_transaction_ids,
            )
            conn.commit()
        finally:
            conn.close()

        data_version = mark_budget_data_changed()
        clean_return_args["data_version"] = data_version
        flash(f"Marked {reviewed_count} listed transactions as reviewed.", "success")
        return redirect(url_for("budget.transactions", **clean_return_args))

    @budget.route("/actions/transactions/<provider_transaction_id>/reset", methods=["POST"])
    @user_required
    def reset_transaction_action(provider_transaction_id: str) -> Any:
        require_csrf()
        user_id = current_user_id()
        return_args = {
            "month": request.form.get("month") or None,
            "q": request.form.get("q") or None,
            "status": request.form.get("status") or None,
            "review": request.form.get("review") or None,
            "category": request.form.get("category") or None,
            "account": request.form.get("account") or None,
            "institution": request.form.get("institution") or None,
        }
        clean_return_args = {key: value for key, value in return_args.items() if value}
        conn = connect(app_config.oracle)
        try:
            store = BudgetStore(conn)
            if not store.transaction_belongs_to_user(
                user_id=user_id,
                provider_transaction_id=provider_transaction_id,
            ):
                flash("That transaction was not found for your user.", "error")
                return redirect(url_for("budget.transactions", **clean_return_args))
            removed_count = store.reset_transaction_edit(
                user_id=user_id,
                provider_transaction_id=provider_transaction_id,
            )
            conn.commit()
        finally:
            conn.close()
        data_version = mark_budget_data_changed()
        clean_return_args["data_version"] = data_version
        flash(
            "Transaction restored to the Teller original." if removed_count else "That transaction was already original.",
            "success",
        )
        return redirect(url_for("budget.transactions", **clean_return_args))

    @budget.route("/actions/transaction-overlays/reset", methods=["POST"])
    @user_required
    def reset_transaction_overlays_action() -> Any:
        require_csrf()
        user_id = current_user_id()
        conn = connect(app_config.oracle)
        try:
            removed_count = BudgetStore(conn).reset_all_transaction_edits(user_id=user_id)
            conn.commit()
        finally:
            conn.close()
        data_version = mark_budget_data_changed()
        flash(f"Restored Teller originals by removing {removed_count} user transaction changes.", "success")
        return redirect(url_for("budget.categories", data_version=data_version))

    @budget.route("/categories")
    @user_required
    def categories() -> Any:
        user_id = current_user_id()
        _ensure_user_category_catalog(user_id)
        rows = _query_all(
            """
            SELECT
                c.CATEGORY_ID,
                c.PARENT_CATEGORY_ID,
                c.NAME,
                p.NAME AS PARENT_NAME,
                c.CATEGORY_TYPE,
                c.STATUS,
                c.CREATED_AT,
                c.UPDATED_AT,
                COUNT(DISTINCT child.CATEGORY_ID) AS SUBCATEGORY_COUNT,
                COUNT(DISTINCT e.PROVIDER_TRANSACTION_ID) AS EDITED_TRANSACTION_COUNT,
                COUNT(DISTINCT b.MONTH_KEY) AS BUDGET_MONTH_COUNT,
                COUNT(DISTINCT t.PROVIDER_TRANSACTION_ID) AS RAW_TRANSACTION_COUNT
            FROM BUDGET_CATEGORIES c
            LEFT JOIN BUDGET_CATEGORIES p
              ON p.USER_ID = c.USER_ID
             AND p.CATEGORY_ID = c.PARENT_CATEGORY_ID
            LEFT JOIN BUDGET_CATEGORIES child
              ON child.USER_ID = c.USER_ID
             AND child.PARENT_CATEGORY_ID = c.CATEGORY_ID
            LEFT JOIN BUDGET_TRANSACTION_EDITS e
              ON e.USER_ID = c.USER_ID
             AND e.CATEGORY_ID = c.CATEGORY_ID
            LEFT JOIN BUDGET_CATEGORY_BUDGETS b
              ON b.USER_ID = c.USER_ID
             AND b.CATEGORY_ID = c.CATEGORY_ID
            LEFT JOIN BUDGET_CATEGORY_ALIASES a
              ON a.USER_ID = c.USER_ID
             AND a.CATEGORY_ID = c.CATEGORY_ID
             AND a.STATUS = 'ACTIVE'
            LEFT JOIN BUDGET_TRANSACTIONS t
              ON t.USER_ID = c.USER_ID
             AND t.PROVIDER = a.SOURCE_PROVIDER
             AND LOWER(NVL(NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized')) = LOWER(a.RAW_NAME)
            WHERE c.USER_ID = :user_id
            GROUP BY
                c.CATEGORY_ID, c.PARENT_CATEGORY_ID, c.NAME, p.NAME, c.CATEGORY_TYPE, c.STATUS, c.CREATED_AT, c.UPDATED_AT
            ORDER BY c.STATUS, LOWER(NVL(p.NAME, c.NAME)), c.PARENT_CATEGORY_ID NULLS FIRST, LOWER(c.NAME)
            """,
            user_id=user_id,
        )
        for row in rows:
            row["display_name"] = _category_display(row)
        parent_options = [
            row for row in rows
            if not row.get("parent_category_id") and row.get("status") == "ACTIVE"
        ]
        return render_template(
            "categories.html",
            categories=rows,
            parent_options=parent_options,
        )

    @budget.route("/actions/categories/create", methods=["POST"])
    @user_required
    def create_category_action() -> Any:
        require_csrf()
        name = request.form.get("name", "").strip()
        category_type = request.form.get("category_type", "expense").strip()
        parent_category_id = request.form.get("parent_category_id", "").strip() or None
        if not name:
            flash("Enter a category name.", "error")
            return redirect(url_for("budget.categories"))
        conn = connect(app_config.oracle)
        try:
            store = BudgetStore(conn)
            category_id = store.ensure_category(
                user_id=current_user_id(),
                name=name,
                category_type=category_type,
                parent_category_id=parent_category_id,
            )
            if category_id:
                store.update_category(
                    user_id=current_user_id(),
                    category_id=category_id,
                    name=name,
                    category_type=category_type,
                    status="ACTIVE",
                    parent_category_id=parent_category_id,
                )
            conn.commit()
        finally:
            conn.close()
        data_version = mark_budget_data_changed()
        flash("Category saved.", "success")
        return redirect(url_for("budget.categories", data_version=data_version))

    @budget.route("/actions/categories/<category_id>/update", methods=["POST"])
    @user_required
    def update_category_action(category_id: str) -> Any:
        require_csrf()
        conn = connect(app_config.oracle)
        try:
            updated = BudgetStore(conn).update_category(
                user_id=current_user_id(),
                category_id=category_id,
                name=request.form.get("name", ""),
                category_type=request.form.get("category_type", "expense"),
                status=request.form.get("status", "ACTIVE"),
                parent_category_id=request.form.get("parent_category_id", "").strip() or None,
            )
            conn.commit()
        finally:
            conn.close()
        data_version = mark_budget_data_changed()
        flash("Category updated." if updated else "Category was not found for your user.", "success" if updated else "error")
        return redirect(url_for("budget.categories", data_version=data_version))

    @budget.route("/actions/categories/<category_id>/delete", methods=["POST"])
    @user_required
    def delete_category_action(category_id: str) -> Any:
        require_csrf()
        target_category_id = request.form.get("target_category_id", "").strip()
        if not target_category_id:
            flash("Choose a category to receive the deleted category's transactions.", "error")
            return redirect(url_for("budget.categories"))

        conn = connect(app_config.oracle)
        try:
            result = BudgetStore(conn).delete_category_with_reassignment(
                user_id=current_user_id(),
                source_category_id=category_id,
                target_category_id=target_category_id,
            )
            if result.get("ok"):
                conn.commit()
            else:
                conn.rollback()
        finally:
            conn.close()

        data_version = mark_budget_data_changed()
        if not result.get("ok"):
            message = {
                "same_category": "Choose a different category before deleting.",
                "source_missing": "That category was not found for your user.",
                "target_missing": "The receiving category was not found for your user.",
            }.get(result.get("error"), "Category could not be deleted.")
            flash(message, "error")
            return redirect(url_for("budget.categories", data_version=data_version))

        flash(
            f"Deleted {result.get('source_name')} and moved its activity to {result.get('target_name')}.",
            "success",
        )
        return redirect(url_for("budget.categories", data_version=data_version))

    @budget.route("/budgets")
    @user_required
    def budgets() -> Any:
        user_id = current_user_id()
        _ensure_user_category_catalog(user_id)
        month_start, month_end, selected_month = _selected_month_bounds()
        current_month_start = dt.date.today().replace(day=1)
        is_past_month = month_start < current_month_start
        is_future_month = month_start > current_month_start
        lookback_start = month_start
        for _ in range(3):
            lookback_start = (lookback_start - dt.timedelta(days=1)).replace(day=1)

        actual_rows = _query_all(
            """
            SELECT
                   COALESCE(e.CATEGORY_ID, raw_c.CATEGORY_ID) AS CATEGORY_ID,
                   COALESCE(edited_c.NAME, raw_c.NAME, NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized') AS CATEGORY,
                   SUM(CASE WHEN t.AMOUNT > 0 THEN t.AMOUNT ELSE 0 END) AS SPEND_TOTAL,
                   COUNT(*) AS TRANSACTION_COUNT
            FROM BUDGET_TRANSACTIONS t
            LEFT JOIN BUDGET_TRANSACTION_EDITS e
              ON e.USER_ID = t.USER_ID
             AND e.PROVIDER = t.PROVIDER
             AND e.PROVIDER_TRANSACTION_ID = t.PROVIDER_TRANSACTION_ID
            LEFT JOIN BUDGET_CATEGORIES edited_c
              ON edited_c.USER_ID = t.USER_ID
             AND edited_c.CATEGORY_ID = e.CATEGORY_ID
            LEFT JOIN BUDGET_CATEGORY_ALIASES raw_alias
              ON raw_alias.USER_ID = t.USER_ID
             AND raw_alias.SOURCE_PROVIDER = t.PROVIDER
             AND raw_alias.STATUS = 'ACTIVE'
             AND LOWER(raw_alias.RAW_NAME) = LOWER(NVL(NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized'))
            LEFT JOIN BUDGET_CATEGORIES raw_c
              ON raw_c.USER_ID = t.USER_ID
             AND raw_c.CATEGORY_ID = raw_alias.CATEGORY_ID
            WHERE t.PROVIDER = 'teller'
              AND t.USER_ID = :user_id
              AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) >= :month_start
              AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) < :month_end
              AND NVL(e.EXCLUDED_FROM_BUDGET, 0) = 0
            GROUP BY
                COALESCE(e.CATEGORY_ID, raw_c.CATEGORY_ID),
                COALESCE(edited_c.NAME, raw_c.NAME, NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized')
            ORDER BY SPEND_TOTAL DESC NULLS LAST
            """,
            user_id=user_id,
            month_start=month_start,
            month_end=month_end,
        )
        recommended_rows = _query_all(
            """
            WITH monthly_spend AS (
                SELECT
                    COALESCE(e.CATEGORY_ID, raw_c.CATEGORY_ID) AS CATEGORY_ID,
                    COALESCE(edited_c.NAME, raw_c.NAME, NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized') AS CATEGORY,
                    TO_CHAR(NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE), 'YYYY-MM') AS MONTH_KEY,
                    SUM(CASE WHEN t.AMOUNT > 0 THEN t.AMOUNT ELSE 0 END) AS SPEND_TOTAL
                FROM BUDGET_TRANSACTIONS t
                LEFT JOIN BUDGET_TRANSACTION_EDITS e
                  ON e.USER_ID = t.USER_ID
                 AND e.PROVIDER = t.PROVIDER
                 AND e.PROVIDER_TRANSACTION_ID = t.PROVIDER_TRANSACTION_ID
                LEFT JOIN BUDGET_CATEGORIES edited_c
                  ON edited_c.USER_ID = t.USER_ID
                 AND edited_c.CATEGORY_ID = e.CATEGORY_ID
                LEFT JOIN BUDGET_CATEGORY_ALIASES raw_alias
                  ON raw_alias.USER_ID = t.USER_ID
                 AND raw_alias.SOURCE_PROVIDER = t.PROVIDER
                 AND raw_alias.STATUS = 'ACTIVE'
                 AND LOWER(raw_alias.RAW_NAME) = LOWER(NVL(NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized'))
                LEFT JOIN BUDGET_CATEGORIES raw_c
                  ON raw_c.USER_ID = t.USER_ID
                 AND raw_c.CATEGORY_ID = raw_alias.CATEGORY_ID
                WHERE t.PROVIDER = 'teller'
                  AND t.USER_ID = :user_id
                  AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) >= :lookback_start
                  AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) < :month_start
                  AND NVL(e.EXCLUDED_FROM_BUDGET, 0) = 0
                GROUP BY
                    COALESCE(e.CATEGORY_ID, raw_c.CATEGORY_ID),
                    COALESCE(edited_c.NAME, raw_c.NAME, NULLIF(TRIM(t.CATEGORY), ''), 'Uncategorized'),
                    TO_CHAR(NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE), 'YYYY-MM')
            )
            SELECT CATEGORY_ID, CATEGORY, AVG(SPEND_TOTAL) AS RECOMMENDED_AMOUNT
            FROM monthly_spend
            GROUP BY CATEGORY_ID, CATEGORY
            """,
            user_id=user_id,
            lookback_start=lookback_start,
            month_start=month_start,
        )
        budget_rows = _query_all(
            """
            SELECT
                b.CATEGORY_ID,
                c.NAME AS CATEGORY,
                c.CATEGORY_TYPE,
                b.BUDGETED_AMOUNT,
                b.ALERT_THRESHOLD,
                b.MONTH_KEY AS SOURCE_MONTH,
                0 AS IS_INHERITED
            FROM BUDGET_CATEGORY_BUDGETS b
            JOIN BUDGET_CATEGORIES c
              ON c.USER_ID = b.USER_ID
             AND c.CATEGORY_ID = b.CATEGORY_ID
            WHERE b.USER_ID = :user_id
              AND b.MONTH_KEY = :month_key
            """,
            user_id=user_id,
            month_key=selected_month,
        )
        if is_future_month:
            inherited_budget_rows = _query_all(
                """
                SELECT
                    CATEGORY_ID,
                    CATEGORY,
                    CATEGORY_TYPE,
                    BUDGETED_AMOUNT,
                    ALERT_THRESHOLD,
                    SOURCE_MONTH,
                    1 AS IS_INHERITED
                FROM (
                    SELECT
                        b.CATEGORY_ID,
                        c.NAME AS CATEGORY,
                        c.CATEGORY_TYPE,
                        b.BUDGETED_AMOUNT,
                        b.ALERT_THRESHOLD,
                        b.MONTH_KEY AS SOURCE_MONTH,
                        ROW_NUMBER() OVER (
                            PARTITION BY b.CATEGORY_ID
                            ORDER BY b.MONTH_KEY DESC
                        ) AS RN
                    FROM BUDGET_CATEGORY_BUDGETS b
                    JOIN BUDGET_CATEGORIES c
                      ON c.USER_ID = b.USER_ID
                     AND c.CATEGORY_ID = b.CATEGORY_ID
                    WHERE b.USER_ID = :user_id
                      AND b.MONTH_KEY < :month_key
                )
                WHERE RN = 1
                """,
                user_id=user_id,
                month_key=selected_month,
            )
            explicit_category_ids = {row.get("category_id") for row in budget_rows}
            budget_rows.extend(
                row for row in inherited_budget_rows
                if row.get("category_id") not in explicit_category_ids
            )
        managed_categories = _query_all(
            """
            SELECT
                c.CATEGORY_ID,
                c.NAME,
                p.NAME AS PARENT_NAME,
                c.CATEGORY_TYPE
            FROM BUDGET_CATEGORIES c
            LEFT JOIN BUDGET_CATEGORIES p
              ON p.USER_ID = c.USER_ID
             AND p.CATEGORY_ID = c.PARENT_CATEGORY_ID
            WHERE c.USER_ID = :user_id
              AND c.STATUS = 'ACTIVE'
            ORDER BY LOWER(NVL(p.NAME, c.NAME)), c.PARENT_CATEGORY_ID NULLS FIRST, LOWER(c.NAME)
            """,
            user_id=user_id,
        )
        for category in managed_categories:
            category["display_name"] = _category_display(category)
        income = _query_one(
            """
            SELECT SUM(CASE WHEN t.AMOUNT < 0 THEN ABS(t.AMOUNT) ELSE 0 END) AS ACTUAL_INCOME
            FROM BUDGET_TRANSACTIONS t
            LEFT JOIN BUDGET_TRANSACTION_EDITS e
              ON e.USER_ID = t.USER_ID
             AND e.PROVIDER = t.PROVIDER
             AND e.PROVIDER_TRANSACTION_ID = t.PROVIDER_TRANSACTION_ID
            WHERE t.PROVIDER = 'teller'
              AND t.USER_ID = :user_id
              AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) >= :month_start
              AND NVL(e.EDITED_TRANSACTION_DATE, t.TRANSACTION_DATE) < :month_end
              AND NVL(e.EXCLUDED_FROM_CASH_FLOW, 0) = 0
            """,
            user_id=user_id,
            month_start=month_start,
            month_end=month_end,
        ) or {}

        category_map: dict[str, dict[str, Any]] = {}
        for category in managed_categories:
            key = f"id:{category.get('category_id')}"
            category_map[key] = {
                "category_id": category.get("category_id"),
                "category": category.get("display_name") or category.get("name"),
                "category_type": category.get("category_type"),
                "spend_total": Decimal("0"),
                "transaction_count": 0,
                "budgeted_amount": Decimal("0"),
                "recommended_amount": Decimal("0"),
                "alert_threshold": Decimal("1"),
            }
        for row in actual_rows:
            key = f"id:{row.get('category_id')}" if row.get("category_id") else str(row.get("category") or "uncategorized").lower()
            item = category_map.setdefault(
                key,
                {
                    "category_id": row.get("category_id"),
                    "category": row.get("category") or "uncategorized",
                    "category_type": "expense",
                    "spend_total": Decimal("0"),
                    "transaction_count": 0,
                    "budgeted_amount": Decimal("0"),
                    "recommended_amount": Decimal("0"),
                    "alert_threshold": Decimal("1"),
                },
            )
            item["category_id"] = item.get("category_id") or row.get("category_id")
            item["spend_total"] = _decimal(row.get("spend_total"))
            item["transaction_count"] = row.get("transaction_count") or 0
        for row in budget_rows:
            key = f"id:{row.get('category_id')}" if row.get("category_id") else str(row.get("category") or "").lower()
            item = category_map.setdefault(
                key,
                {
                    "category_id": row.get("category_id"),
                    "category": row.get("category"),
                    "category_type": "expense",
                    "spend_total": Decimal("0"),
                    "transaction_count": 0,
                    "budgeted_amount": Decimal("0"),
                    "recommended_amount": Decimal("0"),
                    "alert_threshold": Decimal("1"),
                },
            )
            item["category_id"] = row.get("category_id")
            item["category_type"] = row.get("category_type") or item.get("category_type") or "expense"
            item["budgeted_amount"] = _decimal(row.get("budgeted_amount"))
            item["alert_threshold"] = _decimal(row.get("alert_threshold")) or Decimal("1")
            item["budget_source_month"] = row.get("source_month") or selected_month
            item["is_inherited"] = bool(row.get("is_inherited"))
        for row in recommended_rows:
            key = f"id:{row.get('category_id')}" if row.get("category_id") else str(row.get("category") or "").lower()
            item = category_map.setdefault(
                key,
                {
                    "category_id": None,
                    "category": row.get("category"),
                    "category_type": "expense",
                    "spend_total": Decimal("0"),
                    "transaction_count": 0,
                    "budgeted_amount": Decimal("0"),
                    "recommended_amount": Decimal("0"),
                    "alert_threshold": Decimal("1"),
                },
            )
            item["recommended_amount"] = _decimal(row.get("recommended_amount"))

        type_order = {"income": 0, "expense": 1, "transfer": 2, "other": 3}
        rows = sorted(
            category_map.values(),
            key=lambda row: (
                type_order.get(str(row.get("category_type") or "expense"), 4),
                _decimal(row.get("spend_total")) <= 0,
                str(row.get("category")).lower(),
            ),
        )
        spending_rows = [row for row in rows if (row.get("category_type") or "expense") != "income"]
        total_spent = sum((_decimal(row.get("spend_total")) for row in spending_rows), Decimal("0"))
        total_budgeted = sum((_decimal(row.get("budgeted_amount")) for row in spending_rows), Decimal("0"))
        projected_income = sum(
            (
                _decimal(row.get("budgeted_amount"))
                for row in rows
                if (row.get("category_type") or "expense") == "income"
            ),
            Decimal("0"),
        )
        for row in rows:
            spend = _decimal(row.get("spend_total"))
            budgeted = _decimal(row.get("budgeted_amount"))
            if budgeted > 0:
                row["budget_pct"] = min(float((spend / budgeted) * Decimal("100")), 100.0)
                row["budget_delta"] = budgeted - spend
                row["budget_state"] = "Over budget" if spend > budgeted else "On track"
            else:
                row["budget_pct"] = 100.0 if spend > 0 else 0.0
                row["budget_delta"] = -spend
                row["budget_state"] = "Unbudgeted" if spend > 0 else "Not set"
            source_month = row.get("budget_source_month")
            row["budget_source_label"] = ""
            if source_month:
                try:
                    row["budget_source_label"] = dt.date.fromisoformat(f"{source_month}-01").strftime("%B %Y")
                except ValueError:
                    row["budget_source_label"] = str(source_month)
        overbudget_rows = [
            row for row in rows
            if (row.get("category_type") or "expense") != "income"
            and (
                (_decimal(row.get("budgeted_amount")) > 0 and _decimal(row.get("spend_total")) > _decimal(row.get("budgeted_amount")))
                or (_decimal(row.get("budgeted_amount")) == 0 and _decimal(row.get("spend_total")) > 0)
            )
        ]
        group_labels = {
            "income": "Income",
            "expense": "Expense",
            "transfer": "Transfer",
            "other": "Other",
        }
        budget_groups = []
        for category_type in ["income", "expense", "transfer", "other"]:
            group_rows = [row for row in rows if (row.get("category_type") or "expense") == category_type]
            if group_rows:
                budget_groups.append(
                    {
                        "category_type": category_type,
                        "label": group_labels[category_type],
                        "rows": group_rows,
                        "count": len(group_rows),
                        "spent_total": sum(
                            (_decimal(row.get("spend_total")) for row in group_rows),
                            Decimal("0"),
                        ),
                        "budgeted_total": sum(
                            (_decimal(row.get("budgeted_amount")) for row in group_rows),
                            Decimal("0"),
                        ),
                        "inherited_count": sum(1 for row in group_rows if row.get("is_inherited")),
                    }
                )
        actual_income = _decimal(income.get("actual_income"))
        income_pct = min(float((actual_income / projected_income) * Decimal("100")), 100.0) if projected_income > 0 else 0.0
        budget_pct = min(float((total_spent / total_budgeted) * Decimal("100")), 100.0) if total_budgeted > 0 else (100.0 if total_spent > 0 else 0.0)
        summary = {
            "projected_income": projected_income,
            "actual_income": actual_income,
            "income_pct": income_pct,
            "total_budgeted": total_budgeted,
            "total_spent": total_spent,
            "budget_pct": budget_pct,
            "forecast": projected_income - total_budgeted,
            "actual_after_spend": actual_income - total_spent,
        }
        return render_template(
            "budgets.html",
            categories=rows,
            managed_categories=managed_categories,
            budget_groups=budget_groups,
            overbudget_rows=overbudget_rows,
            summary=summary,
            month_start=month_start,
            selected_month=selected_month,
            budget_period={
                "is_past": is_past_month,
                "is_future": is_future_month,
            },
        )

    @budget.route("/actions/budgets/month", methods=["POST"])
    @user_required
    def save_monthly_budget_action() -> Any:
        require_csrf()
        selected_month_date = _parse_month(request.form.get("month")) or dt.date.today().replace(day=1)
        selected_month = selected_month_date.strftime("%Y-%m")
        if selected_month_date < dt.date.today().replace(day=1):
            flash("Past month budget settings are locked.", "error")
            return redirect(url_for("budget.budgets", month=selected_month))
        projected_income = _parse_money(request.form.get("projected_income"))
        if projected_income is None:
            flash("Enter a valid projected income.", "error")
            return redirect(url_for("budget.budgets", month=selected_month))
        conn = connect(app_config.oracle)
        try:
            BudgetStore(conn).save_monthly_plan(
                user_id=current_user_id(),
                month_key=selected_month,
                projected_income=projected_income,
            )
            conn.commit()
        finally:
            conn.close()
        data_version = mark_budget_data_changed()
        flash("Monthly income forecast saved for this month only.", "success")
        return redirect(url_for("budget.budgets", month=selected_month, data_version=data_version))

    @budget.route("/actions/budgets/category", methods=["POST"])
    @user_required
    def save_category_budget_action() -> Any:
        require_csrf()
        selected_month_date = _parse_month(request.form.get("month")) or dt.date.today().replace(day=1)
        selected_month = selected_month_date.strftime("%Y-%m")
        if selected_month_date < dt.date.today().replace(day=1):
            flash("Past month category budgets are locked.", "error")
            return redirect(url_for("budget.budgets", month=selected_month))
        category_name = request.form.get("category_name", "").strip()
        budgeted_amount = _parse_money(request.form.get("budgeted_amount"))
        if not category_name:
            flash("Enter a category name.", "error")
            return redirect(url_for("budget.budgets", month=selected_month))
        if budgeted_amount is None:
            flash("Enter a valid budget amount.", "error")
            return redirect(url_for("budget.budgets", month=selected_month))
        conn = connect(app_config.oracle)
        try:
            store = BudgetStore(conn)
            category_id = _ensure_category_from_input(store, user_id=current_user_id(), value=category_name)
            if not category_id:
                flash("Category could not be created.", "error")
                return redirect(url_for("budget.budgets", month=selected_month))
            store.save_category_budget(
                user_id=current_user_id(),
                month_key=selected_month,
                category_id=category_id,
                budgeted_amount=budgeted_amount,
            )
            conn.commit()
        finally:
            conn.close()
        data_version = mark_budget_data_changed()
        flash("Category budget saved for this month and future months until changed.", "success")
        return redirect(url_for("budget.budgets", month=selected_month, data_version=data_version))

    @budget.route("/net-worth")
    @user_required
    def net_worth() -> Any:
        user_id = current_user_id()
        period, period_label, start_date, end_date = _net_worth_period(request.args.get("period"))
        end_exclusive = end_date + dt.timedelta(days=1)

        account_rows = _query_all(
            """
            SELECT
                PROVIDER_ACCOUNT_ID,
                ACCOUNT_NAME,
                ACCOUNT_TYPE,
                ACCOUNT_SUBTYPE,
                INSTITUTION_NAME,
                UPDATED_AT,
                DBMS_LOB.SUBSTR(RAW_JSON, 32767, 1) AS RAW_JSON
            FROM BUDGET_ACCOUNTS
            WHERE PROVIDER = 'teller'
              AND USER_ID = :user_id
            ORDER BY INSTITUTION_NAME, ACCOUNT_NAME
            """,
            user_id=user_id,
        )

        select_columns = """
            t.PROVIDER_ACCOUNT_ID,
            t.TRANSACTION_DATE,
            t.AMOUNT,
            t.RUNNING_BALANCE,
            t.UPDATED_AT,
            t.PROVIDER_TRANSACTION_ID,
            a.ACCOUNT_NAME,
            a.ACCOUNT_TYPE,
            a.ACCOUNT_SUBTYPE,
            a.INSTITUTION_NAME
        """
        join_clause = """
            FROM BUDGET_TRANSACTIONS t
            JOIN BUDGET_ACCOUNTS a
              ON a.PROVIDER = t.PROVIDER
             AND a.PROVIDER_ACCOUNT_ID = t.PROVIDER_ACCOUNT_ID
             AND a.USER_ID = t.USER_ID
            WHERE t.PROVIDER = 'teller'
              AND t.USER_ID = :user_id
              AND t.TRANSACTION_DATE < :end_exclusive
        """
        if start_date:
            transaction_rows = _query_all(
                f"""
                SELECT {select_columns}
                {join_clause}
                  AND t.TRANSACTION_DATE >= :start_date
                ORDER BY PROVIDER_ACCOUNT_ID, TRANSACTION_DATE, UPDATED_AT, PROVIDER_TRANSACTION_ID
                """,
                user_id=user_id,
                start_date=start_date,
                end_exclusive=end_exclusive,
            )
        else:
            transaction_rows = _query_all(
                f"""
                SELECT {select_columns}
                {join_clause}
                ORDER BY t.PROVIDER_ACCOUNT_ID, t.TRANSACTION_DATE, t.UPDATED_AT, t.PROVIDER_TRANSACTION_ID
                """,
                user_id=user_id,
                end_exclusive=end_exclusive,
            )

        series, accounts = _build_net_worth_series(
            account_rows,
            transaction_rows,
            start_date=start_date,
            end_date=end_date,
        )
        first_point = series[0] if series else {}
        latest_point = series[-1] if series else {}
        net_change = _decimal(latest_point.get("net_worth")) - _decimal(first_point.get("net_worth"))
        summary = {
            "net_worth": latest_point.get("net_worth"),
            "assets": latest_point.get("assets"),
            "liabilities": latest_point.get("liabilities"),
            "net_change": net_change,
            "start_date": first_point.get("date"),
            "end_date": latest_point.get("date"),
        }
        chart = _net_worth_svg(series)
        return render_template(
            "net_worth.html",
            accounts=accounts,
            chart=chart,
            period=period,
            period_label=period_label,
            period_options=[
                ("month", "Current month"),
                ("90d", "Last 90 days"),
                ("year", "Past year"),
                ("all", "All time"),
            ],
            series=series,
            summary=summary,
        )

    @budget.route("/accounts")
    @user_required
    def accounts() -> Any:
        user_id = current_user_id()
        rows = _query_all(
            """
            SELECT
                a.PROVIDER_ACCOUNT_ID,
                a.ACCOUNT_NAME,
                a.ACCOUNT_TYPE,
                a.ACCOUNT_SUBTYPE,
                a.CURRENCY_CODE,
                a.LAST_FOUR,
                a.STATUS,
                a.INSTITUTION_NAME,
                a.CONNECTION_ID,
                c.LAST_SYNC_AT,
                COUNT(t.PROVIDER_TRANSACTION_ID) AS TRANSACTION_COUNT,
                MAX(t.TRANSACTION_DATE) AS LAST_TRANSACTION_DATE
            FROM BUDGET_ACCOUNTS a
            LEFT JOIN BUDGET_CONNECTIONS c
              ON c.CONNECTION_ID = a.CONNECTION_ID
             AND c.USER_ID = a.USER_ID
            LEFT JOIN BUDGET_TRANSACTIONS t
              ON t.PROVIDER = a.PROVIDER
             AND t.PROVIDER_ACCOUNT_ID = a.PROVIDER_ACCOUNT_ID
             AND t.USER_ID = a.USER_ID
            WHERE a.PROVIDER = 'teller'
              AND a.USER_ID = :user_id
            GROUP BY
                a.PROVIDER_ACCOUNT_ID, a.ACCOUNT_NAME, a.ACCOUNT_TYPE, a.ACCOUNT_SUBTYPE,
                a.CURRENCY_CODE, a.LAST_FOUR, a.STATUS, a.INSTITUTION_NAME, a.CONNECTION_ID, c.LAST_SYNC_AT
            ORDER BY a.INSTITUTION_NAME, a.ACCOUNT_NAME
            """,
            user_id=user_id,
        )
        connections = _query_all(
            """
            WITH latest_errors AS (
                SELECT
                    CONNECTION_ID,
                    ERROR_CODE,
                    ERROR_MESSAGE,
                    FINISHED_AT,
                    ROW_NUMBER() OVER (
                        PARTITION BY CONNECTION_ID
                        ORDER BY FINISHED_AT DESC NULLS LAST, STARTED_AT DESC, SYNC_EVENT_ID DESC
                    ) AS RN
                FROM BUDGET_SYNC_EVENTS
                WHERE PROVIDER = 'teller'
                  AND USER_ID = :user_id
                  AND STATUS = 'failed'
            )
            SELECT
                c.CONNECTION_ID,
                c.ENVIRONMENT,
                c.INSTITUTION_ID,
                c.INSTITUTION_NAME,
                c.PROVIDER_ENROLLMENT_ID,
                c.STATUS,
                c.LAST_SYNC_AT,
                c.CREATED_AT,
                e.ERROR_CODE AS LAST_ERROR_CODE,
                e.ERROR_MESSAGE AS LAST_ERROR_MESSAGE,
                e.FINISHED_AT AS LAST_ERROR_AT
            FROM BUDGET_CONNECTIONS c
            LEFT JOIN latest_errors e
              ON e.CONNECTION_ID = c.CONNECTION_ID
             AND e.RN = 1
            WHERE c.PROVIDER = 'teller'
              AND c.USER_ID = :user_id
            ORDER BY c.UPDATED_AT DESC
            """,
            user_id=user_id,
        )
        for connection in connections:
            connection["warning_label"] = _connection_warning_label(connection)
            connection["last_sync_label"] = _datetime_label(connection.get("last_sync_at")) or "Not synced yet"
        repair_connection: dict[str, Any] | None = None
        try:
            connection_id = _selected_connection_id()
        except ValueError:
            connection_id = None
            flash("That Teller connection id is invalid.", "error")
        if connection_id:
            repair_connection = _query_one(
                """
                SELECT CONNECTION_ID, INSTITUTION_NAME, PROVIDER_ENROLLMENT_ID
                FROM BUDGET_CONNECTIONS
                WHERE PROVIDER = 'teller'
                  AND USER_ID = :user_id
                  AND CONNECTION_ID = :connection_id
                """,
                user_id=user_id,
                connection_id=connection_id,
            )
            if not repair_connection:
                flash("That Teller connection was not found for your user.", "error")
        return render_template(
            "accounts.html",
            accounts=rows,
            connections=connections,
            repair_connection=repair_connection,
        )

    @budget.route("/connect")
    @user_required
    def connect_page() -> Any:
        try:
            connection_id = _selected_connection_id()
        except ValueError:
            flash("That Teller connection id is invalid.", "error")
            return redirect(url_for("budget.accounts"))
        return redirect(url_for("budget.accounts", connection_id=connection_id) if connection_id else url_for("budget.accounts"))

    def _record_teller_sync_failure(connection_id: str | None, exc: TellerAPIError) -> None:
        if not connection_id:
            return
        conn = connect(app_config.oracle)
        try:
            user_id = current_user_id()
            store = BudgetStore(conn)
            if _teller_requires_reconnect(exc):
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE BUDGET_CONNECTIONS
                        SET STATUS = 'RECONNECT_REQUIRED',
                            UPDATED_AT = SYSTIMESTAMP
                        WHERE CONNECTION_ID = :connection_id
                          AND USER_ID = :user_id
                        """,
                        connection_id=connection_id,
                        user_id=user_id,
                    )
            store.record_sync_event(
                user_id=user_id,
                connection_id=connection_id,
                account_id=None,
                event_type="connection_sync",
                status="failed",
                error_code=_teller_error_code(exc),
                error_message=str(exc),
                details={"status": exc.status, "path": exc.path},
            )
            conn.commit()
        finally:
            conn.close()

    @budget.route("/settings")
    @admin_required
    def settings() -> Any:
        return render_template(
            "settings.html",
            web_config=web_config,
            app_config=app_config,
            email_config=load_email_config(),
        )

    @budget.route("/actions/sync/<connection_id>", methods=["POST"])
    @user_required
    def sync_action(connection_id: str) -> Any:
        try:
            require_csrf()
            connection = _query_one(
                """
                SELECT LAST_SYNC_AT
                FROM BUDGET_CONNECTIONS
                WHERE PROVIDER = 'teller'
                  AND USER_ID = :user_id
                  AND CONNECTION_ID = :connection_id
                """,
                user_id=current_user_id(),
                connection_id=connection_id,
            )
            if connection is None:
                flash("That institution connection was not found for your user.", "error")
                return redirect(url_for("budget.accounts"))
            start_date = _iso_date(connection.get("last_sync_at")) or None
            summary = _execute_sync(
                connection_id,
                user_id=current_user_id(),
                start_date=start_date,
            )
            data_version = mark_budget_data_changed()
            flash(
                f"Synced {summary['accounts']} accounts and {summary['transactions']} transactions.",
                "success",
            )
            return redirect(url_for("budget.accounts", data_version=data_version))
        except TellerAPIError as exc:
            _record_teller_sync_failure(connection_id, exc)
            flash(_teller_sync_error_message(exc), "error")
        except Exception as exc:
            flash(f"Sync failed: {type(exc).__name__}: {str(exc)[:220]}", "error")
        return redirect(url_for("budget.accounts"))

    @budget.route("/actions/delete-institution/<connection_id>", methods=["POST"])
    @user_required
    def delete_institution_action(connection_id: str) -> Any:
        try:
            require_csrf()
            confirmation = request.form.get("confirm_delete", "").strip().upper()
            if confirmation != "DELETE":
                flash("Type DELETE before removing an institution.", "error")
                return redirect(url_for("budget.accounts"))

            conn = connect(app_config.oracle)
            try:
                store = BudgetStore(conn)
                user_id = current_user_id()
                try:
                    token_cipher = store.get_connection_token_cipher(connection_id, user_id=user_id)
                except RuntimeError:
                    flash("That institution connection was not found for your user.", "error")
                    return redirect(url_for("budget.accounts"))

                access_token = TokenCipher(app_config.master_key).decrypt(token_cipher)
                try:
                    TellerClient(app_config.teller).delete_accounts(access_token)
                except TellerAPIError as exc:
                    if exc.status not in {404, 410}:
                        raise

                result = store.delete_connection(user_id=user_id, connection_id=connection_id)
                if not result:
                    flash("That institution connection was not found for your user.", "error")
                    conn.rollback()
                    return redirect(url_for("budget.accounts"))

                conn.commit()
            finally:
                conn.close()

            institution_name = result["institution_name"] or "Institution"
            data_version = mark_budget_data_changed()
            flash(
                f"Deleted {institution_name}: removed {result['accounts']} accounts, "
                f"{result['transactions']} transactions, sync history, and the encrypted Teller token.",
                "success",
            )
            return redirect(url_for("budget.accounts", data_version=data_version))
        except Exception as exc:
            flash(f"Delete failed: {type(exc).__name__}: {str(exc)[:220]}", "error")
        return redirect(url_for("budget.accounts"))

    @budget.route("/api/config")
    @user_required
    def teller_config() -> Any:
        try:
            institution_id = _selected_institution_id()
            repair_connection_id = _selected_connection_id()
        except ValueError as exc:
            return jsonify({"ok": False, "error": "invalid_request", "message": str(exc)}), 400
        if not app_config.teller.application_id:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "missing_teller_application_id",
                        "message": "Teller application id is not configured on the server.",
                    }
                ),
                500,
            )

        repair_connection = None
        if repair_connection_id:
            repair_connection = _query_one(
                """
                SELECT CONNECTION_ID, PROVIDER_ENROLLMENT_ID, INSTITUTION_NAME
                FROM BUDGET_CONNECTIONS
                WHERE PROVIDER = 'teller'
                  AND USER_ID = :user_id
                  AND CONNECTION_ID = :connection_id
                """,
                user_id=current_user_id(),
                connection_id=repair_connection_id,
            )
            if not repair_connection:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "connection_not_found",
                            "message": "That Teller connection was not found for your user.",
                        }
                    ),
                    404,
                )

        nonce = secrets.token_urlsafe(32)
        teller_csrf_token = secrets.token_urlsafe(32)
        session["teller_nonce"] = nonce
        session["teller_csrf_token"] = teller_csrf_token
        session["teller_institution_id"] = institution_id
        session["teller_repair_connection_id"] = repair_connection_id

        payload = {
            "ok": True,
            "applicationId": app_config.teller.application_id,
            "environment": app_config.teller.environment,
            "products": ["transactions", "balance"],
            "nonce": nonce,
            "csrfToken": teller_csrf_token,
            "institutionId": institution_id,
        }
        if repair_connection:
            payload.update(
                {
                    "mode": "repair",
                    "connectionId": repair_connection["connection_id"],
                    "enrollmentId": repair_connection["provider_enrollment_id"],
                    "institutionName": repair_connection["institution_name"],
                }
            )
        else:
            payload["mode"] = "connect"
        return jsonify(payload)

    @budget.route("/api/institutions")
    @user_required
    def teller_institutions() -> Any:
        query = request.args.get("q", "").strip()
        if len(query) > 80:
            return jsonify({"ok": False, "error": "query_too_long"}), 400

        limit_raw = request.args.get("limit", "30")
        try:
            limit = min(max(int(limit_raw), 1), 100)
        except ValueError:
            limit = 30

        if not query:
            return jsonify({"ok": True, "query": query, "institutions": []})

        try:
            institutions = cached_teller_institutions()
        except Exception as exc:
            return jsonify({"ok": False, "error": type(exc).__name__, "message": str(exc)[:300]}), 502

        results: list[dict[str, Any]] = []
        terms = [term.lower() for term in query.split() if term.strip()]
        for institution in institutions:
            institution_id = str(institution.get("id") or "")
            institution_name = str(institution.get("name") or "")
            products = institution.get("products") or []
            if "transactions" not in products or "balance" not in products:
                continue
            haystack = f"{institution_name} {institution_id}".lower()
            if all(term in haystack for term in terms):
                results.append(public_institution_payload(institution))
                if len(results) >= limit:
                    break

        return jsonify(
            {
                "ok": True,
                "query": query,
                "institutions": results,
            }
        )

    @budget.route("/api/status")
    @user_required
    def teller_status() -> Any:
        return jsonify({"ok": True, "lastEvent": state.last_event})

    @budget.route("/api/teller/enrollment", methods=["POST"])
    @user_required
    def teller_enrollment() -> Any:
        connection_id: str | None = None
        origin = request.headers.get("Origin")
        normalized_origin = _normalized_origin(origin)
        allowed_origins = {
            allowed
            for allowed in (
                _normalized_origin(web_config.external_origin),
                _normalized_origin(request.host_url),
            )
            if allowed
        }
        if normalized_origin and not any(
            secrets.compare_digest(normalized_origin, allowed_origin)
            for allowed_origin in allowed_origins
        ):
            state.remember(
                "blocked",
                "Rejected enrollment callback origin",
                origin=normalized_origin,
                allowedOrigins=sorted(allowed_origins),
            )
            return jsonify({"ok": False, "error": "origin_check_failed"}), 403

        if not request.is_json:
            state.remember("blocked", "Rejected non-JSON enrollment callback")
            return jsonify({"ok": False, "error": "json_required"}), 415

        if not secrets.compare_digest(request.headers.get("X-CSRF-Token") or "", session.get("teller_csrf_token", "")):
            state.remember("blocked", "Rejected enrollment callback CSRF token")
            return jsonify({"ok": False, "error": "csrf_check_failed"}), 403

        try:
            payload = request.get_json(force=True)
            nonce = payload.get("nonce")
            if not secrets.compare_digest(nonce or "", session.get("teller_nonce", "")):
                state.remember("blocked", "Rejected enrollment callback nonce")
                return jsonify({"ok": False, "error": "nonce_mismatch"}), 400

            enrollment_payload = payload["enrollment"]
            access_token = enrollment_payload["accessToken"]
            user_id = enrollment_payload.get("user", {}).get("id")
            enrollment = enrollment_payload.get("enrollment", {})
            enrollment_id = enrollment.get("id")
            institution = enrollment.get("institution") or {}
            institution_id = institution.get("id") or session.get("teller_institution_id")
            institution_name = institution.get("name")
            signatures = enrollment_payload.get("signatures") or []

            if not access_token or not user_id or not enrollment_id:
                state.remember("blocked", "Rejected incomplete Teller enrollment callback")
                return jsonify({"ok": False, "error": "incomplete_teller_enrollment"}), 400

            if not app_config.teller.signing_public_key:
                state.remember("blocked", "Missing Teller signing public key")
                return jsonify({"ok": False, "error": "missing_teller_signing_public_key"}), 400

            valid_signature = verify_teller_enrollment_signature(
                signing_public_key=app_config.teller.signing_public_key,
                signatures=signatures,
                nonce=nonce,
                access_token=access_token,
                user_id=user_id,
                enrollment_id=enrollment_id,
                environment=app_config.teller.environment,
            )
            if not valid_signature:
                state.remember("blocked", "Rejected invalid Teller enrollment signature")
                return jsonify({"ok": False, "error": "invalid_teller_signature"}), 400

            repair_connection_id = session.get("teller_repair_connection_id")
            if repair_connection_id:
                repair_connection = _query_one(
                    """
                    SELECT PROVIDER_ENROLLMENT_ID
                    FROM BUDGET_CONNECTIONS
                    WHERE PROVIDER = 'teller'
                      AND USER_ID = :user_id
                      AND CONNECTION_ID = :connection_id
                    """,
                    user_id=current_user_id(),
                    connection_id=repair_connection_id,
                )
                if not repair_connection:
                    state.remember("blocked", "Rejected repair for unknown Teller connection")
                    return jsonify({"ok": False, "error": "connection_not_found"}), 404
                if not secrets.compare_digest(
                    str(repair_connection["provider_enrollment_id"]),
                    str(enrollment_id),
                ):
                    state.remember("blocked", "Rejected repair enrollment mismatch")
                    return jsonify({"ok": False, "error": "enrollment_mismatch"}), 400

            cipher = TokenCipher(app_config.master_key)
            encrypted_token = cipher.encrypt(access_token)
            conn = connect(app_config.oracle)
            try:
                store = BudgetStore(conn)
                connection_id = store.upsert_connection(
                    user_id=current_user_id(),
                    environment=app_config.teller.environment,
                    provider_user_id=user_id,
                    provider_enrollment_id=enrollment_id,
                    institution_id=institution_id,
                    institution_name=institution_name,
                    access_token_cipher=encrypted_token,
                    token_key_id=app_config.key_id,
                    metadata=enrollment_payload,
                )
                conn.commit()
            finally:
                conn.close()

            summary = _execute_sync(connection_id, user_id=current_user_id())
            data_version = mark_budget_data_changed()
            session.pop("teller_nonce", None)
            session.pop("teller_csrf_token", None)
            session.pop("teller_institution_id", None)
            session.pop("teller_repair_connection_id", None)
            state.remember(
                "sync_success",
                "Stored encrypted Teller token and synced account data",
                accountsSynced=summary["accounts"],
                transactionsSynced=summary["transactions"],
                institution=institution_name,
            )
            return jsonify(
                {
                    "ok": True,
                    "connectionId": connection_id,
                    "accountsSynced": summary["accounts"],
                    "transactionsSynced": summary["transactions"],
                    "dataVersion": data_version,
                }
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
                _record_teller_sync_failure(connection_id, exc)
            state.remember("sync_error", "Enrollment callback failed before sync completed", **details)
            message = _teller_sync_error_message(exc) if isinstance(exc, TellerAPIError) else str(exc)[:500]
            payload = {"ok": False, "error": type(exc).__name__, "message": message}
            if isinstance(exc, TellerAPIError):
                payload.update(
                    {
                        "status": exc.status,
                        "path": exc.path,
                        "code": exc.code,
                        "tellerMessage": exc.teller_message,
                    }
                )
            return jsonify(payload), 500

    @budget.route("/admin/users", methods=["GET", "POST"])
    @admin_required
    def admin_users() -> Any:
        cfg = load_config(require_teller=False)
        conn = connect(cfg.oracle)
        try:
            store = BudgetStore(conn)
            if request.method == "POST":
                require_csrf()
                action = request.form.get("action", "")
                if action == "create":
                    email = _normalize_email(request.form.get("email", ""))
                    display_name = request.form.get("display_name", "").strip() or None
                    password = request.form.get("password", "")
                    if not _valid_email(email):
                        flash("Enter a valid email address.", "error")
                    elif not _valid_password(password):
                        flash("Use at least 12 characters for user passwords.", "error")
                    elif store.get_user_by_email(email):
                        flash("A user with that email already exists.", "error")
                    else:
                        store.create_user(
                            email=email,
                            display_name=display_name,
                            password_hash=hash_password(password),
                        )
                        conn.commit()
                        flash(f"Created user {email}.", "success")
                        return redirect(url_for("budget.admin_users"))
                elif action == "reset_password":
                    user_id = request.form.get("user_id", "")
                    password = request.form.get("password", "")
                    if not user_id:
                        flash("Missing user id.", "error")
                    elif not _valid_password(password):
                        flash("Use at least 12 characters for user passwords.", "error")
                    else:
                        store.set_user_password(user_id=user_id, password_hash=hash_password(password))
                        conn.commit()
                        flash("User password was reset.", "success")
                        return redirect(url_for("budget.admin_users"))
                elif action == "set_status":
                    user_id = request.form.get("user_id", "")
                    status = request.form.get("status", "")
                    if status not in {"ACTIVE", "DISABLED"}:
                        flash("Invalid user status.", "error")
                    elif status == "ACTIVE":
                        user = store.get_user_by_id(user_id)
                        if not user or not user["email_verified_at"] or not user["password_set_at"]:
                            flash("Email verification and password setup are required before activating a user.", "error")
                        else:
                            store.set_user_status(user_id=user_id, status=status)
                            conn.commit()
                            flash("User status was updated.", "success")
                            return redirect(url_for("budget.admin_users"))
                    else:
                        store.set_user_status(user_id=user_id, status=status)
                        conn.commit()
                        flash("User status was updated.", "success")
                        return redirect(url_for("budget.admin_users"))
                elif action == "assign_unowned":
                    user_id = request.form.get("user_id", "")
                    if not user_id:
                        flash("Missing user id.", "error")
                    else:
                        counts = store.assign_unowned_data(user_id=user_id)
                        conn.commit()
                        flash(
                            "Assigned unowned rows: "
                            f"{counts['connections']} connections, "
                            f"{counts['accounts']} accounts, "
                            f"{counts['transactions']} transactions.",
                            "success",
                        )
                        return redirect(url_for("budget.admin_users"))

            users = store.list_users()
        finally:
            conn.close()
        return render_template("admin_users.html", users=users)

    app.register_blueprint(budget)

    @app.route("/")
    def root() -> Any:
        if is_admin():
            return redirect(url_for("budget.admin_users"))
        return redirect(url_for("budget.dashboard"))

    return app


def run_web() -> None:
    web_config = load_web_config()
    app = create_app()
    app.run(host=web_config.host, port=web_config.port, debug=False)
