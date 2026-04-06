from flask import Flask, render_template_string, request
import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import plot
import oracledb


app = Flask(__name__)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
SETTINGS_FILE = DATA_DIR / "ui_settings.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {
    "refresh_interval": 31,
    "chart_interval": "5min",
}

DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
WALLET_DIR = os.environ["WALLET_DIR"]
DB_DSN = os.environ["DB_DSN"]

SOURCE_TABLE = os.environ.get("SOURCE_TABLE", "TICKER_HISTORY")
SPX_TICKER = os.environ.get("SPX_TICKER", "^GSPC")
SPY_TICKER = os.environ.get("SPY_TICKER", "SPY")
INTERVAL_NAME = os.environ.get("INTERVAL_NAME", "1m")
TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "5"))

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Trading Terminal</title>
    <meta http-equiv="refresh" content="{{ data.refresh_interval }}">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        :root{
            --panel:#121821;
            --panel-2:#17202b;
            --border:#273244;
            --text:#e8eef7;
            --muted:#8fa2b7;
            --green:#1fce7a;
            --red:#ff5d5d;
            --yellow:#ffcc66;
        }
        *{box-sizing:border-box}
        body{
            margin:0;
            font-family:Segoe UI, Arial, sans-serif;
            background:linear-gradient(180deg,#0a0e13 0%, #0f141b 100%);
            color:var(--text);
        }
        .wrap{max-width:1800px; margin:0 auto; padding:18px;}
        .topbar{
            display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;
            gap:16px; margin-bottom:16px; padding:14px 18px;
            background:var(--panel); border:1px solid var(--border); border-radius:14px;
        }
        .title h1{margin:0; font-size:28px}
        .title p{margin:4px 0 0; color:var(--muted); font-size:13px}
        .top-right{
            margin-left:auto;
            display:flex; align-items:center; gap:12px; flex-wrap:wrap;
        }
        .control-form{
            display:flex; align-items:center; gap:10px; flex-wrap:wrap;
            background:var(--panel-2); border:1px solid var(--border);
            padding:8px 10px; border-radius:12px;
        }
        .control-label{font-size:13px; color:var(--text); font-weight:600}
        .text-input{
            width:88px; background:#0f141b; color:var(--text);
            border:1px solid var(--border); border-radius:8px; padding:8px 10px; font-size:13px;
        }
        select.text-input{appearance:auto;}
        .status-pill{
            padding:10px 14px; border-radius:999px; font-weight:700;
            border:1px solid var(--border); background:var(--panel-2);
        }
        .enter{color:#062b18; background:var(--green); border-color:var(--green)}
        .no{color:#3b0d0d; background:var(--red); border-color:var(--red)}
        .grid{display:grid; grid-template-columns:1.35fr 0.95fr; gap:16px; align-items:stretch;}
        @media (max-width: 1400px){ .grid{grid-template-columns:1fr;} }
        .card{
            background:var(--panel); border:1px solid var(--border); border-radius:14px;
            padding:10px; overflow:hidden;
        }
        .chart-card,.snapshot-card{display:flex; flex-direction:column; height:100%;}
        .chart-wrap{
            background:var(--panel-2); border:1px solid var(--border); border-radius:12px;
            padding:0; overflow:hidden; flex:1 1 auto; min-height:300px;
        }
        .chart-wrap .plotly-graph-div{width:100% !important; height:100% !important; min-height:300px;}
        table{width:100%; border-collapse:collapse; border-radius:12px;}
        th, td{
            padding:10px 8px; border-bottom:1px solid var(--border); text-align:left; font-size:13px;
            white-space:nowrap;
        }
        th{color:var(--muted); font-weight:600; background:var(--panel-2);}
        .metrics{display:grid; grid-template-columns:repeat(3,1fr); gap:12px;}
        .metric{
            background:var(--panel-2); border:1px solid var(--border); border-radius:12px; padding:14px;
            min-height:92px;
        }
        .metric .label{color:var(--muted); font-size:12px; text-transform:uppercase;}
        .metric .value{margin-top:8px; font-size:26px; font-weight:700}
        .metric .sub{margin-top:4px; color:var(--muted); font-size:12px}
        .pass,.bull{color:var(--green); font-weight:700}
        .fail,.bear{color:var(--red); font-weight:700}
        .neutral{color:var(--yellow); font-weight:700}
        .err{color:var(--red); font-weight:700; font-size:18px}
        .small{font-size:12px; color:var(--muted)}
    </style>
</head>
<body>
<div class="wrap">
    <div class="topbar">
        <div class="title">
            <h1>Trading Terminal</h1>
            <p>SPX dashboard • Auto-refresh {{ data.refresh_interval }}s • Last update: {{ data.time }}</p>
        </div>
        <div class="top-right">
            <form id="settings-form" method="post" action="/settings" class="control-form">
                <span class="control-label">Refresh Interval</span>
                <input id="refresh_interval" class="text-input" type="number" min="15" max="3600" step="1" name="refresh_interval" value="{{ data.refresh_interval }}">
            </form>
            <div class="status-pill {{ 'enter' if data.trade != 'NO TRADE' else 'no' }}">
                {{ 'ENTER TRADE' if data.trade != 'NO TRADE' else 'NO TRADE' }}
            </div>
        </div>
    </div>

    {% if data.error %}
    <div class="card"><div class="err">{{ data.error }}</div></div>
    {% else %}
    <div class="grid">
        <div class="card chart-card">
            <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:4px;">
                <h2 style="margin:0; color:var(--muted); font-size:16px; text-transform:uppercase;">SPX Candlestick Chart</h2>
                <form id="chart-settings-form" method="post" action="/settings" class="control-form" style="padding:6px 8px;">
                    <input type="hidden" name="refresh_interval" value="{{ data.refresh_interval }}">
                    <span class="control-label">Candle Interval</span>
                    <select id="chart_interval" name="chart_interval" class="text-input" style="width:110px;">
                        <option value="5min" {% if data.chart_interval == '5min' %}selected{% endif %}>5 Minute</option>
                        <option value="15min" {% if data.chart_interval == '15min' %}selected{% endif %}>15 Minute</option>
                        <option value="1h" {% if data.chart_interval == '1h' %}selected{% endif %}>1 Hour</option>
                    </select>
                </form>
            </div>
            <div class="chart-wrap">
                {{ data.chart_html|safe }}
            </div>
        </div>

        <div class="card snapshot-card">
            <h2 style="margin:0 0 14px; color:var(--muted); font-size:16px; text-transform:uppercase;">Market Snapshot</h2>
            <table style="margin-bottom:16px;">
                <tr><th>Rule</th><th>Status</th><th>Value</th></tr>
                <tr><td>Outside 9:30–10:00 Range</td><td class="{{ 'pass' if data.outside_range else 'fail' }}">{{ 'PASS' if data.outside_range else 'FAIL' }}</td><td>{{ data.price }} vs {{ data.range_low }} / {{ data.range_high }}</td></tr>
                <tr><td>VWAP Distance ≥ 0.15%</td><td class="{{ 'pass' if data.vwap_distance else 'fail' }}">{{ 'PASS' if data.vwap_distance else 'FAIL' }}</td><td>{{ data.vwap_distance_pct }}%</td></tr>
                <tr><td>Distance from Open > 0.30%</td><td class="{{ 'pass' if data.open_distance else 'fail' }}">{{ 'PASS' if data.open_distance else 'FAIL' }}</td><td>{{ data.open_distance_pct }}%</td></tr>
                <tr><td>Bullish Setup</td><td class="{{ 'pass' if data.bullish else 'fail' }}">{{ 'Yes' if data.bullish else 'No' }}</td><td><span style="color: {{ 'var(--green)' if data.price > data.vwap else 'var(--red)' }}; font-weight:700;">Price &gt; VWAP(SPY)</span>, <span style="color: {{ 'var(--green)' if data.ema9 > data.ema21 else 'var(--red)' }}; font-weight:700;">EMA9 &gt; EMA21</span></td></tr>
                <tr><td>Bearish Setup</td><td class="{{ 'pass' if data.bearish else 'fail' }}">{{ 'Yes' if data.bearish else 'No' }}</td><td><span style="color: {{ 'var(--green)' if data.price < data.vwap else 'var(--red)' }}; font-weight:700;">Price &lt; VWAP(SPY)</span>, <span style="color: {{ 'var(--green)' if data.ema9 < data.ema21 else 'var(--red)' }}; font-weight:700;">EMA9 &lt; EMA21</span></td></tr>
            </table>

            <div class="metrics">
                <div class="metric"><div class="label">SPX Price</div><div class="value">{{ data.price }}</div><div class="sub">Latest SPX close</div></div>
                <div class="metric"><div class="label">Prev Day High</div><div class="value">{{ data.prev_day_high }}</div><div class="sub">Prior session high</div></div>
                <div class="metric"><div class="label">Prev Day Low</div><div class="value">{{ data.prev_day_low }}</div><div class="sub">Prior session low</div></div>

                <div class="metric"><div class="label">Opening Range High</div><div class="value">{{ data.range_high }}</div><div class="sub">9:30–10:00 high</div></div>
                <div class="metric"><div class="label">Opening Range Low</div><div class="value">{{ data.range_low }}</div><div class="sub">9:30–10:00 low</div></div>
                <div class="metric"><div class="label">Open Distance</div><div class="value {{ 'pass' if data.open_distance else 'fail' }}">{{ data.open_distance_pct }}%</div><div class="sub">> 0.30%</div></div>

                <div class="metric"><div class="label">Bias</div><div class="value {{ 'bull' if data.bullish else ('bear' if data.bearish else 'neutral') }}">{{ 'BULLISH' if data.bullish else ('BEARISH' if data.bearish else 'NEUTRAL') }}</div><div class="sub">Trend alignment</div></div>
                <div class="metric"><div class="label">EMA 9</div><div class="value">{{ data.ema9 }}</div><div class="sub">SPX fast trend</div></div>
                <div class="metric"><div class="label">EMA 21</div><div class="value">{{ data.ema21 }}</div><div class="sub">SPX slow trend</div></div>

                <div class="metric"><div class="label">VWAP(SPY)</div><div class="value">{{ data.vwap }}</div><div class="sub">SPY VWAP x 10</div></div>
                <div class="metric"><div class="label">VWAP Distance</div><div class="value {{ 'pass' if data.vwap_distance else 'fail' }}">{{ data.vwap_distance_pct }}%</div><div class="sub">≥ 0.15%</div></div>
                <div class="metric" aria-hidden="true"></div>

                <div class="metric"><div class="label">Current Day High</div><div class="value">{{ data.current_day_high }}</div><div class="sub">Today's high</div></div>
                <div class="metric"><div class="label">Current Day Low</div><div class="value">{{ data.current_day_low }}</div><div class="sub">Today's low</div></div>
            </div>
            <div class="small" style="margin-top:12px;">Source: Oracle table {{ data.source_table }}</div>
        </div>
    </div>
    {% endif %}
</div>

<script>
(function() {
    const settingsForm = document.getElementById('settings-form');
    const chartForm = document.getElementById('chart-settings-form');
    let timer = null;

    function submit(form) {
        const data = new FormData(form);
        const refresh = document.getElementById('refresh_interval');
        const chart = document.getElementById('chart_interval');
        if (refresh) data.set('refresh_interval', refresh.value);
        if (chart) data.set('chart_interval', chart.value);

        fetch('/settings', { method: 'POST', body: data })
            .then(() => window.location.reload())
            .catch(() => {});
    }

    function debounce(form) {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => submit(form), 250);
    }

    const refresh = document.getElementById('refresh_interval');
    if (refresh) refresh.addEventListener('input', () => debounce(settingsForm));

    const chart = document.getElementById('chart_interval');
    if (chart) chart.addEventListener('change', () => debounce(chartForm));

    function resizeChart() {
        const snapshotCard = document.querySelector('.snapshot-card');
        const chartCard = document.querySelector('.chart-card');
        const chartWrap = document.querySelector('.chart-wrap');
        const plotDiv = document.querySelector('.chart-wrap .plotly-graph-div');
        if (!snapshotCard || !chartCard || !chartWrap || !plotDiv || typeof Plotly === 'undefined') return;

        const snapshotRect = snapshotCard.getBoundingClientRect();
        if (!snapshotRect.height || snapshotRect.height < 300) return;

        chartCard.style.height = Math.floor(snapshotRect.height) + 'px';

        requestAnimationFrame(() => {
            const wrapRect = chartWrap.getBoundingClientRect();
            const targetHeight = Math.max(300, Math.floor(wrapRect.height));
            Plotly.relayout(plotDiv, {
                autosize: true,
                height: targetHeight,
                margin: {l: 20, r: 20, t: 6, b: 6}
            });
            Plotly.Plots.resize(plotDiv);
        });
    }

    window.addEventListener('load', () => { resizeChart(); setTimeout(resizeChart, 250); setTimeout(resizeChart, 800); });
    window.addEventListener('resize', resizeChart);
})();
</script>
</body>
</html>
"""


def get_connection():
    return oracledb.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        dsn=DB_DSN,
        config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=DB_PASSWORD,
    )


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            out = DEFAULT_SETTINGS.copy()
            out.update(data)
            out["refresh_interval"] = max(15, min(3600, int(out.get("refresh_interval", 30))))
            out["chart_interval"] = str(out.get("chart_interval", "5min"))
            if out["chart_interval"] not in {"5min", "15min", "1h"}:
                out["chart_interval"] = "5min"
            return out
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def query_ticker_history(conn, ticker: str, interval_name: str, start_utc: dt.datetime) -> pd.DataFrame:
    sql = f"""
        SELECT
            ticker,
            interval_name,
            ts_utc,
            open_price,
            high_price,
            low_price,
            close_price,
            volume
        FROM {SOURCE_TABLE}
        WHERE ticker = :ticker
          AND interval_name = :interval_name
          AND ts_utc >= :start_utc
        ORDER BY ts_utc
    """
    df = pd.read_sql(
        sql,
        conn,
        params={
            "ticker": ticker,
            "interval_name": interval_name,
            "start_utc": start_utc,
        },
    )

    if df.empty:
        return df

    df.columns = [c.lower() for c in df.columns]
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    df["ts"] = df["ts_utc"].dt.tz_convert(TIMEZONE).dt.tz_localize(None)
    return df.sort_values("ts").reset_index(drop=True)


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high_price"] + df["low_price"] + df["close_price"]) / 3.0
    pv = (typical_price * df["volume"]).cumsum()
    vol = df["volume"].replace(0, pd.NA).cumsum()
    return pv / vol



def first_valid_number(series: pd.Series, label: str) -> float:
    valid = pd.to_numeric(series, errors="coerce").dropna()
    if valid.empty:
        raise ValueError(f"No valid numeric values found for {label}.")
    return float(valid.iloc[0])


def last_valid_number(series: pd.Series, label: str) -> float:
    valid = pd.to_numeric(series, errors="coerce").dropna()
    if valid.empty:
        raise ValueError(f"No valid numeric values found for {label}.")
    return float(valid.iloc[-1])

def make_chart(spx_1m: pd.DataFrame, range_high: float, range_low: float, prev_day_high: float, prev_day_low: float, chart_interval: str, start_of_day: pd.Timestamp, chart_end: pd.Timestamp) -> str:
    interval_map = {"5min": "5min", "15min": "15min", "1h": "1h"}
    label_map = {"5min": "5 Minute", "15min": "15 Minute", "1h": "1 Hour"}
    resample_rule = interval_map.get(chart_interval, "5min")
    chart_label = label_map.get(chart_interval, "5 Minute")

    chart_start = chart_end - pd.Timedelta(hours=24)
    spx_1m = spx_1m[spx_1m["ts"] >= chart_start].copy()

    spx_resampled = (
        spx_1m[["ts", "open_price", "high_price", "low_price", "close_price", "ema9_spx", "ema21_spx", "vwap_spy_x10"]]
        .resample(resample_rule, on="ts")
        .agg({
            "open_price": "first",
            "high_price": "max",
            "low_price": "min",
            "close_price": "last",
            "ema9_spx": "last",
            "ema21_spx": "last",
            "vwap_spy_x10": "last",
        })
        .dropna(subset=["open_price", "high_price", "low_price", "close_price"])
    )

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=spx_resampled.index,
        open=spx_resampled["open_price"],
        high=spx_resampled["high_price"],
        low=spx_resampled["low_price"],
        close=spx_resampled["close_price"],
        name="SPX",
        hovertemplate="Time: %{x}<br>Open: %{open:.0f}<br>High: %{high:.0f}<br>Low: %{low:.0f}<br>Close: %{close:.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=spx_resampled.index,
        y=spx_resampled["vwap_spy_x10"],
        mode="lines",
        name="VWAP(SPY)x10",
        hovertemplate="VWAP: %{y:.0f}<extra></extra>",
        line=dict(color="#9b87f5", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=spx_resampled.index,
        y=spx_resampled["ema9_spx"],
        mode="lines",
        name="EMA9",
        hovertemplate="EMA9: %{y:.0f}<extra></extra>",
        line=dict(color="#00cc96", width=1.8),
    ))
    fig.add_trace(go.Scatter(
        x=spx_resampled.index,
        y=spx_resampled["ema21_spx"],
        mode="lines",
        name="EMA21",
        hovertemplate="EMA21: %{y:.0f}<extra></extra>",
        line=dict(color="#ffd166", width=1.8),
    ))

    fig.add_shape(
        type="line",
        x0=start_of_day,
        x1=start_of_day,
        y0=0,
        y1=1,
        xref="x",
        yref="paper",
        line=dict(color="#4da3ff", width=2, dash="dash"),
    )
    fig.add_annotation(
        x=start_of_day,
        y=1,
        xref="x",
        yref="paper",
        text="Start of Day",
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
        font=dict(color="#4da3ff"),
    )

    for y, name, color, dash in [
        (range_high, "OR High", "#00cc96", "dash"),
        (range_low, "OR Low", "#ef553b", "dash"),
        (prev_day_high, "Prev Day High", "#ffd166", "dot"),
        (prev_day_low, "Prev Day Low", "#4da3ff", "dot"),
    ]:
        fig.add_hline(y=y, line_width=1.5, line_dash=dash, line_color=color,
                      annotation_text=name, annotation_position="top left")

    fig.update_layout(
        margin=dict(l=20, r=20, t=6, b=6),
        paper_bgcolor="#17202b",
        plot_bgcolor="#17202b",
        font=dict(color="#e8eef7"),
        xaxis=dict(
            showgrid=True,
            gridcolor="#273244",
            rangeslider=dict(visible=False),
            title=f"Time ({chart_label})",
            title_standoff=4,
            rangebreaks=[
                dict(bounds=[16.5, 9], pattern="hour"),
                dict(bounds=["sat", "mon"]),
            ],
        ),
        yaxis=dict(showgrid=True, gridcolor="#273244", title="SPX", title_standoff=4),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
    )
    fig.update_xaxes(showspikes=True, spikecolor="#8fa2b7", spikesnap="cursor", spikemode="across")
    fig.update_yaxes(showspikes=True, spikecolor="#8fa2b7", spikesnap="cursor", spikemode="across")
    return plot(fig, output_type="div", include_plotlyjs=False, config={"displayModeBar": False})


def run_web_service(settings: dict) -> dict:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_utc = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=LOOKBACK_DAYS)

    with get_connection() as conn:
        spx = query_ticker_history(conn, SPX_TICKER, INTERVAL_NAME, start_utc)
        spy = query_ticker_history(conn, SPY_TICKER, INTERVAL_NAME, start_utc)

    if spx.empty:
        return {"time": now, "error": f"No {SPX_TICKER} rows found in {SOURCE_TABLE}.", **settings}
    if spy.empty:
        return {"time": now, "error": f"No {SPY_TICKER} rows found in {SOURCE_TABLE}.", **settings}

    current_date = spx["ts"].max().date()
    prior_dates = sorted({x.date() for x in spx["ts"] if x.date() < current_date})
    if not prior_dates:
        return {"time": now, "error": "Need at least two trading days in TICKER_HISTORY.", **settings}
    prev_date = prior_dates[-1]

    spx_current = spx[spx["ts"].dt.date == current_date].copy()
    spy_current = spy[spy["ts"].dt.date == current_date].copy()
    spx_prev = spx[spx["ts"].dt.date == prev_date].copy()
    spy_prev = spy[spy["ts"].dt.date == prev_date].copy()

    if spx_current.empty or spy_current.empty or spx_prev.empty or spy_prev.empty:
        return {"time": now, "error": "Could not separate current/prior session data from TICKER_HISTORY.", **settings}

    prev_start_time = dt.time(12, 0)
    spx_prev_4h = spx_prev[spx_prev["ts"].dt.time >= prev_start_time].copy()
    spy_prev_4h = spy_prev[spy_prev["ts"].dt.time >= prev_start_time].copy()
    if spx_prev_4h.empty:
        spx_prev_4h = spx_prev.tail(min(len(spx_prev), 240)).copy()
    if spy_prev_4h.empty:
        spy_prev_4h = spy_prev.tail(min(len(spy_prev), 240)).copy()

    spy_prev = spy_prev.sort_values("ts").reset_index(drop=True).copy()
    spy_current = spy_current.sort_values("ts").reset_index(drop=True).copy()

    spy_prev["vwap_spy"] = calculate_vwap(spy_prev)
    spy_current["vwap_spy"] = calculate_vwap(spy_current)

    spx_prev_4h = spx_prev_4h.drop_duplicates(subset=["ts"]).copy()
    spx_current = spx_current.drop_duplicates(subset=["ts"]).copy()

    spy_prev_4h = spy_prev[spy_prev["ts"].isin(spx_prev_4h["ts"])].copy()
    spy_prev_4h = spy_prev_4h.drop_duplicates(subset=["ts"]).copy()
    spy_current = spy_current.drop_duplicates(subset=["ts"]).copy()

    spy_prev_4h["vwap_spy_x10"] = spy_prev_4h["vwap_spy"] * 10.0
    spy_current["vwap_spy_x10"] = spy_current["vwap_spy"] * 10.0

    spx_current = spx_current.sort_values("ts").reset_index(drop=True)
    spx_current["ema9_spx"] = spx_current["close_price"].ewm(span=9, adjust=False).mean()
    spx_current["ema21_spx"] = spx_current["close_price"].ewm(span=21, adjust=False).mean()

    chart_spx = pd.concat([spx_prev_4h, spx_current], axis=0).sort_values("ts").reset_index(drop=True)
    chart_spx["ema9_spx"] = chart_spx["close_price"].ewm(span=9, adjust=False).mean()
    chart_spx["ema21_spx"] = chart_spx["close_price"].ewm(span=21, adjust=False).mean()

    vwap_map = pd.concat([
        spy_prev_4h[["ts", "vwap_spy_x10"]],
        spy_current[["ts", "vwap_spy_x10"]],
    ], axis=0).drop_duplicates(subset=["ts"], keep="last")

    chart_spx = chart_spx.merge(vwap_map, on="ts", how="left")

    latest_price = last_valid_number(spx_current["close_price"], "latest SPX close")
    latest_ema9 = last_valid_number(spx_current["ema9_spx"], "latest EMA9")
    latest_ema21 = last_valid_number(spx_current["ema21_spx"], "latest EMA21")
    open_price = first_valid_number(spx_current["open_price"], "session open")
    latest_vwap = last_valid_number(spy_current["vwap_spy"], "latest SPY VWAP") * 10.0

    opening_df = spx_current[(spx_current["ts"].dt.time >= dt.time(9, 30)) & (spx_current["ts"].dt.time <= dt.time(10, 0))].copy()
    if opening_df.empty:
        return {"time": now, "error": "No opening range rows found in TICKER_HISTORY.", **settings}

    range_high = float(opening_df["high_price"].max())
    range_low = float(opening_df["low_price"].min())

    prev_day_high = float(spx_prev["high_price"].max())
    prev_day_low = float(spx_prev["low_price"].min())
    current_day_high = float(spx_current["high_price"].max())
    current_day_low = float(spx_current["low_price"].min())

    outside_range = (latest_price > range_high) or (latest_price < range_low)
    vwap_distance_pct = abs(latest_price - latest_vwap) / latest_price * 100.0 if latest_price else 0.0
    open_distance_pct = abs(latest_price - open_price) / open_price * 100.0 if open_price else 0.0

    vwap_distance = vwap_distance_pct >= 0.15
    open_distance = open_distance_pct > 0.30

    bullish = (latest_price > open_price) and (latest_price > latest_vwap) and (latest_ema9 > latest_ema21)
    bearish = (latest_price < open_price) and (latest_price < latest_vwap) and (latest_ema9 < latest_ema21)

    trade = "NO TRADE"
    structure = "No trade today."
    if outside_range and vwap_distance and open_distance:
        if bullish:
            trade = "SELL PUT SPREAD"
            structure = "Sell 10 put credit spreads, 20 points wide, short strike near 0.10 delta, stop at 2x credit received."
        elif bearish:
            trade = "SELL CALL SPREAD"
            structure = "Sell 10 call credit spreads, 20 points wide, short strike near 0.10 delta, stop at 2x credit received."

    chart_html = make_chart(
        chart_spx,
        range_high,
        range_low,
        prev_day_high,
        prev_day_low,
        settings["chart_interval"],
        pd.Timestamp(spx_current["ts"].min()),
        pd.Timestamp(chart_spx["ts"].max()),
    )

    return {
        "time": now,
        "price": int(round(latest_price, 0)),
        "vwap": int(round(latest_vwap, 0)),
        "ema9": int(round(latest_ema9, 0)),
        "ema21": int(round(latest_ema21, 0)),
        "range_high": int(round(range_high, 0)),
        "range_low": int(round(range_low, 0)),
        "prev_day_high": int(round(prev_day_high, 0)),
        "prev_day_low": int(round(prev_day_low, 0)),
        "current_day_high": int(round(current_day_high, 0)),
        "current_day_low": int(round(current_day_low, 0)),
        "vwap_distance_pct": round(vwap_distance_pct, 3),
        "open_distance_pct": round(open_distance_pct, 3),
        "outside_range": outside_range,
        "vwap_distance": vwap_distance,
        "open_distance": open_distance,
        "bullish": bullish,
        "bearish": bearish,
        "trade": trade,
        "structure": structure,
        "chart_html": chart_html,
        "refresh_interval": settings["refresh_interval"],
        "chart_interval": settings["chart_interval"],
        "source_table": SOURCE_TABLE,
        "error": None,
    }


@app.route("/settings", methods=["POST"])
def update_settings():
    current = load_settings()
    try:
        refresh_interval = int(request.form.get("refresh_interval", current["refresh_interval"]))
    except Exception:
        refresh_interval = current["refresh_interval"]

    chart_interval = str(request.form.get("chart_interval", current.get("chart_interval", "5min")))
    if chart_interval not in {"5min", "15min", "1h"}:
        chart_interval = current.get("chart_interval", "5min")

    save_settings({
        "refresh_interval": max(15, min(3600, refresh_interval)),
        "chart_interval": chart_interval,
    })
    return ("", 204)


@app.route("/")
def index():
    settings = load_settings()
    data = run_web_service(settings)
    return render_template_string(HTML, data=data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
