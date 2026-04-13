"""Terminal confirmation helper for destructive operations.

This is the safety gate for `edit_entry` and `delete_entry`. It prints a
before/after diff and waits for a `y` keypress before returning True. The LLM
cannot bypass this gate — it lives in Python code, not the prompt.
"""

import sys
from typing import Any


def _format_diff(before: dict[str, Any], after: dict[str, Any] | None) -> str:
    """Render a before/after diff. If `after` is None, this is a deletion."""
    lines = []
    if after is None:
        lines.append("  This entry will be DELETED:")
        for k, v in before.items():
            lines.append(f"    {k}: {v}")
        return "\n".join(lines)

    all_keys = sorted(set(before.keys()) | set(after.keys()))
    for k in all_keys:
        b = before.get(k, "<unset>")
        a = after.get(k, "<unset>")
        if b == a:
            lines.append(f"    {k}: {b}")
        else:
            lines.append(f"    {k}: {b}  ->  {a}")
    return "\n".join(lines)


def confirm_action(
    title: str,
    before: dict[str, Any],
    after: dict[str, Any] | None,
) -> bool:
    """Show a before/after diff and ask the user to confirm with `y`.

    Args:
        title: Short header, e.g. "Edit entry 12345" or "Delete entry 12345".
        before: Current state of the entry.
        after: New state, or None for deletions.

    Returns:
        True iff the user typed "y" or "yes".
    """
    print()
    print(f"=== {title} ===")
    print(_format_diff(before, after))
    print()
    print("Type 'y' to confirm, anything else to cancel:", end=" ", flush=True)
    response = sys.stdin.readline().strip().lower()
    return response in ("y", "yes")
