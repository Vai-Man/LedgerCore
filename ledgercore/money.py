"""Helpers for converting between decimal strings and integer minor units."""

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from .errors import ValidationError

# Number of decimal places per currency. Anything not listed uses two.
_EXPONENTS = {"JPY": 0, "KRW": 0, "BHD": 3, "KWD": 3}


def exponent(currency: str) -> int:
    return _EXPONENTS.get(currency.upper(), 2)


def to_minor(amount, currency: str = "USD") -> int:
    """Convert a decimal amount (str, int, Decimal) to integer minor units.

    Floats are rejected on purpose: they cannot represent most decimal amounts.
    Amounts with more precision than the currency allows are rejected, not rounded.
    """
    if isinstance(amount, float):
        raise ValidationError("amounts must be int, str or Decimal, not float")
    try:
        value = Decimal(str(amount))
    except InvalidOperation as exc:
        raise ValidationError(f"not a number: {amount!r}") from exc
    scaled = value * (Decimal(10) ** exponent(currency))
    if scaled != scaled.to_integral_value(rounding=ROUND_HALF_EVEN):
        raise ValidationError(f"{amount!r} has more decimals than {currency} allows")
    return int(scaled)


def from_minor(minor: int, currency: str = "USD") -> str:
    """Format integer minor units as a decimal string."""
    exp = exponent(currency)
    if exp == 0:
        return str(minor)
    sign = "-" if minor < 0 else ""
    digits = str(abs(minor)).rjust(exp + 1, "0")
    return f"{sign}{digits[:-exp]}.{digits[-exp:]}"
