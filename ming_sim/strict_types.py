"""Shared strict scalar contracts for structured machine payloads."""


def strict_int(raw: object, *, accept_numeric_strings: bool = True) -> int:
    """Reject bools/floats; optionally retain legacy acceptance of integer strings."""
    if isinstance(raw, bool) or isinstance(raw, float):
        raise ValueError("value must be an integer")
    if not accept_numeric_strings and not isinstance(raw, int):
        raise ValueError("value must be an integer")
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("value must be an integer") from exc
