import time
import datetime as dt
import os
import yfinance as yf
import pandas as pd
import oracledb

DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_DSN = os.environ["DB_DSN"]
WALLET_DIR = os.environ["WALLET_DIR"]

TICKERS = os.environ.get("TICKERS", "SPY,SPX").split(",")
INTERVAL = "1m"
SLEEP_SECONDS = 60


def get_connection():
    return oracledb.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        dsn=DB_DSN,
        config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=DB_PASSWORD,
    )


def fetch_data():
    data = {}
    yf_map = {"SPX": "^GSPC", "SPY": "SPY"}

    for ticker in TICKERS:
        yf_ticker = yf_map.get(ticker, ticker)
        df = yf.download(tickers=yf_ticker, period="1d", interval=INTERVAL, progress=False)
        if df.empty:
            continue

        df = df.reset_index()
        df.rename(columns={
            "Datetime": "ts",
            "Open": "open_price",
            "High": "high_price",
            "Low": "low_price",
            "Close": "close_price",
            "Volume": "volume",
        }, inplace=True)

        df["ts_utc"] = pd.to_datetime(df["ts"], utc=True)
        df["ticker"] = ticker
        df["interval_name"] = INTERVAL

        data[ticker] = df[[
            "ticker",
            "interval_name",
            "ts_utc",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
        ]]

    return data


def insert_rows(conn, rows: pd.DataFrame):
    sql = """
        INSERT /*+ IGNORE_ROW_ON_DUPKEY_INDEX(TICKER_HISTORY) */ INTO TICKER_HISTORY
        (ticker, interval_name, ts_utc, open_price, high_price, low_price, close_price, volume)
        VALUES (:1, :2, :3, :4, :5, :6, :7, :8)
    """

    cur = conn.cursor()
    data = [tuple(x) for x in rows.to_numpy()]
    cur.executemany(sql, data)
    conn.commit()


def main():
    print("Starting ticker collector...")

    while True:
        try:
            data = fetch_data()

            with get_connection() as conn:
                for ticker, df in data.items():
                    if df.empty:
                        continue
                    insert_rows(conn, df)
                    print(f"Inserted {len(df)} rows for {ticker}")

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    main()
