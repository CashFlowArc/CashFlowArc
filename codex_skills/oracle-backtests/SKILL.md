---
name: oracle-backtests
description: Access Oracle market data in this CashFlowArc repo and use `TICKER_HISTORY` for strategy backtests. Use when the user asks to backtest, analyze historical bars from Oracle, inspect the `TICKER_HISTORY` schema or contents, or build/refine a strategy using the Oracle-backed price history in this project.
---

# Oracle Backtests

Use this skill when the task is to work with Oracle-backed historical bar data in this repository, especially `TICKER_HISTORY`.

## What This Skill Covers

- Reuse the repo's existing Oracle connection pattern instead of inventing a new one.
- Treat `TICKER_HISTORY` as the primary historical OHLCV source unless the user says otherwise.
- Pull only the columns needed for the strategy or analysis.
- Keep credentials out of code and rely on environment variables.
- When strategy rules are underspecified, inspect the data first, summarize the available fields and time coverage, then implement or evaluate the backtest logic.

## Repo Context

- Existing Oracle access lives in [getData/getTickerData.py](../../getData/getTickerData.py) and [server/server.py](../../server/server.py).
- `server.py` already queries `TICKER_HISTORY` with the current table shape used by this project.
- The existing `TICKER_HISTORY` query selects:
  - `ticker`
  - `interval_name`
  - `ts_utc`
  - `open_price`
  - `high_price`
  - `low_price`
  - `close_price`
  - `volume`

## Required Environment

Before trying to query Oracle, check for:

- `DB_USER`
- `DB_PASSWORD`
- `DB_DSN`
- `WALLET_DIR`
- optional: `WALLET_PASSWORD`
- optional: `SOURCE_TABLE` or `TABLE_NAME`

If they are missing, do not guess secrets and do not hardcode them into the repo. Ask the user for the missing connection setup or tell them exactly which env vars are required.

## Workflow

1. Read the existing Oracle connection code in `getData/getTickerData.py` or `server/server.py`.
2. Confirm whether the environment variables needed for Oracle access are present in the current session.
3. If credentials are available, inspect the target data before backtesting:
   - confirm row availability
   - confirm time coverage
   - confirm tickers and intervals present
   - confirm whether the expected columns are populated
4. Restate the strategy in precise terms:
   - entry rule
   - exit rule
   - stop or risk rule
   - time filter
   - instrument and interval
   - date range
5. Run the backtest using Oracle data from `TICKER_HISTORY`.
6. Report:
   - assumptions
   - sample size
   - trades
   - win rate
   - aggregate PnL or return metric
   - notable failure modes or data limitations

## Query Guidance

- Prefer parameterized SQL.
- Filter by `ticker`, `interval_name`, and time range as early as possible.
- Order by `ts_utc`.
- Convert `ts_utc` into `America/New_York` only when the strategy requires session logic.
- If the user asks for a schema check or sample rows, start with lightweight queries instead of pulling the full dataset.

For Oracle connection and query patterns in this repo, read [references/oracle-access.md](references/oracle-access.md).

## Backtest Guidance

- For same-day intraday strategies, define session boundaries explicitly in Eastern Time.
- Be explicit about whether fills occur at signal-bar close, next-bar open, or intrabar stop/target conditions.
- Call out when results are optimistic because only OHLCV bars are available.
- If strategy rules are ambiguous, choose a conservative assumption and state it.
- Prefer a reusable implementation path in the repo when the user wants repeated backtests, but only add code when they want code.

## Good Triggers

- "Backtest this strategy on SPX from Oracle"
- "Use `TICKER_HISTORY` to test a breakout setup"
- "Can you query Oracle and see how much 1-minute SPX data we have?"
- "Run a historical test on the bars in my Oracle table"
