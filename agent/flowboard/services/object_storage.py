"""S3-compatible object storage service (boto3 wrapper).

Optional — when FLOWBOARD_S3_BUCKET is not set, is_configured() returns False
and upload_bytes / presigned_get_url raise RuntimeError.
Supports AWS S3, Cloudflare R2, and MinIO via FLOWBOARD_S3_ENDPOINT override.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from flowboard import config

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(config.S3_BUCKET and config.S3_ACCESS_KEY and config.S3_SECRET_KEY)


def s3_key_for(account_id: int, media_id: str, ext: str) -> str:
    """Build the S3 object key: ``<account_id>/<media_id><ext>``."""
    return f"{account_id}/{media_id}{ext}"


def _make_client():
    import boto3
    kwargs: dict = {
        "aws_access_key_id": config.S3_ACCESS_KEY,
        "aws_secret_access_key": config.S3_SECRET_KEY,
        "region_name": config.S3_REGION,
    }
    if config.S3_ENDPOINT:
        kwargs["endpoint_url"] = config.S3_ENDPOINT
    return boto3.client("s3", **kwargs)


async def upload_bytes(key: str, data: bytes, content_type: str) -> str:
    """Upload bytes to the configured S3 bucket. Returns the key on success."""
    if not is_configured():
        raise RuntimeError("S3 not configured")

    def _put():
        client = _make_client()
        client.put_object(
            Bucket=config.S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    await asyncio.to_thread(_put)
    logger.info("s3: uploaded %s (%d bytes)", key, len(data))
    return key


async def presigned_get_url(key: str, expires: int = 300) -> str:
    """Generate a presigned GET URL valid for ``expires`` seconds."""
    if not is_configured():
        raise RuntimeError("S3 not configured")

    def _sign():
        client = _make_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": config.S3_BUCKET, "Key": key},
            ExpiresIn=expires,
        )

    return await asyncio.to_thread(_sign)
