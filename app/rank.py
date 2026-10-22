"""One place decides that suspicious outranks every other label.

A suspicious message is never urgent, including as a secondary label. Callers
that want a category go through ``settle`` instead of setting the two fields
on their own.
"""

from __future__ import annotations


def settle(category: str, secondary: list[str] | None, suspicious: bool) -> tuple[str, list[str]]:
    """Return the category and secondary labels after the rank rule.

    When ``suspicious`` is true the category is suspicious and urgent is
    removed. Otherwise the category is unchanged and a duplicate of itself is
    dropped from the secondary list.
    """
    extras = [item for item in (secondary or []) if item and item != category]
    if suspicious:
        return "suspicious", [item for item in extras if item != "urgent"]
    return category, extras
