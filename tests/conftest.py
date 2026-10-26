import pytest

from ledgercore import Ledger


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(str(tmp_path / "ledger.db"))
    yield led
    led.close()


@pytest.fixture
def funded(ledger):
    """Two USD accounts: alice holds 10_000 minor units, bob holds nothing."""
    ledger.create_account("alice", "USD")
    ledger.create_account("bob", "USD")
    ledger.deposit("alice", 10_000, "seed-alice")
    return ledger
