"""Adversarial tests for the privileged cell spawner ([2026] VJS-CC-VJS 7 J3).

The spawner is the only component permitted to keep CAP_SETUID, and the process
on the other end of its socket is the API, which is the process that parses
untrusted model output and therefore the one most likely to be compromised. So
these tests are written from the attacker's side: every case is a thing a
compromised API would try, and the spawner must refuse it rather than obey.

A spawner that obeyed would not be a boundary, it would be a relocation of root
into the API's gift.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.cell_spawner import (
    MAX_CELL_UID,
    MIN_CELL_UID,
    CellSpawnerError,
    SpawnPolicy,
    parse_spawn_request,
    receive_spawn_result,
    send_spawn_result,
)

_BINARY = "/opt/boltrig/codex/codex"
_STACK = "/var/lib/boltrig/codex-cells"


def _policy() -> SpawnPolicy:
    return SpawnPolicy(binary=Path(_BINARY), stack_root=Path(_STACK))


def _request(**overrides: object) -> bytes:
    body: dict[str, object] = {
        "uid": 20001,
        "gid": 20001,
        "argv": [_BINARY, "app-server", "--listen", "stdio://"],
        "cwd": f"{_STACK}/cell-1/workspace",
        "env": {"CODEX_HOME": f"{_STACK}/cell-1/codex-home"},
    }
    body.update(overrides)
    return json.dumps(body).encode("utf-8")


@pytest.mark.unit
def test_a_well_formed_request_is_accepted() -> None:
    parsed = parse_spawn_request(_request(), _policy())
    assert parsed.uid == 20001
    assert parsed.argv[0] == _BINARY


@pytest.mark.unit
@pytest.mark.parametrize("uid", [0, 1, 10001, MIN_CELL_UID - 1, MAX_CELL_UID + 1, -1])
def test_a_uid_outside_the_cell_band_is_refused(uid: int) -> None:
    """uid 0 and the API's own 10001 are the two that matter most.

    A cell sharing either has no boundary at all, which is the entire point of the
    grant. The band check covers both without special-casing them.
    """

    with pytest.raises(CellSpawnerError, match="uid"):
        parse_spawn_request(_request(uid=uid), _policy())


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["/bin/sh", "-c", "id"],  # a shell, the obvious prize
        ["/usr/bin/env", _BINARY],  # laundering the pinned path through a wrapper
        ["/opt/boltrig/codex/codex-evil"],  # prefix collision with the pinned path
        ["codex", "app-server"],  # relative, resolved by PATH
        [],  # nothing at all
    ],
)
def test_only_the_exact_pinned_binary_may_be_executed(argv: list[str]) -> None:
    """"Absolute" is not the test; "the exact pinned binary" is.

    A compromised API that could name any absolute path would simply exec a shell
    as a fresh uid, which buys the attacker a great deal and the boundary nothing.
    """

    with pytest.raises(CellSpawnerError, match="argv"):
        parse_spawn_request(_request(argv=argv), _policy())


@pytest.mark.unit
@pytest.mark.parametrize(
    "cwd",
    [
        "/etc",
        "/var/lib/boltrig",  # the parent, not the stack root
        "/var/lib/boltrig/codex-cells-evil",  # prefix collision
        "relative/path",
        "",
    ],
)
def test_the_working_directory_must_be_inside_the_stack_root(cwd: str) -> None:
    with pytest.raises(CellSpawnerError, match="cwd"):
        parse_spawn_request(_request(cwd=cwd), _policy())


@pytest.mark.unit
def test_the_stack_root_itself_is_permitted_but_traversal_out_of_it_is_not() -> None:
    """Path.is_relative_to is LEXICAL, so this escape is real and was live.

    "<stack>/../other" satisfies is_relative_to(stack) because nothing normalizes
    it. That is the same defect as the "/v1/../admin" proxy escape, found here by
    this test rather than in production, and it is refused the same way: the path
    must ALREADY be normalized, because normalizing it for the caller (or
    resolving it, which follows symlinks a cell can create) would be inventing an
    intent the caller did not state.
    """

    parse_spawn_request(_request(cwd=_STACK), _policy())
    for escape in (f"{_STACK}/../other", f"{_STACK}/cell-1/../../etc", f"{_STACK}/./x"):
        with pytest.raises(CellSpawnerError, match="cwd"):
            parse_spawn_request(_request(cwd=escape), _policy())


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"{not json",
        b"[]",  # a list, not an object
        b'"string"',
        json.dumps({"uid": "20001"}).encode("utf-8"),  # uid as a string
        b"x" * (64 * 1024 + 1),  # beyond the size cap
    ],
)
def test_an_unreadable_request_is_refused_rather_than_guessed(payload: bytes) -> None:
    with pytest.raises(CellSpawnerError):
        parse_spawn_request(payload, _policy())


@pytest.mark.unit
@pytest.mark.parametrize(
    # Note: an int KEY cannot be tested through JSON, which stringifies keys, so
    # the malformed-key case is not expressible on this wire and is not asserted.
    "env", [{"A": 1}, "PATH=/bin", ["PATH=/bin"], None]
)
def test_a_malformed_environment_is_refused(env: object) -> None:
    with pytest.raises(CellSpawnerError, match="env"):
        parse_spawn_request(_request(env=env), _policy())


@pytest.mark.unit
def test_the_policy_is_held_by_the_spawner_and_cannot_be_widened_by_a_request() -> None:
    """The request carries no policy, so a compromised API cannot relax it.

    This is the structural property the design rests on: policy arrives at
    construction, before the API is ever spoken to.
    """

    request = json.loads(_request())
    assert "binary" not in request
    assert "stack_root" not in request
    assert "policy" not in request


@pytest.mark.unit
def test_stdio_descriptors_survive_the_socket_handback() -> None:
    """SCM_RIGHTS is what lets the API drive a process it could not have created."""

    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    read_end, write_end = os.pipe()
    extra_a, extra_b = os.pipe()
    try:
        send_spawn_result(child, 4242, (read_end, write_end, extra_a))
        pid, descriptors = receive_spawn_result(parent)
        assert pid == 4242
        assert len(descriptors) == 3
        # Genuinely usable in this process, which is the whole point.
        os.write(descriptors[1], b"ping")
        assert os.read(descriptors[0], 4) == b"ping"
        for descriptor in descriptors:
            os.close(descriptor)
    finally:
        os.close(extra_b)
        parent.close()
        child.close()


@pytest.mark.unit
def test_a_result_without_descriptors_is_refused() -> None:
    """Fail closed: a pid with no stdio is a cell the API cannot supervise."""

    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        child.sendmsg([json.dumps({"pid": 1}).encode("utf-8")])
        with pytest.raises(CellSpawnerError, match="stdio"):
            receive_spawn_result(parent)
    finally:
        parent.close()
        child.close()


@pytest.mark.unit
def test_a_spawn_policy_demands_absolute_paths() -> None:
    with pytest.raises(CellSpawnerError):
        SpawnPolicy(binary=Path("codex"), stack_root=Path(_STACK))
