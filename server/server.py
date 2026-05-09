from __future__ import annotations

import os

from flask import Flask, render_template_string, send_from_directory


app = Flask(__name__)


BASE_PAGE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#0F172A">
    <meta name="description" content="{{ description }}">
    <title>{{ title }}</title>
    <link rel="icon" href="{{ url_for('static', filename='favicon.svg', v='4') }}" sizes="any" type="image/svg+xml">
    <style>
        :root {
            --primary: #0F172A;
            --accent: #14B8A6;
            --green: #22C55E;
            --amber: #F59E0B;
            --red: #EF4444;
            --bg: #F8FAFC;
            --card: #FFFFFF;
            --text: #111827;
            --muted: #64748B;
            --line: #E2E8F0;
            --line-dark: rgba(255, 255, 255, 0.14);
            --shadow: 0 18px 42px rgba(15, 23, 42, 0.10);
        }
        * { box-sizing: border-box; }
        html { min-width: 320px; scroll-behavior: smooth; }
        body {
            margin: 0;
            min-height: 100vh;
            background: var(--bg);
            color: var(--text);
            font-family: "Aptos", "Segoe UI", Arial, sans-serif;
            line-height: 1.5;
        }
        a { color: inherit; text-decoration: none; }
        img { display: block; max-width: 100%; }
        p, h1, h2, h3 { margin-top: 0; }
        .shell { min-height: 100vh; overflow: hidden; }
        .site-header {
            position: sticky;
            top: 0;
            z-index: 20;
            background: rgba(15, 23, 42, 0.96);
            color: #FFFFFF;
            box-shadow: 0 14px 34px rgba(15, 23, 42, 0.16);
        }
        .header-inner,
        .section-inner,
        .footer-inner {
            width: min(1180px, calc(100% - 40px));
            margin: 0 auto;
        }
        .header-inner {
            min-height: 76px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 18px;
            padding: 12px 0;
        }
        .brand {
            display: inline-flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
            font-weight: 850;
        }
        .brand img {
            width: 46px;
            height: 46px;
            flex: 0 0 auto;
            border-radius: 8px;
            background: #FFFFFF;
            box-shadow: 0 10px 22px rgba(20, 184, 166, 0.18);
        }
        .brand span {
            font-size: 20px;
            line-height: 1;
            white-space: nowrap;
        }
        .arc {
            color: var(--accent);
            font-weight: 950;
            letter-spacing: 0;
        }
        .brand .arc,
        h1 .arc {
            color: #5EEAD4;
        }
        .nav-links a .arc {
            color: #5EEAD4;
        }
        .nav-links a.active .arc,
        .nav-links a:hover .arc,
        .nav-links a:focus-visible .arc {
            color: #FFFFFF;
        }
        .nav-links {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 4px;
            border: 1px solid rgba(255, 255, 255, 0.10);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.06);
        }
        .nav-links a {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 34px;
            padding: 0 12px;
            border-radius: 6px;
            color: #CBD5E1;
            font-size: 13px;
            font-weight: 800;
            white-space: nowrap;
        }
        .nav-links a.trader-nav-link {
            flex-direction: column;
            gap: 0;
            min-height: 42px;
            padding: 4px 12px;
        }
        .trader-nav-text {
            line-height: 1;
        }
        .nav-beta {
            color: var(--red);
            font-size: 9px;
            font-weight: 950;
            line-height: 1;
            margin-top: 3px;
            text-transform: uppercase;
        }
        .nav-links a:hover .nav-beta,
        .nav-links a:focus-visible .nav-beta,
        .nav-links a.active .nav-beta {
            color: var(--red);
        }
        .nav-links a:hover,
        .nav-links a:focus-visible,
        .nav-links a.active {
            background: var(--accent);
            color: #FFFFFF;
            outline: 0;
        }
        .hero {
            position: relative;
            min-height: calc(100svh - 150px);
            color: #FFFFFF;
            background: var(--primary);
            isolation: isolate;
            overflow: hidden;
        }
        .hero:before {
            content: "";
            position: absolute;
            inset: 0;
            z-index: 1;
            background: linear-gradient(90deg, rgba(15, 23, 42, 0.96) 0%, rgba(15, 23, 42, 0.80) 42%, rgba(15, 23, 42, 0.30) 100%);
        }
        .dashboard-visual {
            position: absolute;
            inset: 0;
            z-index: 0;
            display: block;
            width: min(1420px, 112vw);
            height: 620px;
            margin-left: max(26vw, 240px);
            transform: rotate(-1deg) translateY(24px);
            transform-origin: center;
            border: 1px solid rgba(255, 255, 255, 0.16);
            background: #FFFFFF;
            box-shadow: 0 34px 80px rgba(0, 0, 0, 0.28);
            overflow: hidden;
        }
        .dashboard-visual img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            object-position: left top;
        }
        .mock-sidebar {
            background: var(--primary);
            color: #FFFFFF;
            padding: 26px 18px;
        }
        .mock-brand {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 30px;
            font-size: 26px;
            font-weight: 850;
        }
        .mock-brand img {
            width: 40px;
            height: 40px;
            border-radius: 8px;
            background: #FFFFFF;
        }
        .mock-nav {
            display: grid;
            gap: 10px;
        }
        .mock-nav span {
            display: block;
            min-height: 46px;
            padding: 13px 14px;
            border-radius: 8px;
            color: #CBD5E1;
            background: rgba(255, 255, 255, 0.04);
            font-weight: 750;
        }
        .mock-nav span:first-child {
            color: #FFFFFF;
            background: rgba(20, 184, 166, 0.30);
        }
        .mock-main {
            padding: 34px 36px;
            background: var(--bg);
            color: var(--text);
        }
        .mock-top {
            display: flex;
            justify-content: space-between;
            gap: 18px;
            margin-bottom: 22px;
        }
        .mock-title h2 {
            margin: 0;
            font-size: 32px;
            line-height: 1.1;
        }
        .mock-title p {
            margin: 6px 0 0;
            color: var(--muted);
        }
        .mock-pill {
            align-self: flex-start;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #FFFFFF;
            padding: 9px 12px;
            color: var(--primary);
            font-weight: 800;
        }
        .mock-kpis {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin-bottom: 16px;
        }
        .mock-kpi,
        .mock-panel {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #FFFFFF;
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
        }
        .mock-kpi {
            min-height: 110px;
            padding: 16px;
        }
        .mock-kpi span,
        .mock-panel span {
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
        }
        .mock-kpi strong {
            display: block;
            margin-top: 12px;
            font-size: 26px;
            line-height: 1;
        }
        .mock-kpi b {
            display: block;
            margin-top: 12px;
            color: var(--green);
            font-size: 13px;
        }
        .mock-grid {
            display: grid;
            grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.8fr);
            gap: 16px;
        }
        .mock-panel {
            min-height: 260px;
            padding: 18px;
        }
        .mock-chart {
            display: grid;
            grid-template-columns: repeat(8, 1fr);
            align-items: end;
            gap: 10px;
            height: 180px;
            margin-top: 24px;
            border-bottom: 1px solid var(--line);
        }
        .mock-chart i {
            display: block;
            border-radius: 5px 5px 0 0;
            background: var(--accent);
        }
        .mock-chart i:nth-child(even) {
            background: var(--amber);
        }
        .mock-bars {
            display: grid;
            gap: 18px;
            margin-top: 24px;
        }
        .mock-bar {
            display: grid;
            gap: 7px;
        }
        .mock-bar div {
            height: 9px;
            border-radius: 99px;
            background: #E2E8F0;
            overflow: hidden;
        }
        .mock-bar i {
            display: block;
            height: 100%;
            border-radius: inherit;
            background: var(--green);
        }
        .hero-inner {
            position: relative;
            z-index: 2;
            width: min(1180px, calc(100% - 40px));
            margin: 0 auto;
            min-height: calc(100svh - 150px);
            display: grid;
            align-items: center;
            padding: 62px 0 74px;
        }
        .hero-copy {
            max-width: 650px;
        }
        .eyebrow {
            display: inline-flex;
            align-items: center;
            min-height: 30px;
            margin: 0 0 20px;
            padding: 0 10px;
            border: 1px solid rgba(20, 184, 166, 0.42);
            border-radius: 999px;
            color: #99F6E4;
            font-size: 12px;
            font-weight: 850;
            text-transform: uppercase;
        }
        h1 {
            margin: 0;
            font-size: clamp(52px, 8vw, 98px);
            line-height: 0.92;
            letter-spacing: 0;
        }
        .hero-copy p {
            max-width: 620px;
            margin: 22px 0 0;
            color: #E2E8F0;
            font-size: clamp(18px, 2vw, 23px);
            line-height: 1.48;
        }
        .hero-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 28px;
        }
        .button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 9px;
            min-height: 46px;
            padding: 0 17px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #FFFFFF;
            color: var(--text);
            font-weight: 850;
            box-shadow: 0 12px 26px rgba(15, 23, 42, 0.10);
        }
        .button.primary {
            border-color: var(--accent);
            background: var(--accent);
            color: #FFFFFF;
        }
        .button.dark {
            border-color: rgba(255, 255, 255, 0.20);
            background: rgba(255, 255, 255, 0.08);
            color: #FFFFFF;
        }
        .button svg {
            width: 17px;
            height: 17px;
            flex: 0 0 auto;
        }
        .band {
            padding: 72px 0;
        }
        .band.white {
            background: #FFFFFF;
            border-top: 1px solid var(--line);
            border-bottom: 1px solid var(--line);
        }
        .section-heading {
            max-width: 760px;
            margin-bottom: 28px;
        }
        .section-heading h2,
        .page-hero h1 {
            margin: 0;
            color: var(--primary);
            font-size: clamp(34px, 5vw, 58px);
            line-height: 1;
            letter-spacing: 0;
        }
        .section-heading p,
        .page-hero p {
            margin: 14px 0 0;
            color: var(--muted);
            font-size: 18px;
        }
        .card-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 16px;
        }
        .info-card,
        .app-card,
        .policy-card {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--card);
            box-shadow: var(--shadow);
        }
        .info-card,
        .policy-card {
            padding: 22px;
        }
        .info-card h3,
        .policy-card h2,
        .app-card h3 {
            margin: 0 0 10px;
            color: var(--primary);
            font-size: 21px;
            line-height: 1.15;
        }
        .info-card p,
        .policy-card p,
        .policy-card li,
        .app-card p {
            color: var(--muted);
        }
        .info-card p,
        .policy-card p {
            margin-bottom: 0;
        }
        .badge {
            display: inline-flex;
            align-items: center;
            min-height: 28px;
            margin-bottom: 14px;
            padding: 0 9px;
            border-radius: 999px;
            background: #CCFBF1;
            color: #0F766E;
            font-size: 12px;
            font-weight: 850;
            text-transform: uppercase;
        }
        .app-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 18px;
        }
        .app-card {
            min-height: 330px;
            display: grid;
            grid-template-rows: auto 1fr auto;
            padding: 24px;
            overflow: hidden;
        }
        .app-card.trader {
            background: var(--primary);
            color: #FFFFFF;
            border-color: var(--primary);
        }
        .app-card.trader h3,
        .app-card.trader p {
            color: #FFFFFF;
        }
        .mini-screen {
            display: grid;
            gap: 10px;
            margin: 18px 0 22px;
        }
        .mini-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 14px;
            padding: 12px 14px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #FFFFFF;
        }
        .trader .mini-row {
            border-color: rgba(255, 255, 255, 0.12);
            background: rgba(255, 255, 255, 0.06);
        }
        .mini-row span {
            color: var(--muted);
            font-size: 13px;
            font-weight: 800;
        }
        .trader .mini-row span {
            color: #CBD5E1;
        }
        .mini-row strong.green { color: var(--green); }
        .mini-row strong.amber { color: var(--amber); }
        .mini-row strong.red { color: var(--red); }
        .story {
            display: grid;
            grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
            gap: 42px;
            align-items: start;
        }
        .story-panel {
            border-left: 4px solid var(--accent);
            padding-left: 22px;
        }
        .story-panel p {
            color: var(--muted);
            font-size: 18px;
        }
        .page-hero {
            padding: 70px 0 42px;
        }
        .policy-stack {
            display: grid;
            gap: 16px;
        }
        .policy-card ul {
            margin: 12px 0 0;
            padding-left: 18px;
        }
        .policy-card li + li {
            margin-top: 8px;
        }
        .footer {
            background: var(--primary);
            color: #CBD5E1;
            padding: 28px 0;
        }
        .footer-inner {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 18px;
            font-size: 13px;
        }
        .footer a {
            color: #FFFFFF;
            font-weight: 800;
        }
        .footer-links {
            display: flex;
            flex-wrap: wrap;
            gap: 14px;
        }
        @media (max-width: 1040px) {
            .dashboard-visual {
                margin-left: 24vw;
                opacity: 0.78;
            }
            .card-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @media (max-width: 820px) {
            .header-inner,
            .section-inner,
            .footer-inner {
                width: min(100% - 28px, 1180px);
            }
            .header-inner,
            .footer-inner {
                align-items: flex-start;
                flex-direction: column;
            }
            .nav-links {
                width: 100%;
                flex-wrap: wrap;
                overflow: visible;
            }
            .nav-links a {
                flex: 1 1 calc(33.333% - 4px);
                min-width: 0;
            }
            .hero {
                min-height: calc(100svh - 130px);
            }
            .hero-inner {
                min-height: calc(100svh - 130px);
                padding: 44px 0 56px;
            }
            .dashboard-visual {
                height: 620px;
                margin-left: 18vw;
                transform: rotate(-1deg) translateY(56px);
                opacity: 0.52;
            }
            .mock-main {
                padding: 22px;
            }
            .mock-kpis {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .mock-grid,
            .app-grid,
            .story {
                grid-template-columns: 1fr;
            }
            .card-grid {
                grid-template-columns: 1fr;
            }
            .band {
                padding: 54px 0;
            }
        }
        @media (max-width: 520px) {
            .hero-actions {
                display: grid;
            }
            .button {
                width: 100%;
            }
            .brand span {
                font-size: 18px;
            }
            .dashboard-visual {
                height: 620px;
                margin-left: 5vw;
                opacity: 0.36;
            }
        }
    </style>
</head>
<body>
<div class="shell">
    <header class="site-header">
        <div class="header-inner">
            <a class="brand" href="/" aria-label="cashflowARC home">
                <img src="{{ url_for('static', filename='favicon.svg') }}" alt="">
                <span>cashflow<span class="arc">ARC</span></span>
            </a>
            <nav class="nav-links" aria-label="cashflowARC navigation">
                <a class="{{ 'active' if page == 'home' else '' }}" href="/">cashflow<span class="arc">ARC</span></a>
                <a href="/budget/">budget<span class="arc">ARC</span></a>
                <a class="trader-nav-link" href="/trader/"><span class="trader-nav-text">trader<span class="arc">ARC</span></span><span class="nav-beta">BETA</span></a>
                <a class="{{ 'active' if page == 'security' else '' }}" href="/security">Security</a>
                <a class="{{ 'active' if page == 'privacy' else '' }}" href="/privacy">Privacy</a>
            </nav>
        </div>
    </header>
    {{ content|safe }}
    <footer class="footer">
        <div class="footer-inner">
            <span>cashflow<span class="arc">ARC</span> protects the arc between money today, decisions tomorrow, and long-term direction.</span>
            <div class="footer-links">
                <a href="/">cashflowARC</a>
                <a href="/budget/">budgetARC</a>
                <a href="/trader/">traderARC</a>
                <a href="/security">Security</a>
                <a href="/privacy">Privacy</a>
            </div>
        </div>
    </footer>
</div>
</body>
</html>
"""


HOME_CONTENT = """
<main>
    <section class="hero" aria-label="cashflowARC landing">
        <div class="dashboard-visual" aria-hidden="true">
            <img src="{{ url_for('static', filename='budgetarc-dashboard-bg.png', v='1') }}" alt="">
        </div>
        <div class="hero-inner">
            <div class="hero-copy">
                <p class="eyebrow">Private cash flow intelligence</p>
                <h1>cashflow<span class="arc">ARC</span></h1>
                <p>Know your current cash flow, get ideas to improve it, and predict what your cash flow will be like in the future.</p>
                <div class="hero-actions">
                    <a class="button primary" href="/budget/">budgetARC</a>
                    <a class="button dark" href="/trader/">traderARC</a>
                    <a class="button dark" href="/security">Security</a>
                </div>
            </div>
        </div>
    </section>

    <section class="band white" aria-label="Security and privacy commitments">
        <div class="section-inner">
            <div class="section-heading">
                <h2>Security and privacy are visible, not hidden.</h2>
                <p>The landing page now puts the trust answers up front, then gives you dedicated Security and Privacy pages for the details.</p>
            </div>
            <div class="card-grid">
                <article class="info-card">
                    <span class="badge">SSL and TLS</span>
                    <h3>Encrypted in transit</h3>
                    <p>cashflowARC is intended to run behind HTTPS in production so sensitive pages are protected by modern TLS between the browser and the site.</p>
                </article>
                <article class="info-card">
                    <span class="badge">Bank data</span>
                    <h3>Provider-based connectivity</h3>
                    <p>budgetARC bank linking is handled through Teller-style authorization. Credentials stay with the bank/provider flow, while cashflowARC uses the authorized data needed to run the app.</p>
                </article>
                <article class="info-card">
                    <span class="badge">No sale</span>
                    <h3>We never sell your data</h3>
                    <p>Personal finance data is used to power your dashboard, categorization, planning, and forecasts. It is not sold to advertisers or data brokers.</p>
                </article>
            </div>
        </div>
    </section>

    <section class="band" aria-label="Application previews">
        <div class="section-inner">
            <div class="section-heading">
                <h2>One palette across both apps.</h2>
                <p>budgetARC and traderARC now share the same navy, teal, green, amber, red, light gray, white card, and near-black text system.</p>
            </div>
            <div class="app-grid">
                <a class="app-card" href="/budget/">
                    <span class="badge">budgetARC</span>
                    <h3>Cash flow, budgets, transactions, and net worth</h3>
                    <p>A calm operating dashboard for account-connected personal finance.</p>
                    <div class="mini-screen">
                        <div class="mini-row"><span>Net cash flow</span><strong class="green">$2,450</strong></div>
                        <div class="mini-row"><span>Dining budget</span><strong class="amber">68%</strong></div>
                        <div class="mini-row"><span>Overspend risk</span><strong class="red">Review</strong></div>
                    </div>
                    <div class="button">budgetARC</div>
                </a>
                <a class="app-card trader" href="/trader/">
                    <span class="badge">traderARC</span>
                    <h3>SPX terminal, GEX, option chain, and simulator</h3>
                    <p>Market context uses the same decision colors while keeping the data density traders expect.</p>
                    <div class="mini-screen">
                        <div class="mini-row"><span>Session bias</span><strong class="green">Constructive</strong></div>
                        <div class="mini-row"><span>Gamma level</span><strong class="amber">Watch</strong></div>
                        <div class="mini-row"><span>Risk status</span><strong class="red">Defined</strong></div>
                    </div>
                    <div class="button primary">traderARC</div>
                </a>
            </div>
        </div>
    </section>

    <section class="band white" aria-label="Founder story">
        <div class="section-inner story">
            <div class="section-heading">
                <h2>Founder story</h2>
                <p>cashflowARC started from a simple frustration: financial tools were either pretty but shallow, or powerful but scattered.</p>
            </div>
            <div class="story-panel">
                <p>The founder wanted one private place to answer practical questions every week: how much cash is available, what is changing, which habits are helping, and what the next month could look like. budgetARC grew from that need. traderARC followed the same principle for market decisions: make the important signal visible without burying it in noise.</p>
                <p>That is the arc: know where money is now, find better choices, and make the next decision with more clarity.</p>
            </div>
        </div>
    </section>
</main>
"""


SECURITY_CONTENT = """
<main>
    <section class="page-hero">
        <div class="section-inner">
            <p class="eyebrow">Security</p>
            <h1>Security built around private financial data.</h1>
            <p>cashflowARC is designed for sensitive money workflows. The goal is clear: encrypted connections, minimal exposure, and plain-language controls.</p>
        </div>
    </section>
    <section class="band white">
        <div class="section-inner policy-stack">
            <article class="policy-card">
                <h2>HTTPS, SSL, and TLS</h2>
                <p>Production traffic for cashflowARC should be served through HTTPS so browser sessions are encrypted in transit. Local development URLs such as 127.0.0.1 may use HTTP, but the public site should use TLS.</p>
            </article>
            <article class="policy-card">
                <h2>Encryption messaging</h2>
                <p>Bank and app traffic is handled over encrypted connections. Sensitive service credentials and provider tokens are kept server side and should not be exposed in browser code or public repositories.</p>
            </article>
            <article class="policy-card">
                <h2>Bank connectivity</h2>
                <p>budgetARC uses a bank connectivity provider flow for account access. You authorize access through that flow. cashflowARC does not need to store your bank password; it uses authorized account and transaction data to power the dashboard.</p>
            </article>
            <article class="policy-card">
                <h2>Data access</h2>
                <p>Financial data should be used only for the product experiences you requested: cash flow views, categorization, planning, insights, and forecasts. Access should be limited to the app services that need it to operate.</p>
            </article>
            <article class="policy-card">
                <h2>What security does not mean</h2>
                <p>No website can promise zero risk. cashflowARC should be used with strong passwords, secure devices, HTTPS, and careful access control. If you notice suspicious behavior, stop using the affected connection and contact the site owner through the channel that provided your access.</p>
            </article>
        </div>
    </section>
</main>
"""


PRIVACY_CONTENT = """
<main>
    <section class="page-hero">
        <div class="section-inner">
            <p class="eyebrow">Privacy Policy</p>
            <h1>We never sell your data.</h1>
            <p>Last updated May 9, 2026. cashflowARC is built for private personal finance workflows, not ad targeting or data resale.</p>
        </div>
    </section>
    <section class="band white">
        <div class="section-inner policy-stack">
            <article class="policy-card">
                <h2>What data is used</h2>
                <p>Depending on the app features you use, cashflowARC may process account names, balances, transactions, categories, budgets, net worth records, preferences, and market dashboard settings.</p>
            </article>
            <article class="policy-card">
                <h2>How data is used</h2>
                <ul>
                    <li>To show current cash flow, spending, income, budgets, accounts, and net worth.</li>
                    <li>To generate insights, planning ideas, and future cash flow projections.</li>
                    <li>To operate the traderARC dashboard, including symbols, watchlists, simulations, and market views.</li>
                    <li>To maintain security, troubleshoot errors, and keep the service reliable.</li>
                </ul>
            </article>
            <article class="policy-card">
                <h2>No sale of data</h2>
                <p>cashflowARC does not sell personal data, bank data, transaction history, balances, app activity, or forecasts. The product is not built around advertising profiles or data broker resale.</p>
            </article>
            <article class="policy-card">
                <h2>Bank connectivity</h2>
                <p>When bank linking is enabled, authorization is handled through the bank connectivity provider. cashflowARC receives the authorized data needed to operate the app and should not collect or store your online banking password.</p>
            </article>
            <article class="policy-card">
                <h2>Sharing</h2>
                <p>Data may be processed by service providers that are necessary to run the site, such as hosting, database, security, or bank connectivity providers. cashflowARC should share only what is needed for those services to operate.</p>
            </article>
            <article class="policy-card">
                <h2>Your choices</h2>
                <p>You can stop using bank connectivity, request account/data cleanup through the site owner, and avoid entering information you do not want processed by the app.</p>
            </article>
        </div>
    </section>
</main>
"""


def render_page(content: str, *, page: str, title: str, description: str) -> str:
    return render_template_string(
        BASE_PAGE,
        content=render_template_string(content),
        page=page,
        title=title,
        description=description,
    )


@app.route("/")
def index() -> str:
    return render_page(
        HOME_CONTENT,
        page="home",
        title="cashflowARC | Private Cash Flow Intelligence",
        description="Know your current cash flow, get ideas to improve it, and predict what your cash flow will be like in the future.",
    )


@app.route("/security")
@app.route("/security/")
def security() -> str:
    return render_page(
        SECURITY_CONTENT,
        page="security",
        title="Security | cashflowARC",
        description="cashflowARC security, SSL, encryption, and bank connectivity details.",
    )


@app.route("/privacy")
@app.route("/privacy/")
def privacy() -> str:
    return render_page(
        PRIVACY_CONTENT,
        page="privacy",
        title="Privacy Policy | cashflowARC",
        description="cashflowARC privacy policy. We never sell your data.",
    )


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
