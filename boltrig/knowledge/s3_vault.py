"""S3-compatible ObjectVault. boto3 is lazy and optional outside cloud mode."""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

from .ports import StagedObject, safe_id


class S3ObjectVault:
    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "boltrig",
        endpoint_url: str | None = None,
        client: Any = None,
    ) -> None:
        if not bucket:
            raise ValueError("S3 bucket is required")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._endpoint_url = endpoint_url
        self._client = client

    def _ready(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("S3 vault requires boltrig[s3]") from exc
            self._client = boto3.client("s3", endpoint_url=self._endpoint_url)
        return self._client

    def _key(self, suffix: str) -> str:
        return f"{self.prefix}/{suffix}" if self.prefix else suffix

    def _object_key(self, key: str) -> str:
        root = self._key("tenants/")
        if not key.startswith(root) or any(part in {"", ".", ".."} for part in key.split("/")):
            raise ValueError("object key escapes vault prefix")
        return key

    async def stage(self, tenant_id: str, upload_id: str, data: bytes) -> StagedObject:
        tenant = safe_id(tenant_id, "tenant id")
        upload = safe_id(upload_id, "upload id")
        digest = hashlib.sha256(data).hexdigest()
        key = self._key(f"tenants/{tenant}/staging/{upload}")
        await asyncio.to_thread(
            self._ready().put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            Metadata={"sha256": digest},
        )
        return StagedObject(key=key, digest=digest, byte_size=len(data))

    async def commit(self, tenant_id: str, staged: StagedObject) -> str:
        tenant = safe_id(tenant_id, "tenant id")
        if not re.fullmatch(r"[0-9a-f]{64}", staged.digest):
            raise ValueError("invalid sha256 digest")
        staging_prefix = self._key(f"tenants/{tenant}/staging/")
        if not staged.key.startswith(staging_prefix):
            raise ValueError("staged object crosses tenant boundary")
        data = await self.read(staged.key)
        if len(data) != staged.byte_size or hashlib.sha256(data).hexdigest() != staged.digest:
            raise ValueError("staged object digest mismatch")
        key = self._key(
            f"tenants/{tenant}/blobs/sha256/{staged.digest[:2]}/{staged.digest}"
        )
        client = self._ready()
        await asyncio.to_thread(
            client.copy_object,
            Bucket=self.bucket,
            Key=key,
            CopySource={"Bucket": self.bucket, "Key": staged.key},
            Metadata={"sha256": staged.digest},
            MetadataDirective="REPLACE",
        )
        await asyncio.to_thread(client.delete_object, Bucket=self.bucket, Key=staged.key)
        return key

    async def read(self, object_key: str) -> bytes:
        response = await asyncio.to_thread(
            self._ready().get_object,
            Bucket=self.bucket,
            Key=self._object_key(object_key),
        )
        return await asyncio.to_thread(response["Body"].read)

    async def erase(self, object_key: str) -> None:
        await asyncio.to_thread(
            self._ready().delete_object,
            Bucket=self.bucket,
            Key=self._object_key(object_key),
        )
