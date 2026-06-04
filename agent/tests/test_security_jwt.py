import pytest

from flowboard.services.security import create_access_token, decode_access_token


def test_round_trip_carries_account_id():
    tok = create_access_token(account_id=42)
    claims = decode_access_token(tok)
    assert claims["sub"] == "42"


def test_decode_rejects_garbage():
    with pytest.raises(Exception):
        decode_access_token("not-a-jwt")
