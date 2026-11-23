"""Shared LAMB endpoint defaults without importing a transport backend."""

import os

DEFAULT_LAMB_URL = "http://lamb-server:8000"


def resolve_lamb_url(
    url: str | None = None,
    *,
    profile_url: str | None = None,
) -> str:
    """Resolve explicit/profile URLs, environment, then the standard default."""
    return (url or profile_url or os.getenv("LAMB_SERVER") or DEFAULT_LAMB_URL).rstrip("/")
