"""The spawner's provision verb: build a cell tree AS the cell uid, in ITS OWN slot.

The load-bearing property is the same one the whole per-cell program exists for
([2026] VJS-CC-VJS 5/7): a compromised API must never be able to make the
privileged spawner write into a SIBLING cell's slot. The parser binds every path
to ``stack_root/slot-<uid-20001>`` and refuses anything else, before the fork ever
happens.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.cell_spawner import (
    CellSpawnerError,
    ProvisionRequest,
    SpawnPolicy,
    parse_provision_request,
)
import json


_STACK = Path("/var/lib/boltrig/codex-cells")
_POLICY = SpawnPolicy(binary=Path("/opt/boltrig/codex/codex"), stack_root=_STACK)


def _payload(uid: int, dirs=(), files=()) -> bytes:
    return json.dumps(
        {"verb": "provision", "uid": uid, "gid": uid, "dirs": list(dirs), "files": list(files)}
    ).encode("utf-8")


def test_a_valid_same_slot_request_parses() -> None:
    uid = 20001  # slot-0
    request = parse_provision_request(
        _payload(
            uid,
            dirs=[
                {"path": "/var/lib/boltrig/codex-cells/slot-0/home", "mode": 0o700},
                {"path": "/var/lib/boltrig/codex-cells/slot-0/workspace", "mode": 0o500},
            ],
            files=[
                {
                    "path": "/var/lib/boltrig/codex-cells/slot-0/codex-home/config.toml",
                    "mode": 0o600,
                    "content": "x = 1\n",
                }
            ],
        ),
        _POLICY,
    )
    assert type(request) is ProvisionRequest
    assert request.uid == uid
    assert {d.path for d in request.dirs} == {
        "/var/lib/boltrig/codex-cells/slot-0/home",
        "/var/lib/boltrig/codex-cells/slot-0/workspace",
    }
    assert request.files[0].content == "x = 1\n"


def test_a_cross_slot_write_is_refused_the_anti_vjs5_invariant() -> None:
    # uid 20001 owns slot-0; a path in slot-1 (uid 20002's slot) must be refused, even
    # though 20001 is a valid band uid. This is the exact cross-tenant leak.
    with pytest.raises(CellSpawnerError, match="own slot"):
        parse_provision_request(
            _payload(
                20001,
                dirs=[{"path": "/var/lib/boltrig/codex-cells/slot-1/home", "mode": 0o700}],
            ),
            _POLICY,
        )


def test_upward_traversal_is_refused() -> None:
    with pytest.raises(CellSpawnerError):
        parse_provision_request(
            _payload(
                20001,
                dirs=[{"path": "/var/lib/boltrig/codex-cells/slot-0/../slot-1/home", "mode": 0o700}],
            ),
            _POLICY,
        )


def test_a_disallowed_mode_is_refused() -> None:
    with pytest.raises(CellSpawnerError, match="mode not allowed"):
        parse_provision_request(
            _payload(
                20001,
                dirs=[{"path": "/var/lib/boltrig/codex-cells/slot-0/home", "mode": 0o777}],
            ),
            _POLICY,
        )


def test_an_out_of_band_uid_is_refused() -> None:
    with pytest.raises(CellSpawnerError, match="cell band"):
        parse_provision_request(
            _payload(
                10001,  # the API's own uid, never a cell uid
                dirs=[{"path": "/var/lib/boltrig/codex-cells/slot-0/home", "mode": 0o700}],
            ),
            _POLICY,
        )


def test_a_file_outside_the_slot_is_refused() -> None:
    with pytest.raises(CellSpawnerError, match="own slot"):
        parse_provision_request(
            _payload(
                20001,
                files=[{"path": "/etc/codex/config.toml", "mode": 0o600, "content": "x"}],
            ),
            _POLICY,
        )


def test_the_empty_workspace_digest_constant_does_not_drift(tmp_path: Path) -> None:
    """The per-cell path asserts an EMPTY workspace by a constant rather than a read
    the capless API cannot perform, so the constant must equal what capture_directory
    actually yields on a real empty directory, or the guarantee is hollow."""

    from boltrig.fleet.infrastructure.bounded_filesystem import capture_directory
    from boltrig.fleet.infrastructure.codex_cell_policy import (
        CODEX_WORKSPACE_LIMITS,
        EMPTY_WORKSPACE_DIGEST,
        EMPTY_WORKSPACE_FILE_COUNT,
        EMPTY_WORKSPACE_TOTAL_BYTES,
    )

    empty = tmp_path / "workspace"
    empty.mkdir()
    accounting = capture_directory(empty, CODEX_WORKSPACE_LIMITS, reject_controls=True).accounting
    assert accounting.digest == EMPTY_WORKSPACE_DIGEST
    assert accounting.file_count == EMPTY_WORKSPACE_FILE_COUNT
    assert accounting.total_bytes == EMPTY_WORKSPACE_TOTAL_BYTES


def test_attest_empty_workspace_projection_rejects_a_non_empty_projection() -> None:
    from boltrig.fleet.infrastructure.codex_cell_policy import (
        CodexCellPolicyError,
        EMPTY_WORKSPACE_DIGEST,
        attest_empty_workspace_projection,
    )
    from boltrig.fleet.infrastructure.skill_artifacts import SanitizedWorkspaceProjection

    empty = SanitizedWorkspaceProjection(
        "/s/source", "/s/workspace", EMPTY_WORKSPACE_DIGEST, 0, 0
    )
    attest_empty_workspace_projection(empty)  # the empty constant is accepted

    nonempty = SanitizedWorkspaceProjection(
        "/s/source", "/s/workspace", "sha256:" + "a" * 64, 1, 10
    )
    with pytest.raises(CodexCellPolicyError, match="empty constant"):
        attest_empty_workspace_projection(nonempty)
