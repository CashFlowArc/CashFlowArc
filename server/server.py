from flask import Flask, redirect, render_template_string, request, url_for
import datetime as dt
import json
import math
import os
import re
import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import plot
import oracledb
import yfinance as yf


app = Flask(__name__)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
SETTINGS_FILE = DATA_DIR / "ui_settings.json"
FAVICON_VERSION = "2"

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
GEX_CONTRACT_SIZE = int(os.environ.get("GEX_CONTRACT_SIZE", "100"))
GEX_MIN_TIME_SECONDS = int(os.environ.get("GEX_MIN_TIME_SECONDS", "60"))
GEX_STRIKE_WINDOW = float(os.environ.get("GEX_STRIKE_WINDOW", "50"))

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>CashFlowArc</title>
    <link rel="icon" href="{{ url_for('static', filename='favicon.svg', v=favicon_version) }}" sizes="any" type="image/svg+xml">
    <link rel="shortcut icon" href="{{ url_for('favicon_ico') }}">
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
        .metric .value.compact{font-size:22px; line-height:1.15}
        .metric .value .value-date{
            display:block;
            margin-top:4px;
            font-size:14px;
            font-weight:600;
            color:var(--muted);
        }
        .metric .sub{margin-top:4px; color:var(--muted); font-size:12px}
        .metric.gex-positive{
            background:rgba(31, 206, 122, 0.12);
            border-color:rgba(31, 206, 122, 0.45);
        }
        .metric.gex-negative{
            background:rgba(255, 93, 93, 0.12);
            border-color:rgba(255, 93, 93, 0.45);
        }
        .metric.gex-positive .value{color:var(--green)}
        .metric.gex-negative .value{color:var(--red)}
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
            <div class="control-form" style="padding:6px 8px;">
                <a href="/gex" style="color:var(--text); text-decoration:none; font-size:13px; font-weight:700;">SPX GEX</a>
            </div>
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
                <tr><td>Bullish Setup</td><td class="{{ 'pass' if data.bullish else 'fail' }}">{{ 'Yes' if data.bullish else 'No' }}</td><td><span style="color: {{ 'var(--green)' if data.price > data.vwap else 'var(--red)' }}; font-weight:700;">Price &gt; SPX VWAP Proxy</span>, <span style="color: {{ 'var(--green)' if data.ema9 > data.ema21 else 'var(--red)' }}; font-weight:700;">EMA9 &gt; EMA21</span></td></tr>
                <tr><td>Bearish Setup</td><td class="{{ 'pass' if data.bearish else 'fail' }}">{{ 'Yes' if data.bearish else 'No' }}</td><td><span style="color: {{ 'var(--green)' if data.price < data.vwap else 'var(--red)' }}; font-weight:700;">Price &lt; SPX VWAP Proxy</span>, <span style="color: {{ 'var(--green)' if data.ema9 < data.ema21 else 'var(--red)' }}; font-weight:700;">EMA9 &lt; EMA21</span></td></tr>
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

                <div class="metric"><div class="label">SPX VWAP Proxy</div><div class="value">{{ data.vwap }}</div><div class="sub">SPY VWAP scaled by rolling median SPX/SPY ratio</div></div>
                <div class="metric"><div class="label">VWAP Distance</div><div class="value {{ 'pass' if data.vwap_distance else 'fail' }}">{{ data.vwap_distance_pct }}%</div><div class="sub">≥ 0.15%</div></div>
                <div class="metric {{ data.net_gex_class }}"><div class="label">Net GEX</div><div class="value {{ 'compact' if data.net_gex_date else '' }}">{{ data.net_gex_billions }}{% if data.net_gex_date %}<span class="value-date">{{ data.net_gex_date }}</span>{% endif %}</div><div class="sub">{{ data.net_gex_subtext }}</div></div>

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

GEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>CashFlowArc</title>
    <link rel="icon" href="{{ url_for('static', filename='favicon.svg', v=favicon_version) }}" sizes="any" type="image/svg+xml">
    <link rel="shortcut icon" href="{{ url_for('favicon_ico') }}">
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
            --blue:#1d2ef2;
            --line:#3493ff;
            --green:#00a63f;
            --orange:#ff9800;
            --grid:#273244;
        }
        *{box-sizing:border-box}
        body{
            margin:0;
            font-family:Segoe UI, Arial, sans-serif;
            background:linear-gradient(180deg,#0a0e13 0%, #0f141b 100%);
            color:var(--text);
        }
        .wrap{max-width:1280px; margin:0 auto; padding:20px;}
        .topbar{
            display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;
            margin-bottom:16px; padding:14px 18px; background:var(--panel);
            border:1px solid var(--border); border-radius:14px;
        }
        .title h1{margin:0; font-size:24px}
        .title p{margin:4px 0 0; color:var(--muted); font-size:13px}
        .links{display:flex; gap:10px; align-items:center; flex-wrap:wrap}
        .links a{
            color:var(--muted); text-decoration:none; font-weight:700; font-size:13px;
            padding:8px 10px; border:1px solid var(--border); border-radius:999px; background:var(--panel-2);
        }
        .card{
            background:var(--panel); border:1px solid var(--border); border-radius:14px; padding:16px;
        }
        .controls{
            display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:12px;
        }
        .control-form{
            display:flex; align-items:center; gap:10px; flex-wrap:wrap;
            background:var(--panel-2); border:1px solid var(--border); border-radius:12px; padding:8px 10px;
        }
        .control-label{font-size:13px; color:var(--text); font-weight:700}
        .text-input{
            width:90px; background:#0f141b; color:var(--text);
            border:1px solid var(--border); border-radius:8px; padding:8px 10px; font-size:13px;
        }
        .metrics{
            display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:14px;
        }
        @media (max-width: 960px){ .metrics{grid-template-columns:repeat(2,1fr);} }
        @media (max-width: 640px){ .metrics{grid-template-columns:1fr;} }
        .metric{
            background:var(--panel-2); border:1px solid var(--border); border-radius:12px; padding:14px;
        }
        .metric .label{font-size:12px; color:var(--muted); text-transform:uppercase}
        .metric .value{margin-top:8px; font-size:24px; font-weight:700}
        .metric .sub{margin-top:4px; font-size:12px; color:var(--muted)}
        .chart-wrap{
            min-height:520px; background:var(--panel-2); border:1px solid var(--border); border-radius:12px; overflow:hidden;
        }
        .chart-wrap .plotly-graph-div{width:100% !important; height:520px !important;}
        .error{font-size:18px; color:#b42318; font-weight:700}
        .notes{margin-top:14px; font-size:12px; color:var(--muted); line-height:1.5}
    </style>
</head>
<body>
<div class="wrap">
    <div class="topbar">
        <div class="title">
            <h1>SPX 0DTE Gamma Exposure</h1>
            <p>{{ data.subtitle }}</p>
        </div>
        <div class="links">
            <a href="/">Trading Terminal</a>
            <a href="/gex">GEX View</a>
        </div>
    </div>

    <div class="card">
        {% if data.error %}
        <div class="error">{{ data.error }}</div>
        {% else %}
        <div class="controls">
            <form id="gex-settings-form" method="post" action="/settings" class="control-form">
                <span class="control-label">Refresh Interval</span>
                <input id="refresh_interval" class="text-input" type="number" min="15" max="3600" step="1" name="refresh_interval" value="{{ data.refresh_interval }}">
                <input type="hidden" name="chart_interval" value="{{ data.chart_interval }}">
            </form>
            <div class="control-form">
                <span class="control-label">Expiration</span>
                <span>{{ data.expiration_date }}</span>
            </div>
        </div>

        <div class="chart-wrap">
            {{ data.chart_html|safe }}
        </div>

        <div class="metrics">
            <div class="metric"><div class="label">Spot</div><div class="value">{{ data.spot_price }}</div><div class="sub">Latest SPX price from options feed</div></div>
            <div class="metric"><div class="label">Net GEX</div><div class="value">{{ data.net_gex_billions }}</div><div class="sub">Per 1% move, billions</div></div>
            <div class="metric"><div class="label">Call Wall</div><div class="value">{{ data.call_wall }}</div><div class="sub">Largest positive strike GEX</div></div>
            <div class="metric"><div class="label">Put Wall</div><div class="value">{{ data.put_wall }}</div><div class="sub">Largest negative strike GEX</div></div>
        </div>

        <div class="notes">
            Uses the SPX expiration shown above. During market hours it prefers the current session's expiration, and after 4:00 PM Eastern it rolls forward to the next available expiration. Gamma exposure is estimated from open interest, implied volatility, and Black-Scholes gamma with time capped at a minimum of {{ data.min_time_minutes }} minute(s) to avoid a zero-time singularity.
        </div>
        {% endif %}
    </div>
</div>

<script>
(function() {
    const refresh = document.getElementById('refresh_interval');
    const form = document.getElementById('gex-settings-form');
    let timer = null;

    function submit() {
        const data = new FormData(form);
        fetch('/settings', { method: 'POST', body: data })
            .then(() => window.location.reload())
            .catch(() => {});
    }

    if (refresh) {
        refresh.addEventListener('input', function() {
            if (timer) clearTimeout(timer);
            timer = setTimeout(submit, 250);
        });
    }
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


def format_billions(value: float) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"${value / 1_000_000_000:.2f}B"


def normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def black_scholes_gamma(spot: float, strike: float, volatility: float, time_to_expiry: float) -> float:
    if spot <= 0 or strike <= 0 or volatility <= 0 or time_to_expiry <= 0:
        return 0.0

    vol_term = volatility * math.sqrt(time_to_expiry)
    if vol_term <= 0:
        return 0.0

    d1 = (math.log(spot / strike) + 0.5 * volatility * volatility * time_to_expiry) / vol_term
    return normal_pdf(d1) / (spot * vol_term)


def resolve_gex_expiration_date(now_et: pd.Timestamp, available_dates: list[dt.date]) -> dt.date:
    if not available_dates:
        raise ValueError("Yahoo did not return any SPX expirations.")

    current_date = now_et.date()
    market_close = dt.time(16, 0)

    if now_et.time() >= market_close:
        for expiration_date in available_dates:
            if expiration_date > current_date:
                return expiration_date

    for expiration_date in available_dates:
        if expiration_date >= current_date:
            return expiration_date

    return available_dates[-1]


def fetch_spx_options_for_session(now_et: pd.Timestamp) -> tuple[pd.DataFrame, dict, dt.date]:
    cache_dir = os.path.join(tempfile.gettempdir(), "cashflowarc-yfinance-cache")
    os.makedirs(cache_dir, exist_ok=True)
    yf.set_tz_cache_location(cache_dir)

    ticker = yf.Ticker("^SPX")
    available_expirations = tuple(ticker.options)
    if not available_expirations:
        raise ValueError("Yahoo did not return any SPX expirations.")

    expiration_map = {
        pd.Timestamp(exp).date(): exp
        for exp in available_expirations
    }
    selected_expiration_date = resolve_gex_expiration_date(now_et, sorted(expiration_map))
    expiration_label = expiration_map.get(selected_expiration_date)
    if expiration_label is None:
        available = ", ".join(sorted(expiration_map.values()))
        raise ValueError(
            f"No SPX expiration matched {selected_expiration_date.isoformat()}. Available expirations: {available}"
        )

    chain = ticker.option_chain(expiration_label)
    calls = chain.calls.copy() if chain.calls is not None else pd.DataFrame()
    puts = chain.puts.copy() if chain.puts is not None else pd.DataFrame()
    calls["option_type"] = "call"
    puts["option_type"] = "put"
    options = pd.concat([calls, puts], ignore_index=True, sort=False)
    if options.empty:
        raise ValueError(f"Yahoo returned an empty SPX chain for {selected_expiration_date.isoformat()}.")

    return options, chain.underlying or {}, selected_expiration_date


def build_gex_frame(options: pd.DataFrame, spot_price: float, now_et: pd.Timestamp, expiry_date: dt.date) -> pd.DataFrame:
    expiry_close = pd.Timestamp.combine(expiry_date, dt.time(16, 0)).tz_localize(TIMEZONE)
    time_to_expiry_years = max(
        (expiry_close - now_et).total_seconds(),
        GEX_MIN_TIME_SECONDS,
    ) / (365.0 * 24.0 * 60.0 * 60.0)

    working = options.copy()
    working["strike"] = pd.to_numeric(working.get("strike"), errors="coerce")
    working["openInterest"] = pd.to_numeric(working.get("openInterest"), errors="coerce").fillna(0.0)
    working["impliedVolatility"] = pd.to_numeric(working.get("impliedVolatility"), errors="coerce")
    working["volume"] = pd.to_numeric(working.get("volume"), errors="coerce").fillna(0.0)
    working["lastPrice"] = pd.to_numeric(working.get("lastPrice"), errors="coerce")
    working = working.dropna(subset=["strike", "impliedVolatility"])
    working = working[(working["strike"] > 0) & (working["impliedVolatility"] > 0)].copy()
    if working.empty:
        raise ValueError("No SPX options had both strike and implied volatility for GEX calculation.")

    working["gamma"] = working.apply(
        lambda row: black_scholes_gamma(
            spot=spot_price,
            strike=float(row["strike"]),
            volatility=float(row["impliedVolatility"]),
            time_to_expiry=time_to_expiry_years,
        ),
        axis=1,
    )
    working["direction"] = working["option_type"].map({"call": 1.0, "put": -1.0}).fillna(0.0)
    working["gex"] = (
        working["gamma"]
        * working["openInterest"]
        * GEX_CONTRACT_SIZE
        * (spot_price ** 2)
        * 0.01
        * working["direction"]
    )

    grouped = (
        working.groupby("strike", as_index=False)
        .agg(
            net_gex=("gex", "sum"),
            call_gex=("gex", lambda values: float(sum(x for x in values if x > 0))),
            put_gex=("gex", lambda values: float(sum(x for x in values if x < 0))),
            total_oi=("openInterest", "sum"),
        )
        .sort_values("strike")
        .reset_index(drop=True)
    )
    grouped["abs_gex"] = grouped["net_gex"].abs()
    grouped["cumulative_gex"] = grouped["net_gex"].cumsum()
    return grouped


def make_gex_chart(gex_by_strike: pd.DataFrame, spot_price: float) -> str:
    if gex_by_strike.empty:
        return "<div style='padding:20px;color:#b42318;'>No GEX chart data available.</div>"

    colors = ["#1d2ef2" if value >= 0 else "#ff9800" for value in gex_by_strike["net_gex"]]
    ymax = max(float(gex_by_strike["net_gex"].max()), 0.0)
    ymin = min(float(gex_by_strike["net_gex"].min()), 0.0)
    span = max(ymax - ymin, 1.0)
    ypad = span * 0.18

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[None],
        y=[None],
        name="Gamma Exposure by Strike",
        mode="markers",
        marker=dict(color="#1d2ef2", size=10),
        hoverinfo="skip",
    ))
    fig.add_trace(go.Bar(
        x=gex_by_strike["strike"],
        y=gex_by_strike["net_gex"],
        name="Gamma Exposure by Strike",
        marker_color=colors,
        opacity=0.95,
        showlegend=False,
        hovertemplate="Strike %{x:,.0f}<br>Net GEX %{y:$,.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=gex_by_strike["strike"],
        y=gex_by_strike["cumulative_gex"],
        name="Aggregate Gamma Exposure",
        mode="lines",
        yaxis="y2",
        line=dict(color="#3493ff", width=2),
        hovertemplate="Strike %{x:,.0f}<br>Cumulative GEX %{y:$,.2f}<extra></extra>",
    ))

    fig.add_shape(
        type="line",
        x0=spot_price,
        x1=spot_price,
        y0=0,
        y1=1,
        yref="paper",
        line=dict(color="#00a63f", width=1.5),
    )
    fig.add_annotation(
        x=spot_price,
        y=0.965,
        yref="paper",
        text=f"Last Price: {spot_price:,.2f}",
        showarrow=False,
        yanchor="bottom",
        xanchor="left",
        font=dict(color="#00a63f", size=12),
        bgcolor="#17202b",
        bordercolor="#273244",
        borderwidth=1,
    )

    fig.update_layout(
        title=dict(text="$SPX - Gamma Exposure by Strike", x=0.5, xanchor="center", font=dict(size=18, color="#e8eef7")),
        paper_bgcolor="#17202b",
        plot_bgcolor="#17202b",
        margin=dict(l=70, r=70, t=100, b=70),
        font=dict(color="#e8eef7", family="Segoe UI, Arial, sans-serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        hoverlabel=dict(bgcolor="#0f141b", bordercolor="#273244", font=dict(color="#e8eef7")),
        xaxis=dict(
            title="Strike Price",
            showgrid=False,
            zeroline=False,
            tickformat=",.0f",
        ),
        yaxis=dict(
            title=None,
            showgrid=True,
            gridcolor="#273244",
            zeroline=False,
            tickformat="~s",
            range=[ymin - ypad, ymax + ypad],
        ),
        yaxis2=dict(
            title=None,
            overlaying="y",
            side="right",
            showgrid=False,
            zeroline=False,
            tickformat="~s",
        ),
        bargap=0.7,
    )

    return plot(fig, output_type="div", include_plotlyjs=False, config={"displayModeBar": False, "responsive": True})


def run_gex_service(settings: dict) -> dict:
    now_et = pd.Timestamp.now(tz=TIMEZONE)
    gex_snapshot = get_net_gex_snapshot()
    spot_price = gex_snapshot["spot_price"]
    gex_by_strike = gex_snapshot["gex_by_strike"]
    expiration_date = gex_snapshot["expiration_date"]
    chart_html = make_gex_chart(gex_by_strike, spot_price)

    put_rows = gex_by_strike[gex_by_strike["net_gex"] < 0]
    call_rows = gex_by_strike[gex_by_strike["net_gex"] > 0]
    put_wall = float(put_rows.loc[put_rows["net_gex"].idxmin(), "strike"]) if not put_rows.empty else None
    call_wall = float(call_rows.loc[call_rows["net_gex"].idxmax(), "strike"]) if not call_rows.empty else None
    net_gex = gex_snapshot["net_gex"]

    return {
        "subtitle": f"Current date: {now_et.date().isoformat()} | Last update: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "requested_date": now_et.date().isoformat(),
        "expiration_date": expiration_date.isoformat(),
        "spot_price": f"{spot_price:,.2f}",
        "net_gex_billions": format_billions(net_gex),
        "call_wall": "N/A" if call_wall is None else f"{call_wall:,.0f}",
        "put_wall": "N/A" if put_wall is None else f"{put_wall:,.0f}",
        "chart_html": chart_html,
        "refresh_interval": settings["refresh_interval"],
        "chart_interval": settings["chart_interval"],
        "min_time_minutes": max(GEX_MIN_TIME_SECONDS // 60, 1),
        "error": None,
    }


def get_net_gex_snapshot() -> dict:
    now_et = pd.Timestamp.now(tz=TIMEZONE)

    options, underlying, expiration_date = fetch_spx_options_for_session(now_et)
    spot_price = float(
        underlying.get("regularMarketPrice")
        or underlying.get("postMarketPrice")
        or underlying.get("preMarketPrice")
        or underlying.get("previousClose")
        or 0.0
    )
    if spot_price <= 0:
        raise ValueError("Could not determine the current SPX price from the options feed.")

    gex_by_strike = build_gex_frame(options, spot_price, now_et, expiration_date)
    strike_min = spot_price - GEX_STRIKE_WINDOW
    strike_max = spot_price + GEX_STRIKE_WINDOW
    gex_by_strike = gex_by_strike[
        (gex_by_strike["strike"] >= strike_min) &
        (gex_by_strike["strike"] <= strike_max)
    ].copy()
    if gex_by_strike.empty:
        raise ValueError(
            f"No SPX strikes were available within +/- {int(GEX_STRIKE_WINDOW)} points of spot."
        )

    net_gex = float(gex_by_strike["net_gex"].sum())
    return {
        "spot_price": spot_price,
        "expiration_date": expiration_date,
        "gex_by_strike": gex_by_strike,
        "net_gex": net_gex,
    }


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


def calculate_rolling_median_ratio(series: pd.Series, window: int = 15) -> pd.Series:
    return series.rolling(window=window, min_periods=1).median()




def first_valid_number(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.iloc[0])


def last_valid_number(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.iloc[-1])


def intraday_session_mask(ts_series: pd.Series) -> pd.Series:
    times = ts_series.dt.time
    weekdays = ts_series.dt.weekday < 5
    return weekdays & (times >= dt.time(9, 30)) & (times <= dt.time(16, 0))


def make_chart(spx_1m: pd.DataFrame, range_high: float, range_low: float, prev_day_high: float, prev_day_low: float, chart_interval: str, start_of_day: pd.Timestamp) -> str:
    interval_map = {"5min": "5min", "15min": "15min", "1h": "1h"}
    label_map = {"5min": "5 Minute", "15min": "15 Minute", "1h": "1 Hour"}
    tick_minute_step = {"5min": 60, "15min": 60, "1h": 60}
    resample_rule = interval_map.get(chart_interval, "5min")
    chart_label = label_map.get(chart_interval, "5 Minute")
    label_every = tick_minute_step.get(chart_interval, 60)

    working = spx_1m.copy()
    working = working.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    working = working[intraday_session_mask(working["ts"])].copy()

    if working.empty:
        return "<div style='padding:20px;color:#ff5d5d;'>No chart data available.</div>"

    session_dates = sorted(working["ts"].dt.date.unique())
    if len(session_dates) >= 2:
        keep_dates = set(session_dates[-2:])
        working = working[working["ts"].dt.date.isin(keep_dates)].copy()

    spx_resampled = (
        working[["ts", "open_price", "high_price", "low_price", "close_price", "ema9_spx", "ema21_spx", "vwap_spx_proxy"]]
        .resample(resample_rule, on="ts", label="right", closed="right")
        .agg({
            "open_price": "first",
            "high_price": "max",
            "low_price": "min",
            "close_price": "last",
            "ema9_spx": "last",
            "ema21_spx": "last",
            "vwap_spx_proxy": "last",
        })
        .dropna(subset=["open_price", "high_price", "low_price", "close_price"])
        .reset_index()
    )

    if spx_resampled.empty:
        return "<div style='padding:20px;color:#ff5d5d;'>No chart data available.</div>"

    spx_resampled = spx_resampled.sort_values("ts").reset_index(drop=True)
    spx_resampled["xpos"] = range(len(spx_resampled))
    spx_resampled["date_str"] = spx_resampled["ts"].dt.strftime("%b %-d")
    spx_resampled["time_str"] = spx_resampled["ts"].dt.strftime("%H:%M")
    spx_resampled["hover_time"] = spx_resampled["ts"].dt.strftime("%Y-%m-%d %H:%M")

    tickvals = []
    ticktext = []
    for trade_date, session_df in spx_resampled.groupby(spx_resampled["ts"].dt.date, sort=True):
        session_df = session_df.sort_values("ts")
        session_open_rows = session_df[session_df["ts"].dt.strftime("%H:%M") == "09:30"]
        if not session_open_rows.empty:
            open_row = session_open_rows.iloc[0]
        else:
            open_row = session_df.iloc[0]
        tickvals.append(int(open_row["xpos"]))
        ticktext.append(f"{open_row['ts'].strftime('%b %d')}<br>09:30")

        hourly_rows = session_df[
            (session_df["ts"].dt.minute == 0) &
            (session_df["ts"].dt.hour >= 10) &
            (session_df["ts"].dt.hour <= 15)
        ]
        for row in hourly_rows.itertuples(index=False):
            tickvals.append(int(row.xpos))
            ticktext.append(row.ts.strftime("%H:%M"))

    tick_pairs = sorted(zip(tickvals, ticktext), key=lambda x: x[0])
    tickvals = [x for x, _ in tick_pairs]
    ticktext = [t for _, t in tick_pairs]

    current_session = spx_resampled[spx_resampled["ts"].dt.date == spx_resampled["ts"].dt.date.max()].copy()
    session_open_rows = current_session[current_session["ts"].dt.strftime("%H:%M") == "09:30"]
    if not session_open_rows.empty:
        start_of_day_x = int(session_open_rows.iloc[0]["xpos"])
    else:
        start_of_day_x = int(current_session.iloc[0]["xpos"])

    fig = go.Figure()
    candle_hover = [
        f"Time: {t}<br>Open: {o:.0f}<br>High: {h:.0f}<br>Low: {l:.0f}<br>Close: {c:.0f}"
        for t, o, h, l, c in zip(
            spx_resampled["hover_time"],
            spx_resampled["open_price"],
            spx_resampled["high_price"],
            spx_resampled["low_price"],
            spx_resampled["close_price"],
        )
    ]

    fig.add_trace(go.Candlestick(
        x=spx_resampled["xpos"],
        open=spx_resampled["open_price"],
        high=spx_resampled["high_price"],
        low=spx_resampled["low_price"],
        close=spx_resampled["close_price"],
        name="SPX",
        text=candle_hover,
        hoverinfo="text",
        hovertemplate=None,
    ))
    fig.add_trace(go.Scatter(
        x=spx_resampled["xpos"],
        y=spx_resampled["vwap_spx_proxy"],
        mode="lines",
        name="SPX VWAP Proxy",
        hoverinfo="skip",
        hovertemplate=None,
        line=dict(color="#9b87f5", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=spx_resampled["xpos"],
        y=spx_resampled["ema9_spx"],
        mode="lines",
        name="EMA9",
        hoverinfo="skip",
        hovertemplate=None,
        line=dict(color="#00cc96", width=1.8),
    ))
    fig.add_trace(go.Scatter(
        x=spx_resampled["xpos"],
        y=spx_resampled["ema21_spx"],
        mode="lines",
        name="EMA21",
        hoverinfo="skip",
        hovertemplate=None,
        line=dict(color="#ffd166", width=1.8),
    ))

    fig.add_shape(
        type="line",
        x0=start_of_day_x,
        x1=start_of_day_x,
        xref="x",
        y0=0,
        y1=1,
        yref="paper",
        line=dict(color="#4da3ff", width=2, dash="dash"),
    )
    fig.add_annotation(
        x=start_of_day_x,
        y=1,
        xref="x",
        yref="paper",
        text="Start of Day",
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
        font=dict(color="#4da3ff", size=12),
        bgcolor="#17202b",
        borderpad=2,
    )

    reference_lines = [
        (range_high, "Opening Range High", "#00cc96", "dash"),
        (range_low, "Opening Range Low", "#ef553b", "dash"),
        (prev_day_high, "Prev Day High", "#ffd166", "dot"),
        (prev_day_low, "Prev Day Low", "#4da3ff", "dot"),
    ]
    for y, name, color, dash in reference_lines:
        fig.add_shape(
            type="line",
            x0=0,
            x1=1,
            xref="paper",
            y0=y,
            y1=y,
            yref="y",
            line=dict(color=color, width=1.5, dash=dash),
        )
        fig.add_annotation(
            x=0.02,
            y=y,
            xref="paper",
            yref="y",
            text=name,
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            font=dict(color=color, size=12),
            bgcolor="#17202b",
            borderpad=2,
        )

    fig.update_layout(
        margin=dict(l=28, r=28, t=20, b=50),
        paper_bgcolor="#17202b",
        plot_bgcolor="#17202b",
        font=dict(color="#e8eef7"),
        xaxis=dict(
            type="linear",
            showgrid=True,
            gridcolor="#273244",
            rangeslider=dict(visible=False),
            title=f"Time ({chart_label})",
            title_standoff=4,
            range=[-0.75, len(spx_resampled) - 0.25],
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            automargin=True,
            fixedrange=False,
            showline=False,
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#273244",
            title="SPX",
            title_standoff=4,
            automargin=True,
            fixedrange=False,
            showline=False,
            zeroline=False,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="closest",
        hoverlabel=dict(bgcolor="#0f141b", bordercolor="#273244", font=dict(color="#e8eef7")),
        hoverdistance=20,
    )
    fig.update_xaxes(showspikes=False)
    fig.update_yaxes(showspikes=False)

    chart_div = plot(fig, output_type="div", include_plotlyjs=False, config={"displayModeBar": False, "responsive": True})

    div_match = re.search(r'<div id="([^"]+)"', chart_div)
    if not div_match:
        return chart_div

    plot_div_id = div_match.group(1)
    x_positions = [int(x) for x in spx_resampled["xpos"].tolist()]
    hover_times = spx_resampled["hover_time"].tolist()

    hover_script = f"""
<script>
(function() {{
    var gd = document.getElementById({json.dumps(plot_div_id)});
    if (!gd) return;

    var xPositions = {json.dumps(x_positions)};
    var hoverTimes = {json.dumps(hover_times)};
    var overCandle = false;
    var tooltip = null;
    var crosshairV = null;
    var crosshairH = null;

    function ensureTooltip() {{
        if (tooltip) return tooltip;
        tooltip = document.createElement('div');
        tooltip.style.position = 'fixed';
        tooltip.style.pointerEvents = 'none';
        tooltip.style.zIndex = '9999';
        tooltip.style.background = '#0f141b';
        tooltip.style.border = '1px solid #273244';
        tooltip.style.borderRadius = '6px';
        tooltip.style.padding = '8px 10px';
        tooltip.style.color = '#e8eef7';
        tooltip.style.fontFamily = 'Segoe UI, Arial, sans-serif';
        tooltip.style.fontSize = '12px';
        tooltip.style.lineHeight = '1.35';
        tooltip.style.whiteSpace = 'nowrap';
        tooltip.style.boxShadow = '0 4px 14px rgba(0,0,0,0.35)';
        tooltip.style.display = 'none';
        document.body.appendChild(tooltip);
        return tooltip;
    }}

    function ensureCrosshair() {{
        if (!gd) return;
        if (!gd.style.position) gd.style.position = 'relative';

        if (!crosshairV) {{
            crosshairV = document.createElement('div');
            crosshairV.style.position = 'absolute';
            crosshairV.style.pointerEvents = 'none';
            crosshairV.style.zIndex = '20';
            crosshairV.style.borderLeft = '1px dotted #8fa2b7';
            crosshairV.style.display = 'none';
            gd.appendChild(crosshairV);
        }}

        if (!crosshairH) {{
            crosshairH = document.createElement('div');
            crosshairH.style.position = 'absolute';
            crosshairH.style.pointerEvents = 'none';
            crosshairH.style.zIndex = '20';
            crosshairH.style.borderTop = '1px dotted #8fa2b7';
            crosshairH.style.display = 'none';
            gd.appendChild(crosshairH);
        }}
    }}

    function showCrosshair(plotLeft, plotTop, plotWidth, plotHeight, px, py) {{
        ensureCrosshair();
        if (!crosshairV || !crosshairH) return;

        crosshairV.style.left = px + 'px';
        crosshairV.style.top = plotTop + 'px';
        crosshairV.style.height = plotHeight + 'px';
        crosshairV.style.display = 'block';

        crosshairH.style.left = plotLeft + 'px';
        crosshairH.style.top = py + 'px';
        crosshairH.style.width = plotWidth + 'px';
        crosshairH.style.display = 'block';
    }}

    function hideTooltip() {{
        if (tooltip) tooltip.style.display = 'none';
    }}

    function hideCrosshair() {{
        if (crosshairV) crosshairV.style.display = 'none';
        if (crosshairH) crosshairH.style.display = 'none';
    }}

    function nearestIndex(xVal) {{
        if (!xPositions.length) return -1;
        var bestIdx = 0;
        var bestDist = Math.abs(xPositions[0] - xVal);
        for (var i = 1; i < xPositions.length; i++) {{
            var d = Math.abs(xPositions[i] - xVal);
            if (d < bestDist) {{
                bestDist = d;
                bestIdx = i;
            }}
        }}
        return bestIdx;
    }}

    gd.on('plotly_hover', function() {{
        overCandle = true;
        hideTooltip();
    }});

    gd.on('plotly_unhover', function() {{
        overCandle = false;
    }});

    gd.addEventListener('mouseleave', function() {{
        overCandle = false;
        hideTooltip();
        hideCrosshair();
    }});

    gd.addEventListener('mousemove', function(evt) {{
        if (!gd._fullLayout || !gd._fullLayout.xaxis || !gd._fullLayout.yaxis) {{
            return;
        }}

        var fl = gd._fullLayout;
        var xaxis = fl.xaxis;
        var yaxis = fl.yaxis;
        var plotLeft = fl._size.l;
        var plotTop = fl._size.t;
        var plotWidth = fl._size.w;
        var plotHeight = fl._size.h;

        var rect = gd.getBoundingClientRect();
        var px = evt.clientX - rect.left;
        var py = evt.clientY - rect.top;

        if (px < plotLeft || px > plotLeft + plotWidth || py < plotTop || py > plotTop + plotHeight) {{
            hideTooltip();
            hideCrosshair();
            return;
        }}

        showCrosshair(plotLeft, plotTop, plotWidth, plotHeight, px, py);

        if (overCandle) {{
            hideTooltip();
            return;
        }}

        var xVal = xaxis.p2l(px - plotLeft);
        var yVal = yaxis.p2l(py - plotTop);
        var idx = nearestIndex(xVal);
        if (idx < 0) {{
            hideTooltip();
            return;
        }}

        var t = ensureTooltip();
        t.innerHTML = 'Time: ' + hoverTimes[idx] + '<br>SPX: ' + Math.round(yVal).toLocaleString();
        t.style.display = 'block';
        t.style.left = (evt.clientX + 14) + 'px';
        t.style.top = (evt.clientY + 14) + 'px';
    }});
}})();
</script>
"""
    return chart_div + hover_script


def run_web_service(settings: dict) -> dict:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_utc = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=LOOKBACK_DAYS)
    current_et_date = pd.Timestamp.now(tz=TIMEZONE).date()
    net_gex_billions = "N/A"
    net_gex_date = ""
    net_gex_class = ""
    net_gex_subtext = "Live options feed unavailable"

    with get_connection() as conn:
        spx = query_ticker_history(conn, SPX_TICKER, INTERVAL_NAME, start_utc)
        spy = query_ticker_history(conn, SPY_TICKER, INTERVAL_NAME, start_utc)

    if spx.empty:
        return {"time": now, "error": f"No {SPX_TICKER} rows found in {SOURCE_TABLE}.", **settings}
    if spy.empty:
        return {"time": now, "error": f"No {SPY_TICKER} rows found in {SOURCE_TABLE}.", **settings}

    spx = spx.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    spy = spy.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)

    current_date = spx["ts"].max().date()
    prior_dates = sorted({x.date() for x in spx["ts"] if x.date() < current_date})
    if not prior_dates:
        return {"time": now, "error": f"Need at least two trading days in {SOURCE_TABLE}.", **settings}
    prev_date = prior_dates[-1]

    spx_current = spx[spx["ts"].dt.date == current_date].copy()
    spy_current = spy[spy["ts"].dt.date == current_date].copy()
    spx_prev = spx[spx["ts"].dt.date == prev_date].copy()
    spy_prev = spy[spy["ts"].dt.date == prev_date].copy()

    if spx_current.empty or spy_current.empty or spx_prev.empty or spy_prev.empty:
        return {"time": now, "error": f"Could not separate current/prior session data from {SOURCE_TABLE}.", **settings}

    spx["ema9_spx"] = spx["close_price"].ewm(span=9, adjust=False).mean()
    spx["ema21_spx"] = spx["close_price"].ewm(span=21, adjust=False).mean()
    spy["trade_date"] = spy["ts"].dt.date
    spx["trade_date"] = spx["ts"].dt.date

    spy_session = spy[intraday_session_mask(spy["ts"])].copy()
    spx_session = spx[intraday_session_mask(spx["ts"])].copy()

    spy_session["vwap_spy"] = (
        spy_session.groupby("trade_date", group_keys=False).apply(calculate_vwap).reset_index(level=0, drop=True)
    )

    chart_spx = pd.merge(
        spx_session.sort_values("ts"),
        spy_session[["ts", "trade_date", "close_price", "vwap_spy"]]
        .rename(columns={"close_price": "spy_close"})
        .sort_values("ts"),
        on=["ts", "trade_date"],
        how="inner",
    )
    chart_spx["spx_spy_ratio"] = chart_spx["close_price"] / chart_spx["spy_close"].replace(0, pd.NA)
    chart_spx["spx_spy_ratio"] = pd.to_numeric(chart_spx["spx_spy_ratio"], errors="coerce")
    chart_spx["spx_spy_ratio_median"] = (
        chart_spx.groupby("trade_date", group_keys=False)["spx_spy_ratio"].transform(calculate_rolling_median_ratio)
    )
    chart_spx["vwap_spx_proxy"] = chart_spx["vwap_spy"] * chart_spx["spx_spy_ratio_median"]
    chart_spx = chart_spx.dropna(subset=["open_price", "high_price", "low_price", "close_price", "vwap_spx_proxy"]).copy()

    spx_current = chart_spx[chart_spx["ts"].dt.date == current_date].copy()
    spy_current = spy_session[spy_session["ts"].dt.date == current_date].copy()

    latest_price = last_valid_number(spx_current["close_price"])
    latest_ema9 = last_valid_number(spx_current["ema9_spx"])
    latest_ema21 = last_valid_number(spx_current["ema21_spx"])
    open_price = first_valid_number(spx_current["open_price"])
    latest_vwap = last_valid_number(spx_current["vwap_spx_proxy"])

    if None in {latest_price, latest_ema9, latest_ema21, open_price, latest_vwap}:
        return {"time": now, "error": f"Missing current-session values in {SOURCE_TABLE}.", **settings}

    opening_df = spx_current[
        (spx_current["ts"].dt.time >= dt.time(9, 30)) &
        (spx_current["ts"].dt.time <= dt.time(10, 0))
    ].copy()
    opening_df = opening_df.dropna(subset=["high_price", "low_price"])
    if opening_df.empty:
        return {"time": now, "error": f"No opening range rows found in {SOURCE_TABLE}.", **settings}

    range_high = float(opening_df["high_price"].max())
    range_low = float(opening_df["low_price"].min())

    prev_day_high = float(pd.to_numeric(spx_prev["high_price"], errors="coerce").max())
    prev_day_low = float(pd.to_numeric(spx_prev["low_price"], errors="coerce").min())
    current_day_high = float(pd.to_numeric(spx_current["high_price"], errors="coerce").max())
    current_day_low = float(pd.to_numeric(spx_current["low_price"], errors="coerce").min())

    outside_range = (latest_price > range_high) or (latest_price < range_low)
    vwap_distance_pct = abs(latest_price - latest_vwap) / latest_price * 100.0 if latest_price else float("nan")
    open_distance_pct = abs(latest_price - open_price) / open_price * 100.0 if open_price else float("nan")

    vwap_distance = pd.notna(vwap_distance_pct) and vwap_distance_pct >= 0.15
    open_distance = pd.notna(open_distance_pct) and open_distance_pct > 0.30

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

    try:
        gex_snapshot = get_net_gex_snapshot()
        net_gex = gex_snapshot["net_gex"]
        net_gex_billions = format_billions(net_gex)
        expiration_date = gex_snapshot["expiration_date"]
        if expiration_date > current_et_date:
            net_gex_date = expiration_date.isoformat()
        if net_gex > 0:
            net_gex_class = "gex-positive"
            net_gex_subtext = "Positive gamma regime"
        elif net_gex < 0:
            net_gex_class = "gex-negative"
            net_gex_subtext = "Negative gamma regime"
        else:
            net_gex_subtext = "Flat gamma regime"
    except Exception:
        pass

    chart_html = make_chart(
        chart_spx,
        range_high,
        range_low,
        prev_day_high,
        prev_day_low,
        settings["chart_interval"],
        pd.Timestamp(spx_current["ts"].min()),
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
        "vwap_distance_pct": "N/A" if pd.isna(vwap_distance_pct) else round(vwap_distance_pct, 3),
        "open_distance_pct": "N/A" if pd.isna(open_distance_pct) else round(open_distance_pct, 3),
        "outside_range": outside_range,
        "vwap_distance": vwap_distance,
        "open_distance": open_distance,
        "net_gex_billions": net_gex_billions,
        "net_gex_date": net_gex_date,
        "net_gex_class": net_gex_class,
        "net_gex_subtext": net_gex_subtext,
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


@app.route("/favicon.ico")
def favicon_ico():
    return redirect(url_for("static", filename="favicon.svg", v=FAVICON_VERSION), code=302)


@app.route("/")
def index():
    settings = load_settings()
    data = run_web_service(settings)
    return render_template_string(HTML, data=data, favicon_version=FAVICON_VERSION)


@app.route("/gex")
def gex():
    settings = load_settings()
    try:
        data = run_gex_service(settings)
    except Exception as exc:
        now_et = pd.Timestamp.now(tz=TIMEZONE)
        data = {
            "subtitle": f"Current date: {now_et.date().isoformat()} | Last update: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            "requested_date": now_et.date().isoformat(),
            "expiration_date": now_et.date().isoformat(),
            "spot_price": "N/A",
            "net_gex_billions": "N/A",
            "call_wall": "N/A",
            "put_wall": "N/A",
            "chart_html": "",
            "refresh_interval": settings["refresh_interval"],
            "chart_interval": settings["chart_interval"],
            "min_time_minutes": max(GEX_MIN_TIME_SECONDS // 60, 1),
            "error": str(exc),
        }
    return render_template_string(GEX_HTML, data=data, favicon_version=FAVICON_VERSION)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
