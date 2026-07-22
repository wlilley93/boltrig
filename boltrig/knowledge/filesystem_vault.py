"""Content-addressed filesystem ObjectVault for personal and offline modes."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import re

from .ports import StagedObject, safe_id


class FilesystemObjectVault:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("object key escapes vault root")
        return candidate

    async def stage(self, tenant_id: str, upload_id: str, data: bytes) -> StagedObject:
        tenant = safe_id(tenant_id, "tenant id")
        upload = safe_id(upload_id, "upload id")
        digest = hashlib.sha256(data).hexdigest()
        key = f"tenants/{tenant}/staging/{upload}"
        await asyncio.to_thread(self._write_once, self._path(key), data)
        return StagedObject(key=key, digest=digest, byte_size=len(data))

    async def commit(self, tenant_id: str, staged: StagedObject) -> str:
        tenant = safe_id(tenant_id, "tenant id")
        if not re.fullmatch(r"[0-9a-f]{64}", staged.digest):
            raise ValueError("invalid sha256 digest")
        destination_key = (
            f"tenants/{tenant}/blobs/sha256/{staged.digest[:2]}/{staged.digest}"
        )
        source = self._path(staged.key)
        destination = self._path(destination_key)
        await asyncio.to_thread(self._promote, source, destination, staged.digest)
        return destination_key

    async def read(self, object_key: str) -> bytes:
        return await asyncio.to_thread(self._path(object_key).read_bytes)

    async def erase(self, object_key: str) -> None:
        path = self._path(object_key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    @staticmethod
    def _write_once(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(f".tmp-{os.getpid()}")
        try:
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _promote(source: Path, destination: Path, digest: str) -> None:
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("staged object digest mismatch")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise ValueError("content-addressed object collision")
            source.unlink(missing_ok=True)
            return
        os.replace(source, destination)
        destination.chmod(0o600)
