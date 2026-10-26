"""Exceptions raised by LedgerCore."""


class LedgerError(Exception):
    """Base class for all ledger errors."""


class ValidationError(LedgerError):
    """The request is malformed (unbalanced entries, zero amounts, missing key, ...)."""


class AccountNotFound(LedgerError):
    """A posting refers to an account that does not exist."""


class AccountExists(LedgerError):
    """An account with that name already exists."""


class CurrencyMismatch(LedgerError):
    """Postings of one transaction span more than one currency."""


class InsufficientFunds(LedgerError):
    """A posting would take a non-overdraft account below zero."""


class IdempotencyConflict(LedgerError):
    """An idempotency key was reused with a different request."""
