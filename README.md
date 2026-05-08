# CashFlowArc Home

Landing page for `https://cashflowarc.com`.

This repository now owns the base CashFlowArc site. The app-specific code lives in separate repositories:

- Budget: `CashFlowArc/CashFlowArc-Budget`, mounted at `/budget/`
- Trader: `CashFlowArc/CashFlowArc-Trader`, mounted at `/trader/`

## Local Run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python server/server.py
```

Open `http://127.0.0.1:5000/`.

## Production Shape

- Repo checkout: `/home/opc/CashFlowArc`
- Virtualenv: `/opt/cashflowarc-home/venv`
- systemd service: `cashflowarc-home.service`
- Public mount: `https://cashflowarc.com/`
- Local upstream: `http://127.0.0.1:5000/`

See `docs/REPOSITORY_SPLIT.md` for the three-repository layout.
