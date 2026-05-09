from __future__ import annotations

import os

from flask import Flask, render_template_string, send_from_directory, url_for


app = Flask(__name__)


LANDING_PAGE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#02416d">
    <title>CashFlowArc</title>
    <link rel="icon" href="{{ url_for('static', filename='favicon.svg', v='3') }}" sizes="any" type="image/svg+xml">
    <style>
        :root {
            --canvas: #f5faf7;
            --paper: #ffffff;
            --mint: #e5f4ed;
            --mint-2: #d8eee5;
            --navy: #02416d;
            --deep: #061423;
            --teal: #17b897;
            --teal-dark: #087c7f;
            --blue: #0a6fa7;
            --gold: #f3a31d;
            --coral: #d95d58;
            --ink: #16252d;
            --muted: #66767e;
            --line: rgba(22, 37, 45, 0.14);
            --soft-line: rgba(255, 255, 255, 0.14);
            --shadow: 0 22px 54px rgba(8, 35, 51, 0.14);
        }
        * { box-sizing: border-box; }
        html { min-width: 320px; }
        body {
            margin: 0;
            min-height: 100vh;
            color: var(--ink);
            background:
                linear-gradient(122deg, rgba(2, 65, 109, 0.08) 0 24%, transparent 24% 100%),
                linear-gradient(180deg, #fbfefc 0%, var(--canvas) 48%, #eaf3ef 100%);
            font-family: "Aptos", "Segoe UI", Arial, sans-serif;
            line-height: 1.45;
        }
        a { color: inherit; text-decoration: none; }
        img { display: block; max-width: 100%; }
        .shell {
            min-height: 100vh;
            overflow: hidden;
        }
        .site-header,
        .hero,
        .tools,
        footer {
            width: min(1180px, calc(100% - 40px));
            margin: 0 auto;
        }
        .site-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 20px;
            min-height: 78px;
            padding: 14px 0;
        }
        .brand {
            display: inline-flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
            font-weight: 850;
        }
        .brand img {
            width: 48px;
            height: 48px;
            flex: 0 0 auto;
            border-radius: 8px;
            background: #fff;
            box-shadow: 0 8px 20px rgba(2, 65, 109, 0.13);
        }
        .brand span {
            font-size: 20px;
            line-height: 1;
            white-space: nowrap;
        }
        .nav-links {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.78);
            box-shadow: 0 8px 22px rgba(8, 35, 51, 0.08);
        }
        .nav-links a {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 36px;
            padding: 0 14px;
            border-radius: 6px;
            color: var(--muted);
            font-size: 14px;
            font-weight: 800;
            white-space: nowrap;
        }
        .nav-links a:hover,
        .nav-links a:focus-visible {
            color: var(--ink);
            background: var(--mint);
            outline: 0;
        }
        .hero {
            display: grid;
            grid-template-columns: minmax(0, 0.92fr) minmax(360px, 1.08fr);
            align-items: center;
            gap: 44px;
            padding: 34px 0 32px;
        }
        .hero-copy {
            display: grid;
            gap: 26px;
            align-content: center;
        }
        .hero-mark {
            width: 96px;
            height: 96px;
            border-radius: 8px;
            background: #fff;
            box-shadow: var(--shadow);
        }
        h1,
        h2,
        h3,
        p {
            margin-top: 0;
        }
        h1 {
            margin-bottom: 0;
            max-width: 620px;
            color: var(--deep);
            font-family: "Bahnschrift", "Aptos Display", "Segoe UI", sans-serif;
            font-size: 78px;
            line-height: 0.94;
            letter-spacing: 0;
        }
        .intro {
            max-width: 560px;
            margin: 0;
            color: #425760;
            font-size: 19px;
            line-height: 1.55;
        }
        .actions {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }
        .button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            min-height: 46px;
            padding: 0 18px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #fff;
            color: var(--ink);
            font-weight: 850;
            box-shadow: 0 10px 24px rgba(8, 35, 51, 0.08);
        }
        .button.primary {
            border-color: rgba(2, 65, 109, 0.22);
            background: linear-gradient(135deg, var(--navy), var(--teal-dark));
            color: #fff;
        }
        .button svg {
            width: 17px;
            height: 17px;
            flex: 0 0 auto;
        }
        .summary-row {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            border: 1px solid var(--line);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.74);
            overflow: hidden;
            max-width: 560px;
        }
        .summary-row div {
            min-height: 78px;
            padding: 14px 16px;
            border-left: 1px solid var(--line);
        }
        .summary-row div:first-child { border-left: 0; }
        .summary-row span {
            display: block;
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
        }
        .summary-row strong {
            display: block;
            margin-top: 6px;
            font-size: 20px;
            line-height: 1.15;
        }
        .app-preview {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(0, 0.9fr);
            gap: 16px;
            align-items: stretch;
        }
        .trader-panel,
        .budget-panel,
        .route-card {
            border-radius: 8px;
            box-shadow: var(--shadow);
            overflow: hidden;
        }
        .trader-panel {
            min-height: 520px;
            padding: 18px;
            color: #ecf7ff;
            background:
                linear-gradient(180deg, rgba(12, 27, 48, 0.96), rgba(6, 16, 30, 0.98)),
                var(--deep);
            border: 1px solid rgba(139, 191, 228, 0.24);
        }
        .panel-top {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 14px;
            margin-bottom: 18px;
        }
        .panel-kicker {
            margin: 0 0 6px;
            color: #8dd8ff;
            font-size: 11px;
            font-weight: 850;
            text-transform: uppercase;
        }
        .panel-top h2,
        .budget-panel h2,
        .route-card h3 {
            margin-bottom: 0;
            letter-spacing: 0;
        }
        .panel-top h2 {
            font-size: 26px;
            line-height: 1.05;
        }
        .status-pill {
            flex: 0 0 auto;
            border-radius: 8px;
            background: rgba(23, 184, 151, 0.17);
            color: #9ff5d6;
            border: 1px solid rgba(23, 184, 151, 0.36);
            padding: 8px 10px;
            font-size: 11px;
            font-weight: 850;
            text-transform: uppercase;
        }
        .signal-image {
            height: 148px;
            margin-bottom: 14px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            object-fit: cover;
            background: #0b1627;
        }
        .market-rows,
        .budget-rows {
            display: grid;
            gap: 10px;
        }
        .market-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 12px;
            align-items: center;
            min-height: 50px;
            padding: 10px 12px;
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.035);
        }
        .market-row span,
        .budget-line span,
        .route-card span {
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
        }
        .market-row span {
            color: #91a7c5;
        }
        .market-row strong {
            font-size: 18px;
        }
        .market-row b {
            color: #8ff0bd;
        }
        .budget-panel {
            min-height: 520px;
            padding: 18px;
            background: #fff;
            border: 1px solid #cbd8d2;
        }
        .budget-panel header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding-bottom: 14px;
            border-bottom: 1px solid #d7e1dc;
        }
        .budget-panel h2 {
            font-size: 23px;
        }
        .month-pill {
            border: 1px solid #c0d6cb;
            border-radius: 6px;
            background: var(--mint);
            color: #245d45;
            padding: 7px 10px;
            font-size: 12px;
            font-weight: 850;
            white-space: nowrap;
        }
        .budget-total {
            padding: 20px 0 18px;
            border-bottom: 1px solid #d7e1dc;
        }
        .budget-total span {
            display: block;
            color: var(--muted);
            font-size: 12px;
            font-weight: 850;
        }
        .budget-total strong {
            display: block;
            margin-top: 8px;
            color: #1d3f30;
            font-size: 34px;
            line-height: 1;
        }
        .budget-line {
            display: grid;
            gap: 8px;
            min-height: 70px;
            padding: 13px 0;
            border-bottom: 1px dotted #cfd8d3;
        }
        .budget-line:last-child { border-bottom: 0; }
        .budget-line-header {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            font-weight: 850;
        }
        .meter {
            height: 13px;
            border: 1px solid #cfd8d3;
            background: #eef3f0;
            overflow: hidden;
        }
        .meter i {
            display: block;
            height: 100%;
            background: var(--teal);
        }
        .meter.gold i { background: var(--gold); }
        .meter.coral i { background: var(--coral); }
        .tools {
            padding: 34px 0 54px;
        }
        .section-heading {
            display: flex;
            align-items: end;
            justify-content: space-between;
            gap: 18px;
            margin-bottom: 16px;
        }
        .section-heading h2 {
            margin: 0;
            color: var(--deep);
            font-size: 30px;
            line-height: 1.1;
        }
        .section-heading p {
            max-width: 510px;
            margin: 0;
            color: var(--muted);
        }
        .route-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 16px;
        }
        .route-card {
            min-height: 250px;
            display: grid;
            grid-template-rows: auto 1fr auto;
            padding: 20px;
            border: 1px solid var(--line);
            background: rgba(255, 255, 255, 0.86);
        }
        .route-card.trader {
            color: #eaf6ff;
            border-color: rgba(2, 65, 109, 0.28);
            background:
                linear-gradient(180deg, rgba(10, 28, 48, 0.96), rgba(7, 17, 31, 0.97)),
                var(--deep);
        }
        .route-card.trader span { color: #94abc9; }
        .route-card h3 {
            font-size: 28px;
        }
        .route-card p {
            max-width: 520px;
            margin: 14px 0 0;
            color: inherit;
        }
        .route-card:not(.trader) p {
            color: #485a61;
        }
        .route-footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-top: 22px;
            padding-top: 16px;
            border-top: 1px solid currentColor;
            border-color: rgba(102, 118, 126, 0.22);
            font-weight: 850;
        }
        .route-card.trader .route-footer {
            border-color: rgba(255, 255, 255, 0.14);
        }
        .route-footer svg {
            width: 18px;
            height: 18px;
        }
        footer {
            display: flex;
            justify-content: space-between;
            gap: 18px;
            padding: 0 0 26px;
            color: var(--muted);
            font-size: 13px;
        }
        @media (max-width: 980px) {
            .hero {
                grid-template-columns: 1fr;
                gap: 28px;
            }
            .app-preview {
                grid-template-columns: 1fr 1fr;
            }
            h1 {
                font-size: 58px;
            }
            .intro {
                font-size: 18px;
            }
            .trader-panel,
            .budget-panel {
                min-height: 0;
            }
            .section-heading {
                align-items: start;
                flex-direction: column;
            }
        }
        @media (max-width: 720px) {
            .site-header,
            .hero,
            .tools,
            footer {
                width: min(100% - 28px, 1180px);
            }
            .site-header {
                align-items: flex-start;
                flex-direction: column;
            }
            .nav-links {
                width: 100%;
            }
            .nav-links a {
                flex: 1 1 0;
            }
            h1 {
                font-size: 44px;
            }
            .hero-mark {
                width: 76px;
                height: 76px;
            }
            .summary-row,
            .app-preview,
            .route-grid {
                grid-template-columns: 1fr;
            }
            .summary-row div,
            .summary-row div:first-child {
                border-left: 0;
                border-top: 1px solid var(--line);
            }
            .summary-row div:first-child {
                border-top: 0;
            }
            .signal-image {
                height: 122px;
            }
            footer {
                flex-direction: column;
            }
        }
        @media (max-width: 420px) {
            .actions {
                display: grid;
            }
            .button {
                width: 100%;
            }
            .brand span {
                font-size: 18px;
            }
        }
    </style>
</head>
<body>
<div class="shell">
    <header class="site-header">
        <a class="brand" href="/" aria-label="CashFlowArc home">
            <img src="{{ url_for('static', filename='favicon.svg') }}" alt="">
            <span>CashFlowArc</span>
        </a>
        <nav class="nav-links" aria-label="CashFlowArc apps">
            <a href="/budget/">Budget</a>
            <a href="/trader/">Trader</a>
        </nav>
    </header>

    <main>
        <section class="hero" aria-label="CashFlowArc home">
            <div class="hero-copy">
                <img class="hero-mark" src="{{ url_for('static', filename='favicon.svg') }}" alt="">
                <h1>CashFlowArc</h1>
                <p class="intro">A focused front door for the two sides of your money: everyday cash flow and market execution.</p>
                <div class="actions">
                    <a class="button primary" href="/budget/">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                        Open Budget
                    </a>
                    <a class="button" href="/trader/">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 18 9 9l4 5 7-10M4 20h16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                        Open Trader
                    </a>
                </div>
                <div class="summary-row" aria-label="CashFlowArc focus areas">
                    <div>
                        <span>Budget</span>
                        <strong>Cash flow</strong>
                    </div>
                    <div>
                        <span>Trader</span>
                        <strong>SPX reads</strong>
                    </div>
                    <div>
                        <span>Arc</span>
                        <strong>One home</strong>
                    </div>
                </div>
            </div>

            <div class="app-preview" aria-label="Application previews">
                <article class="trader-panel">
                    <div class="panel-top">
                        <div>
                            <p class="panel-kicker">Trader App</p>
                            <h2>Market terminal</h2>
                        </div>
                        <span class="status-pill">Signal Ready</span>
                    </div>
                    <img class="signal-image" src="{{ url_for('static', filename='bull-signal.png') }}" alt="Trader signal chart preview">
                    <div class="market-rows">
                        <div class="market-row">
                            <span>SPX price</span>
                            <strong>5,219</strong>
                        </div>
                        <div class="market-row">
                            <span>VWAP distance</span>
                            <b>+0.24%</b>
                        </div>
                        <div class="market-row">
                            <span>Session bias</span>
                            <b>Watch long</b>
                        </div>
                        <div class="market-row">
                            <span>Risk mode</span>
                            <strong>Defined</strong>
                        </div>
                    </div>
                </article>

                <article class="budget-panel">
                    <header>
                        <div>
                            <p class="panel-kicker">Budget App</p>
                            <h2>Cash flow board</h2>
                        </div>
                        <span class="month-pill">May</span>
                    </header>
                    <div class="budget-total">
                        <span>Available after plan</span>
                        <strong>$2,840</strong>
                    </div>
                    <div class="budget-rows">
                        <div class="budget-line">
                            <div class="budget-line-header">
                                <strong>Income</strong>
                                <b>$7,600</b>
                            </div>
                            <div class="meter"><i style="width: 88%"></i></div>
                            <span>Recurring deposits and cleared cash</span>
                        </div>
                        <div class="budget-line">
                            <div class="budget-line-header">
                                <strong>Bills</strong>
                                <b>$3,420</b>
                            </div>
                            <div class="meter gold"><i style="width: 61%"></i></div>
                            <span>Mortgage, utilities, subscriptions</span>
                        </div>
                        <div class="budget-line">
                            <div class="budget-line-header">
                                <strong>Investing</strong>
                                <b>$1,340</b>
                            </div>
                            <div class="meter coral"><i style="width: 48%"></i></div>
                            <span>Brokerage transfers and reserves</span>
                        </div>
                    </div>
                </article>
            </div>
        </section>

        <section class="tools" aria-label="CashFlowArc destinations">
            <div class="section-heading">
                <h2>Choose the workspace.</h2>
                <p>The home page now mirrors the personality of both apps: quiet financial organization beside a fast market terminal.</p>
            </div>
            <div class="route-grid">
                <a class="route-card" href="/budget/">
                    <span>Personal finance</span>
                    <h3>Budget</h3>
                    <p>Accounts, transactions, categories, monthly plans, and net worth views in a calm mint workspace.</p>
                    <div class="route-footer">
                        <strong>Open /budget/</strong>
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                    </div>
                </a>
                <a class="route-card trader" href="/trader/">
                    <span>Market execution</span>
                    <h3>Trader</h3>
                    <p>SPX terminal, GEX, option chain, simulator, and signal snapshots in a dark precision dashboard.</p>
                    <div class="route-footer">
                        <strong>Open /trader/</strong>
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                    </div>
                </a>
            </div>
        </section>
    </main>

    <footer>
        <span>cashflowarc.com</span>
        <span>Budget and Trader under one arc.</span>
    </footer>
</div>
</body>
</html>
"""


@app.route("/")
def index() -> str:
    return render_template_string(LANDING_PAGE)


@app.route("/healthz")
def healthz() -> tuple[str, int]:
    return "ok", 200


@app.route("/favicon.ico")
def favicon_ico():
    return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOME_WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("HOME_WEB_PORT", "5000")),
        debug=True,
    )
