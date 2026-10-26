import threading

import pytest

from ledgercore import InsufficientFunds, reconcile


def run_in_threads(ledger, count, worker):
    """Run worker(i) in `count` threads; return (results, errors) lists."""
    results, errors = [], []
    lock = threading.Lock()
    barrier = threading.Barrier(count)

    def target(i):
        try:
            barrier.wait()
            value = worker(i)
            with lock:
                results.append(value)
        except Exception as exc:  # noqa: BLE001 - collected for assertions
            with lock:
                errors.append(exc)
        finally:
            ledger.close()

    threads = [threading.Thread(target=target, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


def test_concurrent_overspend_never_goes_negative(funded):
    # alice has 10_000. Twenty threads each try to send 4_000 with distinct keys.
    results, errors = run_in_threads(
        funded, 20, lambda i: funded.transfer("alice", "bob", 4_000, f"spend-{i}")
    )
    assert len(results) == 2
    assert len(errors) == 18 and all(isinstance(e, InsufficientFunds) for e in errors)
    assert funded.get_balance("alice") == 2_000
    assert funded.get_balance("bob") == 8_000


def test_concurrent_overspend_leaves_ledger_consistent(funded):
    run_in_threads(funded, 12, lambda i: funded.transfer("alice", "bob", 3_000, f"s-{i}"))
    assert reconcile(funded).ok


def test_same_key_from_many_threads_posts_once(funded):
    results, errors = run_in_threads(
        funded, 16, lambda i: funded.transfer("alice", "bob", 500, "same-key")
    )
    assert errors == []
    assert len({txn.id for txn in results}) == 1
    assert sum(1 for txn in results if not txn.replayed) == 1
    assert funded.get_balance("bob") == 500


def test_many_small_concurrent_transfers_add_up(funded):
    results, errors = run_in_threads(
        funded, 40, lambda i: funded.transfer("alice", "bob", 10, f"small-{i}")
    )
    assert errors == []
    assert funded.get_balance("bob") == 400
    assert funded.get_balance("alice") == 9_600


def test_concurrent_transfers_in_both_directions(funded):
    funded.deposit("bob", 10_000, "seed-bob")

    def worker(i):
        if i % 2 == 0:
            return funded.transfer("alice", "bob", 25, f"ab-{i}")
        return funded.transfer("bob", "alice", 25, f"ba-{i}")

    _, errors = run_in_threads(funded, 30, worker)
    assert errors == []
    assert funded.get_balance("alice") + funded.get_balance("bob") == 20_000
    assert reconcile(funded).ok


def test_retry_storm_with_mixed_keys(funded):
    # Ten logical payments, each retried by three threads.
    results, errors = run_in_threads(
        funded, 30, lambda i: funded.transfer("alice", "bob", 100, f"pay-{i % 10}")
    )
    assert errors == []
    assert funded.get_balance("bob") == 1_000
    assert funded.transaction_count() == 11  # seed deposit + ten payments
