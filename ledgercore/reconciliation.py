"""Consistency checks between the ledger's cached balances, its postings and an
optional external statement."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .ledger import Ledger


@dataclass(frozen=True)
class Issue:
    kind: str
    detail: str


@dataclass
class ReconciliationReport:
    issues: List[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def kinds(self) -> List[str]:
        return sorted({i.kind for i in self.issues})


def reconcile(ledger: Ledger, statement: Optional[Dict[str, int]] = None) -> ReconciliationReport:
    """Check the ledger and, if given, compare it with an external statement.

    Checks:
      cached_balance_mismatch   cached balance differs from the sum of postings
      unbalanced_transaction    a transaction's postings do not sum to zero
      currency_not_zero_sum     balances in one currency do not sum to zero
      negative_balance          a non-overdraft account is below zero
      statement_mismatch        statement balance differs from the ledger
      statement_unknown_account statement names an account the ledger does not have
    """
    report = ReconciliationReport()
    con = ledger._con()

    for acc in con.execute("SELECT * FROM accounts ORDER BY id").fetchall():
        computed = ledger.computed_balance(int(acc["id"]))
        if computed != acc["balance"]:
            report.issues.append(Issue(
                "cached_balance_mismatch",
                f"{acc['name']}: cached {acc['balance']}, postings sum to {computed}",
            ))
        if not acc["allow_negative"] and acc["balance"] < 0:
            report.issues.append(Issue("negative_balance", f"{acc['name']}: {acc['balance']}"))

    for row in con.execute(
        "SELECT txn_id, SUM(amount) AS s FROM postings GROUP BY txn_id HAVING s != 0"
    ).fetchall():
        report.issues.append(Issue("unbalanced_transaction", f"txn {row['txn_id']} sums to {row['s']}"))

    for row in con.execute(
        "SELECT currency, SUM(balance) AS s FROM accounts GROUP BY currency HAVING s != 0"
    ).fetchall():
        report.issues.append(Issue("currency_not_zero_sum", f"{row['currency']}: {row['s']}"))

    if statement is not None:
        known = {r["name"]: r["balance"] for r in con.execute("SELECT name, balance FROM accounts")}
        for name, expected in statement.items():
            if name not in known:
                report.issues.append(Issue("statement_unknown_account", name))
            elif known[name] != expected:
                report.issues.append(Issue(
                    "statement_mismatch", f"{name}: ledger {known[name]}, statement {expected}"
                ))
    return report
