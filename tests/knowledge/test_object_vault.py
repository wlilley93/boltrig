from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from boltrig.knowledge.filesystem_vault import FilesystemObjectVault
from boltrig.knowledge.s3_vault import S3ObjectVault


@pytest.mark.invariant("KNO-01")
async def test_filesystem_vault_is_content_addressed_and_traversal_safe(tmp_path: Path) -> None:
    vault = FilesystemObjectVault(tmp_path / "vault")
    data = b"canonical original"
    staged = await vault.stage("tenant-a", "upload-a", data)
    key = await vault.commit("tenant-a", staged)

    assert hashlib.sha256(data).hexdigest() in key
    assert key.startswith("tenants/tenant-a/blobs/sha256/")
    assert await vault.read(key) == data
    with pytest.raises(ValueError, match="escapes"):
        await vault.read("../../etc/passwd")


class _S3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}

    def put_object(self, *, Bucket, Key, Body, Metadata):
        self.objects[(Bucket, Key)] = {"body": bytes(Body), "metadata": dict(Metadata)}

    def copy_object(self, *, Bucket, Key, CopySource, Metadata, MetadataDirective):
        source = self.objects[(CopySource["Bucket"], CopySource["Key"])]
        self.objects[(Bucket, Key)] = {"body": source["body"], "metadata": dict(Metadata)}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)]["body"])}


@pytest.mark.invariant("KNO-01")
@pytest.mark.invariant("KNO-03")
async def test_s3_vault_enforces_the_same_digest_prefix_and_erasure_contract() -> None:
    client = _S3Client()
    vault = S3ObjectVault("bucket", prefix="root", client=client)
    staged = await vault.stage("tenant-a", "upload-a", b"s3 canonical")
    key = await vault.commit("tenant-a", staged)

    assert key.startswith("root/tenants/tenant-a/blobs/sha256/")
    assert await vault.read(key) == b"s3 canonical"
    await vault.erase(key)
    assert ("bucket", key) not in client.objects
    with pytest.raises(ValueError, match="escapes"):
        await vault.read("other/prefix")

    tampered = await vault.stage("tenant-a", "upload-b", b"expected")
    client.objects[("bucket", tampered.key)]["body"] = b"tampered"
    with pytest.raises(ValueError, match="digest mismatch"):
        await vault.commit("tenant-a", tampered)
