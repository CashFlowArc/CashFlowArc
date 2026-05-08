#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/opc/CashFlowArc}"
VENV_DIR="${VENV_DIR:-/opt/cashflowarc-home/venv}"
SERVICE_FILE="/etc/systemd/system/cashflowarc-home.service"

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

curl -sS -I http://127.0.0.1:5000/ | head -5 || true
