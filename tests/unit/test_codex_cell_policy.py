from __future__ import annotations

import hashlib
import os
import pickle
import pwd
from dataclasses import replace
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure import codex_cell_policy as policy
from scripts import check_codex_protocol
from boltrig.fleet.infrastructure import codex_runtime_config_argv as argv
from tests.unit.codex_process_fakes import make_layout

# Every leg here needs a Linux kernel facility macOS does not have: yama
# ptrace_scope, abstract AF_UNIX names, SO_PEERCRED, or bubblewrap. Marked so a
# non-Linux box reports them as unverified instead of failing; on Linux the
# marker is inert and they always run.
pytestmark = pytest.mark.linux_only


def test_runtime_pin_exactly_matches_checked_in_protocol_checker() -> None:
    assert policy.CODEX_CLI_VERSION == check_codex_protocol.PIN_VERSION == "0.144.3"
    assert policy.CODEX_CLI_TARGET == check_codex_protocol.PIN_TARGET
    assert policy.CODEX_CLI_SHA256 == check_codex_protocol.PIN_BINARY_SHA256
    assert argv.CODEX_APP_SERVER_BASE_ARGUMENTS == (
        "app-server",
        "--listen",
        "stdio://",
        "--strict-config",
    )


def test_layout_requires_precreated_private_owned_separated_directories(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)

    assert policy.validate_cell_layout(layout) == layout

    layout.workspace.chmod(0o755)
    with pytest.raises(policy.CodexCellPolicyError, match="unsafe mode"):
        policy.validate_cell_layout(layout)


def test_layout_rejects_workspace_home_overlap_and_non_child_cell(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    overlap = replace(
        layout,
        workspace_projection=replace(
            layout.workspace_projection,
            workspace_path=(layout.home / "workspace").as_posix(),
        ),
    )
    overlap.workspace.mkdir(mode=0o700)
    with pytest.raises(policy.CodexCellPolicyError, match="must not overlap"):
        policy.validate_cell_layout(overlap)

    foreign = tmp_path / "foreign"
    foreign.mkdir(mode=0o700)
    outside = replace(layout, cell_root=foreign)
    with pytest.raises(policy.CodexCellPolicyError, match="child of the stack root"):
        policy.validate_cell_layout(outside)


def test_layout_rejects_service_home_and_symlink_directory(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    personal = Path(pwd.getpwuid(os.geteuid()).pw_dir)
    under_home = replace(
        layout,
        stack_root=personal / "boltrig-cells",
        cell_root=personal / "boltrig-cells/cell-1",
        workspace_projection=replace(
            layout.workspace_projection,
            workspace_path=(personal / "boltrig-cells/cell-1/workspace").as_posix(),
        ),
        home=personal / "boltrig-cells/cell-1/home",
        codex_home=personal / "boltrig-cells/cell-1/codex-home",
    )
    with pytest.raises(policy.CodexCellPolicyError, match="service account home"):
        policy.validate_cell_layout(under_home)

    target = layout.workspace.with_name("workspace-real")
    layout.workspace.rename(target)
    layout.workspace.symlink_to(target, target_is_directory=True)
    with pytest.raises(policy.CodexCellPolicyError, match="non-symlink"):
        policy.validate_cell_layout(layout)


@pytest.mark.parametrize(
    "replacement",
    [Path("relative/codex"), Path("/tmp/../tmp/codex"), Path("//tmp/codex")],
)
def test_paths_must_arrive_absolute_and_normalized(replacement: Path) -> None:
    with pytest.raises(policy.CodexCellPolicyError, match="normalized absolute POSIX"):
        policy.normalized_absolute_path("Codex binary", replacement)


def test_binary_must_be_executable_regular_non_symlink_and_exact_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "codex"
    binary.write_bytes(b"reviewed binary")
    binary.chmod(0o700)
    expected = hashlib.sha256(binary.read_bytes()).hexdigest()
    monkeypatch.setattr(
        policy,
        "reviewed_codex_artifacts",
        lambda: {expected: policy.CODEX_CLI_TARGET},
    )

    verified = policy.verify_pinned_binary(binary)

    assert verified.path == binary and verified.sha256 == expected
    binary.chmod(0o720)
    with pytest.raises(policy.CodexCellPolicyError, match="world-writable"):
        policy.verify_pinned_binary(binary)
    binary.chmod(0o700)
    symlink = tmp_path / "codex-link"
    symlink.symlink_to(binary)
    with pytest.raises(policy.CodexCellPolicyError, match="non-symlink"):
        policy.verify_pinned_binary(symlink)
    binary.write_bytes(b"tampered")
    with pytest.raises(policy.CodexCellPolicyError, match="digest"):
        policy.verify_pinned_binary(binary)


def test_arm64_release_binary_is_an_independent_reviewed_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "codex-arm64"
    binary.write_bytes(b"reviewed arm64 binary")
    binary.chmod(0o700)
    expected = hashlib.sha256(binary.read_bytes()).hexdigest()
    monkeypatch.setattr(
        policy,
        "reviewed_codex_artifacts",
        lambda: {expected: policy.CODEX_CLI_TARGET_ARM64},
    )

    verified = policy.verify_pinned_binary(binary)

    assert verified.sha256 == expected
    assert verified.target == policy.CODEX_CLI_TARGET_ARM64


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="Linux executable fd seam")
def test_verified_descriptor_keeps_reviewed_bytes_after_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "codex"
    reviewed = b"reviewed executable bytes"
    binary.write_bytes(reviewed)
    binary.chmod(0o700)
    expected = hashlib.sha256(reviewed).hexdigest()
    monkeypatch.setattr(
        policy,
        "reviewed_codex_artifacts",
        lambda: {expected: policy.CODEX_CLI_TARGET},
    )
    verified = policy.verify_pinned_binary(binary)
    descriptor = verified.fileno()
    old_inode = tmp_path / "old-inode"

    binary.rename(old_inode)
    binary.write_bytes(b"replacement executable bytes")
    binary.chmod(0o700)

    assert Path(verified.execution_path).read_bytes() == reviewed
    assert verified.path == binary
    verified.close()
    with pytest.raises(OSError):
        os.fstat(descriptor)
    with pytest.raises(policy.CodexCellPolicyError, match="closed"):
        verified.fileno()


def test_environment_is_explicit_minimal_and_auth_is_always_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-provider-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-openai-secret")
    monkeypatch.setenv("CODEX_API_KEY", "ambient-codex-exec-secret")
    monkeypatch.setenv("OPBOX_TOKEN", "ambient-domain-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient-parent-secret")
    auth = policy.CodexUpstreamAuth("supervisor-upstream-secret")

    environment = policy.sanitized_environment(layout, auth)

    assert environment == {
        "CODEX_HOME": layout.codex_home.as_posix(),
        "HOME": layout.home.as_posix(),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "CODEX_ACCESS_TOKEN": "supervisor-upstream-secret",
    }
    assert "supervisor-upstream-secret" not in repr(auth)
    assert "supervisor-upstream-secret" not in repr((auth,))
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(auth)


@pytest.mark.parametrize("secret", ["", " secret", "secret\n", True])
def test_auth_seam_rejects_ambiguous_secrets(secret: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        policy.CodexUpstreamAuth(secret)  # type: ignore[arg-type]
