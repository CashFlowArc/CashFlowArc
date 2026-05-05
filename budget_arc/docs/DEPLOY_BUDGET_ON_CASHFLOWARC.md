# Deploy BudgetArc Beside CashFlowArc

This deploys the budget app as a separate service mounted at `https://CashFlowArc.com/budget`.

It does not modify CashFlowArc's existing `server/server.py`.

## Server Layout

Recommended paths:

```text
/home/opc/CashFlowArc            # existing CashFlowArc git checkout used by pull-on-push
/home/opc/CashFlowArc/budget_arc # BudgetArc app directory in that checkout
/etc/budget-arc/budget.env       # server secrets
/etc/budget-arc/teller/          # Teller certificate and private key
/home/opc/CashFlowArc/budget_arc/wallet/ # Oracle wallet, readable by service user only
```

## One-Time Setup

```bash
cd /home/opc
git clone <CashFlowArc-repo-url> CashFlowArc
cd /home/opc/CashFlowArc/budget_arc
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Create the server env file:

```bash
sudo mkdir -p /etc/budget-arc
sudo cp .env.server.example /etc/budget-arc/budget.env
sudo chmod 600 /etc/budget-arc/budget.env
```

Generate a web admin password hash locally on the server:

```bash
/home/opc/CashFlowArc/budget_arc/.venv/bin/python -m budget_teller_oracle hash-password
```

Put the resulting hash in:

```text
BUDGET_ADMIN_PASSWORD_HASH=
```

Generate `BUDGET_MASTER_KEY` on the server if you are not sourcing it from a secrets manager:

```bash
/home/opc/CashFlowArc/budget_arc/.venv/bin/python -m budget_teller_oracle generate-key
```

## Required Server Environment

Set these in `/etc/budget-arc/budget.env`:

```text
DB_USER=
DB_PASSWORD=
DB_DSN=cfadb1_low
WALLET_DIR=/home/opc/CashFlowArc/budget_arc/wallet
WALLET_PASSWORD=
BUDGET_MASTER_KEY=
BUDGET_KEY_ID=server-v1
TELLER_APPLICATION_ID=
TELLER_ENVIRONMENT=development
TELLER_CERT_PATH=/etc/budget-arc/teller/certificate.pem
TELLER_CERT_KEY_PATH=/etc/budget-arc/teller/private_key.pem
TELLER_SIGNING_PUBLIC_KEY=
TELLER_INSTITUTION_ID=amex
BUDGET_BASE_PATH=/budget
BUDGET_WEB_HOST=127.0.0.1
BUDGET_WEB_PORT=8788
BUDGET_EXTERNAL_ORIGIN=https://CashFlowArc.com
BUDGET_REQUIRE_AUTH=true
BUDGET_COOKIE_SECURE=true
```

## Oracle Tables

Initialize the isolated budget tables:

```bash
/home/opc/CashFlowArc/budget_arc/.venv/bin/python -m budget_teller_oracle init-db
```

The app uses `BUDGET_` tables and does not write to CashFlowArc market-data tables.

## systemd

```bash
sudo cp deploy/budget-arc.service /etc/systemd/system/budget-arc.service
sudo systemctl daemon-reload
sudo systemctl enable --now budget-arc
sudo systemctl status budget-arc
```

## Nginx

Add the contents of `deploy/nginx-budget-location.conf` to the existing `CashFlowArc.com` server block, then reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

If CashFlowArc uses Apache or another reverse proxy, use the same concept:

```text
/budget/ -> http://127.0.0.1:8788/budget/
```

## Validation

```bash
curl -I http://127.0.0.1:8788/budget/login
curl -I https://CashFlowArc.com/budget/login
```

Then sign in at:

```text
https://CashFlowArc.com/budget
```

## Updating

```bash
cd /home/opc/CashFlowArc
git pull
cd /home/opc/CashFlowArc/budget_arc
. .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart budget-arc
```
