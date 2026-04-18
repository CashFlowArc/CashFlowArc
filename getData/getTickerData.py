#!/usr/bin/env python3

import datetime as dt
import os
import sys
import time
import random
import logging
from datetime import timezone
from typing import Dict, List, Optional

import oracledb
import pandas as pd
import yfinance as yf


# =========================
# CONFIG
# =========================
DB_USER = os.getenv("DB_USER", "MYUSER")
DB_PASSWORD = os.getenv("DB_PASSWORD", "CashFlowArc1")
DB_DSN = os.getenv("DB_DSN", "cfadb1_low")

WALLET_DIR = os.getenv("WALLET_DIR", "/home/opc/wallets/myadb")
WALLET_PASSWORD = os.getenv("WALLET_PASSWORD", "your_wallet_password")

TABLE_NAME = os.getenv("TABLE_NAME", "TICKER_HISTORY")
OPTION_TABLE_NAME = os.getenv("OPTION_TABLE_NAME", "TICKER_OPTIONS_HISTORY")
INTERVAL_NAME = "1m"
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))

YF_PERIOD = os.getenv("YF_PERIOD", "8d")
YF_INTERVAL = os.getenv("YF_INTERVAL", "1m")
OPTION_TARGET_DTES = [
    int(value.strip())
    for value in os.getenv("OPTION_TARGET_DTES", "0,1,5,7").split(",")
    if value.strip()
]


# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("ticker-collector")


# =========================
# TICKER MAPPING
# =========================
def normalize_input_tickers(argv: List[str]) -> List[str]:
    """
    Accept either:
      python3 script.py SPY SPX QQQ
      python3 script.py SPY,SPX,QQQ
      python3 script.py SPY-SPX-QQQ
      python3 script.py SPY_SPX_QQQ
    """
    if len(argv) < 2:
        print("Usage: python3 getTickerData.py <TICKER1> [TICKER2 ...]")
        print("   or: python3 getTickerData.py SPY,SPX,QQQ")
        print("   or: python3 getTickerData.py SPY-SPX-QQQ")
        sys.exit(1)

    raw = []
    for arg in argv[1:]:
        raw.extend(
            [
                x.strip().upper()
                for x in arg.replace("-", ",").replace("_", ",").split(",")
                if x.strip()
            ]
        )

    seen = set()
    tickers = []
    for ticker in raw:
        if ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)

    if not tickers:
        print("No valid tickers supplied.")
        sys.exit(1)

    return tickers


def db_to_yf_ticker(db_ticker: str) -> str:
    mapping = {
        "SPX": "^GSPC",
    }
    return mapping.get(db_ticker.upper(), db_ticker.upper())


def yf_to_db_ticker(yf_ticker: str) -> str:
    reverse_mapping = {
        "^GSPC": "SPX",
    }
    return reverse_mapping.get(yf_ticker.upper(), yf_ticker.upper())


INPUT_DB_TICKERS = normalize_input_tickers(sys.argv)
YF_TICKERS = [db_to_yf_ticker(t) for t in INPUT_DB_TICKERS]

logger.info("Starting collector")
logger.info("DB tickers: %s", INPUT_DB_TICKERS)
logger.info("Yahoo tickers: %s", YF_TICKERS)


# =========================
# DB CONNECTION HELPERS
# =========================
def get_connection() -> oracledb.Connection:
    return oracledb.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        dsn=DB_DSN,
        config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=WALLET_PASSWORD,
    )


def is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "429" in msg
        or "too many requests" in msg
        or "rate limit" in msg
    )


def is_disconnect_error(exc: Exception) -> bool:
    msg = str(exc)
    msg_lower = msg.lower()
    return any(token in msg for token in ["DPY-4011", "DPY-1001", "DPI-1080"]) or any(
        token in msg_lower
        for token in [
            "not connected",
            "connection was closed",
            "database or network closed the connection",
            "socket closed",
            "end-of-file on communication channel",
        ]
    )


def sleep_to_next_minute() -> None:
    now = time.time()
    sleep_seconds = POLL_SECONDS - (now % POLL_SECONDS)
    if sleep_seconds < 1:
        sleep_seconds = 1
    time.sleep(sleep_seconds)


def sleep_backoff_429() -> None:
    delay = random.randint(60, 300)
    logger.warning("Rate limit hit. Sleeping %s seconds before retry.", delay)
    time.sleep(delay)


def safe_float(value) -> Optional[float]:
    if pd.isna(value):
        return None
    return float(value)


def safe_int(value) -> int:
    if pd.isna(value):
        return 0
    return int(value)


def safe_bool_number(value) -> Optional[int]:
    if pd.isna(value):
        return None
    return 1 if bool(value) else 0


def safe_timestamp(value) -> Optional[dt.datetime]:
    if value is None or pd.isna(value):
        return None

    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.to_pydatetime()


# =========================
# CREATE / UPGRADE TABLE
# =========================
def create_or_upgrade_tables() -> None:
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            f"""
            BEGIN
                EXECUTE IMMEDIATE '
                    CREATE TABLE {TABLE_NAME} (
                        ticker          VARCHAR2(20)   NOT NULL,
                        interval_name   VARCHAR2(10)   NOT NULL,
                        ts_utc          TIMESTAMP(6)   NOT NULL,
                        open_price      NUMBER(18,6),
                        high_price      NUMBER(18,6),
                        low_price       NUMBER(18,6),
                        close_price     NUMBER(18,6),
                        volume          NUMBER(18,0),
                        created_at      TIMESTAMP(6) DEFAULT SYSTIMESTAMP NOT NULL,
                        CONSTRAINT {TABLE_NAME}_pk PRIMARY KEY (ticker, interval_name, ts_utc)
                    )
                ';
            EXCEPTION
                WHEN OTHERS THEN
                    IF SQLCODE != -955 THEN
                        RAISE;
                    END IF;
            END;
            """
        )

        try:
            cur.execute(f"ALTER TABLE {TABLE_NAME} ADD (interval_name VARCHAR2(10))")
            cur.execute(
                f"UPDATE {TABLE_NAME} SET interval_name = '1m' WHERE interval_name IS NULL"
            )
            cur.execute(f"ALTER TABLE {TABLE_NAME} MODIFY (interval_name NOT NULL)")

            cur.execute(
                f"""
                DECLARE
                    v_pk VARCHAR2(128);
                BEGIN
                    SELECT constraint_name INTO v_pk
                    FROM user_constraints
                    WHERE table_name = UPPER('{TABLE_NAME}')
                      AND constraint_type = 'P';

                    EXECUTE IMMEDIATE 'ALTER TABLE {TABLE_NAME} DROP CONSTRAINT ' || v_pk;
                EXCEPTION
                    WHEN OTHERS THEN NULL;
                END;
                """
            )

            cur.execute(
                f"""
                ALTER TABLE {TABLE_NAME}
                ADD CONSTRAINT {TABLE_NAME}_pk
                PRIMARY KEY (ticker, interval_name, ts_utc)
                """
            )
        except Exception:
            pass

        cur.execute(
            f"""
            BEGIN
                EXECUTE IMMEDIATE '
                    CREATE TABLE {OPTION_TABLE_NAME} (
                        ticker                    VARCHAR2(20)   NOT NULL,
                        snapshot_ts_utc           TIMESTAMP(6)   NOT NULL,
                        expiration_date           DATE           NOT NULL,
                        dte_target                NUMBER(4,0)    NOT NULL,
                        actual_dte                NUMBER(4,0),
                        option_type               VARCHAR2(4)    NOT NULL,
                        contract_symbol           VARCHAR2(64)   NOT NULL,
                        strike                    NUMBER(18,6),
                        last_price                NUMBER(18,6),
                        bid_price                 NUMBER(18,6),
                        ask_price                 NUMBER(18,6),
                        change_amount             NUMBER(18,6),
                        percent_change            NUMBER(18,6),
                        volume                    NUMBER(18,0),
                        open_interest             NUMBER(18,0),
                        implied_volatility        NUMBER(18,8),
                        in_the_money              NUMBER(1,0),
                        last_trade_ts_utc         TIMESTAMP(6),
                        contract_size             VARCHAR2(16),
                        currency                  VARCHAR2(16),
                        underlying_price          NUMBER(18,6),
                        underlying_previous_close NUMBER(18,6),
                        created_at                TIMESTAMP(6) DEFAULT SYSTIMESTAMP NOT NULL,
                        CONSTRAINT {OPTION_TABLE_NAME}_pk PRIMARY KEY (ticker, snapshot_ts_utc, contract_symbol)
                    )
                ';
            EXCEPTION
                WHEN OTHERS THEN
                    IF SQLCODE != -955 THEN
                        RAISE;
                    END IF;
            END;
            """
        )

        conn.commit()
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# Uncomment once if you need it:
# create_or_upgrade_tables()


# =========================
# DB OPERATIONS
# =========================
def get_latest_ts_by_ticker_once(db_tickers: List[str]) -> Dict[str, Optional[object]]:
    """
    Returns dict like:
      {"SPY": datetime(...), "SPX": datetime(...)}
    """
    result = {t: None for t in db_tickers}

    placeholders = ",".join([f":b{i+1}" for i in range(len(db_tickers))])
    sql = f"""
        SELECT ticker, MAX(ts_utc) AS max_ts
        FROM {TABLE_NAME}
        WHERE interval_name = :interval_name
          AND ticker IN ({placeholders})
        GROUP BY ticker
    """

    binds = {"interval_name": INTERVAL_NAME}
    for i, ticker in enumerate(db_tickers):
        binds[f"b{i+1}"] = ticker

    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(sql, binds)
        for ticker, max_ts in cur:
            result[ticker] = max_ts
        return result
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def get_latest_ts_by_ticker(db_tickers: List[str]) -> Dict[str, Optional[object]]:
    try:
        return get_latest_ts_by_ticker_once(db_tickers)
    except Exception as exc:
        if is_disconnect_error(exc):
            logger.warning("DB connection dropped in get_latest_ts_by_ticker(); retrying once: %s", exc)
            time.sleep(1)
            return get_latest_ts_by_ticker_once(db_tickers)
        raise


def insert_rows_once(rows: List[dict]) -> int:
    if not rows:
        return 0

    sql = f"""
        INSERT INTO {TABLE_NAME}
        (ticker, interval_name, ts_utc, open_price, high_price, low_price, close_price, volume)
        SELECT :ticker, :interval_name, :ts_utc, :open_price, :high_price, :low_price, :close_price, :volume
        FROM dual
        WHERE NOT EXISTS (
            SELECT 1
            FROM {TABLE_NAME}
            WHERE ticker = :ticker
              AND interval_name = :interval_name
              AND ts_utc = :ts_utc
        )
    """

    inserted = 0
    conn = None
    cur = None

    try:
        conn = get_connection()
        cur = conn.cursor()

        for row in rows:
            cur.execute(sql, row)
            if cur.rowcount == 1:
                inserted += 1

        conn.commit()
        return inserted
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def insert_rows(rows: List[dict]) -> int:
    try:
        return insert_rows_once(rows)
    except Exception as exc:
        if is_disconnect_error(exc):
            logger.warning("DB connection dropped in insert_rows(); retrying once: %s", exc)
            time.sleep(1)
            return insert_rows_once(rows)
        raise


def insert_option_rows_once(rows: List[dict]) -> int:
    if not rows:
        return 0

    sql = f"""
        INSERT INTO {OPTION_TABLE_NAME}
        (
            ticker,
            snapshot_ts_utc,
            expiration_date,
            dte_target,
            actual_dte,
            option_type,
            contract_symbol,
            strike,
            last_price,
            bid_price,
            ask_price,
            change_amount,
            percent_change,
            volume,
            open_interest,
            implied_volatility,
            in_the_money,
            last_trade_ts_utc,
            contract_size,
            currency,
            underlying_price,
            underlying_previous_close
        )
        SELECT
            :ticker,
            :snapshot_ts_utc,
            :expiration_date,
            :dte_target,
            :actual_dte,
            :option_type,
            :contract_symbol,
            :strike,
            :last_price,
            :bid_price,
            :ask_price,
            :change_amount,
            :percent_change,
            :volume,
            :open_interest,
            :implied_volatility,
            :in_the_money,
            :last_trade_ts_utc,
            :contract_size,
            :currency,
            :underlying_price,
            :underlying_previous_close
        FROM dual
        WHERE NOT EXISTS (
            SELECT 1
            FROM {OPTION_TABLE_NAME}
            WHERE ticker = :ticker
              AND snapshot_ts_utc = :snapshot_ts_utc
              AND contract_symbol = :contract_symbol
        )
    """

    inserted = 0
    conn = None
    cur = None

    try:
        conn = get_connection()
        cur = conn.cursor()

        for row in rows:
            cur.execute(sql, row)
            if cur.rowcount == 1:
                inserted += 1

        conn.commit()
        return inserted
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def insert_option_rows(rows: List[dict]) -> int:
    try:
        return insert_option_rows_once(rows)
    except Exception as exc:
        if is_disconnect_error(exc):
            logger.warning("DB connection dropped in insert_option_rows(); retrying once: %s", exc)
            time.sleep(1)
            return insert_option_rows_once(rows)
        raise


# =========================
# FETCH DATA
# =========================
def build_rows_for_one_ticker(
    db_ticker: str,
    ticker_df: pd.DataFrame,
    latest_ts,
) -> List[dict]:
    rows = []

    if ticker_df is None or ticker_df.empty:
        logger.warning("No rows returned for %s", db_ticker)
        return rows

    expected_cols = {"Open", "High", "Low", "Close", "Volume"}
    missing = expected_cols - set(ticker_df.columns)
    if missing:
        logger.warning("Missing columns for %s: %s", db_ticker, sorted(missing))
        return rows

    for idx, row in ticker_df.iterrows():
        ts = idx.to_pydatetime()

        if ts.tzinfo:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)

        if latest_ts is not None and ts <= latest_ts:
            continue

        rows.append(
            {
                "ticker": db_ticker,
                "interval_name": INTERVAL_NAME,
                "ts_utc": ts,
                "open_price": safe_float(row["Open"]),
                "high_price": safe_float(row["High"]),
                "low_price": safe_float(row["Low"]),
                "close_price": safe_float(row["Close"]),
                "volume": safe_int(row["Volume"]),
            }
        )

    return rows


def get_latest_close_values(ticker_df: pd.DataFrame) -> tuple[Optional[float], Optional[float]]:
    if ticker_df is None or ticker_df.empty or "Close" not in ticker_df.columns:
        return None, None

    closes = pd.to_numeric(ticker_df["Close"], errors="coerce").dropna()
    if closes.empty:
        return None, None

    latest_close = float(closes.iloc[-1])
    previous_close = float(closes.iloc[-2]) if len(closes) >= 2 else latest_close
    return latest_close, previous_close


def select_option_expirations(
    now_et: pd.Timestamp,
    expiration_labels: List[str],
    target_dtes: List[int],
) -> List[tuple[int, dt.date, str]]:
    expiration_map = {
        pd.Timestamp(label).date(): label
        for label in expiration_labels
    }
    available_dates = sorted(expiration_map)
    if not available_dates:
        return []

    selected: List[tuple[int, dt.date, str]] = []
    seen_dates = set()
    current_date = now_et.date()

    for target_dte in target_dtes:
        target_date = current_date + dt.timedelta(days=target_dte)
        chosen_date = next((value for value in available_dates if value >= target_date), available_dates[-1])
        if chosen_date in seen_dates:
            continue
        seen_dates.add(chosen_date)
        selected.append((target_dte, chosen_date, expiration_map[chosen_date]))

    return selected


def build_option_rows_for_chain(
    db_ticker: str,
    snapshot_ts_utc: dt.datetime,
    expiration_date: dt.date,
    dte_target: int,
    actual_dte: int,
    option_type: str,
    frame: pd.DataFrame,
    underlying_price: Optional[float],
    underlying_previous_close: Optional[float],
) -> List[dict]:
    if frame is None or frame.empty:
        return []

    rows: List[dict] = []
    working = frame.copy()
    for _, row in working.iterrows():
        contract_symbol = row.get("contractSymbol")
        if pd.isna(contract_symbol) or not contract_symbol:
            continue

        rows.append(
            {
                "ticker": db_ticker,
                "snapshot_ts_utc": snapshot_ts_utc,
                "expiration_date": expiration_date,
                "dte_target": dte_target,
                "actual_dte": actual_dte,
                "option_type": option_type,
                "contract_symbol": str(contract_symbol),
                "strike": safe_float(row.get("strike")),
                "last_price": safe_float(row.get("lastPrice")),
                "bid_price": safe_float(row.get("bid")),
                "ask_price": safe_float(row.get("ask")),
                "change_amount": safe_float(row.get("change")),
                "percent_change": safe_float(row.get("percentChange")),
                "volume": safe_int(row.get("volume")),
                "open_interest": safe_int(row.get("openInterest")),
                "implied_volatility": safe_float(row.get("impliedVolatility")),
                "in_the_money": safe_bool_number(row.get("inTheMoney")),
                "last_trade_ts_utc": safe_timestamp(row.get("lastTradeDate")),
                "contract_size": None if pd.isna(row.get("contractSize")) else str(row.get("contractSize")),
                "currency": None if pd.isna(row.get("currency")) else str(row.get("currency")),
                "underlying_price": underlying_price,
                "underlying_previous_close": underlying_previous_close,
            }
        )

    return rows


def build_option_rows_for_ticker(
    db_ticker: str,
    yf_ticker: str,
    ticker_client,
    snapshot_ts_utc: dt.datetime,
    latest_close: Optional[float],
    previous_close: Optional[float],
) -> List[dict]:
    now_et = pd.Timestamp.now(tz="America/New_York")

    try:
        expiration_labels = list(ticker_client.options or ())
    except Exception as exc:
        logger.warning("Could not load expirations for %s: %s", yf_ticker, exc)
        return []

    selected_expirations = select_option_expirations(now_et, expiration_labels, OPTION_TARGET_DTES)
    if not selected_expirations:
        logger.info("No options expirations available for %s", yf_ticker)
        return []

    option_rows: List[dict] = []

    for dte_target, expiration_date, expiration_label in selected_expirations:
        try:
            chain = ticker_client.option_chain(expiration_label)
        except Exception as exc:
            logger.warning(
                "Could not load option chain for %s expiration %s: %s",
                yf_ticker,
                expiration_label,
                exc,
            )
            continue

        underlying = chain.underlying or {}
        underlying_price = safe_float(
            underlying.get("regularMarketPrice")
            or underlying.get("postMarketPrice")
            or underlying.get("preMarketPrice")
            or latest_close
        )
        underlying_previous_close = safe_float(
            underlying.get("previousClose")
            or previous_close
        )
        actual_dte = max((expiration_date - now_et.date()).days, 0)

        option_rows.extend(
            build_option_rows_for_chain(
                db_ticker=db_ticker,
                snapshot_ts_utc=snapshot_ts_utc,
                expiration_date=expiration_date,
                dte_target=dte_target,
                actual_dte=actual_dte,
                option_type="call",
                frame=chain.calls,
                underlying_price=underlying_price,
                underlying_previous_close=underlying_previous_close,
            )
        )
        option_rows.extend(
            build_option_rows_for_chain(
                db_ticker=db_ticker,
                snapshot_ts_utc=snapshot_ts_utc,
                expiration_date=expiration_date,
                dte_target=dte_target,
                actual_dte=actual_dte,
                option_type="put",
                frame=chain.puts,
                underlying_price=underlying_price,
                underlying_previous_close=underlying_previous_close,
            )
        )

    return option_rows


def fetch_market_data_once(yf_tickers: List[str]) -> Dict[str, List[dict]]:
    """
    Fetch price history for all tickers in one download call, then fetch the
    requested options expirations for the same tickers in the same collection cycle.
    """
    latest_ts_map = get_latest_ts_by_ticker(INPUT_DB_TICKERS)
    logger.info("Latest DB timestamps: %s", latest_ts_map)
    snapshot_ts_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    df = yf.download(
        tickers=yf_tickers,
        period=YF_PERIOD,
        interval=YF_INTERVAL,
        progress=False,
        auto_adjust=False,
        prepost=False,
        threads=False,
        group_by="ticker",
    )

    if df is None or df.empty:
        logger.warning("Yahoo returned no data.")
        return {"price_rows": [], "option_rows": []}

    price_rows: List[dict] = []
    option_rows: List[dict] = []
    single_ticker = len(yf_tickers) == 1
    ticker_frames: Dict[str, pd.DataFrame] = {}

    if single_ticker:
        yf_ticker = yf_tickers[0]
        db_ticker = yf_to_db_ticker(yf_ticker)
        latest_ts = latest_ts_map.get(db_ticker)

        working_df = df.copy()

        if hasattr(working_df.columns, "nlevels") and working_df.columns.nlevels > 1:
            if yf_ticker in working_df.columns.get_level_values(0):
                working_df = working_df[yf_ticker]
            else:
                working_df.columns = working_df.columns.get_level_values(-1)

        ticker_frames[yf_ticker] = working_df
        price_rows.extend(build_rows_for_one_ticker(db_ticker, working_df, latest_ts))
    else:
        if not hasattr(df.columns, "nlevels") or df.columns.nlevels < 2:
            raise RuntimeError(
                "Expected multi-index dataframe for multi-ticker download, but did not get one."
            )

        available_yf_tickers = list(dict.fromkeys(df.columns.get_level_values(0)))

        for yf_ticker in available_yf_tickers:
            db_ticker = yf_to_db_ticker(yf_ticker)
            if db_ticker not in INPUT_DB_TICKERS:
                continue

            latest_ts = latest_ts_map.get(db_ticker)

            try:
                ticker_df = df[yf_ticker].copy()
            except Exception:
                logger.warning("No dataframe slice found for Yahoo ticker %s", yf_ticker)
                continue

            ticker_frames[yf_ticker] = ticker_df
            price_rows.extend(build_rows_for_one_ticker(db_ticker, ticker_df, latest_ts))

    tickers_client = yf.Tickers(" ".join(yf_tickers))
    for yf_ticker in yf_tickers:
        db_ticker = yf_to_db_ticker(yf_ticker)
        ticker_client = tickers_client.tickers.get(yf_ticker)
        if ticker_client is None:
            logger.warning("No Yahoo ticker client available for %s", yf_ticker)
            continue

        latest_close, previous_close = get_latest_close_values(ticker_frames.get(yf_ticker, pd.DataFrame()))
        option_rows.extend(
            build_option_rows_for_ticker(
                db_ticker=db_ticker,
                yf_ticker=yf_ticker,
                ticker_client=ticker_client,
                snapshot_ts_utc=snapshot_ts_utc,
                latest_close=latest_close,
                previous_close=previous_close,
            )
        )

    return {"price_rows": price_rows, "option_rows": option_rows}


def fetch_market_data(yf_tickers: List[str]) -> Dict[str, List[dict]]:
    try:
        return fetch_market_data_once(yf_tickers)
    except Exception as exc:
        if is_disconnect_error(exc):
            logger.warning("DB disconnect during fetch_market_data(); retrying once: %s", exc)
            time.sleep(1)
            return fetch_market_data_once(yf_tickers)
        raise


# =========================
# MAIN LOOP
# =========================
def main() -> None:
    create_or_upgrade_tables()

    while True:
        try:
            data = fetch_market_data(YF_TICKERS)
            price_rows = data["price_rows"]
            option_rows = data["option_rows"]

            inserted_prices = insert_rows(price_rows)
            inserted_options = insert_option_rows(option_rows)

            inserted_by_ticker: Dict[str, int] = {}
            for row in price_rows:
                ticker = row["ticker"]
                inserted_by_ticker[ticker] = inserted_by_ticker.get(ticker, 0) + 1

            logger.info(
                "Cycle complete | price_rows=%s inserted_prices=%s option_rows=%s inserted_options=%s inserted_by_ticker=%s",
                len(price_rows),
                inserted_prices,
                len(option_rows),
                inserted_options,
                inserted_by_ticker,
            )

        except Exception as exc:
            logger.exception("Collector failure: %s", exc)

            if is_rate_limit_error(exc):
                sleep_backoff_429()
                continue

        sleep_to_next_minute()


if __name__ == "__main__":
    main()
