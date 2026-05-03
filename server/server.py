from flask import Flask, render_template_string, request, send_from_directory, url_for
import datetime as dt
import json
import math
import os
import random
import re
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import plot
from plotly.subplots import make_subplots
import oracledb


app = Flask(__name__)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
SETTINGS_FILE = DATA_DIR / "ui_settings.json"
FAVICON_VERSION = "2"

DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {
    "refresh_interval": 31,
    "chart_interval": "5min",
    "debug_mode": False,
    "debug_trade_date": "",
    "debug_time": "",
    "simulator_speed": 60.0,
    "simulator_points": 70.0,
    "simulator_wide": 20.0,
    "simulator_trade_date": "",
    "simulator_execute_time": "10:30",
    "simulator_execution_end_time": "14:00",
}

DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
WALLET_DIR = os.environ["WALLET_DIR"]
DB_DSN = os.environ["DB_DSN"]

SOURCE_TABLE = os.environ.get("SOURCE_TABLE", "TICKER_HISTORY")
OPTION_SOURCE_TABLE = os.environ.get("OPTION_SOURCE_TABLE", "TICKER_OPTIONS_HISTORY")
SPX_TICKER = os.environ.get("SPX_TICKER", "^GSPC")
SPY_TICKER = os.environ.get("SPY_TICKER", "SPY")
INTERVAL_NAME = os.environ.get("INTERVAL_NAME", "1m")
TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "5"))
GEX_CONTRACT_SIZE = int(os.environ.get("GEX_CONTRACT_SIZE", "100"))
GEX_MIN_TIME_SECONDS = int(os.environ.get("GEX_MIN_TIME_SECONDS", "60"))
GEX_STRIKE_WINDOW = float(os.environ.get("GEX_STRIKE_WINDOW", "50"))


def regular_session_time_options() -> list[str]:
    start = dt.datetime.combine(dt.date(2000, 1, 1), dt.time(9, 30))
    end = dt.datetime.combine(dt.date(2000, 1, 1), dt.time(16, 0))
    options = []
    current = start
    while current <= end:
        options.append(current.strftime("%H:%M"))
        current += dt.timedelta(minutes=5)
    return options


DEBUG_TIME_OPTIONS = regular_session_time_options()


class NoOpenInterestInFeedError(Exception):
    def __init__(self, expiration_date: Optional[dt.date], underlying: Optional[dict] = None):
        super().__init__("No Open Interest In Feed")
        self.expiration_date = expiration_date
        self.underlying = underlying or {}


def db_storage_ticker(ticker: str) -> str:
    mapping = {
        "^GSPC": "SPX",
    }
    return mapping.get(ticker.upper(), ticker.upper())


def nav_class(active_tab: str, tab: str) -> str:
    return "nav-link active" if active_tab == tab else "nav-link"


HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>CashFlowArc</title>
    <link rel="icon" href="{{ url_for('favicon_svg', v=favicon_version) }}" sizes="any" type="image/svg+xml">
    <meta http-equiv="refresh" content="{{ data.refresh_interval }}">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        :root{
            --bg:#07111f;
            --panel:rgba(11, 22, 39, 0.84);
            --panel-2:rgba(15, 30, 52, 0.92);
            --panel-3:rgba(20, 39, 66, 0.92);
            --border:rgba(148, 179, 255, 0.14);
            --text:#edf4ff;
            --muted:#8fa6c7;
            --green:#2ad18b;
            --red:#ff6b6b;
            --yellow:#ffcf70;
            --blue:#7cc4ff;
            --shadow:0 20px 50px rgba(0, 0, 0, 0.34);
        }
        *{box-sizing:border-box}
        body{
            margin:0;
            font-family:"Aptos","Segoe UI Variable","Segoe UI",sans-serif;
            background:
                radial-gradient(circle at top left, rgba(62, 120, 255, 0.18), transparent 30%),
                radial-gradient(circle at top right, rgba(42, 209, 139, 0.12), transparent 24%),
                linear-gradient(180deg, #06111d 0%, #091627 55%, #07111f 100%);
            color:var(--text);
        }
        .wrap{max-width:1840px; margin:0 auto; padding:24px;}
        .topbar{
            position:relative;
            display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap;
            gap:18px; margin-bottom:20px; padding:22px 24px;
            background:linear-gradient(180deg, rgba(15, 31, 52, 0.92), rgba(8, 18, 32, 0.92));
            border:1px solid var(--border);
            border-radius:24px;
            box-shadow:var(--shadow);
            overflow:hidden;
        }
        .topbar::after{
            content:"";
            position:absolute;
            inset:auto -80px -90px auto;
            width:220px;
            height:220px;
            border-radius:50%;
            background:radial-gradient(circle, rgba(124, 196, 255, 0.22), transparent 68%);
            pointer-events:none;
        }
        .title{max-width:680px}
        .title h1{
            margin:0;
            font-family:"Bahnschrift","Aptos Display","Segoe UI",sans-serif;
            font-size:34px;
            line-height:1.05;
            letter-spacing:0;
        }
        .title p{margin:8px 0 0; color:var(--muted); font-size:14px; line-height:1.5}
        .top-right{
            margin-left:auto;
            display:flex; align-items:center; justify-content:flex-end; gap:12px; flex-wrap:wrap;
        }
        .nav-links{
            display:flex; gap:6px; align-items:center; flex-wrap:wrap;
            padding:6px;
            border-radius:999px;
            background:rgba(255,255,255,0.03);
            border:1px solid rgba(255,255,255,0.05);
            backdrop-filter:blur(14px);
        }
        .nav-link{
            color:var(--muted); text-decoration:none; font-size:13px; font-weight:600;
            padding:10px 14px; border-radius:999px; transition:all .18s ease;
        }
        .nav-link:hover{color:var(--text); background:rgba(255,255,255,0.04)}
        .nav-link.active{
            color:#04101c;
            background:linear-gradient(135deg, #8ed4ff, #d7f0ff);
            box-shadow:0 8px 22px rgba(124, 196, 255, 0.28);
        }
        .control-form{
            display:flex; align-items:center; gap:10px; flex-wrap:wrap;
            background:rgba(255,255,255,0.035);
            border:1px solid rgba(255,255,255,0.05);
            padding:10px 12px; border-radius:16px;
            backdrop-filter:blur(14px);
        }
        .control-label{
            font-size:11px; color:var(--muted); font-weight:700;
            letter-spacing:0.08em; text-transform:uppercase;
        }
        .text-input{
            width:92px;
            background:rgba(6, 14, 26, 0.82);
            color:var(--text);
            border:1px solid rgba(148, 179, 255, 0.18);
            border-radius:12px;
            padding:10px 12px;
            font-size:13px;
        }
        .text-input:focus{
            outline:none;
            border-color:rgba(124, 196, 255, 0.56);
            box-shadow:0 0 0 4px rgba(124, 196, 255, 0.12);
            background:rgba(9, 20, 35, 0.95);
        }
        select.text-input{appearance:auto;}
        .status-pill{
            padding:11px 16px;
            border-radius:999px;
            font-weight:700;
            font-size:12px;
            letter-spacing:0.08em;
            text-transform:uppercase;
            border:1px solid transparent;
        }
        .enter{color:#042414; background:linear-gradient(135deg, #39e3a0, #9af1c9); box-shadow:0 12px 24px rgba(42, 209, 139, 0.22)}
        .no{color:#350b0b; background:linear-gradient(135deg, #ff8f8f, #ffc0c0); box-shadow:0 12px 24px rgba(255, 107, 107, 0.2)}
        .grid{display:grid; grid-template-columns:1.35fr 0.95fr; gap:18px; align-items:stretch;}
        @media (max-width: 1400px){ .grid{grid-template-columns:1fr;} }
        @media (max-width: 900px){
            .wrap{padding:16px}
            .topbar{padding:18px}
            .title h1{font-size:28px}
        }
        .card{
            background:linear-gradient(180deg, rgba(11, 22, 39, 0.92), rgba(8, 17, 31, 0.92));
            border:1px solid var(--border);
            border-radius:24px;
            padding:18px;
            overflow:hidden;
            box-shadow:var(--shadow);
        }
        .chart-card,.snapshot-card{display:flex; flex-direction:column; height:100%;}
        .section-head{
            display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px;
        }
        .section-kicker{
            margin:0 0 6px;
            color:var(--blue);
            font-size:11px;
            font-weight:700;
            letter-spacing:0.14em;
            text-transform:uppercase;
        }
        .section-title{
            margin:0;
            font-family:"Bahnschrift","Aptos Display","Segoe UI",sans-serif;
            font-size:22px;
            letter-spacing:0;
        }
        .chart-wrap{
            background:linear-gradient(180deg, rgba(14, 27, 46, 0.96), rgba(12, 24, 42, 0.92));
            border:1px solid rgba(148, 179, 255, 0.08);
            border-radius:20px;
            padding:0; overflow:hidden; flex:1 1 auto; min-height:300px;
        }
        .chart-wrap .plotly-graph-div{width:100% !important; height:100% !important; min-height:300px;}
        .signal-list{display:grid; gap:10px; margin-bottom:18px;}
        .signal-row{
            display:grid;
            grid-template-columns:1.25fr auto 1fr;
            gap:12px;
            align-items:center;
            padding:14px 16px;
            border-radius:18px;
            background:rgba(255,255,255,0.03);
            border:1px solid rgba(255,255,255,0.04);
        }
        .signal-name{font-weight:600}
        .signal-value{color:var(--muted); font-size:13px; text-align:right}
        .signal-badge{
            min-width:84px;
            text-align:center;
            padding:8px 12px;
            border-radius:999px;
            font-size:11px;
            font-weight:700;
            letter-spacing:0.08em;
            text-transform:uppercase;
        }
        .signal-badge.pass{background:rgba(42, 209, 139, 0.18); color:#8ff0bd}
        .signal-badge.fail{background:rgba(255, 107, 107, 0.18); color:#ffb5b5}
        .metrics{display:grid; grid-template-columns:repeat(3,1fr); gap:12px;}
        @media (max-width: 900px){ .metrics{grid-template-columns:repeat(2,1fr);} }
        @media (max-width: 620px){
            .metrics{grid-template-columns:1fr}
            .signal-row{grid-template-columns:1fr}
            .signal-value{text-align:left}
        }
        .metric{
            position:relative;
            background:linear-gradient(180deg, rgba(18, 34, 58, 0.92), rgba(12, 24, 42, 0.94));
            border:1px solid rgba(148, 179, 255, 0.08);
            border-radius:20px;
            padding:16px;
            min-height:104px;
            overflow:hidden;
        }
        .metric::before{
            content:"";
            position:absolute;
            inset:0 auto auto 0;
            width:100%;
            height:2px;
            background:linear-gradient(90deg, rgba(124, 196, 255, 0.7), transparent 60%);
            opacity:0.85;
        }
        .metric .label{color:var(--muted); font-size:11px; font-weight:700; letter-spacing:0.12em; text-transform:uppercase;}
        .metric .value{
            margin-top:10px;
            font-family:"Bahnschrift","Aptos Display","Segoe UI",sans-serif;
            font-size:28px;
            line-height:1.05;
            letter-spacing:0;
            font-weight:700;
        }
        .metric .value.compact{font-size:22px; line-height:1.15}
        .metric .value .value-date{
            display:block;
            margin-top:6px;
            font-size:13px;
            font-family:"Aptos","Segoe UI Variable","Segoe UI",sans-serif;
            font-weight:600;
            color:var(--muted);
        }
        .metric .sub{margin-top:6px; color:var(--muted); font-size:12px; line-height:1.45}
        .metric.hero{
            grid-column:span 2;
            min-height:132px;
            background:linear-gradient(135deg, rgba(17, 39, 67, 0.98), rgba(13, 27, 47, 0.96));
        }
        @media (max-width: 900px){ .metric.hero{grid-column:span 1;} }
        .metric.gex-positive{
            background:linear-gradient(180deg, rgba(14, 49, 36, 0.95), rgba(12, 32, 28, 0.95));
            border-color:rgba(42, 209, 139, 0.22);
        }
        .metric.gex-negative{
            background:linear-gradient(180deg, rgba(54, 23, 25, 0.96), rgba(36, 16, 18, 0.95));
            border-color:rgba(255, 107, 107, 0.24);
        }
        .metric.gex-positive .value{color:var(--green)}
        .metric.gex-negative .value{color:var(--red)}
        .pass,.bull{color:var(--green); font-weight:700}
        .fail,.bear{color:var(--red); font-weight:700}
        .neutral{color:var(--yellow); font-weight:700}
        .err{color:var(--red); font-weight:700; font-size:18px}
        .small{font-size:12px; color:var(--muted); margin-top:14px; line-height:1.5}
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
            <div class="nav-links">
                <a class="nav-link active" href="/terminal">Modern Terminal</a>
                <a class="nav-link" href="/gex">SPX GEX</a>
                <a class="nav-link" href="/option-chain">Option Chain</a>
                <a class="nav-link" href="/simulator">Simulator</a>
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
            <div class="section-head">
                <div>
                    <p class="section-kicker">Execution View</p>
                    <h2 class="section-title">SPX Candlestick Chart</h2>
                </div>
                <form id="chart-settings-form" method="post" action="/settings" class="control-form">
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
            <div class="section-head">
                <div>
                    <p class="section-kicker">Session Read</p>
                    <h2 class="section-title">Market Snapshot</h2>
                </div>
            </div>
            <div class="signal-list">
                <div class="signal-row">
                    <div class="signal-name">Outside 9:30&ndash;10:00 Range</div>
                    <div class="signal-badge {{ 'pass' if data.outside_range else 'fail' }}">{{ 'Pass' if data.outside_range else 'Fail' }}</div>
                    <div class="signal-value">{{ data.price }} vs {{ data.range_low }} / {{ data.range_high }}</div>
                </div>
                <div class="signal-row">
                    <div class="signal-name">VWAP Distance &ge; 0.15%</div>
                    <div class="signal-badge {{ 'pass' if data.vwap_distance else 'fail' }}">{{ 'Pass' if data.vwap_distance else 'Fail' }}</div>
                    <div class="signal-value">{{ data.vwap_distance_pct }}%</div>
                </div>
                <div class="signal-row">
                    <div class="signal-name">Distance from Open &gt; 0.30%</div>
                    <div class="signal-badge {{ 'pass' if data.open_distance else 'fail' }}">{{ 'Pass' if data.open_distance else 'Fail' }}</div>
                    <div class="signal-value">{{ data.open_distance_pct }}%</div>
                </div>
                <div class="signal-row">
                    <div class="signal-name">Bullish Setup</div>
                    <div class="signal-badge {{ 'pass' if data.bullish else 'fail' }}">{{ 'Yes' if data.bullish else 'No' }}</div>
                    <div class="signal-value"><span style="color: {{ 'var(--green)' if data.price > data.vwap else 'var(--red)' }}; font-weight:700;">Price &gt; SPX VWAP Proxy</span>, <span style="color: {{ 'var(--green)' if data.ema9 > data.ema21 else 'var(--red)' }}; font-weight:700;">EMA9 &gt; EMA21</span></div>
                </div>
                <div class="signal-row">
                    <div class="signal-name">Bearish Setup</div>
                    <div class="signal-badge {{ 'pass' if data.bearish else 'fail' }}">{{ 'Yes' if data.bearish else 'No' }}</div>
                    <div class="signal-value"><span style="color: {{ 'var(--green)' if data.price < data.vwap else 'var(--red)' }}; font-weight:700;">Price &lt; SPX VWAP Proxy</span>, <span style="color: {{ 'var(--green)' if data.ema9 < data.ema21 else 'var(--red)' }}; font-weight:700;">EMA9 &lt; EMA21</span></div>
                </div>
            </div>

            <div class="metrics">
                <div class="metric hero"><div class="label">SPX Price</div><div class="value">{{ data.price }}</div><div class="sub">Latest stored SPX close and primary session anchor</div></div>
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

TERMINAL_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>CashFlowArc Terminal</title>
    <link rel="icon" href="{{ url_for('favicon_svg', v=favicon_version) }}" sizes="any" type="image/svg+xml">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        :root{
            --bg:#020506;
            --panel:rgba(3,13,17,.86);
            --panel-2:rgba(6,21,27,.92);
            --cyan:#00e5f0;
            --cyan-soft:rgba(0,229,240,.34);
            --cyan-faint:rgba(0,229,240,.12);
            --text:#f3fbff;
            --muted:#8eaab3;
            --green:#1cff73;
            --red:#ff3148;
            --yellow:#ffc400;
            --blue:#52a5ff;
        }
        *{box-sizing:border-box}
        body{
            margin:0;
            font-family:Segoe UI, Arial, sans-serif;
            color:var(--text);
            background:
                linear-gradient(180deg, rgba(1,7,10,.12), rgba(1,3,5,.72)),
                radial-gradient(circle at 50% 115%, rgba(38,103,119,.55) 0 7%, transparent 34%),
                repeating-linear-gradient(90deg, rgba(0,229,240,.026) 0 1px, transparent 1px 118px),
                repeating-linear-gradient(0deg, rgba(0,229,240,.02) 0 1px, transparent 1px 92px),
                radial-gradient(circle at 50% 20%, rgba(9,44,54,.72) 0%, rgba(2,7,9,.92) 38%, #010303 74%);
        }
        body:before{
            content:"";
            position:fixed;
            inset:0;
            pointer-events:none;
            background:linear-gradient(180deg, transparent 0 48%, rgba(0,229,240,.035) 50%, transparent 52%);
            background-size:100% 7px;
            opacity:.38;
            mix-blend-mode:screen;
        }
        body:after{
            content:"";
            position:fixed;
            inset:0;
            pointer-events:none;
            background:
                radial-gradient(circle, rgba(82,165,255,.75) 0 2px, transparent 3px),
                radial-gradient(circle, rgba(0,229,240,.65) 0 2px, transparent 3px),
                linear-gradient(90deg, transparent 0 9%, rgba(0,229,240,.13) 9% 9.25%, transparent 9.25% 28%, rgba(0,229,240,.10) 28% 28.25%, transparent 28.25%),
                linear-gradient(0deg, transparent 0 18%, rgba(0,229,240,.10) 18% 18.25%, transparent 18.25% 58%, rgba(82,165,255,.09) 58% 58.25%, transparent 58.25%),
                linear-gradient(135deg, transparent 0 48%, rgba(0,229,240,.08) 48% 48.3%, transparent 48.3%);
            background-size:360px 220px,420px 280px,360px 220px,360px 220px,280px 280px;
            background-position:0 0,130px 80px,0 0,0 0,0 0;
            animation:circuit-pulse 6.5s linear infinite;
            opacity:.26;
            mix-blend-mode:screen;
        }
        @keyframes circuit-pulse{0%{background-position:-40px 38px,130px -30px,0 0,0 0,0 0}50%{opacity:.34}100%{background-position:320px 38px,130px 250px,0 0,0 0,0 0}}
        .shell{min-height:100vh; padding:18px; display:grid; grid-template-rows:auto 1fr auto; gap:18px;}
        .topbar,.controlbar,.tickerbar,.panel{
            position:relative;
            border:1px solid var(--cyan-soft);
            background:
                linear-gradient(135deg, rgba(255,255,255,.045), transparent 28%),
                linear-gradient(180deg, rgba(5,23,29,.9), rgba(1,6,8,.94));
            box-shadow:0 0 30px rgba(0,229,240,.16), inset 0 0 36px rgba(0,229,240,.045);
            backdrop-filter:blur(10px);
            clip-path:polygon(18px 0,calc(100% - 18px) 0,100% 18px,100% calc(100% - 18px),calc(100% - 18px) 100%,18px 100%,0 calc(100% - 18px),0 18px);
        }
        .topbar:before,.controlbar:before,.tickerbar:before,.panel:before{
            content:""; position:absolute; inset:6px; pointer-events:none;
            border-top:1px solid rgba(0,229,240,.34);
            border-bottom:1px solid rgba(0,229,240,.14);
            clip-path:polygon(14px 0,42% 0,42% 1px,14px 1px,14px 14px,13px 14px,13px 0,0 0,0 13px,1px 13px,1px 1px,14px 1px);
        }
        .topbar{display:grid; grid-template-columns:minmax(360px,1fr) auto minmax(360px,1fr); align-items:center; gap:24px; padding:10px 22px; min-height:74px;}
        .brand{text-align:center}
        .brand h1{margin:0; font-size:30px; letter-spacing:0; line-height:.95; text-shadow:0 0 16px rgba(255,255,255,.22), 0 0 24px rgba(0,229,240,.22);}
        .brand p{margin:10px 0 0; color:#b5e9f0; font-size:14px; text-transform:uppercase;}
        .timeblock{justify-self:start; display:flex; gap:18px; align-items:center; color:var(--text); font-size:14px; font-weight:800; padding:9px 14px; min-width:320px; border:1px solid rgba(0,229,240,.25); background:linear-gradient(135deg, rgba(0,229,240,.10), rgba(0,9,13,.55)); clip-path:polygon(10px 0,100% 0,100% calc(100% - 10px),calc(100% - 10px) 100%,0 100%,0 10px);}
        .timeblock .label{display:none;}
        .timeblock .clockmark{color:#dffcff; opacity:.88;}
        .nav-panel{justify-self:end; display:grid; gap:6px; justify-items:end;}
        .market-readout{text-align:right; font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.02em;}
        .market-readout b{display:inline-block; margin-right:10px; font-size:18px;}
        .market-readout b:before{content:""; display:inline-block; width:8px; height:8px; margin-right:7px; border-radius:50%; background:currentColor; box-shadow:0 0 12px currentColor;}
        .controlbar{display:flex; justify-content:space-between; align-items:center; gap:18px; padding:9px 16px; min-height:48px;}
        .nav-links{display:flex; justify-content:flex-start; gap:8px; flex-wrap:wrap; opacity:.68;}
        .nav-link{color:var(--muted); text-decoration:none; font-size:11px; font-weight:900; padding:8px 11px; border:1px solid rgba(0,229,240,.18); background:rgba(0,10,14,.38); text-transform:uppercase;}
        .nav-link.active{color:#dffcff; border-color:rgba(0,229,240,.48); box-shadow:inset 0 0 0 1px rgba(0,229,240,.18);}
        .debug-form{display:flex; align-items:center; gap:8px; flex-wrap:wrap; color:var(--muted); font-size:11px; text-transform:uppercase;}
        .debug-form input,.debug-form select{height:28px; border:1px solid rgba(0,229,240,.22); background:rgba(0,8,11,.72); color:var(--text); padding:0 8px; font:inherit;}
        .debug-form .refresh-input{width:68px;}
        .debug-form input[type="date"]{min-width:128px; text-transform:none;}
        .debug-form input[type="time"]{min-width:88px; text-transform:none;}
        .debug-form input:disabled{opacity:1; cursor:not-allowed; color:var(--muted);}
        .debug-picker{position:relative; display:inline-flex; align-items:center;}
        .debug-picker input{padding-right:26px;}
        .debug-picker-button{position:absolute; right:3px; top:50%; width:22px; height:22px; transform:translateY(-50%); display:grid; place-items:center; border:0; background:transparent; color:var(--cyan); padding:0; cursor:pointer;}
        .debug-picker-button:before{content:"\\1F50D"; font-size:12px; line-height:1; opacity:.76; text-shadow:0 0 8px rgba(0,229,240,.36);}
        .debug-picker-button:disabled{display:none;}
        .debug-switch{display:inline-flex; align-items:center; gap:7px; cursor:pointer;}
        .debug-switch input{position:absolute; opacity:0; pointer-events:none;}
        .debug-slider{width:38px; height:20px; border:1px solid rgba(0,229,240,.3); background:rgba(142,170,179,.16); position:relative;}
        .debug-slider:after{content:""; position:absolute; width:14px; height:14px; left:2px; top:2px; background:var(--muted); transition:transform .18s ease, background .18s ease;}
        .debug-switch input:checked + .debug-slider:after{transform:translateX(18px); background:var(--yellow);}
        .debug-switch input:checked + .debug-slider{border-color:var(--yellow); box-shadow:0 0 12px rgba(255,196,0,.18);}
        .market{color:var(--green); font-weight:900; text-align:right; text-transform:uppercase;}
        .layout{display:grid; grid-template-columns:minmax(0,1.16fr) minmax(320px,.74fr) minmax(0,1.04fr); gap:18px; align-items:stretch;}
        .stack{display:grid; gap:18px; align-content:start;}
        .left-stack{grid-template-rows:auto auto;}
        .center-stack{grid-template-rows:300px 206px 174px;}
        .right-stack{grid-template-rows:auto auto; min-width:0; overflow:hidden;}
        .panel{padding:16px; min-width:0;}
        .panel-title{display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; color:#c8f8ff; text-transform:uppercase; font-size:14px; font-weight:900; letter-spacing:.02em;}
        .panel-title span:last-child{color:var(--cyan)}
        .chart-wrap{height:540px; overflow:hidden; background:radial-gradient(circle at 50% 10%, rgba(0,229,240,.06), rgba(0,8,11,.9) 56%); border:1px solid rgba(0,229,240,.22); box-shadow:inset 0 0 28px rgba(0,229,240,.045);}
        .chart-wrap .plotly-graph-div{width:100% !important; height:100% !important;}
        .hero{display:grid; place-items:center; text-align:center;}
        .hero-inner{width:100%; display:grid; justify-items:center; gap:8px;}
        .symbol{font-size:74px; font-weight:900; line-height:.9; text-shadow:0 0 18px rgba(255,255,255,.24);}
        .price{font-size:76px; color:#42f0ba; font-weight:900; line-height:.95; text-shadow:0 0 26px rgba(28,255,115,.36), 0 0 44px rgba(66,240,186,.18);}
        .change{font-size:22px; font-weight:900;}
        .signal{position:relative; text-align:center; padding:20px; display:grid; grid-template-columns:minmax(54px,70px) minmax(0,1fr) minmax(54px,70px); grid-template-rows:minmax(86px,1fr) auto; column-gap:10px; row-gap:14px; align-items:center;}
        .signal-content{position:relative; z-index:1; grid-column:2; grid-row:1; min-width:0; align-self:center;}
        .signal-icons{display:contents; pointer-events:none;}
        .signal-icon{width:70px; height:66px; opacity:.16; filter:drop-shadow(0 0 0 transparent); transition:opacity .2s ease, filter .2s ease; align-self:center; justify-self:center;}
        .signal-icon img{width:100%; height:100%; object-fit:contain;}
        .signal-icon.bull{grid-column:1; grid-row:1;}
        .signal-icon.bear{grid-column:3; grid-row:1;}
        .signal-icon.active{opacity:1; filter:drop-shadow(0 0 16px rgba(28,255,115,.44));}
        .signal-icon.bear.active{filter:drop-shadow(0 0 16px rgba(255,49,72,.42));}
        .signal span{color:#c8f8ff; text-transform:uppercase; font-weight:900; font-size:15px;}
        .signal strong{display:block; color:var(--green); font-size:clamp(28px, 2.35vw, 38px); line-height:1; margin-top:8px; text-shadow:0 0 18px rgba(28,255,115,.32); white-space:nowrap;}
        .signal strong.red{color:var(--red); text-shadow:0 0 18px rgba(255,49,72,.30);}
        .signal strong.yellow{color:var(--yellow); text-shadow:0 0 18px rgba(255,196,0,.24);}
        .bars{grid-column:1 / -1; grid-row:2; display:grid; grid-template-columns:repeat(6,1fr); gap:7px; margin-top:0;}
        .bars i{height:8px; background:rgba(142,170,179,.24); border-radius:1px;}
        .bars i.on{background:var(--green); box-shadow:0 0 12px rgba(28,255,115,.45);}
        .confidence{display:grid; grid-template-columns:132px 1fr; gap:22px; align-items:center;}
        .confidence-meter{display:grid; justify-items:center; gap:7px;}
        .confidence-label{color:#c8f8ff; text-transform:uppercase; font-size:11px; font-weight:900; letter-spacing:.06em;}
        .ring{height:118px; width:118px; border-radius:50%; display:grid; place-items:center; color:var(--text); font-size:30px; font-weight:900; background:conic-gradient(var(--green) calc(var(--score) * 1%), rgba(28,255,115,.16) 0); box-shadow:0 0 20px rgba(28,255,115,.18);}
        .ring span{height:82px; width:82px; border-radius:50%; display:grid; place-items:center; background:#061016;}
        .notes{margin:0; padding-left:24px; line-height:1.58; font-size:14px;}
        .notes li{padding-left:4px;}
        .notes li::marker{font-size:1.42em;}
        .notes li.green{color:var(--green); font-weight:800;}
        .notes li.red{color:var(--red); font-weight:800;}
        .market-grid{display:grid; grid-template-columns:minmax(0,1.16fr) minmax(320px,.74fr) minmax(0,1.04fr); gap:18px;}
        .market-grid .panel{min-height:170px;}
        .market-grid .panel:first-child{grid-column:1;}
        .market-grid .panel:nth-child(2){grid-column:3;}
        table{width:100%; border-collapse:collapse;}
        td,th{padding:9px 7px; border-bottom:1px solid rgba(142,170,179,.18); font-size:14px;}
        th{color:var(--muted); text-align:left; font-size:12px; text-transform:uppercase;}
        td:last-child,th:last-child{text-align:right;}
        .option-grid{display:grid; grid-template-columns:minmax(250px,1.08fr) minmax(170px,.72fr); gap:16px; min-width:0; overflow:hidden;}
        .setup-table{table-layout:fixed;}
        .setup-table td:first-child{width:34%; color:#dffcff;}
        .setup-table td:last-child{width:66%; white-space:normal; overflow-wrap:anywhere;}
        .trade-state{font-weight:900; text-transform:uppercase;}
        .panel-title .trade-state.trade{color:var(--green);}
        .panel-title .trade-state.no-trade{color:var(--red);}
        .option-grid table{min-width:0;}
        .ladder td{font-size:13px; padding:7px 6px;}
        .selected-short{outline:1px solid var(--red); color:var(--red); background:rgba(255,49,72,.08);}
        .selected-long{outline:1px solid var(--green); color:var(--green); background:rgba(28,255,115,.08);}
        .placeholder{color:var(--yellow); font-weight:900;}
        .pl-profile{height:136px; margin-top:14px; position:relative; border:1px solid rgba(0,229,240,.16); background:linear-gradient(180deg, rgba(2,11,14,.78), rgba(0,5,7,.7)); overflow:hidden;}
        .pl-profile:before{content:""; position:absolute; inset:12px; background:linear-gradient(rgba(142,170,179,.18) 1px, transparent 1px), linear-gradient(90deg, rgba(142,170,179,.16) 1px, transparent 1px); background-size:100% 50%,25% 100%;}
        .pl-line{position:absolute; left:28px; right:24px; top:22px; height:92px;}
        .pl-line svg{width:100%; height:100%; overflow:visible;}
        .radar-wrap{display:grid; justify-items:center; gap:6px;}
        .radar{height:112px; width:112px; border-radius:50%; margin:auto; position:relative; background:radial-gradient(circle, rgba(28,255,115,.95) 0 5px, transparent 6px), repeating-radial-gradient(circle, rgba(0,229,240,.28) 0 1px, transparent 1px 15px), conic-gradient(from 180deg, rgba(28,255,115,.38), transparent 35%, rgba(0,229,240,.15) 70%, transparent);}
        .radar:before,.radar:after{content:""; position:absolute; left:50%; top:0; bottom:0; border-left:1px solid rgba(0,229,240,.35);}
        .radar:after{transform:rotate(90deg);}
        .radar b{position:absolute; color:#8eaab3; font-size:10px; font-weight:900;}
        .radar .n{top:-2px; left:50%; transform:translateX(-50%);}
        .radar .e{right:5px; top:50%; transform:translateY(-50%);}
        .radar .s{bottom:-2px; left:50%; transform:translateX(-50%);}
        .radar .w{left:5px; top:50%; transform:translateY(-50%);}
        .radar-caption{color:var(--cyan); font-size:10px; text-transform:uppercase; font-weight:900; letter-spacing:.08em;}
        .snapshot-table{table-layout:fixed;}
        .snapshot-table td{white-space:nowrap;}
        .snapshot-table td:nth-child(2),.snapshot-table td:nth-child(4){text-align:right;}
        .snapshot-table td:nth-child(3){color:var(--muted); border-left:1px solid rgba(142,170,179,.18); padding-left:18px;}
        .green{color:var(--green); font-weight:900}.red{color:var(--red); font-weight:900}.yellow{color:var(--yellow); font-weight:900}.muted{color:var(--muted)}
        .tickerbar{display:flex; align-items:center; gap:34px; overflow:auto; white-space:nowrap; padding:12px 20px;}
        .tickerbar b{color:var(--cyan); margin-right:8px;}
        .err{color:var(--red); font-weight:900; font-size:18px;}
        @media (max-width: 980px){.layout{grid-template-columns:1fr 1fr}.layout>.left-stack{grid-column:1 / -1}.market-grid{grid-template-columns:1fr}.market-grid .panel:first-child,.market-grid .panel:nth-child(2){grid-column:auto}.chart-wrap{height:520px}.topbar{grid-template-columns:1fr}.controlbar{display:grid; justify-items:center}.market,.brand{text-align:center}.nav-panel{justify-self:center;justify-items:center}.market-readout{text-align:center}.nav-links{justify-content:center}.debug-form{justify-self:center;justify-content:center}.timeblock{justify-self:center;justify-content:center}.center-stack{grid-template-rows:260px 180px 156px}}
        @media (max-width: 760px){.shell{padding:10px}.layout{grid-template-columns:1fr}.option-grid,.market-grid{grid-template-columns:1fr}.price,.symbol{font-size:48px}.confidence{grid-template-columns:1fr}.ring{margin:auto}.chart-wrap{height:430px}}
    </style>
</head>
<body>
<main class="shell">
    <header class="topbar">
        <div class="timeblock">
            <span class="clockmark">TIME</span>
            <span>{{ data.header_time }}</span>
            <span>{{ data.header_date }}</span>
            <span>{{ data.header_weekday }}</span>
        </div>
        <div class="brand">
            <h1>CashFlowArc Terminal</h1>
        </div>
        <div class="nav-panel">
            <div class="market-readout"><b class="{{ data.market_status_class }}">{{ data.market_status }}</b>{{ data.market_hours }}</div>
        </div>
    </header>
    <section class="controlbar">
        <nav class="nav-links">
            <a class="nav-link active" href="/terminal">Modern Terminal</a>
            <a class="nav-link" href="/gex">SPX GEX</a>
            <a class="nav-link" href="/option-chain">Option Chain</a>
            <a class="nav-link" href="/simulator">Simulator</a>
        </nav>
        <form class="debug-form" method="post" action="/settings">
            <input type="hidden" name="chart_interval" value="{{ data.chart_interval }}">
            <span>Refresh</span>
            <input class="refresh-input" type="number" min="15" max="3600" step="1" name="refresh_interval" value="{{ data.refresh_interval }}">
            <input type="hidden" name="debug_mode" value="0">
            <label class="debug-switch">
                <span>Debug</span>
                <input type="checkbox" name="debug_mode" value="1" {% if data.debug_mode %}checked{% endif %}>
                <span class="debug-slider"></span>
            </label>
            <span class="debug-picker {{ 'active' if data.debug_mode else '' }}">
                <input type="date" name="debug_trade_date" value="{{ data.debug_control_date }}" max="{{ data.debug_max_date }}" {% if not data.debug_mode %}disabled{% endif %}>
                <button class="debug-picker-button" type="button" aria-label="Open debug date picker" {% if not data.debug_mode %}disabled{% endif %}></button>
            </span>
            <span class="debug-picker {{ 'active' if data.debug_mode else '' }}">
                <input type="time" name="debug_time" step="60" value="{{ data.debug_control_time }}" {% if not data.debug_mode %}disabled{% endif %}>
                <button class="debug-picker-button" type="button" aria-label="Open debug time picker" {% if not data.debug_mode %}disabled{% endif %}></button>
            </span>
        </form>
    </section>

    {% if data.error %}
    <section class="panel"><div class="err">{{ data.error }}</div></section>
    {% else %}
    <section class="layout">
        <div class="stack left-stack">
            <section class="panel">
                <div class="panel-title"><span>SPX {{ data.chart_interval }}</span><span>Updated {{ data.last_update_timestamp }}</span></div>
                <div class="chart-wrap">{{ data.chart_html|safe }}</div>
            </section>
        </div>

        <div class="stack center-stack">
            <section class="panel hero">
                <div class="hero-inner">
                    <div class="muted">S&P 500 INDEX</div>
                    <div class="symbol">SPX</div>
                    <div class="price">{{ data.price_display }}</div>
                    <div class="change {{ data.daily_change_class }}">{{ data.daily_change }} ({{ data.daily_change_pct }}%)</div>
                </div>
            </section>
            <section class="panel signal">
                <div class="signal-icons">
                    <div class="signal-icon bull {{ 'active' if data.bullish else '' }}" aria-hidden="true">
                        <img src="{{ url_for('static', filename='bull-signal.png') }}" alt="">
                    </div>
                    <div class="signal-icon bear {{ 'active' if data.bearish else '' }}" aria-hidden="true">
                        <img src="{{ url_for('static', filename='bear-signal.png') }}" alt="">
                    </div>
                </div>
                <div class="signal-content">
                    <span>TRADE SIGNAL</span>
                    <strong class="{{ 'green' if data.bullish else ('red' if data.bearish else 'yellow') }}">{{ data.bias_label }}</strong>
                </div>
                <div class="bars">
                    {% for bar_on in data.signal_bars %}
                    <i class="{{ 'on' if bar_on else '' }}"></i>
                    {% endfor %}
                </div>
            </section>
            <section class="panel confidence">
                <div class="confidence-meter">
                    <div class="ring" style="--score:{{ data.confidence }}"><span>{{ data.confidence }}%</span></div>
                    <div class="confidence-label">Confidence</div>
                </div>
                <ul class="notes">
                    {% for note in data.setup_notes %}
                    <li class="{{ note.class }}">{{ note.label }}</li>
                    {% endfor %}
                </ul>
            </section>
        </div>

        <div class="stack right-stack">
            <section class="panel">
                <div class="panel-title"><span>Trade Setup</span><span class="trade-state {{ 'no-trade' if data.trade == 'NO TRADE' else 'trade' }}">{{ data.trade }}</span></div>
                <div class="option-grid">
                    <table class="setup-table">
                        <tr><td>Type</td><td class="{{ 'green' if data.trade != 'NO TRADE' else 'yellow' }}">{{ data.trade_type }}</td></tr>
                        <tr><td>Short Strike</td><td>{{ data.short_strike }}</td></tr>
                        <tr><td>Long Strike</td><td>{{ data.long_strike }}</td></tr>
                        <tr><td>Credit</td><td class="placeholder">{{ data.credit }}</td></tr>
                        <tr><td>Delta (Net)</td><td class="placeholder">Needs option Greeks</td></tr>
                        <tr><td>Max Profit</td><td class="placeholder">{{ data.max_profit }}</td></tr>
                        <tr><td>Max Risk</td><td class="placeholder">{{ data.max_risk }}</td></tr>
                        <tr><td>POP</td><td class="placeholder">Needs probability model</td></tr>
                        <tr><td>Breakeven</td><td class="placeholder">Needs option pricing</td></tr>
                        <tr><td>Net GEX</td><td class="{{ data.net_gex_signal_class }}">{{ data.net_gex_billions }}</td></tr>
                    </table>
                    <table class="ladder">
                        <tr><th>Strike</th><th>Put</th><th>Call</th></tr>
                        <tr><td>{{ data.price + 30 }}</td><td class="placeholder">N/A</td><td class="placeholder">N/A</td></tr>
                        <tr><td>{{ data.price + 20 }}</td><td class="placeholder">N/A</td><td class="placeholder">N/A</td></tr>
                        <tr><td>{{ data.price + 10 }}</td><td class="placeholder">N/A</td><td class="placeholder">N/A</td></tr>
                        <tr class="selected-short"><td>{{ data.short_strike }}</td><td class="placeholder">N/A</td><td class="placeholder">N/A</td></tr>
                        <tr class="selected-long"><td>{{ data.long_strike }}</td><td class="placeholder">N/A</td><td class="placeholder">N/A</td></tr>
                        <tr><td>{{ data.price - 30 }}</td><td class="placeholder">N/A</td><td class="placeholder">N/A</td></tr>
                    </table>
                </div>
                <div class="pl-profile">
                    <div class="pl-line">
                        <svg viewBox="0 0 500 100" preserveAspectRatio="none" aria-hidden="true">
                            <polyline points="0,82 80,82 170,12 320,12 420,76 500,76" fill="none" stroke="#1cff73" stroke-width="4"/>
                            <polyline points="0,82 80,82 170,12" fill="none" stroke="#ff3148" stroke-width="4"/>
                            <polyline points="420,76 500,76" fill="none" stroke="#ff3148" stroke-width="4"/>
                        </svg>
                    </div>
                </div>
            </section>
        </div>
    </section>
    <section class="market-grid">
        <section class="panel">
            <div class="panel-title"><span>Market Snapshot</span><span></span></div>
            <table class="snapshot-table">
                <tr><td>VWAP Proxy</td><td>{{ data.vwap }}</td><td>Prev Day High</td><td>{{ data.prev_day_high }}</td></tr>
                <tr><td>Price vs VWAP</td><td class="{{ 'green' if data.price > data.vwap else 'red' }}">{{ data.vwap_distance_pct }}%</td><td>Prev Day Low</td><td>{{ data.prev_day_low }}</td></tr>
                <tr><td>Open</td><td>{{ data.open_price }}</td><td>Prev Day Open</td><td>{{ data.prev_day_open }}</td></tr>
                <tr><td>Day High</td><td>{{ data.current_day_high }}</td><td>Prev Day Close</td><td>{{ data.prev_day_close }}</td></tr>
                <tr><td>Day Low</td><td>{{ data.current_day_low }}</td><td>SPY</td><td>{{ data.spy_price }}</td></tr>
            </table>
        </section>
        <section class="panel">
            <div class="panel-title"><span>Alerts & Checklist</span><span>All systems nominal</span></div>
            <div style="display:grid; grid-template-columns:1fr 128px; gap:18px; align-items:center;">
                <table>
                    {% for item in data.checklist %}
                    <tr><td>{{ item.label }}</td><td class="{{ item.class }}">{{ item.status }}</td></tr>
                    {% endfor %}
                </table>
                <div class="radar-wrap" aria-hidden="true">
                    <div class="radar"><b class="n">N</b><b class="e">E</b><b class="s">S</b><b class="w">W</b></div>
                    <div class="radar-caption">Range Scan</div>
                </div>
            </div>
        </section>
    </section>
    {% endif %}

    <footer class="tickerbar">
        <span><b>WATCHLIST</b></span>
        <span>SPX <span class="green">{{ data.price }}</span></span>
        <span>SPY <span class="green">{{ data.spy_price }}</span></span>
        <span class="muted">Refresh {{ data.refresh_interval }}s</span>
    </footer>
</main>
<script>
document.querySelectorAll('.debug-form').forEach(function(form) {
    form.addEventListener('change', function() {
        fetch('/settings', { method: 'POST', body: new FormData(form) })
            .then(function() { window.location.reload(); })
            .catch(function() {});
    });
});
document.querySelectorAll('.debug-picker-button').forEach(function(button) {
    button.addEventListener('click', function(event) {
        event.preventDefault();
        var wrapper = button.closest('.debug-picker');
        var input = wrapper ? wrapper.querySelector('input') : null;
        if (!input || input.disabled) return;
        input.focus();
        if (typeof input.showPicker === 'function') {
            try {
                input.showPicker();
                return;
            } catch (err) {}
        }
        input.click();
    });
});
setTimeout(function(){ window.location.reload(); }, Math.max(15, Number({{ data.refresh_interval }})) * 1000);
</script>
</body>
</html>
"""

HUD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>CashFlowArc HUD</title>
    <link rel="icon" href="{{ url_for('favicon_svg', v=favicon_version) }}" sizes="any" type="image/svg+xml">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        :root{--bg:#010303;--panel:rgba(1,10,12,.68);--line:#00e5f0;--soft:rgba(0,229,240,.36);--text:#f4fdff;--muted:#8ab1ba;--green:#1cff73;--red:#ff3148;--yellow:#ffc400}
        *{box-sizing:border-box}
        body{margin:0; min-height:100vh; color:var(--text); font-family:Segoe UI, Arial, sans-serif; background:#010303;}
        .hud{min-height:100vh; display:grid; grid-template-rows:auto 1fr auto; gap:12px; padding:14px; background:radial-gradient(circle at 50% 50%, rgba(0,229,240,.035) 0 22%, rgba(1,3,3,.3) 38%, #010303 72%);}
        .top,.bottom,.panel{position:relative; border:1px solid var(--soft); background:linear-gradient(180deg, rgba(2,15,18,.78), rgba(0,5,6,.62)); box-shadow:0 0 22px rgba(0,229,240,.13), inset 0 0 18px rgba(0,229,240,.04); clip-path:polygon(18px 0,calc(100% - 18px) 0,100% 18px,100% calc(100% - 18px),calc(100% - 18px) 100%,18px 100%,0 calc(100% - 18px),0 18px);}
        .top:before,.bottom:before,.panel:before{content:""; position:absolute; inset:7px; pointer-events:none; border-top:1px solid rgba(0,229,240,.4); border-bottom:1px solid rgba(0,229,240,.13);}
        .top{display:grid; grid-template-columns:minmax(260px,1fr) auto minmax(260px,1fr); gap:18px; align-items:center; padding:8px 18px;}
        .time{font-size:18px; font-weight:900}.title{text-align:center}.title h1{margin:0; font-size:34px; line-height:.95; text-shadow:0 0 18px rgba(255,255,255,.2)}.title p{margin:5px 0 0; color:#b5e9f0; text-transform:uppercase}.market{text-align:right; color:var(--green); font-weight:900; font-size:20px;}
        .tabs{display:flex; gap:8px; justify-content:center; flex-wrap:wrap; margin-top:8px;}
        .tabs a{color:var(--muted); text-decoration:none; padding:7px 10px; border:1px solid var(--soft); font-size:12px; font-weight:800; background:#031014;}
        .tabs a.active{color:var(--text); border-color:var(--line)}
        .grid{display:grid; grid-template-columns:370px minmax(520px,1fr) 370px; gap:16px; min-height:0;}
        .side{display:grid; align-content:start; gap:14px; min-width:0;}
        .panel{padding:14px; min-width:0;}
        .ar-space{position:relative; min-height:455px; border:0; background:radial-gradient(circle at center, rgba(0,229,240,.035), rgba(0,0,0,0) 38%);}
        .ar-space:before,.ar-space:after,.reticle-a,.reticle-b{content:""; position:absolute; width:82px; height:82px; border-color:var(--line); opacity:.9;}
        .ar-space:before{left:4%; top:12%; border-left:2px solid; border-top:2px solid}.ar-space:after{right:4%; bottom:12%; border-right:2px solid; border-bottom:2px solid}
        .reticle-a{right:4%; top:12%; border-right:2px solid; border-top:2px solid}.reticle-b{left:4%; bottom:12%; border-left:2px solid; border-bottom:2px solid}
        .ar-guide{position:absolute; left:50%; top:50%; width:min(58vw,760px); height:min(44vh,430px); transform:translate(-50%,-50%); pointer-events:none;}
        .ar-guide:before,.ar-guide:after{content:""; position:absolute; width:86px; height:86px; border-color:var(--line); opacity:.9}
        .ar-guide:before{left:0; top:0; border-left:2px solid; border-top:2px solid}.ar-guide:after{right:0; bottom:0; border-right:2px solid; border-bottom:2px solid}
        .panel-title{display:flex; justify-content:space-between; gap:10px; color:var(--muted); text-transform:uppercase; font-size:13px; font-weight:900; margin-bottom:10px;}
        .chart-mini{height:220px; overflow:hidden; background:#03080a; border:1px solid rgba(0,229,240,.12);}
        .chart-mini .plotly-graph-div{width:100% !important; height:100% !important;}
        .signal{text-align:center}.signal strong{display:block; color:var(--green); font-size:34px; line-height:1; margin-top:6px; text-shadow:0 0 18px rgba(28,255,115,.35);}
        .bars{display:grid; grid-template-columns:repeat(6,1fr); gap:6px; margin-top:12px}.bars i{height:6px; background:rgba(138,177,186,.2)}.bars i.on{background:var(--green); box-shadow:0 0 10px rgba(28,255,115,.45)}
        .ring{height:82px; width:82px; border-radius:50%; background:conic-gradient(var(--green) calc(var(--score) * 1%), rgba(28,255,115,.16) 0); display:grid; place-items:center; font-size:22px; font-weight:900; box-shadow:0 0 18px rgba(28,255,115,.2);}
        .ring span{height:58px; width:58px; border-radius:50%; display:grid; place-items:center; background:#041014;}
        .confidence{display:grid; grid-template-columns:86px 1fr; gap:10px; align-items:center;}
        .hud-lower{display:grid; grid-template-columns:minmax(380px,.74fr) minmax(520px,1fr); gap:16px; margin-top:12px;}
        .placeholder{color:var(--yellow); font-weight:900;}
        .pl-profile{height:90px; margin-top:8px; position:relative; border:1px solid rgba(0,229,240,.16); background:linear-gradient(180deg, rgba(2,11,14,.78), rgba(0,5,7,.7)); overflow:hidden;}
        .pl-profile:before{content:""; position:absolute; inset:12px; background:linear-gradient(rgba(142,170,179,.18) 1px, transparent 1px), linear-gradient(90deg, rgba(142,170,179,.16) 1px, transparent 1px); background-size:100% 50%,25% 100%;}
        .pl-profile svg{position:absolute; left:22px; right:22px; top:10px; width:calc(100% - 44px); height:66px; overflow:visible;}
        .radar{height:112px; width:112px; border-radius:50%; margin:auto; position:relative; background:radial-gradient(circle, rgba(28,255,115,.95) 0 5px, transparent 6px), repeating-radial-gradient(circle, rgba(0,229,240,.28) 0 1px, transparent 1px 15px), conic-gradient(from 180deg, rgba(28,255,115,.38), transparent 35%, rgba(0,229,240,.15) 70%, transparent);}
        .radar:before,.radar:after{content:""; position:absolute; left:50%; top:0; bottom:0; border-left:1px solid rgba(0,229,240,.35);}
        .radar:after{transform:rotate(90deg);}
        ul{margin:0; padding-left:18px; line-height:1.55; font-size:13px;}
        table{width:100%; border-collapse:collapse}td{padding:6px 4px; border-bottom:1px solid rgba(143,176,184,.2); font-size:13px;}td:last-child{text-align:right}
        .green{color:var(--green); font-weight:900}.red{color:var(--red); font-weight:900}.yellow{color:var(--yellow); font-weight:900}.muted{color:var(--muted)}
        .bottom{display:flex; gap:26px; align-items:center; overflow:auto; white-space:nowrap; padding:10px 18px}.bottom b{color:var(--line); margin-right:6px}
        .err{color:var(--red); font-weight:900; font-size:18px}
        @media (max-width: 1280px){.grid,.hud-lower{grid-template-columns:1fr}.ar-space{min-height:420px}.top{grid-template-columns:1fr}.market,.time{text-align:center}}
    </style>
</head>
<body>
<main class="hud">
    <header class="top">
        <div class="time">{{ data.time }}</div>
        <div class="title">
            <h1>CashFlowArc HUD</h1>
            <p>S&P 500 Index - SPX</p>
            <nav class="tabs">
                <a class="active" href="/terminal">Modern Terminal</a>
                <a href="/gex">SPX GEX</a>
                <a href="/option-chain">Option Chain</a>
                <a href="/simulator">Simulator</a>
            </nav>
        </div>
        <div class="market">MARKET DATA LIVE</div>
    </header>

    {% if data.error %}
    <section class="panel"><div class="err">{{ data.error }}</div></section>
    {% else %}
    <section class="grid">
        <aside class="side">
            <section class="panel">
                <div class="panel-title"><span>SPX {{ data.chart_interval }}</span><span>{{ data.price }}</span></div>
                <div class="chart-mini">{{ data.chart_html|safe }}</div>
            </section>
            <section class="panel signal">
                <span>Trade Signal</span>
                <strong>{{ data.bias_label }}</strong>
                <div class="bars">
                    {% for bar_on in data.signal_bars %}
                    <i class="{{ 'on' if bar_on else '' }}"></i>
                    {% endfor %}
                </div>
            </section>
            <section class="panel confidence">
                <div class="ring" style="--score:{{ data.confidence }}"><span>{{ data.confidence }}%</span></div>
                <ul>
                    {% for note in data.setup_notes %}
                    <li>{{ note.label }}</li>
                    {% endfor %}
                </ul>
            </section>
        </aside>

        <section class="ar-space" aria-label="Transparent AR alignment area">
            <span class="reticle-a"></span>
            <span class="reticle-b"></span>
            <div class="ar-guide"></div>
        </section>

        <aside class="side">
            <section class="panel">
                <div class="panel-title"><span>Trade Setup</span><span>{{ data.trade_type }}</span></div>
                <table>
                    <tr><td>Short Strike</td><td>{{ data.short_strike }}</td></tr>
                    <tr><td>Long Strike</td><td>{{ data.long_strike }}</td></tr>
                    <tr><td>Credit</td><td class="placeholder">{{ data.credit }}</td></tr>
                    <tr><td>Delta (Net)</td><td class="placeholder">Needs option Greeks</td></tr>
                    <tr><td>Max Profit</td><td class="placeholder">{{ data.max_profit }}</td></tr>
                    <tr><td>Max Risk</td><td class="placeholder">{{ data.max_risk }}</td></tr>
                    <tr><td>POP</td><td class="placeholder">Needs probability model</td></tr>
                    <tr><td>Breakeven</td><td class="placeholder">Needs option pricing</td></tr>
                    <tr><td>Net GEX</td><td>{{ data.net_gex_billions }}</td></tr>
                </table>
                <div class="pl-profile">
                    <svg viewBox="0 0 500 100" preserveAspectRatio="none" aria-hidden="true">
                        <polyline points="0,82 80,82 170,12 320,12 420,76 500,76" fill="none" stroke="#1cff73" stroke-width="4"/>
                        <polyline points="0,82 80,82 170,12" fill="none" stroke="#ff3148" stroke-width="4"/>
                        <polyline points="420,76 500,76" fill="none" stroke="#ff3148" stroke-width="4"/>
                    </svg>
                </div>
            </section>
        </aside>
    </section>
    <section class="hud-lower">
        <section class="panel">
            <div class="panel-title"><span>Market Snapshot</span><span>Oracle</span></div>
            <table>
                <tr><td>VWAP Proxy</td><td>{{ data.vwap }}</td><td>SPY {{ data.spy_price }}</td></tr>
                <tr><td>Price vs VWAP</td><td class="{{ 'green' if data.price > data.vwap else 'red' }}">{{ data.vwap_distance_pct }}%</td><td>Open {{ data.open_price }}</td></tr>
                <tr><td>Day High</td><td>{{ data.current_day_high }}</td><td>Day Low {{ data.current_day_low }}</td></tr>
                <tr><td>Prev High</td><td>{{ data.prev_day_high }}</td><td>Prev Low {{ data.prev_day_low }}</td></tr>
            </table>
        </section>
        <section class="panel">
            <div class="panel-title"><span>Alerts & Checklist</span><span>All systems nominal</span></div>
            <div style="display:grid; grid-template-columns:1fr 128px; gap:18px; align-items:center;">
                <table>
                    {% for item in data.checklist %}
                    <tr><td>{{ item.label }}</td><td class="{{ item.class }}">{{ item.status }}</td></tr>
                    {% endfor %}
                </table>
                <div class="radar" aria-hidden="true"></div>
            </div>
        </section>
    </section>
    {% endif %}

    <footer class="bottom">
        <span><b>WATCHLIST</b></span>
        <span>SPX <span class="green">{{ data.price }}</span></span>
        <span>SPY <span class="green">{{ data.spy_price }}</span></span>
        <span class="muted">Refresh {{ data.refresh_interval }}s</span>
    </footer>
</main>
<script>
setTimeout(function(){ window.location.reload(); }, Math.max(15, Number({{ data.refresh_interval }})) * 1000);
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
    <link rel="icon" href="{{ url_for('favicon_svg', v=favicon_version) }}" sizes="any" type="image/svg+xml">
    <meta http-equiv="refresh" content="{{ data.refresh_interval }}">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
        <style>
        :root{
            --panel:rgba(11, 22, 39, 0.84);
            --panel-2:rgba(15, 30, 52, 0.92);
            --border:rgba(148, 179, 255, 0.14);
            --text:#edf4ff;
            --muted:#8fa6c7;
            --blue:#7cc4ff;
            --green:#2ad18b;
            --orange:#ffb14d;
            --shadow:0 20px 50px rgba(0, 0, 0, 0.34);
        }
        *{box-sizing:border-box}
        body{
            margin:0;
            font-family:"Aptos","Segoe UI Variable","Segoe UI",sans-serif;
            background:
                radial-gradient(circle at top left, rgba(62, 120, 255, 0.16), transparent 30%),
                radial-gradient(circle at top right, rgba(42, 209, 139, 0.1), transparent 22%),
                linear-gradient(180deg, #06111d 0%, #091627 55%, #07111f 100%);
            color:var(--text);
        }
        .wrap{max-width:1840px; margin:0 auto; padding:24px;}
        .topbar{
            display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap;
            gap:18px; margin-bottom:20px; padding:22px 24px;
            background:linear-gradient(180deg, rgba(15, 31, 52, 0.92), rgba(8, 18, 32, 0.92));
            border:1px solid var(--border); border-radius:24px; box-shadow:var(--shadow);
        }
        .title h1{margin:0; font-family:"Bahnschrift","Aptos Display","Segoe UI",sans-serif; font-size:34px; letter-spacing:0}
        .title p{margin:8px 0 0; color:var(--muted); font-size:14px; line-height:1.5}
        .top-right{margin-left:auto; display:flex; align-items:center; gap:12px; flex-wrap:wrap; justify-content:flex-end;}
        .nav-links{display:flex; gap:6px; align-items:center; flex-wrap:wrap; padding:6px; border-radius:999px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.05);}
        .nav-link{color:var(--muted); text-decoration:none; font-size:13px; font-weight:600; padding:10px 14px; border-radius:999px; transition:all .18s ease;}
        .nav-link:hover{color:var(--text); background:rgba(255,255,255,0.04)}
        .nav-link.active{color:#04101c; background:linear-gradient(135deg, #8ed4ff, #d7f0ff); box-shadow:0 8px 22px rgba(124, 196, 255, 0.28)}
        .card{background:linear-gradient(180deg, rgba(11, 22, 39, 0.92), rgba(8, 17, 31, 0.92)); border:1px solid var(--border); border-radius:24px; padding:18px; box-shadow:var(--shadow);}
        .controls{display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:12px;}
        .control-form{display:flex; align-items:center; gap:10px; flex-wrap:wrap; background:rgba(255,255,255,0.035); border:1px solid rgba(255,255,255,0.05); border-radius:16px; padding:10px 12px;}
        .control-label{font-size:11px; color:var(--muted); font-weight:700; letter-spacing:0.08em; text-transform:uppercase}
        .text-input{width:90px; background:rgba(6, 14, 26, 0.82); color:var(--text); border:1px solid rgba(148, 179, 255, 0.18); border-radius:12px; padding:10px 12px; font-size:13px;}
        .text-input:focus{outline:none; border-color:rgba(124, 196, 255, 0.56); box-shadow:0 0 0 4px rgba(124, 196, 255, 0.12)}
        .status-pill{padding:11px 16px; border-radius:999px; font-weight:700; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;}
        .enter{color:#042414; background:linear-gradient(135deg, #39e3a0, #9af1c9); box-shadow:0 12px 24px rgba(42, 209, 139, 0.22)}
        .no{color:#350b0b; background:linear-gradient(135deg, #ff8f8f, #ffc0c0); box-shadow:0 12px 24px rgba(255, 107, 107, 0.2)}
        .metrics{display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:16px;}
        @media (max-width: 960px){ .metrics{grid-template-columns:repeat(2,1fr);} }
        @media (max-width: 640px){ .metrics{grid-template-columns:1fr;} .wrap{padding:16px} .topbar{padding:18px} .title h1{font-size:28px} }
        .metric{background:linear-gradient(180deg, rgba(18, 34, 58, 0.92), rgba(12, 24, 42, 0.94)); border:1px solid rgba(148, 179, 255, 0.08); border-radius:20px; padding:16px; position:relative; overflow:hidden;}
        .metric::before{content:""; position:absolute; inset:0 auto auto 0; width:100%; height:2px; background:linear-gradient(90deg, rgba(124, 196, 255, 0.7), transparent 60%);}
        .metric .label{font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700; letter-spacing:0.12em}
        .metric .value{margin-top:10px; font-size:28px; font-weight:700; font-family:"Bahnschrift","Aptos Display","Segoe UI",sans-serif; letter-spacing:0}
        .metric .sub{margin-top:6px; font-size:12px; color:var(--muted); line-height:1.45}
        .chart-wrap{min-height:540px; background:linear-gradient(180deg, rgba(14, 27, 46, 0.96), rgba(12, 24, 42, 0.92)); border:1px solid rgba(148, 179, 255, 0.08); border-radius:20px; overflow:hidden;}
        .chart-wrap .plotly-graph-div{width:100% !important; height:540px !important;}
        .error{font-size:18px; color:#ff9b9b; font-weight:700}
        .notes{margin-top:16px; font-size:12px; color:var(--muted); line-height:1.6; background:rgba(255,255,255,0.025); border:1px solid rgba(255,255,255,0.04); border-radius:18px; padding:14px 16px}
    </style>

</head>
<body>
<div class="wrap">
    <div class="topbar">
        <div class="title">
            <h1>SPX 0DTE Gamma Exposure</h1>
            <p>{{ data.subtitle }}</p>
        </div>
        <div class="top-right">
            <div class="nav-links">
                <a class="nav-link" href="/terminal">Modern Terminal</a>
                <a class="nav-link active" href="/gex">SPX GEX</a>
                <a class="nav-link" href="/option-chain">Option Chain</a>
                <a class="nav-link" href="/simulator">Simulator</a>
            </div>
            <form id="gex-settings-form" method="post" action="/settings" class="control-form">
                <span class="control-label">Refresh Interval</span>
                <input id="refresh_interval" class="text-input" type="number" min="15" max="3600" step="1" name="refresh_interval" value="{{ data.refresh_interval }}">
                <input type="hidden" name="chart_interval" value="{{ data.chart_interval }}">
            </form>
            <div class="status-pill {{ 'enter' if data.trade != 'NO TRADE' else 'no' }}">
                {{ 'ENTER TRADE' if data.trade != 'NO TRADE' else 'NO TRADE' }}
            </div>
        </div>
    </div>

    <div class="card">
        {% if data.error %}
        <div class="error">{{ data.error }}</div>
        {% else %}
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
            Uses the SPX expiration shown above. During market hours it prefers the current session's expiration. After 4:00 PM Eastern it prefers the next available expiration, but falls back to the nearest chain with usable near-spot open interest if Yahoo has not populated the forward chain yet. Gamma exposure is estimated from open interest, implied volatility, and Black-Scholes gamma with time capped at a minimum of {{ data.min_time_minutes }} minute(s) to avoid a zero-time singularity.
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

OPTION_CHAIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>CashFlowArc</title>
    <link rel="icon" href="{{ url_for('favicon_svg', v=favicon_version) }}" sizes="any" type="image/svg+xml">
    <meta http-equiv="refresh" content="{{ data.refresh_interval }}">
    <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
        :root{
            --panel:rgba(11, 22, 39, 0.84);
            --panel-2:rgba(15, 30, 52, 0.92);
            --border:rgba(148, 179, 255, 0.14);
            --text:#edf4ff;
            --muted:#8fa6c7;
            --green:#53e0a4;
            --red:#ff9d9d;
            --shadow:0 20px 50px rgba(0, 0, 0, 0.34);
        }
        *{box-sizing:border-box}
        body{margin:0; font-family:"Aptos","Segoe UI Variable","Segoe UI",sans-serif; background:radial-gradient(circle at top left, rgba(62, 120, 255, 0.16), transparent 30%), linear-gradient(180deg, #06111d 0%, #091627 55%, #07111f 100%); color:var(--text);}
        .wrap{max-width:1840px; margin:0 auto; padding:24px;}
        .topbar{display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:18px; margin-bottom:20px; padding:22px 24px; background:linear-gradient(180deg, rgba(15, 31, 52, 0.92), rgba(8, 18, 32, 0.92)); border:1px solid var(--border); border-radius:24px; box-shadow:var(--shadow);}
        .title h1{margin:0; font-family:"Bahnschrift","Aptos Display","Segoe UI",sans-serif; font-size:34px; letter-spacing:0}
        .title p{margin:8px 0 0; color:var(--muted); font-size:14px; line-height:1.5}
        .top-right{margin-left:auto; display:flex; align-items:center; gap:12px; flex-wrap:wrap; justify-content:flex-end;}
        .nav-links{display:flex; gap:6px; align-items:center; flex-wrap:wrap; padding:6px; border-radius:999px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.05);}
        .nav-link{color:var(--muted); text-decoration:none; font-size:13px; font-weight:600; padding:10px 14px; border-radius:999px; transition:all .18s ease;}
        .nav-link:hover{color:var(--text); background:rgba(255,255,255,0.04)}
        .nav-link.active{color:#04101c; background:linear-gradient(135deg, #8ed4ff, #d7f0ff); box-shadow:0 8px 22px rgba(124, 196, 255, 0.28)}
        .card{background:linear-gradient(180deg, rgba(11, 22, 39, 0.92), rgba(8, 17, 31, 0.92)); border:1px solid var(--border); border-radius:24px; padding:18px; box-shadow:var(--shadow);}
        .controls{display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:14px;}
        .control-form{display:flex; align-items:center; gap:10px; flex-wrap:wrap; background:rgba(255,255,255,0.035); border:1px solid rgba(255,255,255,0.05); border-radius:16px; padding:10px 12px;}
        .control-label{font-size:11px; color:var(--muted); font-weight:700; letter-spacing:0.08em; text-transform:uppercase}
        .text-input{width:90px; background:rgba(6, 14, 26, 0.82); color:var(--text); border:1px solid rgba(148, 179, 255, 0.18); border-radius:12px; padding:10px 12px; font-size:13px;}
        .text-input:focus{outline:none; border-color:rgba(124, 196, 255, 0.56); box-shadow:0 0 0 4px rgba(124, 196, 255, 0.12)}
        .status-pill{padding:11px 16px; border-radius:999px; font-weight:700; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;}
        .enter{color:#042414; background:linear-gradient(135deg, #39e3a0, #9af1c9); box-shadow:0 12px 24px rgba(42, 209, 139, 0.22)}
        .no{color:#350b0b; background:linear-gradient(135deg, #ff8f8f, #ffc0c0); box-shadow:0 12px 24px rgba(255, 107, 107, 0.2)}
        .metrics{display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px;}
        @media (max-width: 1100px){ .metrics{grid-template-columns:repeat(2,1fr);} }
        @media (max-width: 640px){ .metrics{grid-template-columns:1fr;} .wrap{padding:16px} .topbar{padding:18px} .title h1{font-size:28px} }
        .metric{background:linear-gradient(180deg, rgba(18, 34, 58, 0.92), rgba(12, 24, 42, 0.94)); border:1px solid rgba(148, 179, 255, 0.08); border-radius:20px; padding:16px; position:relative; overflow:hidden;}
        .metric::before{content:""; position:absolute; inset:0 auto auto 0; width:100%; height:2px; background:linear-gradient(90deg, rgba(124, 196, 255, 0.7), transparent 60%);}
        .metric .label{font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700; letter-spacing:0.12em}
        .metric .value{margin-top:10px; font-size:28px; font-weight:700; font-family:"Bahnschrift","Aptos Display","Segoe UI",sans-serif; letter-spacing:0}
        .metric .sub{margin-top:6px; font-size:12px; color:var(--muted); line-height:1.45}
        .table-wrap{overflow:auto; border:1px solid rgba(148, 179, 255, 0.08); border-radius:20px; background:linear-gradient(180deg, rgba(14, 27, 46, 0.96), rgba(12, 24, 42, 0.92)); max-height:72vh; box-shadow:inset 0 1px 0 rgba(255,255,255,0.02);}
        table{width:100%; border-collapse:separate; border-spacing:0}
        th, td{padding:12px 10px; border-bottom:1px solid rgba(148, 179, 255, 0.08); font-size:12px; white-space:nowrap; text-align:right;}
        th{position:sticky; top:0; z-index:1; background:rgba(7, 17, 31, 0.96); color:var(--muted); font-weight:700; letter-spacing:0.06em; text-transform:uppercase; backdrop-filter:blur(10px);}
        tbody tr:nth-child(even){background:rgba(255,255,255,0.015)}
        tbody tr:hover{background:rgba(124, 196, 255, 0.06)}
        td.strike, th.strike{text-align:center; font-weight:700; color:#f3f7ff; background:rgba(255,255,255,0.02)}
        td.call-last, td.call-bid, td.call-ask, td.call-oi, td.call-vol, td.call-iv{color:var(--green)}
        td.put-last, td.put-bid, td.put-ask, td.put-oi, td.put-vol, td.put-iv{color:var(--red)}
        .error{font-size:18px; color:#ff9b9b; font-weight:700}
        .notes{margin-top:16px; font-size:12px; color:var(--muted); line-height:1.6; background:rgba(255,255,255,0.025); border:1px solid rgba(255,255,255,0.04); border-radius:18px; padding:14px 16px}
    </style>

</head>
<body>
<div class="wrap">
    <div class="topbar">
        <div class="title">
            <h1>SPX Option Chain</h1>
            <p>{{ data.subtitle }}</p>
        </div>
        <div class="top-right">
            <div class="nav-links">
                <a class="nav-link" href="/terminal">Modern Terminal</a>
                <a class="nav-link" href="/gex">SPX GEX</a>
                <a class="nav-link active" href="/option-chain">Option Chain</a>
                <a class="nav-link" href="/simulator">Simulator</a>
            </div>
            <form id="option-settings-form" method="post" action="/settings" class="control-form">
                <span class="control-label">Refresh Interval</span>
                <input id="refresh_interval" class="text-input" type="number" min="15" max="3600" step="1" name="refresh_interval" value="{{ data.refresh_interval }}">
                <input type="hidden" name="chart_interval" value="{{ data.chart_interval }}">
            </form>
            <div class="status-pill {{ 'enter' if data.trade != 'NO TRADE' else 'no' }}">
                {{ 'ENTER TRADE' if data.trade != 'NO TRADE' else 'NO TRADE' }}
            </div>
        </div>
    </div>

    <div class="card">
        {% if data.error %}
        <div class="error">{{ data.error }}</div>
        {% else %}
        <div class="metrics">
            <div class="metric"><div class="label">Spot</div><div class="value">{{ data.spot_price }}</div><div class="sub">Latest stored SPX underlying price</div></div>
            <div class="metric"><div class="label">Contracts</div><div class="value">{{ data.contract_count }}</div><div class="sub">Stored rows in selected chain</div></div>
            <div class="metric"><div class="label">Call OI</div><div class="value">{{ data.call_open_interest }}</div><div class="sub">Total open interest</div></div>
            <div class="metric"><div class="label">Put OI</div><div class="value">{{ data.put_open_interest }}</div><div class="sub">Total open interest</div></div>
        </div>

        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Call Last</th>
                        <th>Call Bid</th>
                        <th>Call Ask</th>
                        <th>Call Vol</th>
                        <th>Call OI</th>
                        <th>Call IV</th>
                        <th class="strike">Strike</th>
                        <th>Put IV</th>
                        <th>Put OI</th>
                        <th>Put Vol</th>
                        <th>Put Bid</th>
                        <th>Put Ask</th>
                        <th>Put Last</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in data.rows %}
                    <tr>
                        <td class="call-last">{{ row.call_last }}</td>
                        <td class="call-bid">{{ row.call_bid }}</td>
                        <td class="call-ask">{{ row.call_ask }}</td>
                        <td class="call-vol">{{ row.call_volume }}</td>
                        <td class="call-oi">{{ row.call_open_interest }}</td>
                        <td class="call-iv">{{ row.call_iv }}</td>
                        <td class="strike">{{ row.strike }}</td>
                        <td class="put-iv">{{ row.put_iv }}</td>
                        <td class="put-oi">{{ row.put_open_interest }}</td>
                        <td class="put-vol">{{ row.put_volume }}</td>
                        <td class="put-bid">{{ row.put_bid }}</td>
                        <td class="put-ask">{{ row.put_ask }}</td>
                        <td class="put-last">{{ row.put_last }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <div class="notes">
            Source: Oracle table {{ data.source_table }}. This view uses the latest stored SPX option snapshot and selects the session-relevant expiration directly from Oracle, with no external fetch in `server.py`.
        </div>
        {% endif %}
    </div>
</div>

<script>
(function() {
    const refresh = document.getElementById('refresh_interval');
    const form = document.getElementById('option-settings-form');
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

SIMULATOR_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>CashFlowArc</title>
    <link rel="icon" href="{{ url_for('favicon_svg', v=favicon_version) }}" sizes="any" type="image/svg+xml">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
        <style>
        :root{
            --panel:rgba(11, 22, 39, 0.84);
            --panel-2:rgba(15, 30, 52, 0.92);
            --border:rgba(148, 179, 255, 0.14);
            --text:#edf4ff;
            --muted:#8fa6c7;
            --green:#2ad18b;
            --red:#ff6b6b;
            --yellow:#ffcf70;
            --shadow:0 20px 50px rgba(0, 0, 0, 0.34);
        }
        *{box-sizing:border-box}
        body{margin:0; font-family:"Aptos","Segoe UI Variable","Segoe UI",sans-serif; background:radial-gradient(circle at top left, rgba(62, 120, 255, 0.16), transparent 30%), linear-gradient(180deg, #06111d 0%, #091627 55%, #07111f 100%); color:var(--text);}
        .wrap{max-width:1840px; margin:0 auto; padding:24px;}
        .topbar{display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:18px; margin-bottom:20px; padding:22px 24px; background:linear-gradient(180deg, rgba(15, 31, 52, 0.92), rgba(8, 18, 32, 0.92)); border:1px solid var(--border); border-radius:24px; box-shadow:var(--shadow);}
        .title h1{margin:0; font-family:"Bahnschrift","Aptos Display","Segoe UI",sans-serif; font-size:34px; letter-spacing:0}
        .title p{margin:8px 0 0; color:var(--muted); font-size:14px; line-height:1.5}
        .top-right{margin-left:auto; display:flex; align-items:center; gap:12px; flex-wrap:wrap; justify-content:flex-end;}
        .nav-links{display:flex; gap:6px; align-items:center; flex-wrap:wrap; padding:6px; border-radius:999px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.05);}
        .nav-link{color:var(--muted); text-decoration:none; font-size:13px; font-weight:600; padding:10px 14px; border-radius:999px; transition:all .18s ease;}
        .nav-link:hover{color:var(--text); background:rgba(255,255,255,0.04)}
        .nav-link.active{color:#04101c; background:linear-gradient(135deg, #8ed4ff, #d7f0ff); box-shadow:0 8px 22px rgba(124, 196, 255, 0.28)}
        .control-form{display:flex; align-items:center; gap:10px; flex-wrap:wrap; background:rgba(255,255,255,0.035); border:1px solid rgba(255,255,255,0.05); border-radius:16px; padding:12px 14px; margin-bottom:16px;}
        .control-label{font-size:11px; color:var(--muted); font-weight:700; letter-spacing:0.08em; text-transform:uppercase}
        .text-input{width:110px; background:rgba(6, 14, 26, 0.82); color:var(--text); border:1px solid rgba(148, 179, 255, 0.18); border-radius:12px; padding:10px 12px; font-size:13px;}
        .text-input:focus{outline:none; border-color:rgba(124, 196, 255, 0.56); box-shadow:0 0 0 4px rgba(124, 196, 255, 0.12)}
        .text-input.ticker-input{width:120px}
        .text-input.date-input{width:150px}
        .text-input.time-input{width:120px}
        .status-pill{padding:11px 16px; border-radius:999px; font-weight:700; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;}
        .enter{color:#042414; background:linear-gradient(135deg, #39e3a0, #9af1c9); box-shadow:0 12px 24px rgba(42, 209, 139, 0.22)}
        .no{color:#350b0b; background:linear-gradient(135deg, #ff8f8f, #ffc0c0); box-shadow:0 12px 24px rgba(255, 107, 107, 0.2)}
        .card{background:linear-gradient(180deg, rgba(11, 22, 39, 0.92), rgba(8, 17, 31, 0.92)); border:1px solid var(--border); border-radius:24px; padding:18px; box-shadow:var(--shadow);}
        .metrics{display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px;}
        @media (max-width: 1100px){ .metrics{grid-template-columns:repeat(2,1fr);} }
        @media (max-width: 640px){ .metrics{grid-template-columns:1fr;} .wrap{padding:16px} .topbar{padding:18px} .title h1{font-size:28px} }
        .metrics.simulator-metrics{grid-template-columns:1fr;}
        .metrics.simulator-metrics .metric{min-height:0;}
        .metrics.simulator-metrics .metric .value{font-size:20px; line-height:1.35; white-space:normal; word-break:break-word;}
        .metric{background:linear-gradient(180deg, rgba(18, 34, 58, 0.92), rgba(12, 24, 42, 0.94)); border:1px solid rgba(148, 179, 255, 0.08); border-radius:20px; padding:16px; position:relative; overflow:hidden;}
        .metric::before{content:""; position:absolute; inset:0 auto auto 0; width:100%; height:2px; background:linear-gradient(90deg, rgba(124, 196, 255, 0.7), transparent 60%);}
        .metric .label{font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700; letter-spacing:0.12em}
        .metric .value{margin-top:10px; font-size:28px; font-weight:700; font-family:"Bahnschrift","Aptos Display","Segoe UI",sans-serif; letter-spacing:0}
        .metric .sub{margin-top:6px; font-size:12px; color:var(--muted); line-height:1.45}
        .chart-wrap{min-height:640px; background:linear-gradient(180deg, rgba(14, 27, 46, 0.96), rgba(12, 24, 42, 0.92)); border:1px solid rgba(148, 179, 255, 0.08); border-radius:20px; overflow:hidden;}
        .chart-wrap .plotly-graph-div{width:100% !important; height:640px !important;}
        .button{cursor:pointer; border:1px solid rgba(124, 196, 255, 0.24); border-radius:14px; padding:11px 16px; background:linear-gradient(135deg, #8ed4ff, #d7f0ff); color:#04101c; font-size:13px; font-weight:700; box-shadow:0 10px 20px rgba(124, 196, 255, 0.18);}
        .button:hover{transform:translateY(-1px)}
        .error{font-size:18px; color:#ff9b9b; font-weight:700}
        .notes{margin-top:16px; font-size:12px; color:var(--muted); line-height:1.6; background:rgba(255,255,255,0.025); border:1px solid rgba(255,255,255,0.04); border-radius:18px; padding:14px 16px}
    </style>

</head>
<body>
<div class="wrap">
    <div class="topbar">
        <div class="title">
            <h1>Simulator</h1>
            <p>{{ data.subtitle }}</p>
        </div>
        <div class="top-right">
            <div class="nav-links">
                <a class="nav-link" href="/terminal">Modern Terminal</a>
                <a class="nav-link" href="/gex">SPX GEX</a>
                <a class="nav-link" href="/option-chain">Option Chain</a>
                <a class="nav-link active" href="/simulator">Simulator</a>
            </div>
            <div class="status-pill {{ 'enter' if data.trade != 'NO TRADE' else 'no' }}">
                {{ 'ENTER TRADE' if data.trade != 'NO TRADE' else 'NO TRADE' }}
            </div>
        </div>
    </div>

    <div class="card">
        {% if data.error %}
        <div class="error">{{ data.error }}</div>
        {% else %}
        <form id="simulator-form" method="get" action="/simulator" class="control-form" style="margin-bottom:16px;">
            <span class="control-label">Ticker</span>
            <input id="simulator-ticker" class="text-input ticker-input" type="text" name="ticker" value="{{ data.ticker }}" spellcheck="false">
            <span class="control-label">Speed</span>
            <input id="simulator-speed" class="text-input" type="number" name="speed" min="0.5" max="360" step="0.5" value="{{ data.speed }}">
            <span class="control-label">Points +/-</span>
            <input id="simulator-points" class="text-input" type="number" name="points" min="0" step="1" value="{{ data.points }}">
            <span class="control-label">Wide</span>
            <input id="simulator-wide" class="text-input" type="number" name="wide" min="0" step="1" value="{{ data.wide }}">
            <span class="control-label">Execute Time</span>
            <input id="simulator-execute-time" class="text-input time-input" type="time" name="execute_time" step="300" value="{{ data.execute_time }}">
            <span class="control-label">Execution End</span>
            <input id="simulator-execution-end-time" class="text-input time-input" type="time" name="execution_end_time" step="300" value="{{ data.execution_end_time }}">
            <button id="simulator-toggle" class="button" type="button">Start Simulation</button>
        </form>

        <div class="metrics simulator-metrics">
            <div class="metric"><div class="label">Status</div><div id="simulator-status" class="value">Ready</div><div class="sub">Simulation clock</div></div>
        </div>

        <div id="simulator-chart" class="chart-wrap"></div>

        <div class="notes">
            Simulation uses the debug date from the terminal header and Oracle data aggregated into 5-minute candles. Each candle plays over 60 simulated seconds: 10 seconds at the open, 20 seconds to a random high/low, 20 seconds to the other extreme, and 10 seconds to the close. Rendering stops after the final intraday candle for the session.
        </div>
        {% endif %}
    </div>
</div>

{% if not data.error %}
<script>
(function() {
    const candles = {{ data.simulator_payload|safe }};
    const tradeDate = {{ data.trade_date|tojson }};
    const speed = {{ data.speed_js }};
    const pointsValue = {{ data.points_js }};
    const wideValue = {{ data.wide_js }};
    const executeTime = {{ data.execute_time|tojson }};
    const executionEndTime = {{ data.execution_end_time|tojson }};
    const formEl = document.getElementById('simulator-form');
    const tickerInputEl = document.getElementById('simulator-ticker');
    const speedInputEl = document.getElementById('simulator-speed');
    const pointsInputEl = document.getElementById('simulator-points');
    const wideInputEl = document.getElementById('simulator-wide');
    const executeTimeInputEl = document.getElementById('simulator-execute-time');
    const executionEndTimeInputEl = document.getElementById('simulator-execution-end-time');
    const chartEl = document.getElementById('simulator-chart');
    const statusEl = document.getElementById('simulator-status');
    const toggleEl = document.getElementById('simulator-toggle');
    const totalSimSeconds = candles.length * 60;
    const guideAnchorLabel = executeTime;
    const guideAnchorIndex = candles.findIndex((candle) => candle.label === guideAnchorLabel);
    const guideEndIndex = candles.findIndex((candle) => candle.label === executionEndTime);
    const guideAnchorClose = guideAnchorIndex >= 0 ? candles[guideAnchorIndex].close : null;
    const config = { displayModeBar: false, responsive: true };
    const layout = {
        margin: {l: 28, r: 28, t: 20, b: 64},
        paper_bgcolor: '#17202b',
        plot_bgcolor: '#17202b',
        font: {color: '#e8eef7'},
        xaxis: {
            type: 'category',
            showgrid: true,
            gridcolor: '#273244',
            rangeslider: {visible: false},
            title: 'Time',
            automargin: true,
            showline: false,
            zeroline: false,
        },
        yaxis: {
            showgrid: true,
            gridcolor: '#273244',
            title: '{{ data.ticker }}',
            automargin: true,
            showline: false,
            zeroline: false,
        },
        hovermode: 'closest',
        hoverlabel: {bgcolor: '#0f141b', bordercolor: '#273244', font: {color: '#e8eef7'}},
    };

    function lerp(a, b, t) {
        return a + ((b - a) * t);
    }

    function buildActiveCandle(candle, phaseSeconds) {
        const firstKey = candle.first_move;
        const secondKey = firstKey === 'high' ? 'low' : 'high';
        const visited = [candle.open];
        let current = candle.open;

        if (phaseSeconds < 10) {
            current = candle.open;
        } else if (phaseSeconds < 30) {
            current = lerp(candle.open, candle[firstKey], (phaseSeconds - 10) / 20);
            visited.push(current);
        } else if (phaseSeconds < 50) {
            visited.push(candle[firstKey]);
            current = lerp(candle[firstKey], candle[secondKey], (phaseSeconds - 30) / 20);
            visited.push(current);
        } else {
            visited.push(candle[firstKey]);
            visited.push(candle[secondKey]);
            current = lerp(candle[secondKey], candle.close, (phaseSeconds - 50) / 10);
            visited.push(current);
        }

        return {
            open: candle.open,
            high: Math.max.apply(null, visited),
            low: Math.min.apply(null, visited),
            close: current,
        };
    }

    function buildGuideTraces(labels, showGuides) {
        if (!showGuides || guideAnchorClose === null) return [];

        const startIndex = labels.indexOf(guideAnchorLabel);
        if (startIndex === -1) return [];

        let guideLabels = labels.slice(startIndex);
        if (guideEndIndex >= 0) {
            const endLabel = candles[guideEndIndex].label;
            const endSliceIndex = labels.indexOf(endLabel);
            if (endSliceIndex >= startIndex) {
                guideLabels = labels.slice(startIndex, endSliceIndex + 1);
            }
        }
        if (!guideLabels.length) return [];

        const redUpper = guideAnchorClose + pointsValue;
        const redLower = guideAnchorClose - pointsValue;
        const blueUpper = guideAnchorClose + pointsValue + wideValue;
        const blueLower = guideAnchorClose - pointsValue - wideValue;

        return [
            {y: redUpper, color: '#ff5d5d'},
            {y: redLower, color: '#ff5d5d'},
            {y: blueUpper, color: '#4da3ff'},
            {y: blueLower, color: '#4da3ff'},
        ].map((guide) => ({
            type: 'scatter',
            mode: 'lines',
            x: guideLabels,
            y: guideLabels.map(() => guide.y),
            line: {color: guide.color, width: 2},
            hoverinfo: 'skip',
            showlegend: false,
        }));
    }

    function computeYRange(highVals, lowVals, labels, showGuides) {
        const values = [];
        values.push.apply(values, highVals);
        values.push.apply(values, lowVals);

        if (showGuides && guideAnchorClose !== null && labels.indexOf(guideAnchorLabel) !== -1) {
            values.push(guideAnchorClose + pointsValue);
            values.push(guideAnchorClose - pointsValue);
            values.push(guideAnchorClose + pointsValue + wideValue);
            values.push(guideAnchorClose - pointsValue - wideValue);
        }

        if (!values.length) return null;

        const minVal = Math.min.apply(null, values);
        const maxVal = Math.max.apply(null, values);
        const padding = Math.max((maxVal - minVal) * 0.1, 10);
        return [minVal - padding, maxVal + padding];
    }

    function formatStatus(label, suffix) {
        return tradeDate + ' ' + label + ' • ' + suffix;
    }

    function normalizeTicker(value) {
        return (value || '').trim().toUpperCase();
    }

    function normalizeNumberString(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? String(parsed) : '';
    }

    function normalizeTimeString(value) {
        return (value || '').trim().slice(0, 5);
    }

    function currentSessionState() {
        return {
            ticker: normalizeTicker(tickerInputEl ? tickerInputEl.value : ''),
            speed: normalizeNumberString(speedInputEl ? speedInputEl.value : ''),
            points: normalizeNumberString(pointsInputEl ? pointsInputEl.value : ''),
            wide: normalizeNumberString(wideInputEl ? wideInputEl.value : ''),
            executeTime: normalizeTimeString(executeTimeInputEl ? executeTimeInputEl.value : ''),
            executionEndTime: normalizeTimeString(executionEndTimeInputEl ? executionEndTimeInputEl.value : ''),
        };
    }

    const initialSessionState = currentSessionState();

    function sessionConfigChanged() {
        const current = currentSessionState();
        return Object.keys(initialSessionState).some((key) => current[key] !== initialSessionState[key]);
    }

    let settingsTimer = null;

    function persistSimulatorSettings() {
        if (!formEl) return Promise.resolve();
        const data = new FormData();
        data.set('simulator_speed', speedInputEl ? speedInputEl.value : '');
        data.set('simulator_points', pointsInputEl ? pointsInputEl.value : '');
        data.set('simulator_wide', wideInputEl ? wideInputEl.value : '');
        data.set('simulator_execute_time', executeTimeInputEl ? executeTimeInputEl.value : '');
        data.set('simulator_execution_end_time', executionEndTimeInputEl ? executionEndTimeInputEl.value : '');
        return fetch('/settings', {method: 'POST', body: data}).catch(() => {});
    }

    function debouncePersist() {
        if (settingsTimer) clearTimeout(settingsTimer);
        settingsTimer = setTimeout(() => {
            persistSimulatorSettings();
        }, 250);
    }

    [speedInputEl, pointsInputEl, wideInputEl, executeTimeInputEl, executionEndTimeInputEl].forEach((input) => {
        if (!input) return;
        input.addEventListener('input', debouncePersist);
        input.addEventListener('change', debouncePersist);
    });

    if (formEl) {
        formEl.addEventListener('submit', function() {
            persistSimulatorSettings();
        });
    }

    function renderChart(openVals, highVals, lowVals, closeVals, labels, showGuides) {
        const traces = [{
            type: 'candlestick',
            x: labels,
            open: openVals,
            high: highVals,
            low: lowVals,
            close: closeVals,
            name: '',
            showlegend: false,
            increasing: {line: {color: '#1fce7a'}, fillcolor: '#1fce7a'},
            decreasing: {line: {color: '#ff5d5d'}, fillcolor: '#ff5d5d'},
            hoverinfo: 'x+open+high+low+close',
        }];
        traces.push.apply(traces, buildGuideTraces(labels, showGuides));

        const yRange = computeYRange(highVals, lowVals, labels, showGuides);
        const nextLayout = Object.assign({}, layout, {
            yaxis: Object.assign({}, layout.yaxis, yRange ? {range: yRange} : {}),
        });

        Plotly.react(chartEl, traces, nextLayout, config);
    }

    if (!candles.length) {
        statusEl.textContent = 'No Data';
        toggleEl.disabled = true;
        renderChart([], [], [], [], [], false);
        return;
    }

    let timerId = null;
    let running = false;
    let completedRun = false;
    let simulatedSeconds = 0;
    let lastTickAt = null;

    function setToggleLabel() {
        if (running) {
            toggleEl.textContent = 'Pause Simulation';
        } else if (simulatedSeconds > 0 && !completedRun) {
            toggleEl.textContent = 'Resume Simulation';
        } else {
            toggleEl.textContent = 'Start Simulation';
        }
    }

    function drawState(cappedSeconds) {
        const completed = Math.floor(cappedSeconds / 60);
        const phase = cappedSeconds - (completed * 60);
        const openVals = [];
        const highVals = [];
        const lowVals = [];
        const closeVals = [];
        const labels = [];

        for (let i = 0; i < Math.min(completed, candles.length); i += 1) {
            const candle = candles[i];
            labels.push(candle.label);
            openVals.push(candle.open);
            highVals.push(candle.high);
            lowVals.push(candle.low);
            closeVals.push(candle.close);
        }

        if (completed < candles.length && cappedSeconds < totalSimSeconds) {
            const candle = candles[completed];
            const active = buildActiveCandle(candle, phase);
            labels.push(candle.label);
            openVals.push(active.open);
            highVals.push(active.high);
            lowVals.push(active.low);
            closeVals.push(active.close);
            statusEl.textContent = formatStatus(candle.label, Math.floor(phase) + 's • ' + speed + 'x');
        } else {
            statusEl.textContent = formatStatus('16:00', 'Complete');
        }

        const showGuides = guideAnchorIndex >= 0 && completed > guideAnchorIndex;
        renderChart(openVals, highVals, lowVals, closeVals, labels, showGuides);
    }

    function stopTimer() {
        if (timerId) {
            clearInterval(timerId);
            timerId = null;
        }
    }

    function tick() {
        if (!running) return;

        const now = Date.now();
        if (lastTickAt !== null) {
            simulatedSeconds += ((now - lastTickAt) / 1000) * speed;
        }
        lastTickAt = now;

        const cappedSeconds = Math.min(simulatedSeconds, totalSimSeconds);
        drawState(cappedSeconds);

        if (cappedSeconds >= totalSimSeconds) {
            simulatedSeconds = totalSimSeconds;
            running = false;
            completedRun = true;
            stopTimer();
            setToggleLabel();
        }
    }

    function startSimulation() {
        if (completedRun) {
            simulatedSeconds = 0;
            completedRun = false;
            drawState(0);
        }
        running = true;
        lastTickAt = Date.now();
        setToggleLabel();
        if (!timerId) {
            timerId = setInterval(tick, 200);
        }
    }

    function stopSimulation() {
        running = false;
        lastTickAt = null;
        setToggleLabel();
        stopTimer();
        if (!completedRun) {
            const latestLabel = candles[Math.min(Math.floor(simulatedSeconds / 60), candles.length - 1)].label;
            statusEl.textContent = formatStatus(latestLabel, 'Paused • ' + speed + 'x');
        }
    }

    toggleEl.addEventListener('click', function() {
        if (sessionConfigChanged()) {
            persistSimulatorSettings();
            formEl.requestSubmit();
            return;
        }

        if (running) {
            stopSimulation();
        } else {
            startSimulation();
        }
    });

    renderChart([], [], [], [], [], false);
    setToggleLabel();
})();
</script>
{% endif %}
</body>
</html>
"""


_TERMINAL_STYLE_MATCH = re.search(r"<style>(.*?)</style>", TERMINAL_HTML, re.S)
TERMINAL_STYLE = _TERMINAL_STYLE_MATCH.group(1) if _TERMINAL_STYLE_MATCH else ""

_SIMULATOR_SCRIPT_MATCH = re.search(
    r"({% if not data.error %}\s*<script>.*?</script>\s*{% endif %})",
    SIMULATOR_HTML,
    re.S,
)
SIMULATOR_TERMINAL_SCRIPT = _SIMULATOR_SCRIPT_MATCH.group(1) if _SIMULATOR_SCRIPT_MATCH else ""

TERMINAL_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>CashFlowArc Terminal</title>
    <link rel="icon" href="{{ url_for('favicon_svg', v=favicon_version) }}" sizes="any" type="image/svg+xml">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
{{ terminal_style|safe }}
        .shell{grid-template-rows:auto auto 1fr auto;}
        .page-stack{display:grid; gap:18px; align-content:start; min-width:0;}
        .page-grid{display:grid; grid-template-columns:minmax(0,1fr); gap:18px; align-items:start; min-width:0;}
        .gex-grid{grid-template-columns:minmax(0,1fr) minmax(300px,420px);}
        .metric-strip{display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px;}
        .terminal-metric{min-height:126px; display:grid; align-content:start; gap:8px;}
        .metric-label{color:var(--muted); font-size:11px; font-weight:900; letter-spacing:.08em; text-transform:uppercase;}
        .metric-value{font-size:clamp(24px,2.2vw,36px); line-height:1; color:#dffcff; font-weight:900;}
        .metric-sub{color:var(--muted); font-size:12px; line-height:1.45;}
        .terminal-note{margin:0; color:var(--muted); font-size:12px; line-height:1.65;}
        .terminal-chart-tall{height:620px;}
        .terminal-chart-tall .plotly-graph-div{height:100% !important;}
        .terminal-table-wrap{overflow:auto; max-height:72vh; border:1px solid rgba(0,229,240,.22); background:rgba(0,8,11,.68); box-shadow:inset 0 0 28px rgba(0,229,240,.045);}
        .terminal-table{min-width:1120px; border-collapse:separate; border-spacing:0;}
        .terminal-table th,.terminal-table td{padding:10px 9px; border-bottom:1px solid rgba(142,170,179,.16); font-size:12px; white-space:nowrap; text-align:right;}
        .terminal-table th{position:sticky; top:0; z-index:1; color:var(--muted); background:rgba(2,12,16,.96); text-transform:uppercase; letter-spacing:.06em;}
        .terminal-table tbody tr:nth-child(even){background:rgba(255,255,255,.018);}
        .terminal-table tbody tr:hover{background:rgba(0,229,240,.06);}
        .terminal-table .strike{text-align:center; color:#f3fbff; background:rgba(255,255,255,.025); font-weight:900;}
        .call-last,.call-bid,.call-ask,.call-vol,.call-oi,.call-iv{color:var(--green);}
        .put-last,.put-bid,.put-ask,.put-vol,.put-oi,.put-iv{color:var(--red);}
        .simulator-controls{display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:16px;}
        .simulator-controls .control-label{font-size:11px; color:var(--muted); font-weight:900; letter-spacing:.08em; text-transform:uppercase; white-space:nowrap;}
        .simulator-controls input{height:32px; border:1px solid rgba(0,229,240,.22); background:rgba(0,8,11,.72); color:var(--text); padding:0 9px; font:inherit;}
        .simulator-controls .ticker-input{width:112px;}
        .simulator-controls .time-input{width:138px; min-width:138px;}
        .terminal-button{height:32px; cursor:pointer; border:1px solid rgba(0,229,240,.34); background:linear-gradient(135deg, rgba(0,229,240,.92), rgba(223,252,255,.92)); color:#031014; font-size:11px; font-weight:900; text-transform:uppercase; padding:0 12px;}
        .terminal-button:hover{filter:brightness(1.08);}
        .debug-form .refresh-input{width:68px;}
        .debug-form input[type="date"]{min-width:128px; text-transform:none;}
        .debug-form input[type="time"]{min-width:88px; text-transform:none;}
        .debug-form input:disabled{opacity:1; cursor:not-allowed; color:var(--muted);}
        .debug-picker{position:relative; display:inline-flex; align-items:center;}
        .debug-picker input{padding-right:26px;}
        .debug-picker-button{position:absolute; right:3px; top:50%; width:22px; height:22px; transform:translateY(-50%); display:grid; place-items:center; border:0; background:transparent; color:var(--cyan); padding:0; cursor:pointer;}
        .debug-picker-button:before{content:"\\1F50D"; font-size:12px; line-height:1; opacity:.76; text-shadow:0 0 8px rgba(0,229,240,.36);}
        .debug-picker-button:disabled{display:none;}
        .simulator-status{margin-bottom:16px;}
        .simulator-status .metric-value{font-size:20px; line-height:1.35; white-space:normal; overflow-wrap:anywhere;}
        .simulator-chart{height:640px;}
        .simulator-chart .plotly-graph-div{height:100% !important;}
        @media (max-width: 980px){.gex-grid{grid-template-columns:1fr}.metric-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.terminal-chart-tall{height:540px}.simulator-chart{height:520px}}
        @media (max-width: 680px){.metric-strip{grid-template-columns:1fr}.simulator-controls input,.simulator-controls .ticker-input,.simulator-controls .time-input{width:100%}.terminal-button{width:100%}.simulator-chart{height:440px}}
    </style>
</head>
<body>
<main class="shell">
    <header class="topbar">
        <div class="timeblock">
            <span class="clockmark">TIME</span>
            <span>{{ data.header_time }}</span>
            <span>{{ data.header_date }}</span>
            <span>{{ data.header_weekday }}</span>
        </div>
        <div class="brand">
            <h1>CashFlowArc Terminal</h1>
        </div>
        <div class="nav-panel">
            <div class="market-readout"><b class="{{ data.market_status_class }}">{{ data.market_status }}</b>{{ data.market_hours }}</div>
        </div>
    </header>
    <section class="controlbar">
        <nav class="nav-links">
            <a class="{{ 'nav-link active' if data.active_tab == 'terminal' else 'nav-link' }}" href="/terminal">Modern Terminal</a>
            <a class="{{ 'nav-link active' if data.active_tab == 'gex' else 'nav-link' }}" href="/gex">SPX GEX</a>
            <a class="{{ 'nav-link active' if data.active_tab == 'option-chain' else 'nav-link' }}" href="/option-chain">Option Chain</a>
            <a class="{{ 'nav-link active' if data.active_tab == 'simulator' else 'nav-link' }}" href="/simulator">Simulator</a>
        </nav>
        <form class="debug-form" method="post" action="/settings">
            <input type="hidden" name="chart_interval" value="{{ data.chart_interval }}">
            <span>Refresh</span>
            <input class="refresh-input" type="number" min="15" max="3600" step="1" name="refresh_interval" value="{{ data.refresh_interval }}">
            <input type="hidden" name="debug_mode" value="0">
            <label class="debug-switch">
                <span>Debug</span>
                <input type="checkbox" name="debug_mode" value="1" {% if data.debug_mode %}checked{% endif %}>
                <span class="debug-slider"></span>
            </label>
            <span class="debug-picker {{ 'active' if data.debug_mode else '' }}">
                <input type="date" name="debug_trade_date" value="{{ data.debug_control_date }}" max="{{ data.debug_max_date }}" {% if not data.debug_mode %}disabled{% endif %}>
                <button class="debug-picker-button" type="button" aria-label="Open debug date picker" {% if not data.debug_mode %}disabled{% endif %}></button>
            </span>
            <span class="debug-picker {{ 'active' if data.debug_mode else '' }}">
                <input type="time" name="debug_time" step="60" value="{{ data.debug_control_time }}" {% if not data.debug_mode %}disabled{% endif %}>
                <button class="debug-picker-button" type="button" aria-label="Open debug time picker" {% if not data.debug_mode %}disabled{% endif %}></button>
            </span>
        </form>
    </section>

    {% if data.error %}
    <section class="panel"><div class="err">{{ data.error }}</div></section>
    {% else %}
    {{ data.page_content|safe }}
    {% endif %}

    <footer class="tickerbar">
        <span><b>WATCHLIST</b></span>
        <span>SPX <span class="green">{{ data.price }}</span></span>
        <span>SPY <span class="green">{{ data.spy_price }}</span></span>
        <span class="muted">Refresh {{ data.refresh_interval }}s</span>
    </footer>
</main>
<script>
document.querySelectorAll('.debug-form').forEach(function(form) {
    form.addEventListener('change', function() {
        fetch('/settings', { method: 'POST', body: new FormData(form) })
            .then(function() { window.location.reload(); })
            .catch(function() {});
    });
});
document.querySelectorAll('.debug-picker-button').forEach(function(button) {
    button.addEventListener('click', function(event) {
        event.preventDefault();
        var wrapper = button.closest('.debug-picker');
        var input = wrapper ? wrapper.querySelector('input') : null;
        if (!input || input.disabled) return;
        input.focus();
        if (typeof input.showPicker === 'function') {
            try {
                input.showPicker();
                return;
            } catch (err) {}
        }
        input.click();
    });
});
{% if data.active_tab != 'simulator' %}
setTimeout(function(){ window.location.reload(); }, Math.max(15, Number({{ data.refresh_interval }})) * 1000);
{% endif %}
</script>
{{ data.page_script|safe }}
</body>
</html>
"""

GEX_TERMINAL_CONTENT = """
<section class="page-grid gex-grid">
    <section class="panel">
        <div class="panel-title"><span>SPX Gamma Exposure</span><span>{{ data.expiration_date }}</span></div>
        <div class="chart-wrap terminal-chart-tall">{{ data.chart_html|safe }}</div>
    </section>
    <section class="page-stack">
        <section class="panel terminal-metric">
            <div class="metric-label">Spot</div>
            <div class="metric-value">{{ data.spot_price }}</div>
            <div class="metric-sub">Latest SPX price from the stored option snapshot.</div>
        </section>
        <section class="panel terminal-metric">
            <div class="metric-label">Net GEX</div>
            <div class="metric-value {{ data.net_gex_signal_class }}">{{ data.net_gex_billions }}</div>
            <div class="metric-sub">Per 1 percent move, shown in billions.</div>
        </section>
        <section class="panel terminal-metric">
            <div class="metric-label">Call Wall</div>
            <div class="metric-value">{{ data.call_wall }}</div>
            <div class="metric-sub">Largest positive strike gamma exposure.</div>
        </section>
        <section class="panel terminal-metric">
            <div class="metric-label">Put Wall</div>
            <div class="metric-value">{{ data.put_wall }}</div>
            <div class="metric-sub">Largest negative strike gamma exposure.</div>
        </section>
    </section>
</section>
<section class="panel">
    <div class="panel-title"><span>Source Notes</span><span>Oracle Snapshot</span></div>
    <p class="terminal-note">{{ data.subtitle }}</p>
    <p class="terminal-note">Gamma exposure is estimated from stored option-chain open interest, implied volatility, and Black-Scholes gamma with time capped at a minimum of {{ data.min_time_minutes }} minute(s).</p>
</section>
"""

OPTION_CHAIN_TERMINAL_CONTENT = """
<section class="page-stack">
    <section class="metric-strip">
        <section class="panel terminal-metric">
            <div class="metric-label">Spot</div>
            <div class="metric-value">{{ data.spot_price }}</div>
            <div class="metric-sub">Latest stored SPX underlying price.</div>
        </section>
        <section class="panel terminal-metric">
            <div class="metric-label">Contracts</div>
            <div class="metric-value">{{ data.contract_count }}</div>
            <div class="metric-sub">Rows in the selected chain.</div>
        </section>
        <section class="panel terminal-metric">
            <div class="metric-label">Call OI</div>
            <div class="metric-value green">{{ data.call_open_interest }}</div>
            <div class="metric-sub">Total call open interest.</div>
        </section>
        <section class="panel terminal-metric">
            <div class="metric-label">Put OI</div>
            <div class="metric-value red">{{ data.put_open_interest }}</div>
            <div class="metric-sub">Total put open interest.</div>
        </section>
    </section>
    <section class="panel">
        <div class="panel-title"><span>SPX Option Chain</span><span>{{ data.expiration_date }}</span></div>
        <div class="terminal-table-wrap">
            <table class="terminal-table">
                <thead>
                    <tr>
                        <th>Call Last</th>
                        <th>Call Bid</th>
                        <th>Call Ask</th>
                        <th>Call Vol</th>
                        <th>Call OI</th>
                        <th>Call IV</th>
                        <th class="strike">Strike</th>
                        <th>Put IV</th>
                        <th>Put OI</th>
                        <th>Put Vol</th>
                        <th>Put Bid</th>
                        <th>Put Ask</th>
                        <th>Put Last</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in data.rows %}
                    <tr>
                        <td class="call-last">{{ row.call_last }}</td>
                        <td class="call-bid">{{ row.call_bid }}</td>
                        <td class="call-ask">{{ row.call_ask }}</td>
                        <td class="call-vol">{{ row.call_volume }}</td>
                        <td class="call-oi">{{ row.call_open_interest }}</td>
                        <td class="call-iv">{{ row.call_iv }}</td>
                        <td class="strike">{{ row.strike }}</td>
                        <td class="put-iv">{{ row.put_iv }}</td>
                        <td class="put-oi">{{ row.put_open_interest }}</td>
                        <td class="put-vol">{{ row.put_volume }}</td>
                        <td class="put-bid">{{ row.put_bid }}</td>
                        <td class="put-ask">{{ row.put_ask }}</td>
                        <td class="put-last">{{ row.put_last }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </section>
    <section class="panel">
        <div class="panel-title"><span>Source Notes</span><span>{{ data.source_table }}</span></div>
        <p class="terminal-note">{{ data.subtitle }}</p>
        <p class="terminal-note">This view uses the latest stored SPX option snapshot selected directly from Oracle.</p>
    </section>
</section>
"""

SIMULATOR_TERMINAL_CONTENT = """
<section class="panel">
    <div class="panel-title"><span>Simulator</span><span>{{ data.debug_control_date }}</span></div>
    <form id="simulator-form" method="get" action="/simulator" class="simulator-controls">
        <span class="control-label">Ticker</span>
        <input id="simulator-ticker" class="ticker-input" type="text" name="ticker" value="{{ data.ticker }}" spellcheck="false">
        <span class="control-label">Speed</span>
        <input id="simulator-speed" type="number" name="speed" min="0.5" max="360" step="0.5" value="{{ data.speed }}">
        <span class="control-label">Points +/-</span>
        <input id="simulator-points" type="number" name="points" min="0" step="1" value="{{ data.points }}">
        <span class="control-label">Wide</span>
        <input id="simulator-wide" type="number" name="wide" min="0" step="1" value="{{ data.wide }}">
        <span class="control-label">Execute Time</span>
        <input id="simulator-execute-time" class="time-input" type="time" name="execute_time" step="300" value="{{ data.execute_time }}">
        <span class="control-label">Execution End</span>
        <input id="simulator-execution-end-time" class="time-input" type="time" name="execution_end_time" step="300" value="{{ data.execution_end_time }}">
        <button id="simulator-toggle" class="terminal-button" type="button">Start Simulation</button>
    </form>
    <section class="panel terminal-metric simulator-status">
        <div class="metric-label">Status</div>
        <div id="simulator-status" class="metric-value">Ready</div>
        <div class="metric-sub">Simulation clock. Debug mode uses the selected debug date; live mode uses today.</div>
    </section>
    <div id="simulator-chart" class="chart-wrap simulator-chart"></div>
    <p class="terminal-note" style="margin-top:16px;">Simulation uses the selected debug date when debug mode is enabled; otherwise it uses today's Eastern date. Rendering stops after the final intraday candle for the session.</p>
</section>
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
            out["debug_mode"] = bool(out.get("debug_mode", False))
            out["debug_trade_date"] = normalize_debug_trade_date(out.get("debug_trade_date", ""))
            out["debug_time"] = normalize_simulator_time(out.get("debug_time", ""), "")
            out["simulator_speed"] = max(0.5, min(360.0, float(out.get("simulator_speed", 60.0))))
            out["simulator_points"] = max(0.0, float(out.get("simulator_points", 70.0)))
            out["simulator_wide"] = max(0.0, float(out.get("simulator_wide", 20.0)))
            out["simulator_trade_date"] = str(out.get("simulator_trade_date", "") or "")
            out["simulator_execute_time"] = normalize_execute_time(out.get("simulator_execute_time", "10:30"))
            out["simulator_execution_end_time"] = normalize_execution_end_time(out.get("simulator_execution_end_time", "14:00"))
            if out["chart_interval"] not in {"5min", "15min", "1h"}:
                out["chart_interval"] = "5min"
            return out
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def normalize_simulator_time(value: Optional[str], default: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    candidate = raw[:5]
    try:
        parsed = dt.time.fromisoformat(candidate)
        return parsed.strftime("%H:%M")
    except ValueError:
        return default


def normalize_debug_trade_date(value: Optional[str], max_date: Optional[str] = None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = dt.date.fromisoformat(raw[:10])
    except ValueError:
        return ""
    if max_date:
        try:
            limit = dt.date.fromisoformat(str(max_date)[:10])
        except ValueError:
            limit = pd.Timestamp.now(tz=TIMEZONE).date()
    else:
        limit = pd.Timestamp.now(tz=TIMEZONE).date()
    if parsed > limit:
        return limit.isoformat()
    return parsed.isoformat()


def normalize_execute_time(value: Optional[str]) -> str:
    return normalize_simulator_time(value, "10:30")


def normalize_execution_end_time(value: Optional[str]) -> str:
    return normalize_simulator_time(value, "14:00")


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
        raise ValueError("No stored SPX expirations were found.")

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
    spx_db_ticker = db_storage_ticker(SPX_TICKER)
    snapshot_as_of_utc = now_et.tz_convert("UTC").tz_localize(None).to_pydatetime()
    with get_connection() as conn:
        snapshot_ts = get_latest_option_snapshot_ts(conn, spx_db_ticker, snapshot_as_of_utc)
        if snapshot_ts is None:
            raise ValueError(f"No stored options snapshots found in {OPTION_SOURCE_TABLE} for {spx_db_ticker}.")
        options = query_option_snapshot(conn, spx_db_ticker, snapshot_ts)

    if options.empty:
        raise ValueError(f"No stored option rows found in {OPTION_SOURCE_TABLE} for {spx_db_ticker}.")

    available_dates = sorted(pd.to_datetime(options["expiration_date"]).dt.date.unique())
    expiration_map = {value: value.isoformat() for value in available_dates}
    preferred_expiration_date = resolve_gex_expiration_date(now_et, available_dates)

    candidate_dates: list[dt.date] = [preferred_expiration_date]
    current_date = now_et.date()
    if current_date in expiration_map and current_date not in candidate_dates:
        candidate_dates.append(current_date)

    last_empty_error = ""
    last_underlying: dict = {}
    last_selected_expiration_date: Optional[dt.date] = None
    for selected_expiration_date in candidate_dates:
        if selected_expiration_date not in expiration_map:
            continue

        selected_options = options[
            pd.to_datetime(options["expiration_date"]).dt.date == selected_expiration_date
        ].copy()
        if selected_options.empty:
            last_empty_error = f"Stored snapshot returned an empty SPX chain for {selected_expiration_date.isoformat()}."
            continue

        underlying = build_underlying_snapshot(selected_options)
        last_underlying = underlying
        last_selected_expiration_date = selected_expiration_date

        total_open_interest = pd.to_numeric(selected_options.get("open_interest"), errors="coerce").fillna(0.0).sum()
        if total_open_interest <= 0:
            last_empty_error = (
                f"Stored snapshot returned no usable SPX open interest for {selected_expiration_date.isoformat()}."
            )
            continue

        if not candidate_has_usable_gex_data(selected_options, underlying):
            last_empty_error = (
                f"Stored snapshot returned no usable near-spot SPX open interest for {selected_expiration_date.isoformat()}."
            )
            continue

        return selected_options, underlying, selected_expiration_date

    if "open interest" in last_empty_error.lower():
        raise NoOpenInterestInFeedError(last_selected_expiration_date or preferred_expiration_date, last_underlying)

    available = ", ".join(sorted(expiration_map.values()))
    raise ValueError(
        last_empty_error or f"No SPX expiration matched usable stored data. Available expirations: {available}"
    )


def fetch_spx_option_chain_for_session(now_et: pd.Timestamp) -> tuple[pd.DataFrame, dict, dt.date, dt.datetime]:
    spx_db_ticker = db_storage_ticker(SPX_TICKER)
    snapshot_as_of_utc = now_et.tz_convert("UTC").tz_localize(None).to_pydatetime()
    with get_connection() as conn:
        snapshot_ts = get_latest_option_snapshot_ts(conn, spx_db_ticker, snapshot_as_of_utc)
        if snapshot_ts is None:
            raise ValueError(f"No stored options snapshots found in {OPTION_SOURCE_TABLE} for {spx_db_ticker}.")
        options = query_option_snapshot(conn, spx_db_ticker, snapshot_ts)

    if options.empty:
        raise ValueError(f"No stored option rows found in {OPTION_SOURCE_TABLE} for {spx_db_ticker}.")

    available_dates = sorted(pd.to_datetime(options["expiration_date"]).dt.date.unique())
    selected_expiration_date = resolve_gex_expiration_date(now_et, available_dates)
    selected_options = options[
        pd.to_datetime(options["expiration_date"]).dt.date == selected_expiration_date
    ].copy()

    if selected_options.empty:
        fallback_expiration_date = available_dates[0]
        selected_options = options[
            pd.to_datetime(options["expiration_date"]).dt.date == fallback_expiration_date
        ].copy()
        selected_expiration_date = fallback_expiration_date

    if selected_options.empty:
        raise ValueError("Latest stored SPX snapshot did not contain a usable expiration chain.")

    underlying = build_underlying_snapshot(selected_options)
    return selected_options, underlying, selected_expiration_date, snapshot_ts


def get_latest_option_snapshot_ts(
    conn,
    ticker: str,
    as_of_utc: Optional[dt.datetime] = None,
) -> Optional[dt.datetime]:
    sql = f"""
        SELECT MAX(snapshot_ts_utc)
        FROM {OPTION_SOURCE_TABLE}
        WHERE ticker = :ticker
    """
    params = {"ticker": ticker}
    if as_of_utc is not None:
        sql += "\n          AND snapshot_ts_utc <= :as_of_utc"
        params["as_of_utc"] = as_of_utc
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        row = cur.fetchone()
        return None if row is None else row[0]
    finally:
        cur.close()


def query_option_snapshot(conn, ticker: str, snapshot_ts_utc: dt.datetime) -> pd.DataFrame:
    sql = f"""
        SELECT
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
        FROM {OPTION_SOURCE_TABLE}
        WHERE ticker = :ticker
          AND snapshot_ts_utc = :snapshot_ts_utc
        ORDER BY expiration_date, strike, option_type, contract_symbol
    """
    df = pd.read_sql(
        sql,
        conn,
        params={
            "ticker": ticker,
            "snapshot_ts_utc": snapshot_ts_utc,
        },
    )
    if df.empty:
        return df

    df.columns = [c.lower() for c in df.columns]
    df["snapshot_ts_utc"] = pd.to_datetime(df["snapshot_ts_utc"], utc=True)
    df["expiration_date"] = pd.to_datetime(df["expiration_date"]).dt.date
    df["last_trade_ts_utc"] = pd.to_datetime(df["last_trade_ts_utc"], utc=True, errors="coerce")
    return df


def build_underlying_snapshot(options: pd.DataFrame) -> dict:
    if options is None or options.empty:
        return {}

    underlying_price_series = pd.to_numeric(options.get("underlying_price"), errors="coerce").dropna()
    previous_close_series = pd.to_numeric(options.get("underlying_previous_close"), errors="coerce").dropna()

    return {
        "regularMarketPrice": float(underlying_price_series.iloc[-1]) if not underlying_price_series.empty else 0.0,
        "previousClose": float(previous_close_series.iloc[-1]) if not previous_close_series.empty else 0.0,
    }


def format_option_price(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):,.2f}"


def format_option_integer(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{int(round(float(value))):,}"


def format_option_iv(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100:.1f}%"


def build_option_chain_rows(options: pd.DataFrame) -> list[dict]:
    if options is None or options.empty:
        return []

    working = options.copy()
    for column in ["strike", "last_price", "bid_price", "ask_price", "volume", "open_interest", "implied_volatility"]:
        working[column] = pd.to_numeric(working.get(column), errors="coerce")

    base_columns = ["strike", "last_price", "bid_price", "ask_price", "volume", "open_interest", "implied_volatility"]
    calls = (
        working[working["option_type"] == "call"][base_columns]
        .drop_duplicates(subset=["strike"], keep="last")
        .rename(columns={
            "last_price": "call_last",
            "bid_price": "call_bid",
            "ask_price": "call_ask",
            "volume": "call_volume",
            "open_interest": "call_open_interest",
            "implied_volatility": "call_iv",
        })
    )
    puts = (
        working[working["option_type"] == "put"][base_columns]
        .drop_duplicates(subset=["strike"], keep="last")
        .rename(columns={
            "last_price": "put_last",
            "bid_price": "put_bid",
            "ask_price": "put_ask",
            "volume": "put_volume",
            "open_interest": "put_open_interest",
            "implied_volatility": "put_iv",
        })
    )

    merged = pd.merge(calls, puts, on="strike", how="outer").sort_values("strike").reset_index(drop=True)
    rows: list[dict] = []
    for row in merged.itertuples(index=False):
        rows.append({
            "call_last": format_option_price(getattr(row, "call_last", None)),
            "call_bid": format_option_price(getattr(row, "call_bid", None)),
            "call_ask": format_option_price(getattr(row, "call_ask", None)),
            "call_volume": format_option_integer(getattr(row, "call_volume", None)),
            "call_open_interest": format_option_integer(getattr(row, "call_open_interest", None)),
            "call_iv": format_option_iv(getattr(row, "call_iv", None)),
            "strike": format_option_price(getattr(row, "strike", None)),
            "put_iv": format_option_iv(getattr(row, "put_iv", None)),
            "put_open_interest": format_option_integer(getattr(row, "put_open_interest", None)),
            "put_volume": format_option_integer(getattr(row, "put_volume", None)),
            "put_bid": format_option_price(getattr(row, "put_bid", None)),
            "put_ask": format_option_price(getattr(row, "put_ask", None)),
            "put_last": format_option_price(getattr(row, "put_last", None)),
        })
    return rows


def candidate_has_usable_gex_data(options: pd.DataFrame, underlying: dict) -> bool:
    spot_price = float(
        underlying.get("regularMarketPrice")
        or underlying.get("postMarketPrice")
        or underlying.get("preMarketPrice")
        or underlying.get("previousClose")
        or 0.0
    )
    if spot_price <= 0:
        return False

    working = options.copy()
    working["strike"] = pd.to_numeric(working.get("strike"), errors="coerce")
    working["open_interest"] = pd.to_numeric(working.get("open_interest"), errors="coerce").fillna(0.0)
    working["implied_volatility"] = pd.to_numeric(working.get("implied_volatility"), errors="coerce")
    working = working.dropna(subset=["strike", "implied_volatility"])
    working = working[
        (working["strike"] > 0) &
        (working["implied_volatility"] > 0) &
        (working["open_interest"] > 0) &
        (working["strike"] >= spot_price - GEX_STRIKE_WINDOW) &
        (working["strike"] <= spot_price + GEX_STRIKE_WINDOW)
    ].copy()
    return not working.empty


def build_gex_frame(options: pd.DataFrame, spot_price: float, now_et: pd.Timestamp, expiry_date: dt.date) -> pd.DataFrame:
    expiry_close = pd.Timestamp.combine(expiry_date, dt.time(16, 0)).tz_localize(TIMEZONE)
    time_to_expiry_years = max(
        (expiry_close - now_et).total_seconds(),
        GEX_MIN_TIME_SECONDS,
    ) / (365.0 * 24.0 * 60.0 * 60.0)

    working = options.copy()
    working["strike"] = pd.to_numeric(working.get("strike"), errors="coerce")
    working["open_interest"] = pd.to_numeric(working.get("open_interest"), errors="coerce").fillna(0.0)
    working["implied_volatility"] = pd.to_numeric(working.get("implied_volatility"), errors="coerce")
    working["volume"] = pd.to_numeric(working.get("volume"), errors="coerce").fillna(0.0)
    working["last_price"] = pd.to_numeric(working.get("last_price"), errors="coerce")
    working = working.dropna(subset=["strike", "implied_volatility"])
    working = working[(working["strike"] > 0) & (working["implied_volatility"] > 0)].copy()
    if working.empty:
        raise ValueError("No SPX options had both strike and implied volatility for GEX calculation.")

    working["gamma"] = working.apply(
        lambda row: black_scholes_gamma(
            spot=spot_price,
            strike=float(row["strike"]),
            volatility=float(row["implied_volatility"]),
            time_to_expiry=time_to_expiry_years,
        ),
        axis=1,
    )
    working["direction"] = working["option_type"].map({"call": 1.0, "put": -1.0}).fillna(0.0)
    working["gex"] = (
        working["gamma"]
        * working["open_interest"]
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
            total_oi=("open_interest", "sum"),
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
    now_et = debug_as_of_timestamp(settings) or pd.Timestamp.now(tz=TIMEZONE)
    gex_snapshot = get_net_gex_snapshot(now_et)
    terminal_snapshot = run_web_service(settings)
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
        "subtitle": (
            f"Current date: {now_et.date().isoformat()} | "
            f"Expiration: {expiration_date.isoformat()} | "
            f"Last update: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        ),
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
        "trade": terminal_snapshot.get("trade", "NO TRADE"),
        "error": None,
    }


def run_option_chain_service(settings: dict) -> dict:
    now_et = debug_as_of_timestamp(settings) or pd.Timestamp.now(tz=TIMEZONE)
    options, underlying, expiration_date, snapshot_ts = fetch_spx_option_chain_for_session(now_et)
    terminal_snapshot = run_web_service(settings)
    rows = build_option_chain_rows(options)
    if not rows:
        raise ValueError("No option-chain rows were available in the latest stored SPX snapshot.")

    spot_price = float(
        underlying.get("regularMarketPrice")
        or underlying.get("postMarketPrice")
        or underlying.get("preMarketPrice")
        or underlying.get("previousClose")
        or 0.0
    )
    call_open_interest = pd.to_numeric(
        options.loc[options["option_type"] == "call", "open_interest"],
        errors="coerce",
    ).fillna(0.0).sum()
    put_open_interest = pd.to_numeric(
        options.loc[options["option_type"] == "put", "open_interest"],
        errors="coerce",
    ).fillna(0.0).sum()
    snapshot_ts_et = pd.Timestamp(snapshot_ts, tz="UTC").tz_convert(TIMEZONE)

    return {
        "subtitle": (
            f"Current date: {now_et.date().isoformat()} | "
            f"Expiration: {expiration_date.isoformat()} | "
            f"Snapshot: {snapshot_ts_et.strftime('%Y-%m-%d %H:%M:%S %Z')} | "
            f"Last update: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        ),
        "expiration_date": expiration_date.isoformat(),
        "snapshot_time": snapshot_ts_et.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "spot_price": "N/A" if spot_price <= 0 else f"{spot_price:,.2f}",
        "contract_count": f"{len(options):,}",
        "call_open_interest": f"{int(round(call_open_interest)):,}",
        "put_open_interest": f"{int(round(put_open_interest)):,}",
        "rows": rows,
        "refresh_interval": settings["refresh_interval"],
        "chart_interval": settings["chart_interval"],
        "source_table": OPTION_SOURCE_TABLE,
        "trade": terminal_snapshot.get("trade", "NO TRADE"),
        "error": None,
    }


def run_simulator_service(
    settings: dict,
    raw_ticker: Optional[str],
    raw_trade_date: Optional[str],
    raw_speed: Optional[str],
    raw_points: Optional[str],
    raw_wide: Optional[str],
    raw_execute_time: Optional[str],
    raw_execution_end_time: Optional[str],
) -> dict:
    ticker = normalize_simulator_ticker(raw_ticker)
    try:
        speed = float(raw_speed) if raw_speed not in {None, ""} else float(settings.get("simulator_speed", 60.0))
    except Exception:
        speed = float(settings.get("simulator_speed", 60.0))
    speed = max(0.5, min(360.0, speed))
    try:
        points = float(raw_points) if raw_points not in {None, ""} else float(settings.get("simulator_points", 70.0))
    except Exception:
        points = float(settings.get("simulator_points", 70.0))
    points = max(0.0, points)
    try:
        wide = float(raw_wide) if raw_wide not in {None, ""} else float(settings.get("simulator_wide", 20.0))
    except Exception:
        wide = float(settings.get("simulator_wide", 20.0))
    wide = max(0.0, wide)
    execute_time = normalize_execute_time(raw_execute_time if raw_execute_time not in {None, ""} else settings.get("simulator_execute_time", "10:30"))
    execution_end_time = normalize_execution_end_time(raw_execution_end_time if raw_execution_end_time not in {None, ""} else settings.get("simulator_execution_end_time", "14:00"))

    if not raw_trade_date:
        raise ValueError("Select a simulator date.")

    try:
        trade_date = dt.date.fromisoformat(raw_trade_date)
    except ValueError as exc:
        raise ValueError("Invalid simulator date. Use YYYY-MM-DD.") from exc

    with get_connection() as conn:
        latest_trade_date = get_latest_trade_date(conn, ticker, INTERVAL_NAME)
        if latest_trade_date is None:
            raise ValueError(f"No {ticker} rows were found in {SOURCE_TABLE}.")

        day_rows = query_ticker_day(conn, ticker, INTERVAL_NAME, trade_date)
        today = pd.Timestamp.now(tz=TIMEZONE).date()
        if (
            day_rows.empty
            and not settings.get("debug_mode", False)
            and trade_date == today
            and latest_trade_date < trade_date
        ):
            trade_date = latest_trade_date
            day_rows = query_ticker_day(conn, ticker, INTERVAL_NAME, trade_date)

    payload = build_simulator_payload(day_rows)
    if not payload:
        raise ValueError(f"No intraday {ticker} candles were found in {SOURCE_TABLE} for {trade_date.isoformat()}.")

    terminal_snapshot = run_web_service(settings)
    return {
        "subtitle": (
            f"Oracle playback for {ticker} | "
            f"Date: {trade_date.isoformat()} | "
            "5-minute candles | Stops at 16:00"
        ),
        "ticker": ticker,
        "trade_date": trade_date.isoformat(),
        "speed": format_option_price(speed),
        "speed_label": f"{speed:g}x",
        "speed_js": json.dumps(speed),
        "points": format_option_price(points),
        "points_label": f"{points:,.0f}",
        "points_js": json.dumps(points),
        "wide": format_option_price(wide),
        "wide_label": f"{wide:,.0f}",
        "wide_js": json.dumps(wide),
        "execute_time": execute_time,
        "execution_end_time": execution_end_time,
        "simulator_payload": json.dumps(payload),
        "trade": terminal_snapshot.get("trade", "NO TRADE"),
        "error": None,
    }


def make_gex_notice(message: str) -> str:
    return (
        "<div style='min-height:520px;display:flex;align-items:center;justify-content:center;"
        "color:#b42318;font-size:22px;font-weight:700;'>"
        f"{message}"
        "</div>"
    )


def get_net_gex_snapshot(now_et: Optional[pd.Timestamp] = None) -> dict:
    now_et = now_et or pd.Timestamp.now(tz=TIMEZONE)
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

    df.columns = [c.lower() for c in df.columns]
    if df.empty:
        if "ts" not in df.columns:
            df["ts"] = pd.to_datetime([])
        return df

    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    df["ts"] = df["ts_utc"].dt.tz_convert(TIMEZONE).dt.tz_localize(None)
    return df.sort_values("ts").reset_index(drop=True)


def normalize_simulator_ticker(raw_ticker: Optional[str]) -> str:
    ticker = (raw_ticker or "").strip()
    if not ticker:
        return SPX_TICKER

    normalized = ticker.upper()
    aliases = {
        "SPX": SPX_TICKER,
        "GSPC": SPX_TICKER,
    }
    return aliases.get(normalized, ticker)


def get_latest_trade_date(conn, ticker: str, interval_name: str) -> Optional[dt.date]:
    sql = f"""
        SELECT MAX(ts_utc)
        FROM {SOURCE_TABLE}
        WHERE ticker = :ticker
          AND interval_name = :interval_name
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, {"ticker": ticker, "interval_name": interval_name})
        row = cur.fetchone()
    finally:
        cur.close()

    if row is None or row[0] is None:
        return None

    return pd.Timestamp(row[0], tz="UTC").tz_convert(TIMEZONE).date()


def query_ticker_day(conn, ticker: str, interval_name: str, trade_date: dt.date) -> pd.DataFrame:
    start_et = pd.Timestamp.combine(trade_date, dt.time(0, 0)).tz_localize(TIMEZONE)
    end_et = start_et + pd.Timedelta(days=1)
    start_utc = start_et.tz_convert("UTC").tz_localize(None)
    end_utc = end_et.tz_convert("UTC").tz_localize(None)

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
          AND ts_utc < :end_utc
        ORDER BY ts_utc
    """
    df = pd.read_sql(
        sql,
        conn,
        params={
            "ticker": ticker,
            "interval_name": interval_name,
            "start_utc": start_utc,
            "end_utc": end_utc,
        },
    )
    if df.empty:
        return df

    df.columns = [c.lower() for c in df.columns]
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    df["ts"] = df["ts_utc"].dt.tz_convert(TIMEZONE).dt.tz_localize(None)
    return df.sort_values("ts").reset_index(drop=True)


def build_simulator_payload(df: pd.DataFrame) -> list[dict]:
    if df.empty or "ts" not in df.columns:
        return []

    working = df.copy()
    working = working[intraday_session_mask(working["ts"])].copy()
    working = working[working["ts"].dt.time <= dt.time(16, 0)].copy()
    working = working.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    if working.empty:
        return []

    working = (
        working[["ts", "open_price", "high_price", "low_price", "close_price", "volume"]]
        .resample("5min", on="ts", label="left", closed="left")
        .agg({
            "open_price": "first",
            "high_price": "max",
            "low_price": "min",
            "close_price": "last",
            "volume": "sum",
        })
        .dropna(subset=["open_price", "high_price", "low_price", "close_price"])
        .reset_index()
    )
    working = working[working["ts"].dt.time <= dt.time(15, 55)].copy()
    if working.empty:
        return []

    rows: list[dict] = []
    for row in working.itertuples(index=False):
        rows.append({
            "label": row.ts.strftime("%H:%M"),
            "open": float(row.open_price),
            "high": float(row.high_price),
            "low": float(row.low_price),
            "close": float(row.close_price),
            "first_move": random.choice(["high", "low"]),
        })
    return rows


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


def chart_interval_minutes(chart_interval: str) -> int:
    return {"5min": 5, "15min": 15, "1h": 60}.get(chart_interval, 5)


def rolling_regular_session_candle_count(chart_interval: str) -> int:
    regular_session_minutes = 390
    interval_minutes = chart_interval_minutes(chart_interval)
    full_session_candles = math.floor(regular_session_minutes / interval_minutes) + 1
    return max(1, math.ceil(full_session_candles * 1.1))


def market_status_info(now_et: pd.Timestamp) -> dict:
    market_open = dt.time(9, 30)
    market_close = dt.time(16, 0)
    is_weekday = now_et.weekday() < 5
    is_open = is_weekday and market_open <= now_et.time() < market_close
    return {
        "market_status": "MARKET OPEN" if is_open else "MARKET CLOSED",
        "market_status_class": "green" if is_open else "yellow",
        "market_hours": "TRADING HOURS - 09:30 AM - 04:00 PM ET",
    }


def debug_as_of_timestamp(settings: dict) -> Optional[pd.Timestamp]:
    if not settings.get("debug_mode"):
        return None
    raw_date = str(settings.get("debug_trade_date", "") or "").strip()
    raw_time = str(settings.get("debug_time", "") or "").strip()
    if not raw_date or not raw_time:
        return None
    try:
        parsed = pd.Timestamp(f"{raw_date} {raw_time}", tz=TIMEZONE)
    except Exception:
        return None
    return parsed


def make_chart(
    spx_1m: pd.DataFrame,
    range_high: float,
    range_low: float,
    prev_day_high: float,
    prev_day_low: float,
    prev_day_open: float,
    prev_day_close: float,
    current_price: float,
    chart_interval: str,
    start_of_day: pd.Timestamp,
) -> str:
    interval_map = {"5min": "5min", "15min": "15min", "1h": "1h"}
    label_map = {"5min": "5 Minute", "15min": "15 Minute", "1h": "1 Hour"}
    tick_minute_step = {"5min": 60, "15min": 60, "1h": 60}
    resample_rule = interval_map.get(chart_interval, "5min")
    label_every = tick_minute_step.get(chart_interval, 60)

    working = spx_1m.copy()
    working = working.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    working = working[intraday_session_mask(working["ts"])].copy()

    if working.empty:
        return "<div style='padding:20px;color:#ff5d5d;'>No chart data available.</div>"

    spx_resampled = (
        working[["ts", "open_price", "high_price", "low_price", "close_price", "volume", "ema9_spx", "ema21_spx", "vwap_spx_proxy"]]
        .resample(resample_rule, on="ts", label="right", closed="right")
        .agg({
            "open_price": "first",
            "high_price": "max",
            "low_price": "min",
            "close_price": "last",
            "volume": "sum",
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
    spx_resampled = spx_resampled.tail(rolling_regular_session_candle_count(chart_interval)).reset_index(drop=True)
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
        ticktext.append("09:30")

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

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.82, 0.18],
        vertical_spacing=0.02,
    )
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
    ), row=1, col=1)
    volume_colors = [
        "#1cff73" if close >= open_ else "#ff3148"
        for open_, close in zip(spx_resampled["open_price"], spx_resampled["close_price"])
    ]
    fig.add_trace(go.Bar(
        x=spx_resampled["xpos"],
        y=spx_resampled["volume"],
        name="Volume",
        marker=dict(color=volume_colors, opacity=0.38),
        hoverinfo="skip",
        showlegend=False,
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=spx_resampled["xpos"],
        y=spx_resampled["vwap_spx_proxy"],
        mode="lines",
        name="SPX VWAP Proxy",
        hoverinfo="skip",
        hovertemplate=None,
        line=dict(color="#9b87f5", width=2),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=spx_resampled["xpos"],
        y=spx_resampled["ema9_spx"],
        mode="lines",
        name="EMA9",
        hoverinfo="skip",
        hovertemplate=None,
        line=dict(color="#00cc96", width=1.8),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=spx_resampled["xpos"],
        y=spx_resampled["ema21_spx"],
        mode="lines",
        name="EMA21",
        hoverinfo="skip",
        hovertemplate=None,
        line=dict(color="#ffd166", width=1.8),
    ), row=1, col=1)

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
        y=0.88,
        xref="x",
        yref="paper",
        text="Start Of Day",
        showarrow=False,
        xanchor="left",
        yanchor="top",
        xshift=8,
        font=dict(color="#4da3ff", size=11),
        bgcolor="rgba(23,32,43,0.78)",
        borderpad=2,
    )

    reference_lines = [
        (current_price, "Current", "#42f0ba", "solid"),
        (range_high, "Opening Range High", "#00cc96", "dash"),
        (range_low, "Opening Range Low", "#ef553b", "dash"),
        (prev_day_open, "Prev Day Open", "#8ab1ba", "dot"),
        (prev_day_close, "Prev Day Close", "#b5e9f0", "dot"),
        (prev_day_high, "Prev Day High", "#ffd166", "dot"),
        (prev_day_low, "Prev Day Low", "#4da3ff", "dot"),
    ]
    for y, name, color, dash in reference_lines:
        if y is None or pd.isna(y):
            continue
        fig.add_trace(go.Scatter(
            x=[0, len(spx_resampled) - 1],
            y=[y, y],
            mode="lines",
            name=f"{name} {y:,.0f}",
            hoverinfo="skip",
            hovertemplate=None,
            line=dict(color=color, width=1.5, dash=dash),
        ), row=1, col=1)

    fig.update_layout(
        margin=dict(l=18, r=58, t=18, b=28),
        paper_bgcolor="#17202b",
        plot_bgcolor="#17202b",
        font=dict(color="#e8eef7"),
        xaxis=dict(
            type="linear",
            showgrid=False,
            rangeslider=dict(visible=False),
            title="",
            title_standoff=4,
            range=[-0.75, len(spx_resampled) - 0.25],
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            tickangle=0,
            tickfont=dict(size=9),
            automargin=True,
            fixedrange=False,
            showline=False,
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=False,
            title="",
            title_standoff=4,
            automargin=True,
            fixedrange=False,
            side="right",
            showline=False,
            zeroline=False,
        ),
        xaxis2=dict(
            type="linear",
            showgrid=False,
            title="",
            range=[-0.75, len(spx_resampled) - 0.25],
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            tickangle=0,
            tickfont=dict(size=9),
            automargin=True,
            fixedrange=False,
            showline=False,
            zeroline=False,
        ),
        yaxis2=dict(
            showgrid=False,
            title="",
            side="right",
            showticklabels=False,
            fixedrange=True,
            showline=False,
            zeroline=False,
        ),
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.08,
            bgcolor="rgba(5,13,17,0.62)",
            bordercolor="rgba(0,229,240,0.16)",
            borderwidth=1,
            font=dict(size=10),
            itemclick="toggle",
            itemdoubleclick="toggleothers",
        ),
        showlegend=False,
        hovermode="closest",
        hoverlabel=dict(bgcolor="#0f141b", bordercolor="#273244", font=dict(color="#e8eef7")),
        hoverdistance=20,
        bargap=0.08,
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
    var labelsVisible = false;

    if (!gd.style.position) gd.style.position = 'relative';

    var legendButton = document.createElement('button');
    legendButton.type = 'button';
    legendButton.textContent = 'Labels +';
    legendButton.setAttribute('aria-label', 'Toggle chart labels');
    legendButton.style.position = 'absolute';
    legendButton.style.left = '8px';
    legendButton.style.top = '8px';
    legendButton.style.zIndex = '30';
    legendButton.style.border = '1px solid rgba(0,229,240,.3)';
    legendButton.style.background = 'rgba(5,13,17,.76)';
    legendButton.style.color = '#00e5f0';
    legendButton.style.font = '700 10px Segoe UI, Arial, sans-serif';
    legendButton.style.textTransform = 'uppercase';
    legendButton.style.padding = '4px 7px';
    legendButton.style.cursor = 'pointer';
    legendButton.addEventListener('click', function(event) {{
        event.preventDefault();
        labelsVisible = !labelsVisible;
        legendButton.textContent = labelsVisible ? 'Labels -' : 'Labels +';
        if (window.Plotly) Plotly.relayout(gd, {{showlegend: labelsVisible}});
    }});
    gd.appendChild(legendButton);

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
    as_of_et = debug_as_of_timestamp(settings)
    now_et = as_of_et or pd.Timestamp.now(tz=TIMEZONE)
    now = now_et.strftime("%Y-%m-%d %H:%M:%S")
    start_utc = now_et.tz_convert("UTC").to_pydatetime() - dt.timedelta(days=LOOKBACK_DAYS)
    current_et_date = now_et.date()
    market_info = market_status_info(now_et)
    net_gex_billions = "N/A"
    net_gex_date = ""
    net_gex_class = ""
    net_gex_signal_class = "yellow"
    net_gex_subtext = "Stored options snapshot unavailable"

    with get_connection() as conn:
        spx = query_ticker_history(conn, SPX_TICKER, INTERVAL_NAME, start_utc)
        spy = query_ticker_history(conn, SPY_TICKER, INTERVAL_NAME, start_utc)

    if spx.empty:
        return {"time": now, "error": f"No {SPX_TICKER} rows found in {SOURCE_TABLE}.", **settings}
    if spy.empty:
        return {"time": now, "error": f"No {SPY_TICKER} rows found in {SOURCE_TABLE}.", **settings}

    spx = spx.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    spy = spy.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    if as_of_et is not None:
        as_of_naive = as_of_et.tz_localize(None)
        spx = spx[spx["ts"] <= as_of_naive].copy()
        spy = spy[spy["ts"] <= as_of_naive].copy()

    spy["trade_date"] = spy["ts"].dt.date
    spx["trade_date"] = spx["ts"].dt.date
    spx["ema9_spx"] = spx["close_price"].ewm(span=9, adjust=False).mean()
    spx["ema21_spx"] = spx["close_price"].ewm(span=21, adjust=False).mean()
    spx_regular = spx[intraday_session_mask(spx["ts"])].copy()
    spy_regular = spy[intraday_session_mask(spy["ts"])].copy()
    if spx_regular.empty or spy_regular.empty:
        return {"time": now, "error": f"No regular-session rows found in {SOURCE_TABLE} for the selected time.", **settings}

    current_date = spx_regular["ts"].max().date()
    prior_dates = sorted({x.date() for x in spx_regular["ts"] if x.date() < current_date})
    if not prior_dates:
        return {"time": now, "error": f"Need at least two trading days in {SOURCE_TABLE}.", **settings}
    prev_date = prior_dates[-1]

    spx_current = spx[spx["ts"].dt.date == current_date].copy()
    spy_current = spy[spy["ts"].dt.date == current_date].copy()
    spx_prev = spx[spx["ts"].dt.date == prev_date].copy()
    spy_prev = spy[spy["ts"].dt.date == prev_date].copy()

    if spx_current.empty or spy_current.empty or spx_prev.empty or spy_prev.empty:
        return {"time": now, "error": f"Could not separate current/prior session data from {SOURCE_TABLE}.", **settings}

    spy_session = spy_regular.copy()
    spx_session = spx_regular.copy()

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
    prev_close = last_valid_number(chart_spx[chart_spx["ts"].dt.date == prev_date]["close_price"])
    prev_open = first_valid_number(chart_spx[chart_spx["ts"].dt.date == prev_date]["open_price"])

    if None in {latest_price, latest_ema9, latest_ema21, open_price, latest_vwap, prev_close, prev_open}:
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
    daily_change = latest_price - prev_close
    daily_change_pct = daily_change / prev_close * 100.0 if prev_close else float("nan")

    vwap_distance = pd.notna(vwap_distance_pct) and vwap_distance_pct >= 0.15
    open_distance = pd.notna(open_distance_pct) and open_distance_pct > 0.30

    bullish = (latest_price > open_price) and (latest_price > latest_vwap) and (latest_ema9 > latest_ema21)
    bearish = (latest_price < open_price) and (latest_price < latest_vwap) and (latest_ema9 < latest_ema21)
    bias_label = "BULLISH" if bullish else ("BEARISH" if bearish else "NEUTRAL")

    trade = "NO TRADE"
    structure = "No trade today."
    if outside_range and vwap_distance and open_distance:
        if bullish:
            trade = "SELL PUT SPREAD"
            structure = "Sell 10 put credit spreads, 20 points wide, short strike near 0.10 delta, stop at 2x credit received."
        elif bearish:
            trade = "SELL CALL SPREAD"
            structure = "Sell 10 call credit spreads, 20 points wide, short strike near 0.10 delta, stop at 2x credit received."

    checklist = [
        {
            "label": "Price > VWAP" if not bearish else "Price < VWAP",
            "status": "PASS" if ((latest_price > latest_vwap and not bearish) or (latest_price < latest_vwap and bearish)) else "WATCH",
            "class": "green" if ((latest_price > latest_vwap and not bearish) or (latest_price < latest_vwap and bearish)) else "yellow",
        },
        {
            "label": "EMA9 > EMA21" if not bearish else "EMA9 < EMA21",
            "status": "PASS" if ((latest_ema9 > latest_ema21 and not bearish) or (latest_ema9 < latest_ema21 and bearish)) else "WATCH",
            "class": "green" if ((latest_ema9 > latest_ema21 and not bearish) or (latest_ema9 < latest_ema21 and bearish)) else "yellow",
        },
        {
            "label": "Outside Opening Range",
            "status": "PASS" if outside_range else "WATCH",
            "class": "green" if outside_range else "yellow",
        },
        {
            "label": "Distance from VWAP OK",
            "status": "PASS" if vwap_distance else "WATCH",
            "class": "green" if vwap_distance else "yellow",
        },
    ]
    confidence = int(round(sum(1 for item in checklist if item["status"] == "PASS") / len(checklist) * 100))
    pass_count = sum(1 for item in checklist if item["status"] == "PASS")
    active_signal_bars = int(round(pass_count / len(checklist) * 6))
    signal_bars = [i < active_signal_bars for i in range(6)]
    setup_notes = [
        {
            "label": "Price above VWAP" if latest_price > latest_vwap else "Price below VWAP",
            "class": "green" if ((latest_price > latest_vwap and not bearish) or (latest_price < latest_vwap and bearish)) else "red",
        },
        {
            "label": "EMA9 above EMA21" if latest_ema9 > latest_ema21 else "EMA9 below EMA21",
            "class": "green" if ((latest_ema9 > latest_ema21 and not bearish) or (latest_ema9 < latest_ema21 and bearish)) else "red",
        },
        {
            "label": "Breakout beyond opening range" if outside_range else "Inside opening range",
            "class": "green" if outside_range else "red",
        },
        {
            "label": "VWAP distance threshold met" if vwap_distance else "VWAP distance below threshold",
            "class": "green" if vwap_distance else "red",
        },
    ]

    spy_latest = last_valid_number(spy_current["close_price"]) if not spy_current.empty else None
    strike_points = float(settings.get("simulator_points", 70.0))
    spread_width = float(settings.get("simulator_wide", 20.0))
    if trade == "SELL PUT SPREAD":
        short_strike_value = latest_price - strike_points
        long_strike_value = short_strike_value - spread_width
    elif trade == "SELL CALL SPREAD":
        short_strike_value = latest_price + strike_points
        long_strike_value = short_strike_value + spread_width
    else:
        short_strike_value = None
        long_strike_value = None

    trade_type = "Bull Put Credit Spread" if trade == "SELL PUT SPREAD" else ("Bear Call Credit Spread" if trade == "SELL CALL SPREAD" else "No trade")

    try:
        gex_snapshot = get_net_gex_snapshot(now_et)
        net_gex = gex_snapshot["net_gex"]
        net_gex_billions = format_billions(net_gex)
        expiration_date = gex_snapshot["expiration_date"]
        if expiration_date > current_et_date:
            net_gex_date = expiration_date.isoformat()
        if net_gex > 0:
            net_gex_class = "gex-positive"
            net_gex_signal_class = "green"
            net_gex_subtext = "Positive gamma regime"
        elif net_gex < 0:
            net_gex_class = "gex-negative"
            net_gex_signal_class = "red"
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
        prev_open,
        prev_close,
        latest_price,
        settings["chart_interval"],
        pd.Timestamp(spx_current["ts"].min()),
    )

    return {
        "time": now,
        "header_time": now_et.strftime("%I:%M:%S %p").lstrip("0"),
        "header_date": now_et.strftime("%b %d, %Y").upper(),
        "header_weekday": now_et.strftime("%a").upper(),
        "price": int(round(latest_price, 0)),
        "price_display": f"{latest_price:,.2f}",
        "vwap": int(round(latest_vwap, 0)),
        "ema9": int(round(latest_ema9, 0)),
        "ema21": int(round(latest_ema21, 0)),
        "open_price": int(round(open_price, 0)),
        "range_high": int(round(range_high, 0)),
        "range_low": int(round(range_low, 0)),
        "prev_day_open": int(round(prev_open, 0)),
        "prev_day_close": int(round(prev_close, 0)),
        "prev_day_high": int(round(prev_day_high, 0)),
        "prev_day_low": int(round(prev_day_low, 0)),
        "current_day_high": int(round(current_day_high, 0)),
        "current_day_low": int(round(current_day_low, 0)),
        "last_update_date": current_et_date.isoformat(),
        "last_update_timestamp": now_et.strftime("%Y-%m-%d %H:%M:%S"),
        "spy_price": "N/A" if spy_latest is None else f"{spy_latest:,.2f}",
        "daily_change": f"{daily_change:+,.2f}",
        "daily_change_pct": "N/A" if pd.isna(daily_change_pct) else f"{daily_change_pct:+.2f}",
        "daily_change_class": "green" if daily_change >= 0 else "red",
        "vwap_distance_pct": "N/A" if pd.isna(vwap_distance_pct) else round(vwap_distance_pct, 3),
        "open_distance_pct": "N/A" if pd.isna(open_distance_pct) else round(open_distance_pct, 3),
        "outside_range": outside_range,
        "vwap_distance": vwap_distance,
        "open_distance": open_distance,
        "net_gex_billions": net_gex_billions,
        "net_gex_date": net_gex_date,
        "net_gex_class": net_gex_class,
        "net_gex_signal_class": net_gex_signal_class,
        "net_gex_subtext": net_gex_subtext,
        **market_info,
        "bullish": bullish,
        "bearish": bearish,
        "bias_label": bias_label,
        "confidence": confidence,
        "signal_bars": signal_bars,
        "setup_notes": setup_notes,
        "checklist": checklist,
        "trade": trade,
        "trade_type": trade_type,
        "short_strike": "N/A" if short_strike_value is None else f"{short_strike_value:,.0f}",
        "long_strike": "N/A" if long_strike_value is None else f"{long_strike_value:,.0f}",
        "credit": "Needs option Greeks/selection",
        "max_profit": "N/A",
        "max_risk": "N/A",
        "structure": structure,
        "chart_html": chart_html,
        "refresh_interval": settings["refresh_interval"],
        "chart_interval": settings["chart_interval"],
        "debug_mode": settings.get("debug_mode", False),
        "debug_trade_date": settings.get("debug_trade_date", ""),
        "debug_time": settings.get("debug_time", ""),
        "debug_time_options": DEBUG_TIME_OPTIONS,
        "source_table": SOURCE_TABLE,
        "error": None,
    }


def ensure_terminal_display_data(data: dict) -> dict:
    defaults = {
        "header_time": "",
        "header_date": "",
        "header_weekday": "",
        "price": "N/A",
        "price_display": "N/A",
        "spy_price": "N/A",
        "vwap": "N/A",
        "open_price": "N/A",
        "ema9": "N/A",
        "ema21": "N/A",
        "range_high": "N/A",
        "range_low": "N/A",
        "prev_day_open": "N/A",
        "prev_day_close": "N/A",
        "prev_day_high": "N/A",
        "prev_day_low": "N/A",
        "current_day_high": "N/A",
        "current_day_low": "N/A",
        "last_update_date": dt.date.today().isoformat(),
        "last_update_timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "daily_change": "N/A",
        "daily_change_pct": "N/A",
        "daily_change_class": "yellow",
        "vwap_distance_pct": "N/A",
        "open_distance_pct": "N/A",
        "bias_label": "NEUTRAL",
        "confidence": 0,
        "signal_bars": [False, False, False, False, False, False],
        "setup_notes": [{"label": "Waiting for Oracle market data", "class": "red"}],
        "checklist": [{"label": "Oracle data available", "status": "WATCH", "class": "yellow"}],
        "trade": "NO TRADE",
        "trade_type": "No trade",
        "short_strike": "N/A",
        "long_strike": "N/A",
        "credit": "N/A",
        "max_profit": "N/A",
        "max_risk": "N/A",
        "net_gex_billions": "N/A",
        "net_gex_signal_class": "yellow",
        "market_status": "MARKET CLOSED",
        "market_status_class": "yellow",
        "market_hours": "TRADING HOURS - 09:30 AM - 04:00 PM ET",
        "refresh_interval": DEFAULT_SETTINGS["refresh_interval"],
        "chart_interval": DEFAULT_SETTINGS["chart_interval"],
        "debug_mode": False,
        "debug_trade_date": "",
        "debug_max_date": dt.date.today().isoformat(),
        "debug_control_date": dt.date.today().isoformat(),
        "debug_time": "",
        "debug_control_time": dt.datetime.now().strftime("%H:%M"),
        "debug_time_options": DEBUG_TIME_OPTIONS,
        "chart_html": "",
        "source_table": SOURCE_TABLE,
        "active_tab": "terminal",
        "page_content": "",
        "page_script": "",
    }
    for key, value in defaults.items():
        data.setdefault(key, value)
    now_et = pd.Timestamp.now(tz=TIMEZONE)
    today = now_et.date().isoformat()
    current_time = now_et.strftime("%H:%M")
    saved_debug_date = normalize_debug_trade_date(data.get("debug_trade_date", ""), today)
    saved_debug_time = normalize_simulator_time(data.get("debug_time", ""), "")
    data["debug_trade_date"] = saved_debug_date
    data["debug_max_date"] = today
    data["debug_control_date"] = (saved_debug_date or today) if data.get("debug_mode", False) else today
    data["debug_control_time"] = (saved_debug_time or current_time) if data.get("debug_mode", False) else current_time
    return data


def add_terminal_chrome_data(settings: dict, page_data: dict, active_tab: str) -> dict:
    try:
        chrome_data = ensure_terminal_display_data(run_web_service(settings))
    except Exception:
        chrome_data = ensure_terminal_display_data({})

    merged = chrome_data.copy()
    merged.update(page_data)
    merged["active_tab"] = active_tab
    merged["refresh_interval"] = settings.get("refresh_interval", DEFAULT_SETTINGS["refresh_interval"])
    merged["chart_interval"] = settings.get("chart_interval", DEFAULT_SETTINGS["chart_interval"])
    merged["debug_mode"] = settings.get("debug_mode", False)
    merged["debug_trade_date"] = settings.get("debug_trade_date", "")
    merged["debug_time"] = settings.get("debug_time", "")
    merged["debug_control_time"] = settings.get("debug_control_time", "")
    merged["debug_time_options"] = DEBUG_TIME_OPTIONS
    return ensure_terminal_display_data(merged)


def render_terminal_page(
    content_template: str,
    data: dict,
    active_tab: str,
    page_script_template: str = "",
) -> str:
    data = ensure_terminal_display_data(data)
    data["active_tab"] = active_tab
    data["page_content"] = "" if data.get("error") else render_template_string(content_template, data=data)
    data["page_script"] = ""
    if page_script_template and not data.get("error"):
        data["page_script"] = render_template_string(page_script_template, data=data)
    return render_template_string(
        TERMINAL_PAGE_HTML,
        data=data,
        terminal_style=TERMINAL_STYLE,
        favicon_version=FAVICON_VERSION,
    )


def get_simulator_effective_trade_date(settings: dict) -> str:
    today = pd.Timestamp.now(tz=TIMEZONE).date().isoformat()
    if not settings.get("debug_mode", False):
        return today
    return str(settings.get("debug_trade_date", "") or "").strip() or today


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

    debug_mode_values = request.form.getlist("debug_mode")
    if debug_mode_values:
        debug_mode = str(debug_mode_values[-1]) == "1"
    else:
        debug_mode = bool(current.get("debug_mode", False))
    today = pd.Timestamp.now(tz=TIMEZONE).date().isoformat()
    debug_trade_date = normalize_debug_trade_date(
        request.form.get("debug_trade_date", current.get("debug_trade_date", "")),
        today,
    )
    debug_time = normalize_simulator_time(request.form.get("debug_time", current.get("debug_time", "")), "")

    try:
        simulator_speed = float(request.form.get("simulator_speed", current.get("simulator_speed", 60.0)))
    except Exception:
        simulator_speed = current.get("simulator_speed", 60.0)
    simulator_speed = max(0.5, min(360.0, simulator_speed))

    try:
        simulator_points = float(request.form.get("simulator_points", current.get("simulator_points", 70.0)))
    except Exception:
        simulator_points = current.get("simulator_points", 70.0)
    simulator_points = max(0.0, simulator_points)

    try:
        simulator_wide = float(request.form.get("simulator_wide", current.get("simulator_wide", 20.0)))
    except Exception:
        simulator_wide = current.get("simulator_wide", 20.0)
    simulator_wide = max(0.0, simulator_wide)

    simulator_trade_date = str(request.form.get("simulator_trade_date", current.get("simulator_trade_date", "")) or "")
    simulator_execute_time = normalize_execute_time(request.form.get("simulator_execute_time", current.get("simulator_execute_time", "10:30")))
    simulator_execution_end_time = normalize_execution_end_time(request.form.get("simulator_execution_end_time", current.get("simulator_execution_end_time", "14:00")))

    save_settings({
        "refresh_interval": max(15, min(3600, refresh_interval)),
        "chart_interval": chart_interval,
        "debug_mode": debug_mode,
        "debug_trade_date": debug_trade_date,
        "debug_time": debug_time,
        "simulator_speed": simulator_speed,
        "simulator_points": simulator_points,
        "simulator_wide": simulator_wide,
        "simulator_trade_date": simulator_trade_date,
        "simulator_execute_time": simulator_execute_time,
        "simulator_execution_end_time": simulator_execution_end_time,
    })
    return ("", 204)


@app.route("/favicon.svg")
def favicon_svg():
    return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")


@app.route("/favicon.ico")
def favicon_ico():
    return ("", 204)


@app.route("/")
def index():
    settings = load_settings()
    data = ensure_terminal_display_data(run_web_service(settings))
    return render_template_string(TERMINAL_HTML, data=data, favicon_version=FAVICON_VERSION)


@app.route("/terminal")
def modern_terminal():
    settings = load_settings()
    data = ensure_terminal_display_data(run_web_service(settings))
    return render_template_string(TERMINAL_HTML, data=data, favicon_version=FAVICON_VERSION)


@app.route("/hud")
def hud():
    settings = load_settings()
    data = ensure_terminal_display_data(run_web_service(settings))
    return render_template_string(TERMINAL_HTML, data=data, favicon_version=FAVICON_VERSION)


@app.route("/gex")
def gex():
    settings = load_settings()
    try:
        data = run_gex_service(settings)
    except NoOpenInterestInFeedError as exc:
        now_et = debug_as_of_timestamp(settings) or pd.Timestamp.now(tz=TIMEZONE)
        terminal_snapshot = run_web_service(settings)
        underlying = exc.underlying or {}
        spot_price = float(
            underlying.get("regularMarketPrice")
            or underlying.get("postMarketPrice")
            or underlying.get("preMarketPrice")
            or underlying.get("previousClose")
            or 0.0
        )
        expiration_date = exc.expiration_date or now_et.date()
        data = {
            "subtitle": (
                f"Current date: {now_et.date().isoformat()} | "
                f"Expiration: {expiration_date.isoformat()} | "
                f"Last update: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            ),
            "requested_date": now_et.date().isoformat(),
            "expiration_date": expiration_date.isoformat(),
            "spot_price": "N/A" if spot_price <= 0 else f"{spot_price:,.2f}",
            "net_gex_billions": "N/A",
            "call_wall": "N/A",
            "put_wall": "N/A",
            "chart_html": make_gex_notice("No Open Interest In Feed"),
            "refresh_interval": settings["refresh_interval"],
            "chart_interval": settings["chart_interval"],
            "min_time_minutes": max(GEX_MIN_TIME_SECONDS // 60, 1),
            "trade": terminal_snapshot.get("trade", "NO TRADE"),
            "error": None,
        }
    except Exception as exc:
        now_et = debug_as_of_timestamp(settings) or pd.Timestamp.now(tz=TIMEZONE)
        terminal_snapshot = run_web_service(settings)
        data = {
            "subtitle": (
                f"Current date: {now_et.date().isoformat()} | "
                f"Expiration: {now_et.date().isoformat()} | "
                f"Last update: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            ),
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
            "trade": terminal_snapshot.get("trade", "NO TRADE"),
            "error": str(exc),
        }
    data = add_terminal_chrome_data(settings, data, "gex")
    return render_terminal_page(GEX_TERMINAL_CONTENT, data, "gex")


@app.route("/option-chain")
def option_chain():
    settings = load_settings()
    try:
        data = run_option_chain_service(settings)
    except Exception as exc:
        now_et = debug_as_of_timestamp(settings) or pd.Timestamp.now(tz=TIMEZONE)
        terminal_snapshot = run_web_service(settings)
        data = {
            "subtitle": (
                f"Current date: {now_et.date().isoformat()} | "
                f"Expiration: {now_et.date().isoformat()} | "
                "Snapshot: N/A | "
                f"Last update: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            ),
            "expiration_date": now_et.date().isoformat(),
            "snapshot_time": "N/A",
            "spot_price": "N/A",
            "contract_count": "0",
            "call_open_interest": "0",
            "put_open_interest": "0",
            "rows": [],
            "refresh_interval": settings["refresh_interval"],
            "chart_interval": settings["chart_interval"],
            "source_table": OPTION_SOURCE_TABLE,
            "trade": terminal_snapshot.get("trade", "NO TRADE"),
            "error": str(exc),
        }
    data = add_terminal_chrome_data(settings, data, "option-chain")
    return render_terminal_page(OPTION_CHAIN_TERMINAL_CONTENT, data, "option-chain")


@app.route("/simulator")
def simulator():
    settings = load_settings()
    raw_speed = request.args.get("speed")
    raw_points = request.args.get("points")
    raw_wide = request.args.get("wide")
    raw_execute_time = request.args.get("execute_time")
    raw_execution_end_time = request.args.get("execution_end_time")
    effective_trade_date = get_simulator_effective_trade_date(settings)
    try:
        data = run_simulator_service(
            settings,
            request.args.get("ticker"),
            effective_trade_date,
            raw_speed,
            raw_points,
            raw_wide,
            raw_execute_time,
            raw_execution_end_time,
        )
    except Exception as exc:
        fallback_ticker = normalize_simulator_ticker(request.args.get("ticker"))
        fallback_speed = request.args.get("speed") or format_option_price(settings.get("simulator_speed", 60.0))
        fallback_points = request.args.get("points") or format_option_price(settings.get("simulator_points", 70.0))
        fallback_wide = request.args.get("wide") or format_option_price(settings.get("simulator_wide", 20.0))
        fallback_execute_time = normalize_execute_time(request.args.get("execute_time") or settings.get("simulator_execute_time", "10:30"))
        fallback_execution_end_time = normalize_execution_end_time(request.args.get("execution_end_time") or settings.get("simulator_execution_end_time", "14:00"))
        data = {
            "subtitle": "Oracle playback simulator",
            "ticker": fallback_ticker,
            "trade_date": effective_trade_date or "",
            "speed": fallback_speed,
            "speed_label": f"{fallback_speed}x",
            "speed_js": json.dumps(float(settings.get("simulator_speed", 60.0))),
            "points": fallback_points,
            "points_label": f"{float(fallback_points):,.0f}" if fallback_points not in {"", None} else "70",
            "points_js": json.dumps(float(settings.get("simulator_points", 70.0))),
            "wide": fallback_wide,
            "wide_label": f"{float(fallback_wide):,.0f}" if fallback_wide not in {"", None} else "20",
            "wide_js": json.dumps(float(settings.get("simulator_wide", 20.0))),
            "execute_time": fallback_execute_time,
            "execution_end_time": fallback_execution_end_time,
            "simulator_payload": "[]",
            "trade": run_web_service(settings).get("trade", "NO TRADE"),
            "error": str(exc),
        }
    data = add_terminal_chrome_data(settings, data, "simulator")
    return render_terminal_page(SIMULATOR_TERMINAL_CONTENT, data, "simulator", SIMULATOR_TERMINAL_SCRIPT)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
