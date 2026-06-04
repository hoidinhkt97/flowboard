from flowboard.services.security import (
    decrypt_secret,
    encrypt_secret,
    generate_token,
    hash_token,
)


def test_generate_token_is_random_and_long():
    a, b = generate_token(), generate_token()
    assert a != b
    assert len(a) >= 32


def test_hash_token_is_stable_and_opaque():
    raw = "abc123"
    assert hash_token(raw) == hash_token(raw)
    assert hash_token(raw) != raw


def test_encrypt_decrypt_round_trips():
    blob = encrypt_secret("sk-ant-secret")
    assert isinstance(blob, bytes)
    assert blob != b"sk-ant-secret"
    assert decrypt_secret(blob) == "sk-ant-secret"
