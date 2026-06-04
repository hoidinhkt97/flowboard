"""JWT secret minimum-length startup check."""
import logging
import pytest


def test_startup_warns_on_short_jwt_secret(monkeypatch, caplog):
    import flowboard.config as cfg
    monkeypatch.setattr(cfg, "JWT_SECRET", "short")  # 5 bytes — below minimum

    with caplog.at_level(logging.WARNING, logger="flowboard.main"):
        from flowboard.main import _check_jwt_secret_length
        _check_jwt_secret_length()

    warning_messages = " ".join(r.message for r in caplog.records)
    assert "JWT_SECRET" in warning_messages
    assert "32" in warning_messages or "minimum" in warning_messages.lower()


def test_startup_no_warning_on_adequate_secret(monkeypatch, caplog):
    import flowboard.config as cfg
    monkeypatch.setattr(cfg, "JWT_SECRET", "a" * 32)  # exactly 32 bytes

    with caplog.at_level(logging.WARNING, logger="flowboard.main"):
        from flowboard.main import _check_jwt_secret_length
        _check_jwt_secret_length()

    jwt_warnings = [r for r in caplog.records if "JWT_SECRET" in r.message]
    assert len(jwt_warnings) == 0


def test_check_does_not_raise(monkeypatch):
    """Check must only warn, never crash the server."""
    import flowboard.config as cfg
    monkeypatch.setattr(cfg, "JWT_SECRET", "short")
    from flowboard.main import _check_jwt_secret_length
    _check_jwt_secret_length()  # must not raise
