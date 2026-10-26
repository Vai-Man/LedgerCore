import pytest

from ledgercore import (
    AccountNotFound,
    CurrencyMismatch,
    InsufficientFunds,
    ValidationError,
)


def test_transfer_moves_money(funded):
    funded.transfer("alice", "bob", 2_500, "t1")
    assert funded.get_balance("alice") == 7_500
    assert funded.get_balance("bob") == 2_500


def test_transfer_postings_sum_to_zero(funded):
    txn = funded.transfer("alice", "bob", 1_000, "t1")
    assert sum(amount for _, amount in txn.postings) == 0


def test_transfer_whole_balance(funded):
    funded.transfer("alice", "bob", 10_000, "t1")
    assert funded.get_balance("alice") == 0


def test_transfer_more_than_balance_fails(funded):
    with pytest.raises(InsufficientFunds):
        funded.transfer("alice", "bob", 10_001, "t1")


def test_failed_transfer_changes_nothing(funded):
    with pytest.raises(InsufficientFunds):
        funded.transfer("alice", "bob", 99_999, "t1")
    assert funded.get_balance("alice") == 10_000
    assert funded.get_balance("bob") == 0
    assert funded.get_transaction("t1") is None


def test_failed_transfer_does_not_burn_the_key(funded):
    with pytest.raises(InsufficientFunds):
        funded.transfer("alice", "bob", 99_999, "t1")
    funded.transfer("alice", "bob", 100, "t1")
    assert funded.get_balance("bob") == 100


@pytest.mark.parametrize("amount", [0, -5])
def test_non_positive_transfer_rejected(funded, amount):
    with pytest.raises(ValidationError):
        funded.transfer("alice", "bob", amount, "t1")


def test_float_transfer_rejected(funded):
    with pytest.raises(ValidationError):
        funded.transfer("alice", "bob", 10.5, "t1")


def test_boolean_amount_rejected(funded):
    with pytest.raises(ValidationError):
        funded.transfer("alice", "bob", True, "t1")


def test_self_transfer_rejected(funded):
    with pytest.raises(ValidationError):
        funded.transfer("alice", "alice", 100, "t1")


def test_transfer_to_unknown_account(funded):
    with pytest.raises(AccountNotFound):
        funded.transfer("alice", "ghost", 100, "t1")


def test_cross_currency_transfer_rejected(funded):
    funded.create_account("eur-acc", "EUR")
    with pytest.raises(CurrencyMismatch):
        funded.transfer("alice", "eur-acc", 100, "t1")


def test_overdraft_account_may_go_negative(ledger):
    ledger.create_account("credit", "USD", allow_negative=True)
    ledger.create_account("shop", "USD")
    ledger.transfer("credit", "shop", 500, "t1")
    assert ledger.get_balance("credit") == -500


def test_deposit_and_withdraw_use_external_account(ledger):
    ledger.create_account("a", "USD")
    ledger.deposit("a", 1_000, "d1")
    ledger.withdraw("a", 400, "w1")
    assert ledger.get_balance("a") == 600
    assert ledger.get_balance("@external:USD") == -600


def test_withdraw_more_than_balance_fails(ledger):
    ledger.create_account("a", "USD")
    ledger.deposit("a", 100, "d1")
    with pytest.raises(InsufficientFunds):
        ledger.withdraw("a", 101, "w1")


def test_post_with_three_legs(funded):
    funded.create_account("fees", "USD")
    funded.post([("alice", -1_000), ("bob", 900), ("fees", 100)], "split-1")
    assert funded.get_balance("fees") == 100
    assert funded.get_balance("bob") == 900


def test_post_same_account_twice_is_aggregated_for_balance_check(funded):
    # alice has 10_000; two debits of 6_000 in one transaction must be rejected.
    with pytest.raises(InsufficientFunds):
        funded.post([("alice", -6_000), ("alice", -6_000), ("bob", 12_000)], "dbl")


def test_unbalanced_post_rejected(funded):
    with pytest.raises(ValidationError):
        funded.post([("alice", -100), ("bob", 99)], "bad")


def test_single_leg_post_rejected(funded):
    with pytest.raises(ValidationError):
        funded.post([("alice", 0)], "bad")


def test_zero_amount_leg_rejected(funded):
    with pytest.raises(ValidationError):
        funded.post([("alice", -100), ("bob", 100), ("alice", 0)], "bad")


def test_history_lists_newest_first(funded):
    funded.transfer("alice", "bob", 100, "t1")
    funded.transfer("alice", "bob", 200, "t2")
    keys = [key for _, _, key in funded.history("bob")]
    assert keys == ["t2", "t1"]
