# BudgetArc Version 1.1 Specification

## 1. Product Vision

BudgetArc 1.1 keeps the Version 1 look and feel while turning the app into a post-aggregation personal finance system. Teller remains the source feed, but Teller payloads are treated as immutable evidence. User edits, rules, categories, splits, merchant cleanup, and future AI suggestions live in separate user-scoped tables.

The core rule is: never overwrite the original Teller transaction payload. The app may create derived views, user overlays, normalized merchants, category assignments, forecasts, and reports, but every derived value must be traceable back to the raw Teller record.

## 2. Product Principles

- Preserve the V1 aesthetic: quiet, dense, finance-first, and familiar.
- Store all user-authored data separately from Teller-originated data.
- Scope every query and mutation by `USER_ID`.
- Prefer explainable rules before AI suggestions.
- Keep raw data append-only; derived data can be recalculated.
- Make edits reversible by retaining the original transaction.

## 3. Data Flow

```text
Teller transaction
  -> immutable raw Teller store
  -> insert-once source transaction record
  -> transaction processing engine
  -> merchant normalization
  -> transfer detection
  -> category assignment
  -> recurring detection
  -> budgets, cash flow, reports, and alerts
```

## 4. V1.1 Data Contract

### Immutable Teller Layer

`BUDGET_RAW_TELLER_ACCOUNTS` and `BUDGET_RAW_TELLER_TRANSACTIONS` store every unique Teller payload version by user, source ID, and payload hash. Repeated syncs of the same payload are ignored. Changed Teller payloads create a new raw event instead of overwriting the first one.

`BUDGET_TRANSACTIONS` becomes insert-once for Teller transactions. If Teller returns a transaction ID already stored, the app keeps the original row unchanged. Future processing should use overlay tables for user-facing changes.

### User Overlay Layer

User edits are stored away from Teller data:

- `BUDGET_TRANSACTION_EDITS`: date changes, merchant overrides, category overrides, notes, reviewed status, and budget/cash-flow exclusions.
- `BUDGET_TRANSACTION_SPLITS`: user-created split lines for one source transaction.
- `BUDGET_CATEGORIES`: user-owned category tree.
- `BUDGET_MERCHANTS`: user-owned normalized merchant records.
- `BUDGET_TRANSACTION_RULES`: user-owned rules for merchant and category automation.

All tables include `USER_ID`, and application reads must filter by the active user.

## 5. Core Modules

### Transaction Processing Engine

Responsibilities:

- Store raw Teller payloads immutably.
- Deduplicate identical raw payloads by hash.
- Keep source transaction rows insert-once.
- Apply user overlays when displaying transactions.
- Support pending-to-posted matching as derived metadata, not source mutation.

### Merchant Normalization Engine

Responsibilities:

- Convert raw descriptions into readable merchants.
- Support exact, contains, starts-with, and regex rules.
- Remember user merchant overrides.
- Support bulk apply to past and future transactions.
- Track confidence for automated merchant matches.

### Categorization and Rules Engine

Priority order:

1. User explicit transaction override.
2. User split lines.
3. User merchant rule.
4. User keyword/rule engine.
5. Transfer detection.
6. Recurring series rule.
7. System suggestion.
8. Uncategorized.

### Budgeting Engine

V1.1 should keep the existing monthly budget view and prepare for three budgeting modes:

- Category budgets.
- Spending plan.
- Zero-based/envelope budgets.

### Recurring Bills and Subscription Engine

Detect recurring patterns using normalized merchant, amount range, interval, account, category, and confidence. Initial UI should focus on confirming or ignoring detected series.

### Cash Flow Forecasting Engine

Projected balance should combine current balance, expected income, bills, subscriptions, planned spending, debt payments, and goals. V1.1 should begin with a 30/60/90-day forecast.

### Goals Engine

Support savings goals, debt payoff goals, and net worth goals. Goal contributions should be excluded or included in cash flow based on user settings.

### Net Worth Engine

Continue Teller balance history and add manual assets, manual liabilities, inclusion rules, and periodic snapshots.

### Investment Tracking Engine

V1.1 scope is balance-only plus manual holdings. Holdings import, tax lots, performance, and rebalancing belong in later versions.

### Reporting and Insights Engine

Reports should be built from derived transactions plus user overlays, never by rewriting Teller records. Initial reports should cover spending, income, trends, merchant totals, budget variance, and alerts.

## 6. Screen-by-Screen UX

V1.1 should preserve the V1 shell, spacing, typography, nav behavior, and restrained color system.

- Overview: add insight cards that explain alerts and upcoming cash-flow pressure.
- Transactions: add merchant/category editing, review state, split entry, and original transaction details.
- Budgets: retain current monthly budget layout and add category management.
- Accounts: keep Teller sync, repair, delete, and institution connection controls.
- Cash Flow: add projected balances, bills, subscriptions, and scenario inputs.
- Goals: add savings/debt/net worth goal list.
- Reports: add spend, income, category, merchant, and variance summaries.
- Settings: add category/rule/merchant management over time.

## 7. Security Requirements

- Every table containing user-owned or user-visible data must include `USER_ID`.
- Every query must filter by `USER_ID`.
- Teller access tokens remain encrypted.
- Raw Teller payloads must not be edited through the UI.
- Deleting a connection can remove active app projections, but raw immutable history should remain for audit and recovery.

## 8. Roadmap

### Version 1.1

- Immutable raw Teller account and transaction tables.
- Insert-once Teller transaction records.
- User overlay tables for edits, splits, merchants, categories, and rules.
- Transaction list editing UX.
- Merchant cleanup and category rules.
- Monthly budget improvements.

### Version 1.2

- Recurring bill/subscription detection.
- Cash-flow forecast.
- Manual assets and liabilities.
- Basic reports.

### Version 1.3

- Goals.
- Advanced budget modes.
- Insights and anomaly detection.
- Investment balances and manual holdings.

### Later

- Holdings import.
- Investment transactions.
- Cost basis and tax lots.
- Allocation, performance, and rebalancing.
