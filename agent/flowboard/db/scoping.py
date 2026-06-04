"""Tenant-isolation helpers. Every multi-tenant route resolves rows through
these so a cross-tenant id always looks like 'not found' (404), never 403 —
we don't leak the existence of another account's data."""
from __future__ import annotations

from fastapi import HTTPException


def owned_or_404(session, model, pk, account_id):
    """Fetch `model` by primary key, but only if it belongs to `account_id`.
    Raises 404 for missing rows AND for rows owned by a different account."""
    row = session.get(model, pk)
    if row is None or getattr(row, "account_id", None) != account_id:
        raise HTTPException(status_code=404, detail=f"{model.__name__.lower()} not found")
    return row
