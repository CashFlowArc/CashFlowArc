from __future__ import annotations

import os

from flask import Flask, render_template_string, url_for


app = Flask(__name__)


LANDING_PAGE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>CashFlowArc</title>
    <link rel="icon" href="{{ url_for('static', filename='favicon.svg') }}" sizes="any" type="image/svg+xml">
    <style>
        :root {
            --bg: #f7f5ef;
            --ink: #17202a;
            --muted: #5f6872;
            --line: rgba(23, 32, 42, 0.14);
            --green: #157f62;
            --red: #a33a3a;
            --gold: #b7791f;
            --panel: rgba(255, 255, 255, 0.82);
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            font-family: "Aptos", "Segoe UI", system-ui, sans-serif;
            color: var(--ink);
            background:
                linear-gradient(135deg, rgba(21, 127, 98, 0.10), transparent 38%),
                linear-gradient(315deg, rgba(163, 58, 58, 0.10), transparent 34%),
                var(--bg);
        }
        main {
            min-height: 100vh;
            display: grid;
            grid-template-rows: auto 1fr auto;
        }
        header, footer {
            width: min(1120px, calc(100% - 40px));
            margin: 0 auto;
        }
        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 24px 0;
        }
        .brand {
            display: inline-flex;
            align-items: center;
            gap: 12px;
            color: inherit;
            text-decoration: none;
            font-weight: 800;
        }
        .brand-mark {
            width: 34px;
            height: 34px;
            border-radius: 8px;
            display: grid;
            place-items: center;
            background: #17202a;
            color: #fff;
            font-size: 18px;
            line-height: 1;
        }
        .top-link {
            color: var(--muted);
            text-decoration: none;
            font-weight: 700;
        }
        .hero {
            width: min(1120px, calc(100% - 40px));
            margin: 0 auto;
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(300px, 420px);
            align-items: center;
            gap: 56px;
            padding: 40px 0 56px;
        }
        h1 {
            margin: 0;
            max-width: 760px;
            font-size: clamp(52px, 8vw, 104px);
            line-height: 0.92;
            letter-spacing: 0;
        }
        .intro {
            max-width: 620px;
            margin: 24px 0 0;
            color: var(--muted);
            font-size: 20px;
            line-height: 1.55;
        }
        .actions {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            margin-top: 34px;
        }
        .button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 46px;
            padding: 0 18px;
            border-radius: 8px;
            border: 1px solid var(--line);
            background: #fff;
            color: var(--ink);
            text-decoration: none;
            font-weight: 800;
        }
        .button.primary {
            background: var(--ink);
            color: #fff;
            border-color: var(--ink);
        }
        .signal-stack {
            display: grid;
            gap: 16px;
        }
        .signal {
            min-height: 178px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--panel);
            overflow: hidden;
            display: grid;
            grid-template-columns: 128px 1fr;
            align-items: center;
            box-shadow: 0 22px 60px rgba(23, 32, 42, 0.10);
        }
        .signal img {
            width: 100%;
            height: 100%;
            min-height: 178px;
            object-fit: cover;
            background: #101820;
        }
        .signal-copy {
            padding: 22px;
        }
        .signal-kicker {
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
            text-transform: uppercase;
        }
        .signal-title {
            margin: 8px 0 0;
            font-size: 26px;
            font-weight: 850;
        }
        .signal-text {
            margin: 10px 0 0;
            color: var(--muted);
            line-height: 1.45;
        }
        .destinations {
            width: min(1120px, calc(100% - 40px));
            margin: 0 auto;
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 16px;
            padding-bottom: 56px;
        }
        .destination {
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 24px;
            background: rgba(255, 255, 255, 0.74);
            color: inherit;
            text-decoration: none;
        }
        .destination strong {
            display: block;
            font-size: 28px;
        }
        .destination span {
            display: block;
            margin-top: 8px;
            color: var(--muted);
            line-height: 1.45;
        }
        footer {
            padding: 0 0 24px;
            color: var(--muted);
            font-size: 14px;
        }
        @media (max-width: 800px) {
            .hero {
                grid-template-columns: 1fr;
                gap: 28px;
                padding-top: 24px;
            }
            .destinations {
                grid-template-columns: 1fr;
            }
            .signal {
                grid-template-columns: 92px 1fr;
                min-height: 144px;
            }
            .signal img {
                min-height: 144px;
            }
            .intro {
                font-size: 18px;
            }
        }
    </style>
</head>
<body>
<main>
    <header>
        <a class="brand" href="/">
            <span class="brand-mark">C</span>
            <span>CashFlowArc</span>
        </a>
        <a class="top-link" href="/trader/">Trader</a>
    </header>

    <section class="hero" aria-label="CashFlowArc home">
        <div>
            <h1>CashFlowArc</h1>
            <p class="intro">A simple home base for the tools running under cashflowarc.com.</p>
            <div class="actions">
                <a class="button primary" href="/budget/">Open Budget</a>
                <a class="button" href="/trader/">Open Trader</a>
            </div>
        </div>
        <div class="signal-stack" aria-hidden="true">
            <div class="signal">
                <img src="{{ url_for('static', filename='bull-signal.png') }}" alt="">
                <div class="signal-copy">
                    <div class="signal-kicker">Market</div>
                    <div class="signal-title">Trader</div>
                    <p class="signal-text">Live SPX dashboards and signal views.</p>
                </div>
            </div>
            <div class="signal">
                <img src="{{ url_for('static', filename='bear-signal.png') }}" alt="">
                <div class="signal-copy">
                    <div class="signal-kicker">Personal</div>
                    <div class="signal-title">Budget</div>
                    <p class="signal-text">Cash flow, accounts, categories, and goals.</p>
                </div>
            </div>
        </div>
    </section>

    <section class="destinations" aria-label="CashFlowArc destinations">
        <a class="destination" href="/budget/">
            <strong>Budget</strong>
            <span>Manage personal finances at cashflowarc.com/budget.</span>
        </a>
        <a class="destination" href="/trader/">
            <strong>Trader</strong>
            <span>Open the trading dashboard at cashflowarc.com/trader.</span>
        </a>
    </section>

    <footer>cashflowarc.com</footer>
</main>
</body>
</html>
"""


@app.route("/")
def index() -> str:
    return render_template_string(LANDING_PAGE)


@app.route("/healthz")
def healthz() -> tuple[str, int]:
    return "ok", 200


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOME_WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("HOME_WEB_PORT", "5000")),
        debug=True,
    )
