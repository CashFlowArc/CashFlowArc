# Mint UI Research Notes

This app is a fresh implementation inspired by public descriptions and historical screenshots of Mint. It does not copy Mint assets, logos, or source code.

## Publicly Observed Patterns

- Mint emphasized a single overview page for linked financial accounts, spending, and alerts.
- The navigation commonly included Overview, Transactions, Budgets, Goals/Trends, Accounts, and Settings-style areas.
- The transaction screen centered on a ledger table with search/filtering, account selection, dates, categories, and merchant descriptions.
- The budget screen used progress bars by category to show monthly spending against a target.
- Account management included connected-account lists and options for hiding inactive accounts from budgets/trends.
- The visual language leaned on green accents, white cards, light gray page backgrounds, and dense but readable tables.

## Sources Consulted

- Teller-style account aggregation capability context came from `https://teller.io/docs`.
- Mint public homepage/failover copy described account aggregation, automatic categorization, budgets, and goals: `https://mint.intuit.com/failover/homepage/index.html`.
- Bible Money Matters' Mint review described overview alerts, transaction views, and demo-account budget screenshots: `https://www.biblemoneymatters.com/mint-com-review/`.
- PCWorld's Mint review described automatic transaction categorization and budget progress bars: `https://www.pcworld.com/article/3239387/software/mint-review-financial-budgeting-app.html`.
- Public Reddit discussions described account-management behaviors in old/new Mint UIs, including inactive account visibility and transaction-page account lists: `https://www.reddit.com/r/mintuit/comments/uco7zt/`.

## Design Translation

BudgetArc keeps the recognizable budgeting affordances:

- A green-accent sidebar and card dashboard.
- Month-to-date spend cards.
- Budget progress bars generated from Oracle transactions.
- Transaction search and filters.
- Account connection and management screens.

BudgetArc intentionally avoids:

- Mint branding or logos.
- Pixel-perfect cloning.
- Scraping or storing bank credentials.
