#!/usr/bin/env bash

set -euo pipefail

sudo systemctl stop getTickerData@SPY-SPX.service
sudo systemctl disable getTickerData@SPY-SPX.service
sudo systemctl enable getTickerData@SPY-SPX.service
sudo systemctl start getTickerData@SPY-SPX.service
sudo systemctl daemon-reload

journalctl -u getTickerData@SPY-SPX.service -n 50 --no-pager
