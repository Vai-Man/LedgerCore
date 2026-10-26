from ledgercore import reconcile


def test_clean_ledger_reconciles(funded):
    funded.transfer("alice", "bob", 1_234, "t1")
    assert reconcile(funded).ok


def test_empty_ledger_reconciles(ledger):
    assert reconcile(ledger).ok


def test_detects_cached_balance_drift(funded):
    funded._con().execute("UPDATE accounts SET balance = balance + 5 WHERE name = 'alice'")
    report = reconcile(funded)
    assert "cached_balance_mismatch" in report.kinds()


def test_detects_unbalanced_transaction(funded):
    con = funded._con()
    con.execute("INSERT INTO transactions(idempotency_key, request_hash, created_at) VALUES ('x','h',0)")
    txn_id = con.execute("SELECT id FROM transactions WHERE idempotency_key='x'").fetchone()["id"]
    alice = con.execute("SELECT id FROM accounts WHERE name='alice'").fetchone()["id"]
    con.execute("INSERT INTO postings(txn_id, account_id, amount) VALUES (?,?,?)", (txn_id, alice, 50))
    assert "unbalanced_transaction" in reconcile(funded).kinds()


def test_detects_negative_balance_on_normal_account(funded):
    funded._con().execute("UPDATE accounts SET balance = -1 WHERE name = 'bob'")
    assert "negative_balance" in reconcile(funded).kinds()


def test_detects_currency_not_summing_to_zero(funded):
    funded._con().execute("UPDATE accounts SET balance = balance + 1 WHERE name = 'bob'")
    assert "currency_not_zero_sum" in reconcile(funded).kinds()


def test_matching_statement_is_ok(funded):
    funded.transfer("alice", "bob", 400, "t1")
    assert reconcile(funded, {"alice": 9_600, "bob": 400}).ok


def test_statement_mismatch_is_reported(funded):
    funded.transfer("alice", "bob", 400, "t1")
    report = reconcile(funded, {"alice": 9_600, "bob": 399})
    assert report.kinds() == ["statement_mismatch"]
    assert "bob" in report.issues[0].detail


def test_statement_with_unknown_account_is_reported(funded):
    report = reconcile(funded, {"nobody": 1})
    assert report.kinds() == ["statement_unknown_account"]


def test_statement_may_cover_a_subset_of_accounts(funded):
    assert reconcile(funded, {"alice": 10_000}).ok


def test_report_collects_several_issues(funded):
    funded._con().execute("UPDATE accounts SET balance = balance + 7 WHERE name = 'bob'")
    report = reconcile(funded, {"alice": 0})
    assert {"cached_balance_mismatch", "currency_not_zero_sum", "statement_mismatch"} <= set(report.kinds())
