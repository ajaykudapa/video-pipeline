"""MinIO (S3-compatible) helpers.

Two clients:
  - internal: talks to minio over the docker network (uploads/downloads)
  - public:   signs presigned URLs against the endpoint the *browser* uses.
    Presigned URLs embed the host in the signature, so they must be signed
    with the externally reachable endpoint.
"""
from __future__ import annotations

import os
from datetime import timedelta

from minio import Minio

RAW_BUCKET = "raw"
PROCESSED_BUCKET = "processed"

_PART_SIZE = 10 * 1024 * 1024  # 10 MiB multipart parts


def _client(endpoint: str) -> Minio:
    return Minio(
        endpoint,
        access_key=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
        secure=False,
        region="us-east-1",
    )


def internal() -> Minio:
    return _client(os.environ.get("MINIO_ENDPOINT", "minio:9000"))


def public() -> Minio:
    return _client(os.environ.get("MINIO_PUBLIC_ENDPOINT", "localhost:9000"))


def upload_stream(client: Minio, bucket: str, key: str, stream,
                  content_type: str = "application/octet-stream") -> None:
    """Streaming multipart upload — never buffers the whole file in memory."""
    client.put_object(bucket, key, stream, length=-1,
                      part_size=_PART_SIZE, content_type=content_type)


def presign(client: Minio, bucket: str, key: str, hours: int = 24) -> str:
    return client.presigned_get_object(bucket, key, expires=timedelta(hours=hours))
