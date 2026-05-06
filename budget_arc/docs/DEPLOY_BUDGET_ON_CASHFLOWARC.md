# Deploy BudgetArc Beside CashFlowArc

This deploys the budget app as a separate service mounted at `https://CashFlowArc.com/budget`.

It does not modify CashFlowArc's existing `server/server.py`.

## Server Layout

Recommended paths:

```text
/home/opc/CashFlowArc            # existing CashFlowArc git checkout used by pull-on-push
/home/opc/CashFlowArc/budget_arc # BudgetArc app directory in that checkout
/opt/budget-arc/venv             # BudgetArc production Python virtualenv
/etc/budget-arc/budget.env       # server secrets
/etc/budget-arc/teller/          # Teller certificate and private key
/home/opc/CashFlowArc/budget_arc/wallet/ # Oracle wallet, readable by service user only
```

## One-Time Setup

```bash
cd /home/opc
git clone <CashFlowArc-repo-url> CashFlowArc
cd /home/opc/CashFlowArc/budget_arc
sudo mkdir -p /opt/budget-arc
sudo chown opc:opc /opt/budget-arc
python3 -m venv /opt/budget-arc/venv
. /opt/budget-arc/venv/bin/activate
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
/opt/budget-arc/venv/bin/python -m budget_teller_oracle hash-password
```

Put the resulting hash in:

```text
BUDGET_ADMIN_PASSWORD_HASH=
```

For the GitHub Actions deployment, prefer storing the raw password as a GitHub Actions secret named
`BUDGET_ADMIN_PASSWORD`. The OEL installer hashes it on the server and writes only
`BUDGET_ADMIN_PASSWORD_HASH` to `/etc/budget-arc/budget.env`.

The deployment workflow can also be run manually from GitHub Actions after the secret is created.

Generate `BUDGET_MASTER_KEY` on the server if you are not sourcing it from a secrets manager:

```bash
/opt/budget-arc/venv/bin/python -m budget_teller_oracle generate-key
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
BUDGET_EMAIL_FROM=
BUDGET_SMTP_HOST=
BUDGET_SMTP_PORT=587
BUDGET_SMTP_USERNAME=
BUDGET_SMTP_PASSWORD=
BUDGET_SMTP_USE_TLS=true
```

## Oracle Tables

Initialize the isolated budget tables:

```bash
/opt/budget-arc/venv/bin/python -m budget_teller_oracle init-db
```

The app uses `BUDGET_` tables and does not write to CashFlowArc market-data tables.

The deployment installer runs `init-db` on each deploy. Existing installs are migrated in place by adding `BUDGET_USERS`, `BUDGET_EMAIL_TOKENS`, `USER_ID` columns to Teller connection/account/transaction/sync-event tables, and institution fields on transaction rows.

After signing in as `admin`, create regular users from `Users`, or enable self-registration by configuring SMTP. If older Teller rows were loaded before user ownership existed, use `Assign unowned data` on the intended user once.

The installer preserves `/etc/budget-arc/budget.env` using a privileged file check because the directory is intentionally owner-only. Teller values can be refreshed from GitHub Actions secrets/defaults without committing private certs or keys.

## Email Registration

For GitHub Actions deployment, add these repository secrets if you want verification and password-reset emails to send:

```text
BUDGET_EMAIL_FROM
BUDGET_SMTP_HOST
BUDGET_SMTP_PORT
BUDGET_SMTP_USERNAME
BUDGET_SMTP_PASSWORD
BUDGET_SMTP_USE_TLS
BUDGET_SMTP_USE_SSL
BUDGET_SMTP_TIMEOUT
```

The installer writes non-empty secret values to `/etc/budget-arc/budget.env` without printing them. It also installs `swaks` when available from the OEL package repositories so the OCI SMTP relay can be tested from the server. Verification links expire after 24 hours; password-reset links expire after 60 minutes. Raw link tokens are never stored in Oracle, only SHA-256 token hashes.

See [OCI Email Delivery](OCI_EMAIL_DELIVERY.md) for the exact relay values and test commands.

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
. /opt/budget-arc/venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart budget-arc
```
