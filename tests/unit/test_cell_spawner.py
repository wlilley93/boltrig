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
    reap_cell,
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


@pytest.mark.unit
@pytest.mark.parametrize(
    ("pid", "uid", "number"),
    [
        (0, 20001, 15),      # not a real pid
        (1, 20001, 15),      # pid 1, which is never a cell
        (-5, 20001, 15),     # negative: a process GROUP, not a process
        (999, 0, 15),        # root
        (999, 10001, 15),    # the API's own uid
        (999, 20001, 9999),  # not a signal
        (999, 20001, 2),     # SIGINT: not one a supervisor needs
        (999, 20001, 19),    # SIGSTOP: would wedge a cell rather than end it
    ],
)
def test_the_reaper_refuses_anything_outside_its_narrow_job(
    pid: int, uid: int, number: int
) -> None:
    """A general signal verb would let a compromised API poke at anything.

    The negative-pid case matters most: on Linux a negative pid means a process
    GROUP, so an unchecked reaper would let one request signal every process the
    cell uid can reach rather than the single cell it named.
    """

    with pytest.raises(CellSpawnerError):
        reap_cell(pid, uid, number)


# --------------------------------------------------------------------------- #
# The ENVIRONMENT, held to policy the spawner owns (2026-08-02).
#
# Until this date the env was the ONE field this module obeyed instead of validating: it was
# proved to be a str->str mapping and then handed straight to `execve`, while `argv[0]`, the
# uid and the cwd were each checked against policy the spawner holds. The module docstring
# meanwhile asserted the environment was "rebuilt from the request's cell values, not passed
# through", which was false. These tests exist so that claim is now enforced rather than
# merely written down.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    ["LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "DYLD_INSERT_LIBRARIES"],
)
def test_a_compromised_api_cannot_redirect_the_dynamic_linker(key: str) -> None:
    """THE ATTACK THIS CLOSES. The digest check proves the binary's BYTES are the reviewed
    ones. It says nothing about what else gets mapped into that process. A compromised API
    that could set LD_PRELOAD would run code of its own choosing inside the pinned binary,
    as the cell uid, with every other check still green.

    Today's pinned binary is static-pie, so none of these bites. That is a property of ONE
    ARTEFACT, not of this spawner, and a defence that rests on the current build being static
    expires silently on the day someone bumps the pin.
    """
    env = {"CODEX_HOME": f"{_STACK}/c1/codex-home", "PATH": "/usr/bin", key: "/tmp/evil.so"}
    with pytest.raises(CellSpawnerError, match="dynamic linker"):
        parse_spawn_request(_request(env=env), _policy())


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "/etc",                       # outside the stack root entirely
        f"{_STACK}/../../etc",        # lexical escape, the "/v1/../admin" shape
        "relative/path",              # not absolute
        f"{_STACK}//c1//codex-home",  # not normalized
    ],
)
def test_codex_home_is_held_inside_the_stack_root(value: str) -> None:
    """CODEX_HOME decides where the cell reads its config.toml, which decides its sandbox
    mode and its feature set. Pointing it outside the cell tree is the same class of escape
    as pointing `cwd` there, and is refused by the same lexical discipline: demand the path
    already be normalized rather than normalize it for the caller, and never resolve, because
    a cell uid can plant a symlink inside its own tree."""
    with pytest.raises(CellSpawnerError, match="CODEX_HOME"):
        parse_spawn_request(_request(env={"CODEX_HOME": value, "PATH": "/usr/bin"}), _policy())


@pytest.mark.unit
def test_home_is_held_inside_the_stack_root_too() -> None:
    with pytest.raises(CellSpawnerError, match="HOME"):
        parse_spawn_request(_request(env={"HOME": "/root", "PATH": "/usr/bin"}), _policy())


@pytest.mark.unit
@pytest.mark.parametrize("key", ["lowercase", "1LEADING_DIGIT", "HAS-DASH", "", "A" * 65])
def test_an_environment_key_that_is_not_a_bounded_name_is_refused(key: str) -> None:
    """Mirrors `codex_cell_policy._ENV_ADDITION_KEY`, so the API-side bound and the
    spawner-side bound cannot come to disagree about what a legitimate key looks like."""
    with pytest.raises(CellSpawnerError, match="env"):
        parse_spawn_request(_request(env={key: "x", "PATH": "/usr/bin"}), _policy())


@pytest.mark.unit
def test_an_unbounded_or_non_printable_environment_value_is_refused() -> None:
    for value in ["x" * 4097, "has\nnewline", "has\x00nul", ""]:
        with pytest.raises(CellSpawnerError, match="env"):
            parse_spawn_request(_request(env={"SOME_KEY": value, "PATH": "/usr/bin"}), _policy())


@pytest.mark.unit
def test_too_many_environment_entries_are_refused() -> None:
    env = {f"K{i}": "v" for i in range(15)}
    with pytest.raises(CellSpawnerError, match="too many"):
        parse_spawn_request(_request(env=env), _policy())


@pytest.mark.unit
def test_THE_POSITIVE_CONTROL_a_real_cell_environment_is_still_accepted() -> None:
    """Without this the refusals above are indistinguishable from a spawner that refuses
    every environment, which would pass all of them and break every cell.

    This is the exact shape `codex_cell_policy.sanitized_environment` produces, plus the one
    in-tree addition (`BOLTRIG_CODEX_MCP_RUN_TOKEN`, the kernel-tools bearer).
    """
    env = {
        "CODEX_HOME": f"{_STACK}/c1/codex-home",
        "HOME": f"{_STACK}/c1/home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "BOLTRIG_CODEX_MCP_RUN_TOKEN": "a" * 64,
    }
    parsed = parse_spawn_request(_request(env=env), _policy())
    assert parsed.env == env
    # And the stack root itself is a legitimate value, not an off-by-one refusal.
    parse_spawn_request(_request(env={"CODEX_HOME": _STACK, "PATH": "/usr/bin"}), _policy())


@pytest.mark.unit
def test_the_cell_actually_runs_in_the_requested_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exec path must APPLY the cwd it so carefully validated.

    THE BUG THIS PINS. Until 2026-08-20 `_exec_cell` validated `cwd`
    exhaustively and then never chdir'd: every cell inherited the kernel's own
    working directory, codex reported that as `auth.cwd`, and the surface
    attestation refused every cell ("Codex provider auth differs from its
    receipt") - chat degraded on every turn, with the cause swallowed.

    The privilege drop is stubbed (tests do not run as root); the fork, the
    chdir and the exec are real: the pinned binary is `pwd`, so the child's
    stdout IS the working directory the cell actually got.
    """
    from boltrig.fleet.infrastructure import cell_spawner

    pwd_binary = next(
        (candidate for candidate in ("/bin/pwd", "/usr/bin/pwd") if os.path.exists(candidate)),
        None,
    )
    assert pwd_binary is not None, "no pwd binary on this host"
    workspace = tmp_path / "cell-1" / "workspace"
    workspace.mkdir(parents=True)
    policy = SpawnPolicy(binary=Path(pwd_binary), stack_root=tmp_path)
    request = parse_spawn_request(
        json.dumps(
            {
                "uid": 20001,
                "gid": 20001,
                "argv": [pwd_binary],
                "cwd": workspace.as_posix(),
                "env": {"PATH": "/usr/bin:/bin"},
            }
        ).encode("utf-8"),
        policy,
    )
    monkeypatch.setattr(cell_spawner, "drop_privileges", lambda uid, gid: None)
    pid, (stdin_w, stdout_r, stderr_r) = cell_spawner.spawn_cell(request, policy)
    try:
        os.close(stdin_w)
        output = b""
        while chunk := os.read(stdout_r, 4096):
            output += chunk
    finally:
        os.close(stdout_r)
        os.close(stderr_r)
        os.waitpid(pid, 0)
    assert output.decode().strip() == workspace.as_posix()
