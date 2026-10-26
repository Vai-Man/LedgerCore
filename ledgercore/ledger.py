"""Double-entry ledger on SQLite.

Design rules:
  * Amounts are integers in minor units (cents, paise, ...). Never floats.
  * A transaction is a set of signed postings that sum to zero in one currency.
  * Every write runs inside BEGIN IMMEDIATE, so balance checks and updates are
    atomic with respect to every other writer (this is what prevents double-spend).
  * Every write carries an idempotency key. Replaying a key with the same request
    returns the original transaction; replaying it with a different request fails.
"""

import hashlib
import json
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from .errors import (
    AccountExists,
    AccountNotFound,
    CurrencyMismatch,
    IdempotencyConflict,
    InsufficientFunds,
    ValidationError,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL UNIQUE,
    currency       TEXT    NOT NULL,
    allow_negative INTEGER NOT NULL DEFAULT 0,
    balance        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT    NOT NULL UNIQUE,
    request_hash    TEXT    NOT NULL,
    memo            TEXT    NOT NULL DEFAULT '',
    created_at      REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS postings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id     INTEGER NOT NULL REFERENCES transactions(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount     INTEGER NOT NULL CHECK (amount != 0)
);
CREATE INDEX IF NOT EXISTS idx_postings_account ON postings(account_id);
CREATE INDEX IF NOT EXISTS idx_postings_txn     ON postings(txn_id);
"""

AccountRef = Union[str, int]
Entry = Tuple[AccountRef, int]


@dataclass(frozen=True)
class Transaction:
    id: int
    idempotency_key: str
    memo: str
    created_at: float
    postings: Tuple[Tuple[str, int], ...]  # (account name, signed amount)
    replayed: bool = False


class Ledger:
    """A ledger stored in a SQLite file. Safe to share between threads."""

    def __init__(self, path: str, busy_timeout: float = 30.0):
        if path == ":memory:":
            raise ValueError("use a file path; in-memory databases are per-connection")
        self.path = path
        self._busy_timeout = busy_timeout
        self._local = threading.local()
        con = self._con()
        con.executescript(SCHEMA)

    # ------------------------------------------------------------------ plumbing
    def _con(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.path, timeout=self._busy_timeout, isolation_level=None)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            self._local.con = con
        return con

    def close(self) -> None:
        con = getattr(self._local, "con", None)
        if con is not None:
            con.close()
            self._local.con = None

    # ------------------------------------------------------------------ accounts
    def create_account(self, name: str, currency: str = "USD", allow_negative: bool = False) -> int:
        if not name or not name.strip():
            raise ValidationError("account name is required")
        if not currency or len(currency) != 3 or not currency.isalpha():
            raise ValidationError("currency must be a 3-letter code")
        con = self._con()
        try:
            cur = con.execute(
                "INSERT INTO accounts(name, currency, allow_negative) VALUES (?,?,?)",
                (name, currency.upper(), 1 if allow_negative else 0),
            )
        except sqlite3.IntegrityError as exc:
            raise AccountExists(name) from exc
        return int(cur.lastrowid)

    def _account(self, con: sqlite3.Connection, ref: AccountRef) -> sqlite3.Row:
        column = "id" if isinstance(ref, int) else "name"
        row = con.execute(f"SELECT * FROM accounts WHERE {column} = ?", (ref,)).fetchone()
        if row is None:
            raise AccountNotFound(str(ref))
        return row

    def get_balance(self, ref: AccountRef) -> int:
        """Cached balance in minor units."""
        return int(self._account(self._con(), ref)["balance"])

    def computed_balance(self, ref: AccountRef) -> int:
        """Balance recomputed from postings (used by reconciliation)."""
        con = self._con()
        acc = self._account(con, ref)
        row = con.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM postings WHERE account_id = ?", (acc["id"],)
        ).fetchone()
        return int(row["s"])

    def list_accounts(self) -> List[sqlite3.Row]:
        return self._con().execute("SELECT * FROM accounts ORDER BY id").fetchall()

    # ------------------------------------------------------------------ writes
    def post(self, entries: Sequence[Entry], idempotency_key: str, memo: str = "") -> Transaction:
        """Post a balanced set of signed entries atomically."""
        if not idempotency_key or not str(idempotency_key).strip():
            raise ValidationError("idempotency_key is required")
        entries = self._validate_entries(entries)
        request_hash = self._hash_request(entries, memo)

        con = self._con()
        con.execute("BEGIN IMMEDIATE")
        try:
            existing = con.execute(
                "SELECT id, request_hash FROM transactions WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict(
                        f"key {idempotency_key!r} was already used for a different request"
                    )
                txn = self._load(con, int(existing["id"]), replayed=True)
                con.execute("COMMIT")
                return txn

            # Resolve accounts and aggregate by account (a txn may touch one account twice).
            totals = OrderedDict()
            for ref, amount in entries:
                acc = self._account(con, ref)
                bucket = totals.setdefault(acc["id"], [acc, 0])
                bucket[1] += amount

            currencies = {acc["currency"] for acc, _ in totals.values()}
            if len(currencies) != 1:
                raise CurrencyMismatch(", ".join(sorted(currencies)))

            for acc, delta in totals.values():
                if not acc["allow_negative"] and acc["balance"] + delta < 0:
                    raise InsufficientFunds(
                        f"{acc['name']}: balance {acc['balance']}, change {delta}"
                    )

            now = time.time()
            cur = con.execute(
                "INSERT INTO transactions(idempotency_key, request_hash, memo, created_at) VALUES (?,?,?,?)",
                (idempotency_key, request_hash, memo, now),
            )
            txn_id = int(cur.lastrowid)
            for ref, amount in entries:
                acc = self._account(con, ref)
                con.execute(
                    "INSERT INTO postings(txn_id, account_id, amount) VALUES (?,?,?)",
                    (txn_id, acc["id"], amount),
                )
            for acc, delta in totals.values():
                con.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (delta, acc["id"]))

            txn = self._load(con, txn_id, replayed=False)
            con.execute("COMMIT")
            return txn
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise

    def transfer(self, source: AccountRef, destination: AccountRef, amount: int,
                 idempotency_key: str, memo: str = "") -> Transaction:
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValidationError("transfer amount must be a positive integer (minor units)")
        if source == destination:
            raise ValidationError("source and destination must differ")
        return self.post([(source, -amount), (destination, amount)], idempotency_key, memo)

    def deposit(self, account: AccountRef, amount: int, idempotency_key: str, memo: str = "") -> Transaction:
        """Credit an account from the per-currency external account."""
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValidationError("deposit amount must be a positive integer (minor units)")
        con = self._con()
        currency = self._account(con, account)["currency"]
        external = self._external_account(currency)
        return self.post([(external, -amount), (account, amount)], idempotency_key, memo)

    def withdraw(self, account: AccountRef, amount: int, idempotency_key: str, memo: str = "") -> Transaction:
        """Debit an account to the per-currency external account."""
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValidationError("withdrawal amount must be a positive integer (minor units)")
        con = self._con()
        currency = self._account(con, account)["currency"]
        external = self._external_account(currency)
        return self.post([(account, -amount), (external, amount)], idempotency_key, memo)

    def _external_account(self, currency: str) -> str:
        name = f"@external:{currency}"
        try:
            self.create_account(name, currency, allow_negative=True)
        except AccountExists:
            pass
        return name

    # ------------------------------------------------------------------ reads
    def get_transaction(self, idempotency_key: str) -> Optional[Transaction]:
        con = self._con()
        row = con.execute("SELECT id FROM transactions WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        return None if row is None else self._load(con, int(row["id"]), replayed=False)

    def history(self, ref: AccountRef, limit: int = 100) -> List[Tuple[int, int, str]]:
        """Most recent postings for an account: (txn_id, amount, idempotency_key)."""
        con = self._con()
        acc = self._account(con, ref)
        rows = con.execute(
            """SELECT p.txn_id, p.amount, t.idempotency_key
                 FROM postings p JOIN transactions t ON t.id = p.txn_id
                WHERE p.account_id = ? ORDER BY p.id DESC LIMIT ?""",
            (acc["id"], limit),
        ).fetchall()
        return [(int(r["txn_id"]), int(r["amount"]), r["idempotency_key"]) for r in rows]

    def transaction_count(self) -> int:
        return int(self._con().execute("SELECT COUNT(*) AS c FROM transactions").fetchone()["c"])

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _validate_entries(entries: Iterable[Entry]) -> List[Entry]:
        entries = list(entries)
        if len(entries) < 2:
            raise ValidationError("a transaction needs at least two postings")
        total = 0
        for ref, amount in entries:
            if not isinstance(amount, int) or isinstance(amount, bool):
                raise ValidationError("amounts must be integers in minor units")
            if amount == 0:
                raise ValidationError("zero-amount postings are not allowed")
            total += amount
        if total != 0:
            raise ValidationError(f"postings must sum to zero, got {total}")
        return entries

    @staticmethod
    def _hash_request(entries: Sequence[Entry], memo: str) -> str:
        canonical = json.dumps(
            {"entries": sorted((str(ref), amount) for ref, amount in entries), "memo": memo},
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _load(con: sqlite3.Connection, txn_id: int, replayed: bool) -> Transaction:
        head = con.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
        rows = con.execute(
            """SELECT a.name AS name, p.amount AS amount
                 FROM postings p JOIN accounts a ON a.id = p.account_id
                WHERE p.txn_id = ? ORDER BY p.id""",
            (txn_id,),
        ).fetchall()
        return Transaction(
            id=int(head["id"]),
            idempotency_key=head["idempotency_key"],
            memo=head["memo"],
            created_at=float(head["created_at"]),
            postings=tuple((r["name"], int(r["amount"])) for r in rows),
            replayed=replayed,
        )
