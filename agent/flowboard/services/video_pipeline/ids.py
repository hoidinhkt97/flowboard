"""Human-friendly short ids for runs: ``vpr_<5 base32 chars>``."""
from __future__ import annotations

import secrets

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def new_short_id() -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(5))
    return f"vpr_{body}"
