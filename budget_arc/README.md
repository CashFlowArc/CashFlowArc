# Teller to Oracle Budget Ingest

This is a security-first test harness for connecting a Teller enrollment, encrypting the Teller access token at the application layer, and storing normalized account/transaction data in isolated Oracle tables.

The Oracle tables are intentionally prefixed with `BUDGET_` so they remain separate from existing CashFlowArc tables.
Budget users are stored in `BUDGET_USERS`; Teller connections, accounts, transactions, and sync events carry a `USER_ID` so data remains separated by user.

This directory is designed to live inside the CashFlowArc git repository at `budget_arc/`. It runs as a separate service mounted at `/budget`, so it does not import or modify CashFlowArc's existing `server/server.py`.

## Current Robinhood Status

Teller's public Institutions API currently returns no `Robinhood` institution match. This app includes a preflight checker so we do not accidentally build around an unsupported connection.

If Robinhood is required, we will likely need a second provider adapter later, such as Plaid, MX, or another provider that supports Robinhood brokerage/investment data.

## Security Defaults

- The local Teller Connect server binds to `127.0.0.1` by default.
- Teller access tokens are encrypted before they are written to Oracle.
- Teller access tokens are never intentionally logged or stored in raw JSON.
- Live Teller development/production API calls require client certificate paths.
- Teller enrollment signatures are required outside sandbox unless explicitly bypassed.
- `.env`, certs, private keys, and wallet files are ignored by git.

For a real Amex/Teller connection, see [Secure Server Setup](docs/SECURE_SERVER_SETUP.md).

## Setup

1. Copy `.env.example` to `.env`.
2. Or create a secure local starter `.env` for American Express:

```powershell
python -m budget_teller_oracle bootstrap-env
```

3. Harden local secret storage:

```powershell
python -m budget_teller_oracle secure-local
```

4. Fill in the Oracle wallet values and Teller dashboard values that were intentionally left blank.
5. Create the isolated Oracle tables:

```powershell
python -m budget_teller_oracle init-db
```

6. Check whether Teller supports an institution:

```powershell
python -m budget_teller_oracle check-institution Robinhood
```

7. Check whether the local Amex connection setup is ready:

```powershell
python -m budget_teller_oracle doctor
```

8. Start the local Teller Connect page:

```powershell
python -m budget_teller_oracle serve
```

9. Open `http://127.0.0.1:8787`, complete Teller Connect, and the server will store the encrypted enrollment token, pull accounts, and sync transactions.

## Budget Web App

Generate a web admin password hash:

```powershell
python -m budget_teller_oracle hash-password
```

For server deployment through GitHub Actions, set a repository secret named `BUDGET_ADMIN_PASSWORD` instead. The server installer hashes it and writes only the hash into `/etc/budget-arc/budget.env`.

Put the result into `.env` for local-only admin access:

```text
BUDGET_ADMIN_PASSWORD_HASH=
```

Run the web app locally:

```powershell
python -m budget_teller_oracle web
```

Open:

```text
http://127.0.0.1:8788/budget
```

Sign in as `admin` to create budget users. Regular users sign in with their email address, connect their own Teller institutions, and only see rows tied to their `USER_ID`.

Users can also self-register with an email verification link and reset passwords by email. Configure SMTP with:

```text
BUDGET_EMAIL_FROM=
BUDGET_SMTP_HOST=
BUDGET_SMTP_PORT=587
BUDGET_SMTP_USERNAME=
BUDGET_SMTP_PASSWORD=
BUDGET_SMTP_USE_TLS=true
```

On the server, store those values as GitHub Actions secrets or in `/etc/budget-arc/budget.env`; never commit them.

For CashFlowArc.com deployment, use:

- [Deploy BudgetArc Beside CashFlowArc](docs/DEPLOY_BUDGET_ON_CASHFLOWARC.md)
- [Secure Server Setup](docs/SECURE_SERVER_SETUP.md)
- [OCI Email Delivery](docs/OCI_EMAIL_DELIVERY.md)
- `deploy/budget-arc.service`
- `deploy/nginx-budget-location.conf`

## Teller Environments

- `sandbox`: simulated data, no real bank connection.
- `development`: real financial data, free up to Teller's development enrollment limit, requires mTLS cert/key.
- `production`: real users, paid, requires Teller production approval.
