"""Primitive keyword query normalization shared by profile modules."""


def normalize_query(raw: str) -> str:
    """Trim whitespace and casefold a single query string."""
    return raw.strip().casefold()
