# Oracle Access

This repo already contains the working Oracle access pattern.

## Existing Connection Pattern

Read one of these first:

- [getData/getTickerData.py](../../../getData/getTickerData.py)
- [server/server.py](../../../server/server.py)

Both use `oracledb.connect(...)` with wallet-based access.

Expected environment variables:

- `DB_USER`
- `DB_PASSWORD`
- `DB_DSN`
- `WALLET_DIR`
- optional `WALLET_PASSWORD`

Typical connection shape in this repo:

```python
oracledb.connect(
    user=DB_USER,
    password=DB_PASSWORD,
    dsn=DB_DSN,
    config_dir=WALLET_DIR,
    wallet_location=WALLET_DIR,
    wallet_password=WALLET_PASSWORD,
)
```

## Current `TICKER_HISTORY` Query Shape

`server/server.py` already uses the table with this query pattern:

```sql
SELECT
    ticker,
    interval_name,
    ts_utc,
    open_price,
    high_price,
    low_price,
    close_price,
    volume
FROM TICKER_HISTORY
WHERE ticker = :ticker
  AND interval_name = :interval_name
  AND ts_utc >= :start_utc
ORDER BY ts_utc
```

Use this as the starting point for backtests unless the user tells you the schema changed.

## Recommended Discovery Queries

Use small, targeted queries before a full backtest:

1. Coverage check

```sql
SELECT
    ticker,
    interval_name,
    MIN(ts_utc) AS min_ts_utc,
    MAX(ts_utc) AS max_ts_utc,
    COUNT(*) AS row_count
FROM TICKER_HISTORY
GROUP BY ticker, interval_name
ORDER BY ticker, interval_name
```

2. Sample rows

```sql
SELECT *
FROM TICKER_HISTORY
WHERE ticker = :ticker
  AND interval_name = :interval_name
ORDER BY ts_utc DESC
FETCH FIRST 20 ROWS ONLY
```

3. Date-bounded pull for a backtest

```sql
SELECT
    ticker,
    interval_name,
    ts_utc,
    open_price,
    high_price,
    low_price,
    close_price,
    volume
FROM TICKER_HISTORY
WHERE ticker = :ticker
  AND interval_name = :interval_name
  AND ts_utc >= :start_utc
  AND ts_utc < :end_utc
ORDER BY ts_utc
```

## Notes

- Keep queries parameterized.
- Avoid embedding credentials or wallet paths in committed code.
- If Oracle env vars are missing in the current session, stop and ask for connection setup instead of guessing.
