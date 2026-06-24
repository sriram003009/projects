"""User-facing error messages for cache-only vs live-fetch modes."""

from __future__ import annotations

LIVE_FETCH_HINT = (
    " No cached data on disk. Check **Fetch live data** and try again."
)


def cache_miss_message(what: str, *, ticker: str = "", detail: str = "") -> str:
    """Plain message when ``live_fetch=False`` and nothing is on disk."""
    base = f"No cached {what}"
    if ticker:
        base += f" for `{ticker}`"
    if detail:
        base += f" ({detail})"
    return base + "." + LIVE_FETCH_HINT
