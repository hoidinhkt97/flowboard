"""User identity surfaced from the extension.

The Chrome extension proactively fetches Google's
``/oauth2/v2/userinfo`` once it captures a Bearer token, then pushes
the resolved profile to the agent over WebSocket. This route just
exposes the cached object for the frontend's AccountPanel.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from flowboard.db.models import Account
from flowboard.deps import get_current_account
from flowboard.services.registry import registry

router = APIRouter(prefix="/api/auth", tags=["auth"])


# Test hook kept for backward compatibility with existing test imports.
def _reset_db_tier_cache_for_tests() -> None:
    """No-op — preserved so existing tests' `from .auth import
    _reset_db_tier_cache_for_tests` doesn't break."""
    return


@router.get("/me")
def get_me(acct: Account = Depends(get_current_account)) -> dict:
    fc = registry.get(acct.id)
    info = (fc.user_info or {}) if fc else {}
    return {
        "email": info.get("email"),
        "name": info.get("name"),
        "picture": info.get("picture"),
        "verified_email": info.get("verified_email"),
        "paygate_tier": fc.paygate_tier if fc else None,
        "sku": fc.sku if fc else None,
        "credits": fc.credits if fc else None,
    }


@router.post("/logout")
async def logout(acct: Account = Depends(get_current_account)) -> dict:
    fc = registry.get(acct.id)
    extension_notified = False
    if fc is not None:
        extension_notified = await fc.notify({"type": "logout"})
        fc.clear_extension()
    return {"ok": True, "extension_notified": extension_notified}


@router.post("/scan")
async def scan_extension(acct: Account = Depends(get_current_account)) -> dict:
    fc = registry.get(acct.id)
    if fc is None:
        return {"extension_connected": False, "has_user_info": False,
                "has_paygate_tier": False, "userinfo_nudged": False, "tier_fetched": False}
    nudged = False
    if fc.connected and fc.user_info is None:
        nudged = await fc.notify({"type": "please_resend_userinfo"})
    tier_fetched = False
    if fc.paygate_tier is None:
        tier_fetched = await fc.fetch_paygate_tier()
    return {
        "extension_connected": fc.connected,
        "has_user_info": fc.user_info is not None,
        "has_paygate_tier": fc.paygate_tier is not None,
        "userinfo_nudged": nudged,
        "tier_fetched": tier_fetched,
    }
