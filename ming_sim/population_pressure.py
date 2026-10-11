"""Applied population-transfer predicates shared by covert levy and settlement."""

from __future__ import annotations


def is_actual_population_transfer(item: object) -> bool:
    """Applied feedback includes legal zero attempts; only positive amounts moved people."""
    return (isinstance(item, dict) and not item.get("rejected")
            and int(item.get("amount") or 0) > 0)
