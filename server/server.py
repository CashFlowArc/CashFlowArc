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
            gap: 14px;
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
            width: 42px;
            height: 42px;
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
            justify-content: flex-end;
            flex-wrap: wrap;
            gap: 4px;
            max-width: 920px;
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
            padding: 0 8px;
            border-radius: 6px;
            color: #CBD5E1;
            font-size: 12px;
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
        .hero-copy .hero-trust {
            max-width: 640px;
            margin: 18px 0 0;
            padding-top: 16px;
            border-top: 1px solid rgba(255, 255, 255, 0.14);
            color: #CBD5E1;
            font-size: 14px;
            line-height: 1.55;
        }
        .hero-copy .hero-trust a {
            color: #5EEAD4;
            font-weight: 850;
        }
        .hero-copy .hero-trust a:hover,
        .hero-copy .hero-trust a:focus-visible {
            color: #99F6E4;
        }
        .scroll-cue {
            position: absolute;
            left: 50%;
            bottom: 18px;
            z-index: 3;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 44px;
            height: 44px;
            border: 1px solid rgba(20, 184, 166, 0.48);
            border-radius: 999px;
            background: rgba(15, 23, 42, 0.72);
            box-shadow: 0 14px 34px rgba(0, 0, 0, 0.24);
            transform: translateX(-50%);
            animation: scrollCueBob 1.9s ease-in-out infinite;
        }
        .scroll-cue:before {
            content: "";
            position: absolute;
            inset: -7px;
            border: 1px solid rgba(20, 184, 166, 0.22);
            border-radius: inherit;
        }
        .scroll-cue:hover,
        .scroll-cue:focus-visible {
            background: rgba(20, 184, 166, 0.20);
            outline: 0;
        }
        .scroll-cue-arrow {
            width: 13px;
            height: 13px;
            border-right: 3px solid #5EEAD4;
            border-bottom: 3px solid #5EEAD4;
            transform: rotate(45deg) translate(-2px, -2px);
        }
        @keyframes scrollCueBob {
            0%,
            100% {
                transform: translate(-50%, 0);
            }
            50% {
                transform: translate(-50%, 7px);
            }
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
        .step-grid {
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 14px;
        }
        .info-card,
        .step-card,
        .policy-card {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--card);
            box-shadow: var(--shadow);
        }
        .info-card,
        .step-card,
        .policy-card {
            padding: 22px;
        }
        a.info-card {
            display: block;
            color: inherit;
            text-decoration: none;
            transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
        }
        a.info-card:hover,
        a.info-card:focus-visible {
            border-color: rgba(20, 184, 166, 0.58);
            box-shadow: 0 24px 54px rgba(15, 23, 42, 0.14);
            outline: 0;
            transform: translateY(-2px);
        }
        .info-card h3,
        .step-card h3,
        .policy-card h2 {
            margin: 0 0 10px;
            color: var(--primary);
            font-size: 21px;
            line-height: 1.15;
        }
        .info-card p,
        .step-card p,
        .policy-card p,
        .policy-card li {
            color: var(--muted);
        }
        .info-card p,
        .step-card p,
        .policy-card p {
            margin-bottom: 0;
        }
        .step-number {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 26px;
            height: 26px;
            flex: 0 0 26px;
            margin-bottom: 16px;
            border-radius: 999px;
            background: var(--accent);
            color: #FFFFFF;
            font-size: 12px;
            font-weight: 900;
        }
        .step-top {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-bottom: 14px;
        }
        .step-top .step-number {
            margin-bottom: 0;
        }
        .step-module,
        .step-status {
            display: inline-flex;
            align-items: center;
            min-height: 22px;
            padding: 0 6px;
            border-radius: 999px;
            font-size: 10px;
            font-weight: 900;
            white-space: nowrap;
        }
        .step-module {
            background: #CCFBF1;
            color: #0F766E;
        }
        .step-status {
            margin-left: auto;
            background: #E2E8F0;
            color: #334155;
        }
        .step-status.free {
            background: rgba(34, 197, 94, 0.14);
            color: #15803D;
        }
        .step-status.pro {
            background: rgba(245, 158, 11, 0.14);
            color: #B45309;
        }
        .funded-callout {
            margin-top: 28px;
            padding: 24px 28px;
            border: 1px solid rgba(20, 184, 166, 0.34);
            border-radius: 8px;
            background: var(--primary);
            color: #FFFFFF;
            box-shadow: var(--shadow);
            font-size: clamp(28px, 4vw, 50px);
            font-weight: 950;
            line-height: 1.04;
            text-align: center;
        }
        .funded-callout span {
            color: #5EEAD4;
        }
        .pro-note {
            max-width: 820px;
            margin: 18px auto 0;
            color: var(--muted);
            font-size: 15px;
            text-align: center;
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
        .security-heading {
            max-width: none;
        }
        .security-heading h2 {
            white-space: nowrap;
            font-size: clamp(34px, 4vw, 52px);
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
            .step-grid {
                grid-template-columns: repeat(3, minmax(0, 1fr));
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
                flex: 1 1 calc(50% - 4px);
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
            .step-grid,
            .story {
                grid-template-columns: 1fr;
            }
            .card-grid {
                grid-template-columns: 1fr;
            }
            .security-heading h2 {
                white-space: normal;
            }
            .band {
                padding: 54px 0;
            }
        }
        @media (max-width: 520px) {
            h1 {
                font-size: 48px;
            }
            .hero-copy p {
                max-width: 320px;
                font-size: 18px;
            }
            .hero-copy .hero-trust {
                max-width: 320px;
                font-size: 13px;
            }
            .funded-callout {
                padding: 20px;
                font-size: 28px;
                text-align: left;
            }
            .pro-note {
                text-align: left;
            }
            .hero-actions {
                display: grid;
            }
            .scroll-cue {
                bottom: 12px;
                width: 40px;
                height: 40px;
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
        @media (prefers-reduced-motion: reduce) {
            .scroll-cue {
                animation: none;
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
                <a href="/#planning-workflow">collect<span class="arc">ARC</span></a>
                <a href="/#planning-workflow">budget<span class="arc">ARC</span></a>
                <a href="/#planning-workflow">forecast<span class="arc">ARC</span></a>
                <a href="/#planning-workflow">life<span class="arc">ARC</span></a>
                <a href="/#planning-workflow">lifestyle<span class="arc">ARC</span></a>
                <a href="/#planning-workflow">whatif<span class="arc">ARC</span></a>
                <a class="trader-nav-link" href="/trader/"><span class="trader-nav-text">trader<span class="arc">ARC</span></span><span class="nav-beta">BETA</span></a>
                <a class="{{ 'active' if page == 'security' else '' }}" href="/security">Security</a>
                <a href="/budget/login">Log In</a>
            </nav>
        </div>
    </header>
    {{ content|safe }}
    <footer class="footer">
        <div class="footer-inner">
            <span>cashflow<span class="arc">ARC</span> protects the arc between money today, decisions tomorrow, and long-term direction.</span>
            <div class="footer-links">
                <a href="/">cashflowARC</a>
                <a href="/#planning-workflow">collectARC</a>
                <a href="/#planning-workflow">budgetARC</a>
                <a href="/#planning-workflow">forecastARC</a>
                <a href="/#planning-workflow">lifeARC</a>
                <a href="/#planning-workflow">lifestyleARC</a>
                <a href="/#planning-workflow">whatifARC</a>
                <a href="/trader/">traderARC</a>
                <a href="/security">Security</a>
                <a href="/budget/login">Log In</a>
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
                <p>A planning engine that collects transactions and upcoming life events, then builds a living forecast of your future financial lifestyle.</p>
                <div class="hero-actions">
                    <a class="button primary" href="/budget/register">Sign Up</a>
                    <a class="button dark" href="/budget/login">Log In</a>
                    <a class="button dark" href="/budget/">budgetARC</a>
                    <a class="button dark" href="/trader/">traderARC</a>
                    <a class="button dark" href="/security">Security</a>
                </div>
                <p class="hero-trust">cashflowARC never sees, reads, or stores your financial institution usernames or passwords, and we do not sell your personal information. <a href="/security">Learn more about security.</a></p>
            </div>
        </div>
        <a class="scroll-cue" href="#planning-workflow" aria-label="Scroll to planning workflow">
            <span class="scroll-cue-arrow" aria-hidden="true"></span>
        </a>
    </section>

    <section id="planning-workflow" class="band white" aria-label="Planning workflow">
        <div class="section-inner">
            <div class="section-heading">
                <h2>Plan the next version of your financial life.</h2>
                <p>One login powers every ARC module and identifies which transactions each one can use.</p>
            </div>
            <div class="step-grid">
                <article class="step-card">
                    <div class="step-top">
                        <span class="step-number">1</span>
                        <span class="step-module">collectARC</span>
                        <span class="step-status free">Free</span>
                    </div>
                    <h3>Collect transactions</h3>
                    <p>Bring spending, income, and account activity into one planning view.</p>
                </article>
                <article class="step-card">
                    <div class="step-top">
                        <span class="step-number">2</span>
                        <span class="step-module">budgetARC</span>
                        <span class="step-status free">Free</span>
                    </div>
                    <h3>Set budget</h3>
                    <p>Define the spending plan that future forecasts should respect.</p>
                </article>
                <article class="step-card">
                    <div class="step-top">
                        <span class="step-number">3</span>
                        <span class="step-module">forecastARC</span>
                        <span class="step-status pro">Pro</span>
                    </div>
                    <h3>Forecast budget for next 12 months</h3>
                    <p>Project your budget against expected income, expenses, and timing.</p>
                </article>
                <article class="step-card">
                    <div class="step-top">
                        <span class="step-number">4</span>
                        <span class="step-module">lifeARC</span>
                        <span class="step-status pro">Pro</span>
                    </div>
                    <h3>Plan for major life events</h3>
                    <p>Add big changes before they hit your bank account.</p>
                </article>
                <article class="step-card">
                    <div class="step-top">
                        <span class="step-number">5</span>
                        <span class="step-module">lifestyleARC</span>
                        <span class="step-status pro">Pro</span>
                    </div>
                    <h3>Forecast funded lifestyle months</h3>
                    <p>See how long your current plan can support the lifestyle you want.</p>
                </article>
                <article class="step-card">
                    <div class="step-top">
                        <span class="step-number">6</span>
                        <span class="step-module">whatifARC</span>
                        <span class="step-status pro">Pro</span>
                    </div>
                    <h3>What if I... scenario planning</h3>
                    <p>Ask "what if I..." and compare choices for a better future.</p>
                </article>
            </div>
            <div class="funded-callout">How many <span>funded lifestyle months</span> does future you have?</div>
            <p class="pro-note">collectARC and budgetARC are free. forecastARC, lifeARC, lifestyleARC, and whatifARC are in development for a Pro monthly plan.</p>
        </div>
    </section>

    <section class="band white" aria-label="Security and privacy commitments">
        <div class="section-inner">
            <div class="section-heading security-heading">
                <h2>Security and privacy are visible, not hidden.</h2>
            </div>
            <div class="card-grid">
                <a class="info-card" href="/security">
                    <span class="badge">SSL and TLS</span>
                    <h3>Encrypted in transit</h3>
                    <p>cashflowARC communications are encrypted end to end, meaning that no one can listen in and capture your personal data.</p>
                </a>
                <a class="info-card" href="/security">
                    <span class="badge">Bank data</span>
                    <h3>Provider-based connectivity</h3>
                    <p>cashflowARC does not see, read, or store your financial institution username or password.</p>
                </a>
                <a class="info-card" href="/security">
                    <span class="badge">No sale</span>
                    <h3>We never sell your data</h3>
                    <p>Personal finance data is used to power your dashboard, categorization, planning, and forecasts. It is not sold to advertisers or data brokers.</p>
                </a>
            </div>
        </div>
    </section>

    <section class="band white" aria-label="Founder story">
        <div class="section-inner story">
            <div class="section-heading">
                <h2>Founder story</h2>
                <p>In the end, financial tools were good at showing where money was going, but not what lifestyle I could afford in the future.</p>
            </div>
            <div class="story-panel">
                <p>The founder wanted one private place to answer practical questions every week: how much cash is available, what is changing, which habits are helping, and what the next month could look like.</p>
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
                <p>cashflowARC communications are encrypted end to end, meaning that no one can listen in and capture your personal data. Sensitive service credentials and provider tokens are kept server side and should not be exposed in browser code or public repositories.</p>
            </article>
            <article class="policy-card">
                <h2>Bank connectivity</h2>
                <p>budgetARC uses a bank connectivity provider flow for account access. You authorize access through that flow. cashflowARC does not see, read, or store your financial institution username or password; it uses authorized account and transaction data to power the dashboard.</p>
            </article>
            <article class="policy-card">
                <h2>Personal information</h2>
                <p>cashflowARC does not sell your personal information, financial data, transaction history, balances, app activity, or forecasts. The product is not built around advertising profiles or data broker resale.</p>
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
        description="A planning engine that collects transactions and upcoming life events, then builds a living forecast of your future financial lifestyle.",
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
