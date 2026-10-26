import pytest

from ledgercore import (
    AccountExists,
    AccountNotFound,
    ValidationError,
    from_minor,
    to_minor,
)


def test_create_account_returns_id(ledger):
    assert isinstance(ledger.create_account("a", "USD"), int)


def test_duplicate_account_name_rejected(ledger):
    ledger.create_account("a", "USD")
    with pytest.raises(AccountExists):
        ledger.create_account("a", "USD")


def test_empty_account_name_rejected(ledger):
    with pytest.raises(ValidationError):
        ledger.create_account("   ", "USD")


@pytest.mark.parametrize("currency", ["", "US", "USDD", "12$"])
def test_bad_currency_rejected(ledger, currency):
    with pytest.raises(ValidationError):
        ledger.create_account("a", currency)


def test_currency_is_uppercased(ledger):
    ledger.create_account("a", "usd")
    assert ledger.list_accounts()[0]["currency"] == "USD"


def test_new_account_has_zero_balance(ledger):
    ledger.create_account("a", "USD")
    assert ledger.get_balance("a") == 0


def test_unknown_account_raises(ledger):
    with pytest.raises(AccountNotFound):
        ledger.get_balance("ghost")


def test_account_lookup_by_id(ledger):
    acc_id = ledger.create_account("a", "USD")
    assert ledger.get_balance(acc_id) == 0


def test_to_minor_two_decimals():
    assert to_minor("12.34", "USD") == 1234


def test_to_minor_zero_decimal_currency():
    assert to_minor("500", "JPY") == 500


def test_to_minor_three_decimal_currency():
    assert to_minor("1.234", "KWD") == 1234


def test_to_minor_rejects_float():
    with pytest.raises(ValidationError):
        to_minor(1.1, "USD")


def test_to_minor_rejects_excess_precision():
    with pytest.raises(ValidationError):
        to_minor("1.005", "USD")


def test_to_minor_rejects_garbage():
    with pytest.raises(ValidationError):
        to_minor("abc", "USD")


def test_from_minor_roundtrip():
    assert from_minor(to_minor("-7.05", "USD"), "USD") == "-7.05"


def test_from_minor_small_amounts_are_padded():
    assert from_minor(5, "USD") == "0.05"
