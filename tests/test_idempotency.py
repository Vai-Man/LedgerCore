import pytest

from ledgercore import IdempotencyConflict, ValidationError


def test_replay_returns_same_transaction(funded):
    first = funded.transfer("alice", "bob", 500, "k1")
    second = funded.transfer("alice", "bob", 500, "k1")
    assert second.id == first.id
    assert second.replayed is True
    assert first.replayed is False


def test_replay_does_not_move_money_twice(funded):
    for _ in range(5):
        funded.transfer("alice", "bob", 500, "k1")
    assert funded.get_balance("bob") == 500


def test_replay_does_not_add_transactions(funded):
    funded.transfer("alice", "bob", 500, "k1")
    before = funded.transaction_count()
    funded.transfer("alice", "bob", 500, "k1")
    assert funded.transaction_count() == before


def test_same_key_different_amount_conflicts(funded):
    funded.transfer("alice", "bob", 500, "k1")
    with pytest.raises(IdempotencyConflict):
        funded.transfer("alice", "bob", 501, "k1")


def test_same_key_different_destination_conflicts(funded):
    funded.create_account("carol", "USD")
    funded.transfer("alice", "bob", 500, "k1")
    with pytest.raises(IdempotencyConflict):
        funded.transfer("alice", "carol", 500, "k1")


def test_same_key_different_memo_conflicts(funded):
    funded.transfer("alice", "bob", 500, "k1", memo="rent")
    with pytest.raises(IdempotencyConflict):
        funded.transfer("alice", "bob", 500, "k1", memo="food")


def test_entry_order_does_not_change_the_request_hash(funded):
    funded.post([("alice", -100), ("bob", 100)], "k1")
    again = funded.post([("bob", 100), ("alice", -100)], "k1")
    assert again.replayed is True


def test_replay_works_after_balance_has_changed(funded):
    funded.transfer("alice", "bob", 9_000, "k1")
    # alice could not afford this again, but a replay must still succeed.
    again = funded.transfer("alice", "bob", 9_000, "k1")
    assert again.replayed is True


@pytest.mark.parametrize("key", ["", "   ", None])
def test_missing_key_rejected(funded, key):
    with pytest.raises(ValidationError):
        funded.transfer("alice", "bob", 100, key)


def test_get_transaction_by_key(funded):
    funded.transfer("alice", "bob", 100, "k1", memo="hello")
    txn = funded.get_transaction("k1")
    assert txn is not None and txn.memo == "hello"


def test_get_transaction_unknown_key(funded):
    assert funded.get_transaction("nope") is None


def test_different_keys_make_different_transactions(funded):
    a = funded.transfer("alice", "bob", 100, "k1")
    b = funded.transfer("alice", "bob", 100, "k2")
    assert a.id != b.id
    assert funded.get_balance("bob") == 200
