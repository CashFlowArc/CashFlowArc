from __future__ import annotations

import json
import hashlib
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
import uuid

import oracledb

from .config import OracleConfig


def connect(config: OracleConfig) -> oracledb.Connection:
    return oracledb.connect(
        user=config.user,
        password=config.password,
        dsn=config.dsn,
        config_dir=config.wallet_dir,
        wallet_location=config.wallet_dir,
        wallet_password=config.wallet_password,
    )


def _table_exists(conn: oracledb.Connection, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM user_tables WHERE table_name = :table_name",
            table_name=table_name.upper(),
        )
        return bool(cur.fetchone()[0])


def _column_exists(conn: oracledb.Connection, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM user_tab_columns
            WHERE table_name = :table_name
              AND column_name = :column_name
            """,
            table_name=table_name.upper(),
            column_name=column_name.upper(),
        )
        return bool(cur.fetchone()[0])


def _connection_id(user_id: str, provider_enrollment_id: str) -> str:
    return hashlib.sha256(f"{user_id}:teller:{provider_enrollment_id}".encode("utf-8")).hexdigest()


def initialize_schema(conn: oracledb.Connection) -> list[str]:
    statements: list[tuple[str, str]] = [
        (
            "BUDGET_USERS",
            """
            CREATE TABLE BUDGET_USERS (
                USER_ID VARCHAR2(64) PRIMARY KEY,
                EMAIL VARCHAR2(320) NOT NULL,
                DISPLAY_NAME VARCHAR2(256),
                PASSWORD_HASH VARCHAR2(512) NOT NULL,
                STATUS VARCHAR2(32) DEFAULT 'ACTIVE' NOT NULL,
                CREATED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
                UPDATED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
                LAST_LOGIN_AT TIMESTAMP WITH TIME ZONE,
                CONSTRAINT BUDGET_USERS_EMAIL_UK UNIQUE (EMAIL)
            )
            """,
        ),
        (
            "BUDGET_CONNECTIONS",
            """
            CREATE TABLE BUDGET_CONNECTIONS (
                CONNECTION_ID VARCHAR2(128) PRIMARY KEY,
                USER_ID VARCHAR2(64) NOT NULL,
                PROVIDER VARCHAR2(32) NOT NULL,
                ENVIRONMENT VARCHAR2(32) NOT NULL,
                PROVIDER_USER_ID VARCHAR2(128),
                PROVIDER_ENROLLMENT_ID VARCHAR2(128) NOT NULL,
                INSTITUTION_ID VARCHAR2(128),
                INSTITUTION_NAME VARCHAR2(256),
                ACCESS_TOKEN_CIPHER CLOB NOT NULL,
                TOKEN_KEY_ID VARCHAR2(128) NOT NULL,
                STATUS VARCHAR2(32) DEFAULT 'ACTIVE' NOT NULL,
                CREATED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
                UPDATED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
                LAST_SYNC_AT TIMESTAMP WITH TIME ZONE,
                METADATA_JSON CLOB,
                CONSTRAINT BUDGET_CONN_USER_FK FOREIGN KEY (USER_ID)
                    REFERENCES BUDGET_USERS (USER_ID),
                CONSTRAINT BUDGET_CONN_PROVIDER_UK UNIQUE (PROVIDER, USER_ID, PROVIDER_ENROLLMENT_ID)
            )
            """,
        ),
        (
            "BUDGET_ACCOUNTS",
            """
            CREATE TABLE BUDGET_ACCOUNTS (
                PROVIDER VARCHAR2(32) NOT NULL,
                PROVIDER_ACCOUNT_ID VARCHAR2(128) NOT NULL,
                USER_ID VARCHAR2(64) NOT NULL,
                CONNECTION_ID VARCHAR2(128) NOT NULL,
                PROVIDER_ENROLLMENT_ID VARCHAR2(128),
                INSTITUTION_ID VARCHAR2(128),
                INSTITUTION_NAME VARCHAR2(256),
                ACCOUNT_NAME VARCHAR2(256),
                ACCOUNT_TYPE VARCHAR2(64),
                ACCOUNT_SUBTYPE VARCHAR2(64),
                CURRENCY_CODE VARCHAR2(8),
                LAST_FOUR VARCHAR2(16),
                STATUS VARCHAR2(32),
                SUPPORTS_BALANCES NUMBER(1) DEFAULT 0 NOT NULL,
                SUPPORTS_TRANSACTIONS NUMBER(1) DEFAULT 0 NOT NULL,
                CREATED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
                UPDATED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
                RAW_JSON CLOB,
                CONSTRAINT BUDGET_ACCOUNTS_PK PRIMARY KEY (PROVIDER, PROVIDER_ACCOUNT_ID),
                CONSTRAINT BUDGET_ACCOUNTS_USER_FK FOREIGN KEY (USER_ID)
                    REFERENCES BUDGET_USERS (USER_ID),
                CONSTRAINT BUDGET_ACCOUNTS_CONN_FK FOREIGN KEY (CONNECTION_ID)
                    REFERENCES BUDGET_CONNECTIONS (CONNECTION_ID)
            )
            """,
        ),
        (
            "BUDGET_TRANSACTIONS",
            """
            CREATE TABLE BUDGET_TRANSACTIONS (
                PROVIDER VARCHAR2(32) NOT NULL,
                PROVIDER_TRANSACTION_ID VARCHAR2(128) NOT NULL,
                USER_ID VARCHAR2(64) NOT NULL,
                PROVIDER_ACCOUNT_ID VARCHAR2(128) NOT NULL,
                CONNECTION_ID VARCHAR2(128) NOT NULL,
                INSTITUTION_ID VARCHAR2(128),
                INSTITUTION_NAME VARCHAR2(256),
                TRANSACTION_DATE DATE,
                AMOUNT NUMBER(19, 4),
                CURRENCY_CODE VARCHAR2(8),
                DESCRIPTION VARCHAR2(1024),
                CATEGORY VARCHAR2(128),
                COUNTERPARTY_NAME VARCHAR2(512),
                COUNTERPARTY_TYPE VARCHAR2(64),
                STATUS VARCHAR2(32),
                TRANSACTION_TYPE VARCHAR2(64),
                RUNNING_BALANCE NUMBER(19, 4),
                CREATED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
                UPDATED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
                RAW_JSON CLOB,
                CONSTRAINT BUDGET_TXNS_PK PRIMARY KEY (PROVIDER, PROVIDER_TRANSACTION_ID),
                CONSTRAINT BUDGET_TXNS_USER_FK FOREIGN KEY (USER_ID)
                    REFERENCES BUDGET_USERS (USER_ID),
                CONSTRAINT BUDGET_TXNS_ACCT_FK FOREIGN KEY (PROVIDER, PROVIDER_ACCOUNT_ID)
                    REFERENCES BUDGET_ACCOUNTS (PROVIDER, PROVIDER_ACCOUNT_ID),
                CONSTRAINT BUDGET_TXNS_CONN_FK FOREIGN KEY (CONNECTION_ID)
                    REFERENCES BUDGET_CONNECTIONS (CONNECTION_ID)
            )
            """,
        ),
        (
            "BUDGET_SYNC_EVENTS",
            """
            CREATE TABLE BUDGET_SYNC_EVENTS (
                SYNC_EVENT_ID NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                PROVIDER VARCHAR2(32) NOT NULL,
                USER_ID VARCHAR2(64),
                CONNECTION_ID VARCHAR2(128),
                PROVIDER_ACCOUNT_ID VARCHAR2(128),
                EVENT_TYPE VARCHAR2(64) NOT NULL,
                STATUS VARCHAR2(32) NOT NULL,
                STARTED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
                FINISHED_AT TIMESTAMP WITH TIME ZONE,
                ROWS_UPSERTED NUMBER DEFAULT 0 NOT NULL,
                ERROR_CODE VARCHAR2(128),
                ERROR_MESSAGE VARCHAR2(1024),
                DETAILS_JSON CLOB
            )
            """,
        ),
        (
            "BUDGET_INSTITUTION_SUPPORT",
            """
            CREATE TABLE BUDGET_INSTITUTION_SUPPORT (
                PROVIDER VARCHAR2(32) NOT NULL,
                INSTITUTION_ID VARCHAR2(128) NOT NULL,
                INSTITUTION_NAME VARCHAR2(256) NOT NULL,
                PRODUCTS_JSON CLOB,
                CHECKED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
                CONSTRAINT BUDGET_INST_SUPPORT_PK PRIMARY KEY (PROVIDER, INSTITUTION_ID)
            )
            """,
        ),
    ]

    created: list[str] = []
    with conn.cursor() as cur:
        for table_name, ddl in statements:
            if not _table_exists(conn, table_name):
                cur.execute(ddl)
                created.append(table_name)

        user_columns = [
            ("BUDGET_CONNECTIONS", "USER_ID"),
            ("BUDGET_ACCOUNTS", "USER_ID"),
            ("BUDGET_TRANSACTIONS", "USER_ID"),
            ("BUDGET_SYNC_EVENTS", "USER_ID"),
        ]
        for table_name, column_name in user_columns:
            if _table_exists(conn, table_name) and not _column_exists(conn, table_name, column_name):
                cur.execute(f"ALTER TABLE {table_name} ADD ({column_name} VARCHAR2(64))")

        transaction_columns = [
            ("INSTITUTION_ID", "VARCHAR2(128)"),
            ("INSTITUTION_NAME", "VARCHAR2(256)"),
        ]
        for column_name, column_type in transaction_columns:
            if _table_exists(conn, "BUDGET_TRANSACTIONS") and not _column_exists(
                conn, "BUDGET_TRANSACTIONS", column_name
            ):
                cur.execute(f"ALTER TABLE BUDGET_TRANSACTIONS ADD ({column_name} {column_type})")

        indexes = [
            "CREATE INDEX BUDGET_USERS_STATUS_IDX ON BUDGET_USERS (STATUS, EMAIL)",
            "CREATE INDEX BUDGET_CONN_USER_IDX ON BUDGET_CONNECTIONS (USER_ID, UPDATED_AT)",
            "CREATE INDEX BUDGET_ACCTS_USER_INST_IDX ON BUDGET_ACCOUNTS (USER_ID, INSTITUTION_NAME)",
            "CREATE INDEX BUDGET_TXNS_USER_DATE_IDX ON BUDGET_TRANSACTIONS (USER_ID, TRANSACTION_DATE)",
            "CREATE INDEX BUDGET_TXNS_ACCT_DATE_IDX ON BUDGET_TRANSACTIONS (PROVIDER_ACCOUNT_ID, TRANSACTION_DATE)",
            "CREATE INDEX BUDGET_TXNS_CONN_DATE_IDX ON BUDGET_TRANSACTIONS (CONNECTION_ID, TRANSACTION_DATE)",
            "CREATE INDEX BUDGET_SYNC_CONN_IDX ON BUDGET_SYNC_EVENTS (CONNECTION_ID, STARTED_AT)",
        ]
        for ddl in indexes:
            try:
                cur.execute(ddl)
            except oracledb.DatabaseError as exc:
                error_obj = exc.args[0]
                if getattr(error_obj, "code", None) != 955:
                    raise

    conn.commit()
    return created


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


class BudgetStore:
    def __init__(self, conn: oracledb.Connection):
        self.conn = conn

    def create_user(self, *, email: str, password_hash: str, display_name: str | None = None) -> str:
        user_id = uuid.uuid4().hex
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO BUDGET_USERS (
                    USER_ID, EMAIL, DISPLAY_NAME, PASSWORD_HASH, STATUS
                ) VALUES (
                    :user_id, :email, :display_name, :password_hash, 'ACTIVE'
                )
                """,
                user_id=user_id,
                email=email.strip().lower(),
                display_name=display_name,
                password_hash=password_hash,
            )
        return user_id

    def ensure_user(self, *, email: str, password_hash: str, display_name: str | None = None) -> str:
        existing = self.get_user_by_email(email)
        if existing:
            return existing["user_id"]
        return self.create_user(email=email, password_hash=password_hash, display_name=display_name)

    def list_users(self) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    u.USER_ID,
                    u.EMAIL,
                    u.DISPLAY_NAME,
                    u.STATUS,
                    u.CREATED_AT,
                    u.UPDATED_AT,
                    u.LAST_LOGIN_AT,
                    COUNT(DISTINCT c.CONNECTION_ID) AS CONNECTION_COUNT,
                    COUNT(DISTINCT a.PROVIDER_ACCOUNT_ID) AS ACCOUNT_COUNT
                FROM BUDGET_USERS u
                LEFT JOIN BUDGET_CONNECTIONS c
                  ON c.USER_ID = u.USER_ID
                 AND c.PROVIDER = 'teller'
                LEFT JOIN BUDGET_ACCOUNTS a
                  ON a.USER_ID = u.USER_ID
                 AND a.PROVIDER = 'teller'
                GROUP BY
                    u.USER_ID, u.EMAIL, u.DISPLAY_NAME, u.STATUS,
                    u.CREATED_AT, u.UPDATED_AT, u.LAST_LOGIN_AT
                ORDER BY u.EMAIL
                """
            )
            return [
                {
                    "user_id": row[0],
                    "email": row[1],
                    "display_name": row[2],
                    "status": row[3],
                    "created_at": row[4],
                    "updated_at": row[5],
                    "last_login_at": row[6],
                    "connection_count": row[7],
                    "account_count": row[8],
                }
                for row in cur.fetchall()
            ]

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT USER_ID, EMAIL, DISPLAY_NAME, PASSWORD_HASH, STATUS
                FROM BUDGET_USERS
                WHERE EMAIL = :email
                """,
                email=email.strip().lower(),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "user_id": row[0],
                "email": row[1],
                "display_name": row[2],
                "password_hash": row[3],
                "status": row[4],
            }

    def set_user_password(self, *, user_id: str, password_hash: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE BUDGET_USERS
                SET PASSWORD_HASH = :password_hash,
                    UPDATED_AT = SYSTIMESTAMP
                WHERE USER_ID = :user_id
                """,
                user_id=user_id,
                password_hash=password_hash,
            )

    def set_user_status(self, *, user_id: str, status: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE BUDGET_USERS
                SET STATUS = :status,
                    UPDATED_AT = SYSTIMESTAMP
                WHERE USER_ID = :user_id
                """,
                user_id=user_id,
                status=status,
            )

    def mark_user_login(self, user_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE BUDGET_USERS
                SET LAST_LOGIN_AT = SYSTIMESTAMP
                WHERE USER_ID = :user_id
                """,
                user_id=user_id,
            )

    def assign_unowned_data(self, *, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        updates = [
            ("connections", "UPDATE BUDGET_CONNECTIONS SET USER_ID = :user_id, UPDATED_AT = SYSTIMESTAMP WHERE USER_ID IS NULL"),
            ("accounts", "UPDATE BUDGET_ACCOUNTS SET USER_ID = :user_id, UPDATED_AT = SYSTIMESTAMP WHERE USER_ID IS NULL"),
            ("transactions", "UPDATE BUDGET_TRANSACTIONS SET USER_ID = :user_id, UPDATED_AT = SYSTIMESTAMP WHERE USER_ID IS NULL"),
            ("sync_events", "UPDATE BUDGET_SYNC_EVENTS SET USER_ID = :user_id WHERE USER_ID IS NULL"),
        ]
        with self.conn.cursor() as cur:
            for key, sql in updates:
                cur.execute(sql, user_id=user_id)
                counts[key] = cur.rowcount
        return counts

    def upsert_connection(
        self,
        *,
        user_id: str,
        environment: str,
        provider_user_id: str | None,
        provider_enrollment_id: str,
        institution_id: str | None,
        institution_name: str | None,
        access_token_cipher: str,
        token_key_id: str,
        metadata: dict[str, Any],
    ) -> str:
        connection_id = _connection_id(user_id, provider_enrollment_id)
        safe_metadata = dict(metadata)
        safe_metadata.pop("accessToken", None)

        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT CONNECTION_ID
                FROM BUDGET_CONNECTIONS
                WHERE PROVIDER = 'teller'
                  AND PROVIDER_ENROLLMENT_ID = :provider_enrollment_id
                  AND (USER_ID = :user_id OR USER_ID IS NULL)
                FETCH FIRST 1 ROWS ONLY
                """,
                provider_enrollment_id=provider_enrollment_id,
                user_id=user_id,
            )
            row = cur.fetchone()
            if row:
                connection_id = row[0]

            cur.execute(
                """
                MERGE INTO BUDGET_CONNECTIONS target
                USING (
                    SELECT
                        :connection_id AS CONNECTION_ID,
                        :user_id AS USER_ID,
                        'teller' AS PROVIDER,
                        :environment AS ENVIRONMENT,
                        :provider_user_id AS PROVIDER_USER_ID,
                        :provider_enrollment_id AS PROVIDER_ENROLLMENT_ID,
                        :institution_id AS INSTITUTION_ID,
                        :institution_name AS INSTITUTION_NAME,
                        :access_token_cipher AS ACCESS_TOKEN_CIPHER,
                        :token_key_id AS TOKEN_KEY_ID,
                        :metadata_json AS METADATA_JSON
                    FROM dual
                ) source
                ON (target.CONNECTION_ID = source.CONNECTION_ID)
                WHEN MATCHED THEN UPDATE SET
                    target.ENVIRONMENT = source.ENVIRONMENT,
                    target.USER_ID = source.USER_ID,
                    target.PROVIDER_USER_ID = source.PROVIDER_USER_ID,
                    target.PROVIDER_ENROLLMENT_ID = source.PROVIDER_ENROLLMENT_ID,
                    target.INSTITUTION_ID = source.INSTITUTION_ID,
                    target.INSTITUTION_NAME = source.INSTITUTION_NAME,
                    target.ACCESS_TOKEN_CIPHER = source.ACCESS_TOKEN_CIPHER,
                    target.TOKEN_KEY_ID = source.TOKEN_KEY_ID,
                    target.STATUS = 'ACTIVE',
                    target.UPDATED_AT = SYSTIMESTAMP,
                    target.METADATA_JSON = source.METADATA_JSON
                WHEN NOT MATCHED THEN INSERT (
                    CONNECTION_ID, USER_ID, PROVIDER, ENVIRONMENT, PROVIDER_USER_ID,
                    PROVIDER_ENROLLMENT_ID, INSTITUTION_ID, INSTITUTION_NAME,
                    ACCESS_TOKEN_CIPHER, TOKEN_KEY_ID, METADATA_JSON
                ) VALUES (
                    source.CONNECTION_ID, source.USER_ID, source.PROVIDER, source.ENVIRONMENT,
                    source.PROVIDER_USER_ID, source.PROVIDER_ENROLLMENT_ID,
                    source.INSTITUTION_ID, source.INSTITUTION_NAME, source.ACCESS_TOKEN_CIPHER,
                    source.TOKEN_KEY_ID, source.METADATA_JSON
                )
                """,
                connection_id=connection_id,
                user_id=user_id,
                environment=environment,
                provider_user_id=provider_user_id,
                provider_enrollment_id=provider_enrollment_id,
                institution_id=institution_id,
                institution_name=institution_name,
                access_token_cipher=access_token_cipher,
                token_key_id=token_key_id,
                metadata_json=_json(safe_metadata),
            )
        return connection_id

    def get_connection_token_cipher(self, connection_id: str, *, user_id: str | None = None) -> str:
        user_clause = "AND USER_ID = :user_id" if user_id else ""
        params = {"connection_id": connection_id}
        if user_id:
            params["user_id"] = user_id
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ACCESS_TOKEN_CIPHER
                FROM BUDGET_CONNECTIONS
                WHERE CONNECTION_ID = :connection_id
                  AND PROVIDER = 'teller'
                  {user_clause}
                """,
                params,
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"No Teller connection found for {connection_id}")
            value = row[0]
            return value.read() if hasattr(value, "read") else value

    def upsert_account(self, *, user_id: str, connection_id: str, account: dict[str, Any]) -> None:
        links = account.get("links") or {}
        institution = account.get("institution") or {}
        with self.conn.cursor() as cur:
            cur.execute(
                """
                MERGE INTO BUDGET_ACCOUNTS target
                USING (
                    SELECT
                        'teller' AS PROVIDER,
                        :provider_account_id AS PROVIDER_ACCOUNT_ID,
                        :user_id AS USER_ID,
                        :connection_id AS CONNECTION_ID,
                        :provider_enrollment_id AS PROVIDER_ENROLLMENT_ID,
                        :institution_id AS INSTITUTION_ID,
                        :institution_name AS INSTITUTION_NAME,
                        :account_name AS ACCOUNT_NAME,
                        :account_type AS ACCOUNT_TYPE,
                        :account_subtype AS ACCOUNT_SUBTYPE,
                        :currency_code AS CURRENCY_CODE,
                        :last_four AS LAST_FOUR,
                        :status AS STATUS,
                        :supports_balances AS SUPPORTS_BALANCES,
                        :supports_transactions AS SUPPORTS_TRANSACTIONS,
                        :raw_json AS RAW_JSON
                    FROM dual
                ) source
                ON (
                    target.PROVIDER = source.PROVIDER
                    AND target.PROVIDER_ACCOUNT_ID = source.PROVIDER_ACCOUNT_ID
                )
                WHEN MATCHED THEN UPDATE SET
                    target.USER_ID = source.USER_ID,
                    target.CONNECTION_ID = source.CONNECTION_ID,
                    target.PROVIDER_ENROLLMENT_ID = source.PROVIDER_ENROLLMENT_ID,
                    target.INSTITUTION_ID = source.INSTITUTION_ID,
                    target.INSTITUTION_NAME = source.INSTITUTION_NAME,
                    target.ACCOUNT_NAME = source.ACCOUNT_NAME,
                    target.ACCOUNT_TYPE = source.ACCOUNT_TYPE,
                    target.ACCOUNT_SUBTYPE = source.ACCOUNT_SUBTYPE,
                    target.CURRENCY_CODE = source.CURRENCY_CODE,
                    target.LAST_FOUR = source.LAST_FOUR,
                    target.STATUS = source.STATUS,
                    target.SUPPORTS_BALANCES = source.SUPPORTS_BALANCES,
                    target.SUPPORTS_TRANSACTIONS = source.SUPPORTS_TRANSACTIONS,
                    target.UPDATED_AT = SYSTIMESTAMP,
                    target.RAW_JSON = source.RAW_JSON
                WHEN NOT MATCHED THEN INSERT (
                    PROVIDER, PROVIDER_ACCOUNT_ID, USER_ID, CONNECTION_ID, PROVIDER_ENROLLMENT_ID,
                    INSTITUTION_ID, INSTITUTION_NAME, ACCOUNT_NAME, ACCOUNT_TYPE,
                    ACCOUNT_SUBTYPE, CURRENCY_CODE, LAST_FOUR, STATUS,
                    SUPPORTS_BALANCES, SUPPORTS_TRANSACTIONS, RAW_JSON
                ) VALUES (
                    source.PROVIDER, source.PROVIDER_ACCOUNT_ID, source.USER_ID, source.CONNECTION_ID,
                    source.PROVIDER_ENROLLMENT_ID, source.INSTITUTION_ID,
                    source.INSTITUTION_NAME, source.ACCOUNT_NAME, source.ACCOUNT_TYPE,
                    source.ACCOUNT_SUBTYPE, source.CURRENCY_CODE, source.LAST_FOUR,
                    source.STATUS, source.SUPPORTS_BALANCES, source.SUPPORTS_TRANSACTIONS,
                    source.RAW_JSON
                )
                """,
                provider_account_id=account.get("id"),
                user_id=user_id,
                connection_id=connection_id,
                provider_enrollment_id=account.get("enrollment_id"),
                institution_id=institution.get("id"),
                institution_name=institution.get("name"),
                account_name=account.get("name"),
                account_type=account.get("type"),
                account_subtype=account.get("subtype"),
                currency_code=account.get("currency"),
                last_four=account.get("last_four"),
                status=account.get("status"),
                supports_balances=1 if links.get("balances") else 0,
                supports_transactions=1 if links.get("transactions") else 0,
                raw_json=_json(account),
            )

    def upsert_transaction(
        self,
        *,
        user_id: str,
        connection_id: str,
        account: dict[str, Any],
        transaction: dict[str, Any],
    ) -> None:
        details = transaction.get("details") or {}
        counterparty = details.get("counterparty") or {}
        with self.conn.cursor() as cur:
            cur.execute(
                """
                MERGE INTO BUDGET_TRANSACTIONS target
                USING (
                    SELECT
                        'teller' AS PROVIDER,
                        :provider_transaction_id AS PROVIDER_TRANSACTION_ID,
                        :user_id AS USER_ID,
                        :provider_account_id AS PROVIDER_ACCOUNT_ID,
                        :connection_id AS CONNECTION_ID,
                        :institution_id AS INSTITUTION_ID,
                        :institution_name AS INSTITUTION_NAME,
                        :transaction_date AS TRANSACTION_DATE,
                        :amount AS AMOUNT,
                        :currency_code AS CURRENCY_CODE,
                        :description AS DESCRIPTION,
                        :category AS CATEGORY,
                        :counterparty_name AS COUNTERPARTY_NAME,
                        :counterparty_type AS COUNTERPARTY_TYPE,
                        :status AS STATUS,
                        :transaction_type AS TRANSACTION_TYPE,
                        :running_balance AS RUNNING_BALANCE,
                        :raw_json AS RAW_JSON
                    FROM dual
                ) source
                ON (
                    target.PROVIDER = source.PROVIDER
                    AND target.PROVIDER_TRANSACTION_ID = source.PROVIDER_TRANSACTION_ID
                )
                WHEN MATCHED THEN UPDATE SET
                    target.USER_ID = source.USER_ID,
                    target.PROVIDER_ACCOUNT_ID = source.PROVIDER_ACCOUNT_ID,
                    target.CONNECTION_ID = source.CONNECTION_ID,
                    target.INSTITUTION_ID = source.INSTITUTION_ID,
                    target.INSTITUTION_NAME = source.INSTITUTION_NAME,
                    target.TRANSACTION_DATE = source.TRANSACTION_DATE,
                    target.AMOUNT = source.AMOUNT,
                    target.CURRENCY_CODE = source.CURRENCY_CODE,
                    target.DESCRIPTION = source.DESCRIPTION,
                    target.CATEGORY = source.CATEGORY,
                    target.COUNTERPARTY_NAME = source.COUNTERPARTY_NAME,
                    target.COUNTERPARTY_TYPE = source.COUNTERPARTY_TYPE,
                    target.STATUS = source.STATUS,
                    target.TRANSACTION_TYPE = source.TRANSACTION_TYPE,
                    target.RUNNING_BALANCE = source.RUNNING_BALANCE,
                    target.UPDATED_AT = SYSTIMESTAMP,
                    target.RAW_JSON = source.RAW_JSON
                WHEN NOT MATCHED THEN INSERT (
                    PROVIDER, PROVIDER_TRANSACTION_ID, USER_ID, PROVIDER_ACCOUNT_ID,
                    CONNECTION_ID, INSTITUTION_ID, INSTITUTION_NAME, TRANSACTION_DATE, AMOUNT, CURRENCY_CODE,
                    DESCRIPTION, CATEGORY, COUNTERPARTY_NAME, COUNTERPARTY_TYPE,
                    STATUS, TRANSACTION_TYPE, RUNNING_BALANCE, RAW_JSON
                ) VALUES (
                    source.PROVIDER, source.PROVIDER_TRANSACTION_ID,
                    source.USER_ID, source.PROVIDER_ACCOUNT_ID, source.CONNECTION_ID,
                    source.INSTITUTION_ID, source.INSTITUTION_NAME,
                    source.TRANSACTION_DATE, source.AMOUNT, source.CURRENCY_CODE,
                    source.DESCRIPTION, source.CATEGORY, source.COUNTERPARTY_NAME,
                    source.COUNTERPARTY_TYPE, source.STATUS, source.TRANSACTION_TYPE,
                    source.RUNNING_BALANCE, source.RAW_JSON
                )
                """,
                provider_transaction_id=transaction.get("id"),
                user_id=user_id,
                provider_account_id=transaction.get("account_id") or account.get("id"),
                connection_id=connection_id,
                institution_id=(account.get("institution") or {}).get("id"),
                institution_name=(account.get("institution") or {}).get("name"),
                transaction_date=_date(transaction.get("date")),
                amount=_decimal(transaction.get("amount")),
                currency_code=account.get("currency"),
                description=transaction.get("description"),
                category=details.get("category"),
                counterparty_name=counterparty.get("name"),
                counterparty_type=counterparty.get("type"),
                status=transaction.get("status"),
                transaction_type=transaction.get("type"),
                running_balance=_decimal(transaction.get("running_balance")),
                raw_json=_json(transaction),
            )

    def record_sync_event(
        self,
        *,
        user_id: str | None,
        connection_id: str | None,
        account_id: str | None,
        event_type: str,
        status: str,
        rows_upserted: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO BUDGET_SYNC_EVENTS (
                    PROVIDER, USER_ID, CONNECTION_ID, PROVIDER_ACCOUNT_ID, EVENT_TYPE, STATUS,
                    FINISHED_AT, ROWS_UPSERTED, ERROR_CODE, ERROR_MESSAGE, DETAILS_JSON
                ) VALUES (
                    'teller', :user_id, :connection_id, :account_id, :event_type, :status,
                    SYSTIMESTAMP, :rows_upserted, :error_code, :error_message, :details_json
                )
                """,
                user_id=user_id,
                connection_id=connection_id,
                account_id=account_id,
                event_type=event_type,
                status=status,
                rows_upserted=rows_upserted,
                error_code=error_code,
                error_message=(error_message or "")[:1024] or None,
                details_json=_json(details or {}),
            )

    def mark_connection_synced(self, connection_id: str, *, user_id: str | None = None) -> None:
        user_clause = "AND USER_ID = :user_id" if user_id else ""
        params = {"connection_id": connection_id}
        if user_id:
            params["user_id"] = user_id
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE BUDGET_CONNECTIONS
                SET LAST_SYNC_AT = SYSTIMESTAMP,
                    UPDATED_AT = SYSTIMESTAMP
                WHERE CONNECTION_ID = :connection_id
                  {user_clause}
                """,
                params,
            )

    def list_connections(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        user_clause = "AND USER_ID = :user_id" if user_id else ""
        params: dict[str, Any] = {}
        if user_id:
            params["user_id"] = user_id
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT CONNECTION_ID, ENVIRONMENT, INSTITUTION_ID, INSTITUTION_NAME, STATUS, LAST_SYNC_AT
                FROM BUDGET_CONNECTIONS
                WHERE PROVIDER = 'teller'
                  {user_clause}
                ORDER BY UPDATED_AT DESC
                """,
                params,
            )
            return [
                {
                    "connection_id": row[0],
                    "environment": row[1],
                    "institution_id": row[2],
                    "institution_name": row[3],
                    "status": row[4],
                    "last_sync_at": row[5].isoformat() if row[5] else None,
                }
                for row in cur.fetchall()
            ]
