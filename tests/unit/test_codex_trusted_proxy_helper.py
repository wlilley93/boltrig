"""Tests for the trusted per-cell model-auth helper ([2026] VJS-CC-VJS 2, D2).

The helper is what Codex's ``[model_providers.*.auth] command`` invokes. Its
contract is pinned here against the verified Codex 0.144.3 behaviour (openai/codex
PR #16288 "core: support dynamic auth tokens for model providers"): the command
writes the RAW bearer token to stdout (Codex trims whitespace) and exits 0. It is
NOT JSON. It reveals only the short-TTL scoped bearer from its sibling 0600 file;
the real upstream key is never present. A cell-id mismatch fails without leaking.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (
    BEARER_FILENAME,
    HELPER_FILENAME,
    materialize_helper,
    write_bearer,
)

_CELL_ID = "cell-abc1234567890ab"
_BEARER = "scoped-bearer-token-0123456789"


def test_helper_prints_the_raw_bearer_for_its_cell(tmp_path: Path) -> None:
    helper_path, digest = materialize_helper(tmp_path, _CELL_ID)
    write_bearer(tmp_path, _BEARER)

    assert helper_path == tmp_path / HELPER_FILENAME
    assert oct(helper_path.stat().st_mode & 0o777) == "0o700"
    assert digest.startswith("sha256:")
    assert digest == "sha256:" + hashlib.sha256(helper_path.read_bytes()).hexdigest()

    result = subprocess.run(
        [helper_path.as_posix(), "--cell-id", _CELL_ID],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    # Codex trims surrounding whitespace; the token itself must match exactly.
    assert result.stdout.strip() == _BEARER


def test_helper_refuses_a_mismatched_cell_id_without_leaking(tmp_path: Path) -> None:
    helper_path, _digest = materialize_helper(tmp_path, _CELL_ID)
    write_bearer(tmp_path, _BEARER)

    result = subprocess.run(
        [helper_path.as_posix(), "--cell-id", "cell-someoneelse00"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert _BEARER not in result.stdout


def test_bearer_file_is_owner_only_readable(tmp_path: Path) -> None:
    bearer_path = write_bearer(tmp_path, _BEARER)
    assert bearer_path == tmp_path / BEARER_FILENAME
    assert oct(bearer_path.stat().st_mode & 0o777) == "0o600"
