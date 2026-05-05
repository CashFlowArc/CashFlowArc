from __future__ import annotations

from dataclasses import dataclass

from .crypto import TokenCipher
from .db import BudgetStore
from .teller import TellerClient


@dataclass(frozen=True)
class SyncSummary:
    connection_id: str
    accounts: int
    transactions: int


def sync_connection(
    *,
    store: BudgetStore,
    teller: TellerClient,
    cipher: TokenCipher,
    connection_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> SyncSummary:
    token_cipher = store.get_connection_token_cipher(connection_id)
    access_token = cipher.decrypt(token_cipher)

    accounts = teller.list_accounts(access_token)
    total_transactions = 0

    for account in accounts:
        store.upsert_account(connection_id, account)
    store.conn.commit()

    for account in accounts:
        links = account.get("links") or {}
        if not links.get("transactions"):
            continue

        try:
            transactions = teller.list_transactions(
                access_token,
                account["id"],
                start_date=start_date,
                end_date=end_date,
            )
            for transaction in transactions:
                store.upsert_transaction(
                    connection_id=connection_id,
                    account=account,
                    transaction=transaction,
                )
            total_transactions += len(transactions)
            store.record_sync_event(
                connection_id=connection_id,
                account_id=account.get("id"),
                event_type="transactions_sync",
                status="success",
                rows_upserted=len(transactions),
            )
        except Exception as exc:
            store.record_sync_event(
                connection_id=connection_id,
                account_id=account.get("id"),
                event_type="transactions_sync",
                status="failed",
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
            raise

    store.mark_connection_synced(connection_id)
    return SyncSummary(
        connection_id=connection_id,
        accounts=len(accounts),
        transactions=total_transactions,
    )
