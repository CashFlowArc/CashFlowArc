from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
from dataclasses import dataclass
from decimal import Decimal
from functools import wraps
from typing import Any, Callable

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
from .signature import verify_teller_enrollment_signature
from .sync import sync_connection
from .teller import TellerAPIError, TellerClient
from .web_security import hash_password, verify_password


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INSTITUTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


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


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


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


def _selected_institution_id(default_id: str | None) -> str | None:
    raw = (request.args.get("institution_id") or "").strip()
    if raw == "__default__":
        raw = default_id or ""
    if not raw:
        return None
    if not INSTITUTION_ID_RE.fullmatch(raw):
        raise ValueError("Invalid institution id")
    return raw


def _month_bounds() -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    start = today.replace(day=1)
    if today.month == 12:
        end = dt.date(today.year + 1, 1, 1)
    else:
        end = dt.date(today.year, today.month + 1, 1)
    return start, end


def _previous_month_bounds() -> tuple[dt.date, dt.date]:
    start, _ = _month_bounds()
    previous_end = start
    previous_start = (start - dt.timedelta(days=1)).replace(day=1)
    return previous_start, previous_end


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
    app = Flask(__name__, static_folder=None)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.secret_key = secrets.token_urlsafe(32) if not app_config.master_key else app_config.master_key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=web_config.cookie_secure,
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

    @app.after_request
    def add_security_headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://cdn.teller.io https://*.teller.io 'unsafe-inline'; "
            "connect-src 'self' https://api.teller.io https://cdn.teller.io https://connect.teller.io https://*.teller.io; "
            "frame-src https://connect.teller.io https://*.teller.io; "
            "child-src https://connect.teller.io https://*.teller.io; "
            "img-src 'self' data: https://*.teller.io; "
            "style-src 'self' https://*.teller.io 'unsafe-inline'; "
            "font-src 'self' https://*.teller.io",
        )
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
        month_start, month_end = _month_bounds()
        previous_start, previous_end = _previous_month_bounds()
        summary = _query_one(
            """
            SELECT
                COUNT(*) AS transaction_count,
                SUM(CASE WHEN AMOUNT > 0 THEN AMOUNT ELSE 0 END) AS spend_total,
                SUM(CASE WHEN AMOUNT < 0 THEN ABS(AMOUNT) ELSE 0 END) AS payment_total
            FROM BUDGET_TRANSACTIONS
            WHERE PROVIDER = 'teller'
              AND USER_ID = :user_id
              AND TRANSACTION_DATE >= :month_start
              AND TRANSACTION_DATE < :month_end
            """,
            user_id=user_id,
            month_start=month_start,
            month_end=month_end,
        ) or {}
        previous = _query_one(
            """
            SELECT SUM(CASE WHEN AMOUNT > 0 THEN AMOUNT ELSE 0 END) AS spend_total
            FROM BUDGET_TRANSACTIONS
            WHERE PROVIDER = 'teller'
              AND USER_ID = :user_id
              AND TRANSACTION_DATE >= :month_start
              AND TRANSACTION_DATE < :month_end
            """,
            user_id=user_id,
            month_start=previous_start,
            month_end=previous_end,
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
        recent_transactions = _query_all(
            """
            SELECT TRANSACTION_DATE, AMOUNT, STATUS, CATEGORY, DESCRIPTION, COUNTERPARTY_NAME, TRANSACTION_TYPE
            FROM BUDGET_TRANSACTIONS
            WHERE PROVIDER = 'teller'
              AND USER_ID = :user_id
            ORDER BY TRANSACTION_DATE DESC, UPDATED_AT DESC
            FETCH FIRST 12 ROWS ONLY
            """,
            user_id=user_id,
        )
        categories = _query_all(
            """
            SELECT NVL(CATEGORY, 'uncategorized') AS CATEGORY,
                   SUM(CASE WHEN AMOUNT > 0 THEN AMOUNT ELSE 0 END) AS SPEND_TOTAL,
                   COUNT(*) AS TRANSACTION_COUNT
            FROM BUDGET_TRANSACTIONS
            WHERE PROVIDER = 'teller'
              AND USER_ID = :user_id
              AND TRANSACTION_DATE >= :month_start
              AND TRANSACTION_DATE < :month_end
            GROUP BY NVL(CATEGORY, 'uncategorized')
            ORDER BY SPEND_TOTAL DESC NULLS LAST
            FETCH FIRST 8 ROWS ONLY
            """,
            user_id=user_id,
            month_start=month_start,
            month_end=month_end,
        )
        categories = _attach_bar_percent(categories, "spend_total")
        return render_template(
            "dashboard.html",
            summary=summary,
            previous=previous,
            accounts=accounts,
            recent_transactions=recent_transactions,
            categories=categories,
            month_start=month_start,
        )

    @budget.route("/transactions")
    @user_required
    def transactions() -> Any:
        user_id = current_user_id()
        search = request.args.get("q", "").strip()
        status = request.args.get("status", "").strip()
        account_id = request.args.get("account", "").strip()
        institution_id = request.args.get("institution", "").strip()
        params: dict[str, Any] = {"user_id": user_id}
        clauses = ["t.PROVIDER = 'teller'", "t.USER_ID = :user_id"]
        if search:
            clauses.append("(LOWER(t.DESCRIPTION) LIKE :search OR LOWER(NVL(t.COUNTERPARTY_NAME, '')) LIKE :search)")
            params["search"] = f"%{search.lower()}%"
        if status:
            clauses.append("t.STATUS = :status")
            params["status"] = status
        if account_id:
            clauses.append("t.PROVIDER_ACCOUNT_ID = :account_id")
            params["account_id"] = account_id
        if institution_id:
            clauses.append("NVL(t.INSTITUTION_ID, a.INSTITUTION_ID) = :institution_id")
            params["institution_id"] = institution_id

        rows = _query_all(
            f"""
            SELECT
                t.TRANSACTION_DATE,
                t.AMOUNT,
                t.CURRENCY_CODE,
                t.STATUS,
                t.CATEGORY,
                t.COUNTERPARTY_NAME,
                t.DESCRIPTION,
                t.TRANSACTION_TYPE,
                a.ACCOUNT_NAME,
                NVL(t.INSTITUTION_ID, a.INSTITUTION_ID) AS INSTITUTION_ID,
                NVL(t.INSTITUTION_NAME, a.INSTITUTION_NAME) AS INSTITUTION_NAME,
                t.PROVIDER_TRANSACTION_ID
            FROM BUDGET_TRANSACTIONS t
            LEFT JOIN BUDGET_ACCOUNTS a
              ON a.PROVIDER = t.PROVIDER
             AND a.PROVIDER_ACCOUNT_ID = t.PROVIDER_ACCOUNT_ID
             AND a.USER_ID = t.USER_ID
            WHERE {" AND ".join(clauses)}
            ORDER BY t.TRANSACTION_DATE DESC, t.UPDATED_AT DESC
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
        return render_template(
            "transactions.html",
            transactions=rows,
            accounts=accounts,
            institutions=institutions,
            filters={"q": search, "status": status, "account": account_id, "institution": institution_id},
        )

    @budget.route("/budgets")
    @user_required
    def budgets() -> Any:
        user_id = current_user_id()
        month_start, month_end = _month_bounds()
        rows = _query_all(
            """
            SELECT NVL(CATEGORY, 'uncategorized') AS CATEGORY,
                   SUM(CASE WHEN AMOUNT > 0 THEN AMOUNT ELSE 0 END) AS SPEND_TOTAL,
                   COUNT(*) AS TRANSACTION_COUNT
            FROM BUDGET_TRANSACTIONS
            WHERE PROVIDER = 'teller'
              AND USER_ID = :user_id
              AND TRANSACTION_DATE >= :month_start
              AND TRANSACTION_DATE < :month_end
            GROUP BY NVL(CATEGORY, 'uncategorized')
            ORDER BY SPEND_TOTAL DESC NULLS LAST
            """,
            user_id=user_id,
            month_start=month_start,
            month_end=month_end,
        )
        rows = _attach_bar_percent(rows, "spend_total")
        return render_template("budgets.html", categories=rows, month_start=month_start)

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
            SELECT CONNECTION_ID, ENVIRONMENT, INSTITUTION_ID, INSTITUTION_NAME, STATUS, LAST_SYNC_AT, CREATED_AT
            FROM BUDGET_CONNECTIONS
            WHERE PROVIDER = 'teller'
              AND USER_ID = :user_id
            ORDER BY UPDATED_AT DESC
            """,
            user_id=user_id,
        )
        return render_template("accounts.html", accounts=rows, connections=connections)

    @budget.route("/connect")
    @user_required
    def connect_page() -> Any:
        institution_options = [
            {"id": "", "name": "Teller institution picker"},
            {"id": "amex", "name": "American Express"},
        ]
        return render_template(
            "connect.html",
            default_institution_id=app_config.teller.institution_id,
            institution_options=institution_options,
        )

    @budget.route("/settings")
    @admin_required
    def settings() -> Any:
        return render_template("settings.html", web_config=web_config, app_config=app_config)

    @budget.route("/actions/sync/<connection_id>", methods=["POST"])
    @user_required
    def sync_action(connection_id: str) -> Any:
        try:
            require_csrf()
            start_date = request.form.get("start_date") or None
            end_date = request.form.get("end_date") or None
            summary = _execute_sync(
                connection_id,
                user_id=current_user_id(),
                start_date=start_date,
                end_date=end_date,
            )
            flash(
                f"Synced {summary['accounts']} accounts and {summary['transactions']} transactions.",
                "success",
            )
        except Exception as exc:
            flash(f"Sync failed: {type(exc).__name__}: {str(exc)[:220]}", "error")
        return redirect(url_for("budget.accounts"))

    @budget.route("/api/config")
    @user_required
    def teller_config() -> Any:
        try:
            institution_id = _selected_institution_id(app_config.teller.institution_id)
        except ValueError as exc:
            return jsonify({"ok": False, "error": "invalid_institution_id", "message": str(exc)}), 400

        nonce = secrets.token_urlsafe(32)
        teller_csrf_token = secrets.token_urlsafe(32)
        session["teller_nonce"] = nonce
        session["teller_csrf_token"] = teller_csrf_token
        session["teller_institution_id"] = institution_id
        return jsonify(
            {
                "ok": True,
                "applicationId": app_config.teller.application_id,
                "environment": app_config.teller.environment,
                "products": ["transactions", "balance"],
                "nonce": nonce,
                "csrfToken": teller_csrf_token,
                "institutionId": institution_id,
            }
        )

    @budget.route("/api/status")
    @user_required
    def teller_status() -> Any:
        return jsonify({"ok": True, "lastEvent": state.last_event})

    @budget.route("/api/teller/enrollment", methods=["POST"])
    @user_required
    def teller_enrollment() -> Any:
        expected_origin = web_config.external_origin or request.host_url.rstrip("/")
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != expected_origin:
            state.remember("blocked", "Rejected enrollment callback origin", origin=origin)
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
            session.pop("teller_nonce", None)
            session.pop("teller_csrf_token", None)
            session.pop("teller_institution_id", None)
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
            state.remember("sync_error", "Enrollment callback failed before sync completed", **details)
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
