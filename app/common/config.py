"""Runtime settings, read from environment variables set by Terraform."""

import os

# Fixed list the Extractor must pick from (also enforced in its JSON schema).
CATEGORIES = [
    "Office supplies",
    "Travel",
    "Utilities",
    "Software",
    "Meals",
    "Professional services",
    "Other",
]

DOCUMENT_TYPES = ["invoice", "receipt", "credit_note", "not_financial"]


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"missing environment variable {name}")
    return value
