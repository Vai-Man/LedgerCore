# LedgerCore

A small double-entry payments ledger in Python, backed by SQLite. It was written to get the hard parts of money movement right: balanced entries, idempotent retries, no double-spend under concurrency, and a reconciliation job that catches drift.

No dependencies outside the standard library.

## What it does

- **Double-entry postings.** Each transaction is a set of signed postings in one currency that must sum to zero.
- **Integer money.** Amounts are minor units (cents, paise). Floats are rejected.
- **Idempotency keys.** Every write needs one. Replaying a key with the same request returns the original transaction; reusing it for a different request raises `IdempotencyConflict`.
- **No overdrafts, no double-spend.** Writes run in `BEGIN IMMEDIATE`, so the balance check and the update are one atomic step across threads and processes.
- **Reconciliation.** Checks cached balances against postings, balanced transactions, per-currency zero-sum, non-negative balances, and an optional external statement.

## Quick start

```bash
pip install -e .
python -m pytest
```

```python
from ledgercore import Ledger, reconcile

ledger = Ledger("ledger.db")
ledger.create_account("alice", "USD")
ledger.create_account("bob", "USD")

ledger.deposit("alice", 10_000, idempotency_key="seed-1")      # $100.00
ledger.transfer("alice", "bob", 2_500, idempotency_key="pay-1")
ledger.transfer("alice", "bob", 2_500, idempotency_key="pay-1")  # replay: no second transfer

print(ledger.get_balance("bob"))             # 2500
print(reconcile(ledger).ok)                  # True
```

## How it works

| Table | Purpose |
|---|---|
| `accounts` | Name, currency, overdraft flag, cached balance |
| `transactions` | One row per posted transaction; unique `idempotency_key` and a hash of the request |
| `postings` | Signed amounts per account; each transaction's postings sum to zero |

The request hash covers the sorted entries and the memo, so entry order does not matter but any change in amount, account or memo is a conflict.

Balances are cached on `accounts` for fast reads and verified against the postings by `reconcile()`.

## Reconciliation

`reconcile(ledger, statement=None)` returns a report. Issue kinds:

`cached_balance_mismatch`, `unbalanced_transaction`, `currency_not_zero_sum`, `negative_balance`, `statement_mismatch`, `statement_unknown_account`.

## Tests

The suite covers validation, transfers and overdrafts, idempotent replays and conflicts, reconciliation failures, and concurrent scenarios (overspend, retry storms, transfers in both directions).

```bash
python -m pytest
```

## Limitations

- SQLite serialises writers, so this is a correctness reference, not a high-throughput system.
- One database file; there is no sharding or replication.
- Multi-currency transactions (FX) are rejected rather than modelled.
- No authentication or API layer. It is a library.

## License

MIT
