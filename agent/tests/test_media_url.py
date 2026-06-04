"""Tests for GET /api/media/{media_id}/url."""
import pytest
from flowboard.db.models import Asset
from flowboard.db import get_session
from flowboard.services import object_storage


def _seed_asset(media_id: str, account_id: int | None, s3_key: str | None = None):
    with get_session() as s:
        s.add(Asset(
            uuid_media_id=media_id,
            kind="image",
            mime="image/jpeg",
            account_id=account_id,
            s3_key=s3_key,
        ))
        s.commit()


def test_media_url_returns_presigned_url(client, auth, monkeypatch):
    media_id = "cccccccccccccccccccccccccccccccccccc"
    _seed_asset(media_id, account_id=1, s3_key="1/cccc.jpg")

    monkeypatch.setattr(object_storage, "is_configured", lambda: True)

    async def fake_presigned(key: str, expires: int = 300) -> str:
        return f"https://bucket.s3.example.com/{key}?signed=1"

    monkeypatch.setattr(object_storage, "presigned_get_url", fake_presigned)

    resp = client.get(f"/api/media/{media_id}/url", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert "bucket.s3.example.com" in data["url"]
    assert data["expires_in"] == 300


def test_media_url_404_for_unknown(client, auth):
    resp = client.get("/api/media/unknownid-not-real/url", headers=auth)
    assert resp.status_code == 404


def test_media_url_404_for_wrong_account(client, auth):
    """Account cannot get a presigned URL for media belonging to a different account."""
    media_id = "dddddddddddddddddddddddddddddddddddd"
    # account_id=None means "no owner" — will not match the authed user (id=1)
    _seed_asset(media_id, account_id=None, s3_key="other/dddd.jpg")

    resp = client.get(f"/api/media/{media_id}/url", headers=auth)
    assert resp.status_code == 404


def test_media_url_fallback_when_no_s3_key(client, auth):
    """Without s3_key, return the local /media/:id serve path."""
    media_id = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    _seed_asset(media_id, account_id=1, s3_key=None)

    resp = client.get(f"/api/media/{media_id}/url", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert f"/media/{media_id}" in data["url"]
    assert data["expires_in"] is None


def test_media_url_requires_auth(client):
    resp = client.get("/api/media/anyid/url")
    assert resp.status_code == 401
