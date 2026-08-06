"""Deterministic evaluation fixture intentionally kept small."""


def normalize_username(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("username is required")
    return value.strip().lower()

