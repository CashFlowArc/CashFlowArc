#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/opc/CashFlowArc/budget_arc}"
VENV_DIR="${VENV_DIR:-/opt/budget-arc/venv}"
ENV_DIR="${ENV_DIR:-/etc/budget-arc}"
ENV_FILE="${ENV_FILE:-$ENV_DIR/budget.env}"
SERVICE_FILE="/etc/systemd/system/budget-arc.service"
NGINX_CONF="${NGINX_CONF:-/etc/nginx/conf.d/app.conf}"

echo "BudgetArc installer: app dir=$APP_DIR"
echo "BudgetArc installer: venv=$VENV_DIR"

if [[ ! -d "$APP_DIR" ]]; then
  echo "BudgetArc app dir is missing: $APP_DIR" >&2
  exit 1
fi

cd "$APP_DIR"
sudo mkdir -p "$(dirname "$VENV_DIR")"
sudo chown -R opc:opc "$(dirname "$VENV_DIR")"
python3 -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"
pip install -r requirements.txt

if ! command -v swaks >/dev/null 2>&1; then
  echo "Installing swaks for OCI Email Delivery SMTP diagnostics."
  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y swaks || sudo yum install -y swaks || true
  else
    sudo yum install -y swaks || true
  fi
fi
if command -v swaks >/dev/null 2>&1; then
  echo "swaks is installed: $(swaks --version 2>&1 | head -1)"
else
  echo "swaks is not installed; install it with 'sudo yum install swaks -y' if the package repo is enabled."
fi

sudo mkdir -p "$ENV_DIR"
sudo chmod 700 "$ENV_DIR"

if ! sudo test -f "$ENV_FILE"; then
  WALLET_DIR_DEFAULT="/home/opc/wallets/myadb"
  if [[ ! -f "$WALLET_DIR_DEFAULT/tnsnames.ora" ]]; then
    WALLET_DIR_DEFAULT="$APP_DIR/wallet"
  fi

  MASTER_KEY="$("$VENV_DIR/bin/python" -m budget_teller_oracle generate-key)"
  TMP_ENV="$(mktemp)"
  cat > "$TMP_ENV" <<EOF
# BudgetArc server config. Keep this file out of git.
ORACLE_CONFIG_SOURCE=cashflowarc
CASHFLOWARC_REPO=/home/opc/CashFlowArc
DB_DSN=cfadb1_low
WALLET_DIR=$WALLET_DIR_DEFAULT
WALLET_PASSWORD=

BUDGET_MASTER_KEY=$MASTER_KEY
BUDGET_KEY_ID=server-v1

TELLER_APPLICATION_ID=
TELLER_ENVIRONMENT=development
TELLER_API_VERSION=
TELLER_CERT_PATH=/etc/budget-arc/teller/certificate.pem
TELLER_CERT_KEY_PATH=/etc/budget-arc/teller/private_key.pem
TELLER_SIGNING_PUBLIC_KEY=
TELLER_ALLOW_UNVERIFIED_SIGNATURES=false
TELLER_INSTITUTION_ID=amex

BUDGET_BASE_PATH=/budget
BUDGET_WEB_HOST=127.0.0.1
BUDGET_WEB_PORT=8788
BUDGET_EXTERNAL_ORIGIN=https://CashFlowArc.com
BUDGET_REQUIRE_AUTH=true
BUDGET_ADMIN_USERNAME=admin
BUDGET_ADMIN_PASSWORD_HASH=
BUDGET_COOKIE_SECURE=true

BUDGET_EMAIL_FROM=
BUDGET_SMTP_HOST=
BUDGET_SMTP_PORT=587
BUDGET_SMTP_USERNAME=
BUDGET_SMTP_PASSWORD=
BUDGET_SMTP_USE_TLS=true
BUDGET_SMTP_USE_SSL=false
BUDGET_SMTP_TIMEOUT=20
EOF
  sudo install -m 600 "$TMP_ENV" "$ENV_FILE"
  rm -f "$TMP_ENV"
  echo "Created $ENV_FILE with generated BUDGET_MASTER_KEY and safe placeholders."
else
  echo "$ENV_FILE already exists; preserving existing secrets."
fi

TELLER_ENV_KEYS=(
  TELLER_APPLICATION_ID
  TELLER_ENVIRONMENT
  TELLER_API_VERSION
  TELLER_CERT_PATH
  TELLER_CERT_KEY_PATH
  TELLER_SIGNING_PUBLIC_KEY
  TELLER_ALLOW_UNVERIFIED_SIGNATURES
  TELLER_INSTITUTION_ID
)
TELLER_ENV_PROVIDED=false
for key in "${TELLER_ENV_KEYS[@]}"; do
  if [[ -n "${!key:-}" ]]; then
    TELLER_ENV_PROVIDED=true
    break
  fi
done

if [[ "$TELLER_ENV_PROVIDED" == true ]]; then
  TMP_TELLER_SECRETS="$(mktemp)"
  trap 'rm -f "${TMP_TELLER_SECRETS:-}" "${TMP_EMAIL_SECRETS:-}"' EXIT
  chmod 600 "$TMP_TELLER_SECRETS"
  for key in "${TELLER_ENV_KEYS[@]}"; do
    if [[ -n "${!key:-}" ]]; then
      printf '%s=%s\n' "$key" "${!key}" >> "$TMP_TELLER_SECRETS"
    fi
  done
  TMP_ENV_UPDATE="$(sudo mktemp)"
  sudo python3 - "$ENV_FILE" "$TMP_ENV_UPDATE" "$TMP_TELLER_SECRETS" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
secret_file = Path(sys.argv[3])
updates = {}
for line in secret_file.read_text().splitlines():
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    if value:
        updates[key] = value

lines = source.read_text().splitlines()
for key, value in updates.items():
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")

target.write_text("\n".join(lines) + "\n")
PY
  sudo install -m 600 "$TMP_ENV_UPDATE" "$ENV_FILE"
  sudo rm -f "$TMP_ENV_UPDATE"
  rm -f "$TMP_TELLER_SECRETS"
  echo "Updated BudgetArc Teller settings from GitHub Actions secrets/defaults."
else
  echo "BudgetArc Teller settings not provided; preserving existing Teller settings."
fi

if [[ -n "${BUDGET_ADMIN_PASSWORD:-}" ]]; then
  ADMIN_HASH="$("$VENV_DIR/bin/python" -m budget_teller_oracle hash-password --password-env BUDGET_ADMIN_PASSWORD)"
  TMP_ENV_UPDATE="$(sudo mktemp)"
  sudo python3 - "$ENV_FILE" "$TMP_ENV_UPDATE" "$ADMIN_HASH" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
password_hash = sys.argv[3]
lines = source.read_text().splitlines()
updated = False
for index, line in enumerate(lines):
    if line.startswith("BUDGET_ADMIN_PASSWORD_HASH="):
        lines[index] = f"BUDGET_ADMIN_PASSWORD_HASH={password_hash}"
        updated = True
        break
if not updated:
    lines.append(f"BUDGET_ADMIN_PASSWORD_HASH={password_hash}")
target.write_text("\n".join(lines) + "\n")
PY
  sudo install -m 600 "$TMP_ENV_UPDATE" "$ENV_FILE"
  sudo rm -f "$TMP_ENV_UPDATE"
  unset ADMIN_HASH
  echo "Updated BudgetArc admin password hash from GitHub Actions secret."
else
  echo "BUDGET_ADMIN_PASSWORD secret not provided; preserving existing admin password hash."
fi

EMAIL_ENV_KEYS=(
  BUDGET_EMAIL_FROM
  BUDGET_SMTP_HOST
  BUDGET_SMTP_PORT
  BUDGET_SMTP_USERNAME
  BUDGET_SMTP_PASSWORD
  BUDGET_SMTP_USE_TLS
  BUDGET_SMTP_USE_SSL
  BUDGET_SMTP_TIMEOUT
)
EMAIL_ENV_PROVIDED=false
for key in "${EMAIL_ENV_KEYS[@]}"; do
  if [[ -n "${!key:-}" ]]; then
    EMAIL_ENV_PROVIDED=true
    break
  fi
done

if [[ "$EMAIL_ENV_PROVIDED" == true ]]; then
  TMP_EMAIL_SECRETS="$(mktemp)"
  trap 'rm -f "${TMP_TELLER_SECRETS:-}" "${TMP_EMAIL_SECRETS:-}"' EXIT
  chmod 600 "$TMP_EMAIL_SECRETS"
  for key in "${EMAIL_ENV_KEYS[@]}"; do
    if [[ -n "${!key:-}" ]]; then
      printf '%s=%s\n' "$key" "${!key}" >> "$TMP_EMAIL_SECRETS"
    fi
  done
  TMP_ENV_UPDATE="$(sudo mktemp)"
  sudo python3 - "$ENV_FILE" "$TMP_ENV_UPDATE" "$TMP_EMAIL_SECRETS" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
secret_file = Path(sys.argv[3])
updates = {}
for line in secret_file.read_text().splitlines():
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    if value:
        updates[key] = value

lines = source.read_text().splitlines()
for key, value in updates.items():
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")

target.write_text("\n".join(lines) + "\n")
PY
  sudo install -m 600 "$TMP_ENV_UPDATE" "$ENV_FILE"
  sudo rm -f "$TMP_ENV_UPDATE"
  rm -f "$TMP_EMAIL_SECRETS"
  echo "Updated BudgetArc email delivery settings from GitHub Actions secrets."
else
  echo "BudgetArc email delivery secrets not provided; preserving existing SMTP settings."
fi

sudo python3 - "$APP_DIR" "$VENV_DIR" "$ENV_FILE" <<'PY'
from pathlib import Path
import os
import subprocess
import sys

app_dir = Path(sys.argv[1])
venv_dir = Path(sys.argv[2])
env_file = Path(sys.argv[3])
env = os.environ.copy()

for raw_line in env_file.read_text().splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip().strip('"').strip("'")

subprocess.run(
    [str(venv_dir / "bin" / "python"), "-m", "budget_teller_oracle", "init-db"],
    cwd=app_dir,
    env=env,
    check=True,
)
PY

sudo install -m 644 "$APP_DIR/deploy/budget-arc.service" "$SERVICE_FILE"
sudo systemctl daemon-reload
sudo systemctl enable budget-arc
sudo systemctl restart budget-arc
sudo systemctl --no-pager --full status budget-arc || true

if [[ -f "$NGINX_CONF" ]]; then
  BACKUP="$NGINX_CONF.budget-arc.$(date +%Y%m%d%H%M%S).bak"
  sudo cp "$NGINX_CONF" "$BACKUP"
  echo "Backed up nginx config to $BACKUP"

  TMP_NGINX="$(sudo mktemp)"
  sudo python3 - "$NGINX_CONF" "$TMP_NGINX" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text()

budget_block = """    location = /budget {
        return 301 /budget/;
    }

    location /budget/ {
        proxy_pass http://127.0.0.1:8788/budget/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_read_timeout 180s;
        proxy_send_timeout 180s;
    }

"""

legacy_prefix = "        proxy_set_header X-Forwarded-Prefix /budget;\n"
if "127.0.0.1:8788" in text:
    text = text.replace(legacy_prefix, "")
    print("Updated existing BudgetArc nginx route.")
else:
    marker = "    location / {"
    count = text.count(marker)
    if count == 0:
        raise SystemExit("Could not find nginx 'location / {' marker")
    text = text.replace(marker, budget_block + marker)
    print(f"Inserted BudgetArc nginx route before {count} location / block(s).")

target.write_text(text)
PY
  sudo install -m 644 "$TMP_NGINX" "$NGINX_CONF"
  sudo rm -f "$TMP_NGINX"

  sudo nginx -t
  sudo systemctl reload nginx
else
  echo "nginx config not found at $NGINX_CONF" >&2
fi

echo "=== local checks ==="
curl -sS -I http://127.0.0.1:8788/budget/login | head -5 || true
curl -sS -I http://127.0.0.1/budget/ | head -5 || true
echo "BudgetArc install complete."
