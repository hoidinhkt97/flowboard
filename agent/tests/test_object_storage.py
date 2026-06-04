import pytest
from unittest.mock import MagicMock, patch


def test_is_configured_false_when_no_bucket(monkeypatch):
    import flowboard.config as cfg
    monkeypatch.setattr(cfg, "S3_BUCKET", None)
    from flowboard.services import object_storage
    assert object_storage.is_configured() is False


def test_is_configured_true_when_bucket_set(monkeypatch):
    import flowboard.config as cfg
    monkeypatch.setattr(cfg, "S3_BUCKET", "my-bucket")
    monkeypatch.setattr(cfg, "S3_ACCESS_KEY", "key")
    monkeypatch.setattr(cfg, "S3_SECRET_KEY", "secret")
    from flowboard.services import object_storage
    assert object_storage.is_configured() is True


def test_s3_key_for():
    from flowboard.services.object_storage import s3_key_for
    assert s3_key_for(42, "abc-123", ".jpg") == "42/abc-123.jpg"
    assert s3_key_for(1, "xyz", ".mp4") == "1/xyz.mp4"


@pytest.mark.asyncio
async def test_upload_bytes_calls_put_object(monkeypatch):
    import flowboard.config as cfg
    monkeypatch.setattr(cfg, "S3_BUCKET", "my-bucket")
    monkeypatch.setattr(cfg, "S3_ACCESS_KEY", "key")
    monkeypatch.setattr(cfg, "S3_SECRET_KEY", "secret")
    monkeypatch.setattr(cfg, "S3_ENDPOINT", None)
    monkeypatch.setattr(cfg, "S3_REGION", "us-east-1")

    mock_client = MagicMock()
    mock_client.put_object = MagicMock()
    with patch("boto3.client", return_value=mock_client):
        from flowboard.services import object_storage
        key = await object_storage.upload_bytes("42/abc.jpg", b"imgdata", "image/jpeg")
    assert key == "42/abc.jpg"
    mock_client.put_object.assert_called_once_with(
        Bucket="my-bucket",
        Key="42/abc.jpg",
        Body=b"imgdata",
        ContentType="image/jpeg",
    )


@pytest.mark.asyncio
async def test_presigned_get_url(monkeypatch):
    import flowboard.config as cfg
    monkeypatch.setattr(cfg, "S3_BUCKET", "my-bucket")
    monkeypatch.setattr(cfg, "S3_ACCESS_KEY", "key")
    monkeypatch.setattr(cfg, "S3_SECRET_KEY", "secret")
    monkeypatch.setattr(cfg, "S3_ENDPOINT", None)
    monkeypatch.setattr(cfg, "S3_REGION", "us-east-1")

    mock_client = MagicMock()
    mock_client.generate_presigned_url = MagicMock(
        return_value="https://s3.example.com/signed"
    )
    with patch("boto3.client", return_value=mock_client):
        from flowboard.services import object_storage
        url = await object_storage.presigned_get_url("42/abc.jpg", expires=300)
    assert url == "https://s3.example.com/signed"
    mock_client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "my-bucket", "Key": "42/abc.jpg"},
        ExpiresIn=300,
    )
