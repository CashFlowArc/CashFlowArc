# CashFlowArc Repository Split

The CashFlowArc deployment is split into three repositories:

| Repository | Public path | Server checkout | Local upstream |
| --- | --- | --- | --- |
| `CashFlowArc/CashFlowArc` | `/` | `/home/opc/CashFlowArc` | `127.0.0.1:5000` |
| `CashFlowArc/CashFlowArc-Budget` | `/budget/` | `/home/opc/CashFlowArc-Budget` | `127.0.0.1:8788` |
| `CashFlowArc/CashFlowArc-Trader` | `/trader/` | `/home/opc/CashFlowArc-Trader` | `127.0.0.1:8790` |

The home repository owns the landing page and documents the front-door nginx routing. Budget and Trader each own their app code, service file, deploy script, and GitHub Actions workflow.

The self-hosted runner must be available to all three GitHub repositories, either through the CashFlowArc organization or as a repo-specific runner on each repository.
