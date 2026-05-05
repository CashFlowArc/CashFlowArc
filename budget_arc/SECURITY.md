# Security Policy

This project handles financial account metadata and transaction data. Treat every change as security-sensitive.

## Non-Negotiables

- Never store bank credentials. Teller Connect handles bank login directly.
- Never log Teller access tokens, encrypted token values, Oracle passwords, wallet contents, certs, private keys, or raw request bodies.
- Store Teller access tokens encrypted at the application layer before database writes.
- Store the app encryption master key in Windows DPAPI for local development; do not keep it in plaintext `.env`.
- Keep `.env`, wallet files, Teller certs, and private keys out of git.
- Keep the local Teller Connect server bound to `127.0.0.1` unless a future design explicitly adds authenticated remote access.
- Require Teller enrollment signature verification for development/production data.
- Use least-privilege Oracle users when this moves beyond local testing.
- Prefer a server deployment for real financial data; local PC setup is only for short-lived development.
- Keep admin and user responsibilities separate: `admin` is for global management, while email-based users own Teller data.
- Store email verification and password reset tokens only as one-way hashes; never store the raw link token.
- Keep SMTP credentials in server environment variables, GitHub Actions secrets, or a secret manager.
- Use generic registration and reset responses so the app does not reveal whether an email address exists.

## Data Separation

All budgeting tables use the `BUDGET_` prefix and must remain separate from CashFlowArc market-data tables. User-owned Teller rows must include `USER_ID` so one user's connections, accounts, transactions, and sync events cannot be queried by another user.

## Review Checklist

Before merging future changes, check whether the change:

- Adds a new secret or token path.
- Adds logging near authentication, enrollment, webhook, or sync code.
- Expands network exposure beyond loopback.
- Stores new raw provider payloads.
- Changes encryption, key loading, or token decryption.
- Touches Oracle writes or schema migrations.
- Exposes the web app beyond localhost without HTTPS and `BUDGET_REQUIRE_AUTH=true`.
- Changes `/budget/api/teller/enrollment`, because that path receives signed Teller enrollment callbacks.
- Changes user scoping on account, transaction, connection, or sync-event queries.

## Web App

The `/budget` web app must be served behind HTTPS in production and must require a password hash generated with:

```text
python -m budget_teller_oracle hash-password
```

For server deployment, the GitHub Actions secret `BUDGET_ADMIN_PASSWORD` can be used by the installer to generate the hash on the server without committing or printing the raw password.

Do not deploy with an empty `BUDGET_ADMIN_PASSWORD_HASH`.

Email registration and password reset require SMTP settings. At minimum set `BUDGET_EMAIL_FROM`, `BUDGET_SMTP_HOST`, `BUDGET_SMTP_PORT`, and any provider-specific username/password values. Prefer a transactional email provider or app-specific SMTP password over a primary mailbox password.
