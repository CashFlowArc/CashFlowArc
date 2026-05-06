# OCI Email Delivery for BudgetArc

BudgetArc sends verification and password reset emails through SMTP. For OCI Email Delivery, configure the server with the SMTP credentials generated in OCI; do not use your normal OCI console password.

## Required OCI Values

- `BUDGET_EMAIL_FROM`: the approved sender email address in OCI Email Delivery.
- `BUDGET_SMTP_HOST`: the public endpoint from OCI Email Delivery Configuration, for example `smtp.email.us-ashburn-1.oci.oraclecloud.com`.
- `BUDGET_SMTP_PORT`: `587`.
- `BUDGET_SMTP_USERNAME`: the username from Generate SMTP Credentials.
- `BUDGET_SMTP_PASSWORD`: the generated SMTP password.
- `BUDGET_SMTP_USE_TLS`: `true`.
- `BUDGET_SMTP_USE_SSL`: `false`.

The approved sender must be created in the same OCI region as the SMTP endpoint. OCI requires encrypted SMTP transport; port `587` uses STARTTLS.

## GitHub Actions Secrets

Add these repository secrets, then rerun or trigger the deploy workflow:

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

The deploy script writes non-empty values into `/etc/budget-arc/budget.env` with `0600` permissions and restarts `budget-arc`.

## Server Tests

The deploy script installs `swaks` when the package is available from the OEL repos. OCI's documented swaks pattern is:

```bash
swaks --pipeline -tls \
  --server smtp.email.us-ashburn-1.oci.oraclecloud.com \
  --port 587 \
  --auth-user '<smtp credential username>' \
  --from '<approved sender email>' \
  --to '<recipient email>' \
  --data 'From: <approved sender email>\nSubject: BudgetArc SMTP test\n\nTest email'
```

Swaks prompts for the SMTP password if you omit `--auth-password`, which keeps the password out of shell history.

You can also test through the BudgetArc Python mailer without printing the password:

```bash
cd /home/opc/CashFlowArc/budget_arc
sudo /opt/budget-arc/venv/bin/python -m budget_teller_oracle test-email \
  --env-file /etc/budget-arc/budget.env \
  --to you@example.com
```

If swaks succeeds but BudgetArc does not, check `/etc/budget-arc/budget.env` for mismatched `BUDGET_EMAIL_FROM`, TLS flags, or a missing service restart. If both fail, check the approved sender, SMTP endpoint region, and generated SMTP credential username/password in OCI.
