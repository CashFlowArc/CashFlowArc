#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/opc/CashFlowArc}"
VENV_DIR="${VENV_DIR:-/opt/cashflowarc-home/venv}"
SERVICE_FILE="/etc/systemd/system/cashflowarc-home.service"
NGINX_CONF="${NGINX_CONF:-/etc/nginx/conf.d/app.conf}"

if [[ ! -d "$APP_DIR" ]]; then
  echo "Home app dir is missing: $APP_DIR" >&2
  exit 1
fi

cd "$APP_DIR"
sudo mkdir -p "$(dirname "$VENV_DIR")"
sudo chown -R opc:opc "$(dirname "$VENV_DIR")"
python3 -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"
pip install -r requirements.txt

sudo install -m 644 "$APP_DIR/deploy/cashflowarc-home.service" "$SERVICE_FILE"
sudo systemctl daemon-reload
sudo systemctl enable cashflowarc-home
sudo systemctl restart cashflowarc-home
sudo systemctl --no-pager --full status cashflowarc-home || true

if [[ -f "$NGINX_CONF" ]]; then
  BACKUP="$NGINX_CONF.cashflowarc-home.$(date +%Y%m%d%H%M%S).bak"
  sudo cp "$NGINX_CONF" "$BACKUP"
  echo "Backed up nginx config to $BACKUP"

  TMP_NGINX="$(sudo mktemp)"
  sudo python3 - "$NGINX_CONF" "$TMP_NGINX" <<'PY'
import re
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text()

updated_text = re.sub(r"server\s*\{\n(?!\s*server_tokens off;)", "server {\n    server_tokens off;\n", text)
if updated_text != text:
    text = updated_text
    print("Disabled nginx version tokens for CashFlowArc server blocks.")

routes = []
if "127.0.0.1:8788" not in text:
    routes.append("""    location = /budget {
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

""")

if "127.0.0.1:8790" not in text:
    routes.append("""    location = /trader {
        return 301 /trader/;
    }

    location /trader/ {
        proxy_pass http://127.0.0.1:8790;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_read_timeout 180s;
        proxy_send_timeout 180s;
    }

""")

if routes:
    marker = "    location / {"
    if marker not in text:
        raise SystemExit("Could not find nginx 'location / {' marker")
    text = text.replace(marker, "".join(routes) + marker, 1)
    print("Inserted missing CashFlowArc app routes.")
else:
    print("CashFlowArc app routes already exist.")

target.write_text(text)
PY
  sudo install -m 644 "$TMP_NGINX" "$NGINX_CONF"
  sudo rm -f "$TMP_NGINX"
  sudo nginx -t
  sudo systemctl reload nginx
else
  echo "nginx config not found at $NGINX_CONF; skipping route install." >&2
fi

curl -sS -I http://127.0.0.1:5000/ | head -5 || true
