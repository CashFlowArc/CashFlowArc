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

sudo mkdir -p "$ENV_DIR"
sudo chmod 700 "$ENV_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
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
EOF
  sudo install -m 600 "$TMP_ENV" "$ENV_FILE"
  rm -f "$TMP_ENV"
  echo "Created $ENV_FILE with generated BUDGET_MASTER_KEY and safe placeholders."
else
  echo "$ENV_FILE already exists; preserving existing secrets."
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
