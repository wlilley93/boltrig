"""Exact reviewed Codex 0.144.3 Linux binary artifact identities."""

from __future__ import annotations

import os
from pathlib import Path

from . import codex_protocol as wire

CODEX_CLI_VERSION = "0.144.3"
CODEX_CLI_TARGET = "x86_64-unknown-linux-musl"
CODEX_CLI_SHA256 = "37e6f5953f191b04f7b62cb07dae90f51d0947ad89f0355665b421fbde28700b"
CODEX_CLI_TARGET_ARM64 = "aarch64-unknown-linux-musl"
CODEX_CLI_SHA256_ARM64 = "afb0d0379242b598de8a2d44174e0c7ccdf1512b7b41a32adf2c6c9a6f5b6f15"


class CodexCellPolicyError(wire.CodexAppServerError):
    """A cell path, binary, or environment violated supervisor policy."""


def reviewed_codex_artifacts() -> dict[str, str]:
    """Return the exact reviewed binary-digest to target pairs."""

    return {
        CODEX_CLI_SHA256: CODEX_CLI_TARGET,
        CODEX_CLI_SHA256_ARM64: CODEX_CLI_TARGET_ARM64,
    }


class PinnedCodexBinary:
    """One held, reviewed executable descriptor; the pathname is audit-only."""

    __slots__ = ("path", "sha256", "version", "target", "_descriptor")

    def __init__(
        self,
        path: Path,
        sha256: str,
        descriptor: int,
        target: str = CODEX_CLI_TARGET,
    ) -> None:
        if type(descriptor) is not int or descriptor < 0:
            raise ValueError("pinned Codex descriptor must be a non-negative integer")
        self.path = path
        self.sha256 = sha256
        self.version = CODEX_CLI_VERSION
        self.target = target
        self._descriptor = descriptor

    def fileno(self) -> int:
        if self._descriptor < 0:
            raise CodexCellPolicyError("pinned Codex descriptor is closed")
        return self._descriptor

    @property
    def execution_path(self) -> str:
        return f"/proc/self/fd/{self.fileno()}"

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, -1
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                raise CodexCellPolicyError("pinned Codex descriptor could not be closed") from None

    def __del__(self) -> None:
        descriptor, self._descriptor = self._descriptor, -1
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


__all__ = [
    "CODEX_CLI_SHA256",
    "CODEX_CLI_SHA256_ARM64",
    "CODEX_CLI_TARGET",
    "CODEX_CLI_TARGET_ARM64",
    "CODEX_CLI_VERSION",
    "CodexCellPolicyError",
    "PinnedCodexBinary",
    "reviewed_codex_artifacts",
]
