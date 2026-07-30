"""Support values for the trusted single-tenant read-only Codex proxy provider.

Ruling [2026] VJS-CC-VJS 2. This module holds the pure, individually-testable
pieces the provider (codex_trusted_proxy_provider.py) composes: the child's REAL
``/proc`` process identity (D3), the secretless auth-helper materialization and
its raw-bearer contract (D2), the loopback-proxy config render (D6), the fixed
read-only budget, atomic 0600 bearer delivery to a SINGLE service uid (D5), and a
generation-tracking bearer verifier.

[2026] VJS-CC-VJS 5 G2: this module no longer materializes a per-cell auth helper.
It used to write ``model_auth_helper`` at 0700 INSIDE the mutable cell root, which
under a single shared cell uid was writable by every sibling cell, so cell A could
rewrite cell B's helper and have B's App Server execute it as its own child. There
is now exactly ONE shared helper, root-owned and non-writable on the read-only
image mount, resolved and proved by ``codex_cell_boundary``.

D3 caveat (stated here and echoed at every call site): the cell scope is built
from the child's real ``/proc`` identity but WITHOUT the SO_PEERCRED cross-check
that production issuance performs over the unix socket. The value is therefore
observed, not attested; it must never be treated as a peer-attested identity. The
only thing absent versus production is that one cross-check, so the trusted path
maps onto the future SO_PEERCRED swap with an identical delivery contract (D5).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from boltrig.fleet.domain import NativeSubagentLimits, PhaseAssignmentRef
from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyBudgetBinding,
    ModelProxyCellScope,
    ModelProxyModelBinding,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
)
from boltrig.fleet.infrastructure.codex_model_proxy_server import BearerDigestLookup
from boltrig.fleet.infrastructure.codex_runtime_config import (
    ComposedCodexRuntimeConfig,
    CodexReasoningEffort,
    CodexRuntimeConfigRequest,
    compose_codex_runtime_config,
)
from boltrig.fleet.infrastructure.skill_config import REVIEWED_SYSTEM_SKILLS_0_144_3

# 0600 for the cell's private config.toml (there is no bearer file - Option B).
_PRIVATE_FILE_MODE = 0o600

# A fixed, small read-only reasoning budget. Read-only cutover only (D6); the
# write/effects phase is separately court-gated (PR8).
READ_ONLY_BUDGET_ID = "codex-read-only"
READ_ONLY_MAX_INPUT_TOKENS = 200_000
READ_ONLY_MAX_OUTPUT_TOKENS = 32_000
READ_ONLY_MAX_TOTAL_TOKENS = 232_000
READ_ONLY_MAX_COST_MICROS = 5_000_000

# Codex 0.144.3 ``[model_providers.*.auth] command`` contract (verified against
# openai/codex PR #16288 "core: support dynamic auth tokens for model providers"):
# the command receives no stdin, writes the RAW bearer token to stdout (any
# leading/trailing whitespace is trimmed), and exits 0. It is NOT JSON.
#
# Option-B delivery ([2026] VJS-CC-VJS 3): the helper CONNECTS to the per-cell
# SO_PEERCRED unix socket and drains the raw bearer from that connection to stdout -
# NO bearer file at rest. The kernel attests THIS process over the socket and mints
# the bearer at issuance; the upstream key is injected server-side by the loopback
# proxy and never lives here. Only the acquisition changed (socket read, not
# ``cat`` of a file); the stdout contract (E3) is identical. python3 is the ABSOLUTE
# ``/usr/local/bin/python3`` because the sanitized cell PATH is ``/usr/bin:/bin``
# (no ``/usr/local/bin``, and no socat/nc). The socket path is passed as argv so it
# never has to be escaped into the Python literal.


class TrustedProxyProvisionError(RuntimeError):
    """A trusted read-only Codex cell could not be provisioned safely."""


class GenerationHolder:
    """A single mutable current-generation value shared with the proxy verifier.

    Generation supersession revokes a cell's prior grant on every refresh (a
    same-generation re-mint would collide), so the loopback proxy must verify a
    presented bearer at the generation currently in force, not a fixed one.
    """

    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value


def tracking_bearer_verifier(
    store: BearerDigestLookup, holder: GenerationHolder
) -> Callable[[str], Awaitable[bool]]:
    """``store_bearer_verifier`` generalized over the live refresh generation.

    Identical digest-only check as the fixed-generation helper, but reads the
    holder so a refreshed (superseded) generation keeps verifying after a re-mint.
    """

    async def verify(bearer: str) -> bool:
        try:
            digest = hashlib.sha256(bearer.encode("ascii")).hexdigest()
        except UnicodeEncodeError:
            return False
        found = await store.find_active_by_bearer_digest(digest, generation=holder.value)
        return found is not None

    return verify


def _sha256_prefixed(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def model_policy_digest(model_id: str, reasoning_effort: CodexReasoningEffort) -> str:
    """A deterministic model-policy digest shared by the config and the grant.

    Both the runtime-config ``model_policy_digest`` and the grant's model binding
    use this one value, so the credential the proxy authorizes and the config the
    cell runs are provably about the same model policy.
    """

    material = json.dumps(
        {"model_id": model_id, "reasoning_effort": reasoning_effort.value},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return _sha256_prefixed(material)


def read_only_budget() -> ModelProxyBudgetBinding:
    """The fixed small read-only reasoning budget for a trusted cell (D6)."""

    return ModelProxyBudgetBinding(
        READ_ONLY_BUDGET_ID,
        READ_ONLY_MAX_INPUT_TOKENS,
        READ_ONLY_MAX_OUTPUT_TOKENS,
        READ_ONLY_MAX_TOTAL_TOKENS,
        READ_ONLY_MAX_COST_MICROS,
        model_policy_digest("codex-read-only-budget", CodexReasoningEffort.HIGH),
    )


def _read_proc_identity(pid: int) -> tuple[int, str, int, str]:
    """Read the child's real ``/proc`` identity (D3: observed, NOT SO_PEERCRED-attested).

    Returns ``(pid_start_ticks, boot_id, pid_namespace_inode, cgroup_identity_digest)``.
    ``pid_start_ticks`` is field 22 of ``/proc/<pid>/stat`` (parsed after the last
    ``)`` so a comm with spaces or parens cannot shift the fields).
    """

    proc = Path("/proc") / str(pid)
    try:
        stat_text = (proc / "stat").read_text(encoding="ascii", errors="strict")
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        namespace_inode = int(os.stat(proc / "ns" / "pid").st_ino)
        cgroup = (proc / "cgroup").read_bytes()
    except (OSError, ValueError) as error:
        raise TrustedProxyProvisionError("child /proc identity is unavailable") from error
    rparen = stat_text.rfind(")")
    fields = stat_text[rparen + 2 :].split() if rparen >= 0 else []
    if rparen < 0 or len(fields) < 20:
        raise TrustedProxyProvisionError("child /proc/stat is malformed")
    try:
        start_ticks = int(fields[19])
    except ValueError as error:
        raise TrustedProxyProvisionError("child /proc/stat start time is malformed") from error
    return start_ticks, boot_id, namespace_inode, _sha256_prefixed(cgroup)


def build_cell_scope(
    assignment: PhaseAssignmentRef, cell_id: str, pid: int
) -> ModelProxyCellScope:
    """Build the cell scope from the child's REAL ``/proc`` identity (D3).

    The identity is observed, never fabricated; but it is NOT SO_PEERCRED-attested
    (the one production cross-check absent on this trusted path), so the returned
    scope must never be mistaken for a peer-attested identity.
    """

    if type(assignment) is not PhaseAssignmentRef:
        raise TypeError("assignment must be an exact PhaseAssignmentRef")
    if type(pid) is not int or pid <= 0:
        raise TrustedProxyProvisionError("child pid is invalid")
    phase = assignment.phase
    root = ModelProxyRootScope(phase.principal.tenant_id, phase.workspace_id, phase.root_run_id)
    scope_phase = ModelProxyPhaseScope(root, phase.phase_id)
    scope_assignment = ModelProxyAssignmentScope(scope_phase, assignment.assignment_id)
    start_ticks, boot_id, namespace_inode, cgroup_digest = _read_proc_identity(pid)
    return ModelProxyCellScope(
        scope_assignment,
        cell_id,
        pid,
        start_ticks,
        boot_id,
        namespace_inode,
        cgroup_digest,
    )


def cell_model_binding(model_id: str, policy_digest: str) -> ModelProxyModelBinding:
    return ModelProxyModelBinding(model_id, policy_digest)


def _system_skill_fragment(codex_home: Path) -> bytes:
    """The reviewed-system-skills-disabled skill fragment for an empty workspace.

    The read-only MVP cell selects no skills, so the fragment is exactly the
    reviewed 0.144.3 system skills, each disabled (matching the config policy's
    required prefix).
    """

    lines = ["# Boltrig trusted read-only Codex skill fragment (no selected skills)."]
    for name in REVIEWED_SYSTEM_SKILLS_0_144_3:
        path = (codex_home / "skills" / ".system" / name / "SKILL.md").as_posix()
        lines.extend(("", "[[skills.config]]", f'path = "{path}"', "enabled = false"))
    return ("\n".join(lines) + "\n").encode("ascii")


def render_trusted_config(
    *,
    cell_id: str,
    cell_root: Path,
    codex_home: Path,
    helper_path: Path,
    helper_sha256: str,
    socket_name: str,
    model_id: str,
    policy_digest: str,
    reasoning_effort: CodexReasoningEffort,
    proxy_port: int,
    native_subagents: NativeSubagentLimits = NativeSubagentLimits(),
    mcp_server_url: str | None = None,
    mcp_bearer_env_var: str | None = None,
) -> ComposedCodexRuntimeConfig:
    """Render the exact read-only config.toml pointing at the loopback proxy (D6).

    ``base_url`` is ``http://127.0.0.1:{proxy_port}/v1``, ``wire_api`` is
    ``responses``, and the provider auth is the SHARED root-owned helper proved by
    ``assert_cell_isolation_boundary`` ([2026] VJS-CC-VJS 5 G2), never a file this
    process wrote into the cell root; the per-cell values travel on ``auth.args``.

    The kernel-tools lane additionally renders ONE ``[mcp_servers.boltrig]``
    entry (url + bearer env var NAME only); the run-scoped token itself is
    delivered in the child environment, never in this file.
    """

    fragment = _system_skill_fragment(codex_home)
    request = CodexRuntimeConfigRequest(
        cell_id=cell_id,
        cell_root=cell_root,
        codex_home=codex_home,
        helper_path=helper_path,
        helper_sha256=helper_sha256,
        socket_name=socket_name,
        model_id=model_id,
        model_policy_digest=policy_digest,
        reasoning_effort=reasoning_effort,
        proxy_port=proxy_port,
        skill_config_fragment=fragment,
        skill_inventory_digest=_sha256_prefixed(fragment),
        native_subagents=native_subagents,
        mcp_server_url=mcp_server_url,
        mcp_bearer_env_var=mcp_bearer_env_var,
    )
    return compose_codex_runtime_config(request)


def write_cell_config(codex_home: Path, config_toml: str) -> Path:
    """Atomically write the rendered ``config.toml`` into the cell's CODEX_HOME."""

    config_path = codex_home / "config.toml"
    _atomic_write(config_path, config_toml.encode("ascii"), _PRIVATE_FILE_MODE)
    return config_path


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    directory = path.parent
    descriptor, temp_name = tempfile.mkstemp(dir=directory.as_posix(), prefix=".trusted-")
    temp_path = Path(temp_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def startup_request_id(cell_id: str) -> str:
    """A fresh per-mint startup request id (a new one on every refresh)."""

    return f"startup-{cell_id}-{secrets.token_hex(12)}"


__all__ = [
    "GenerationHolder",
    "TrustedProxyProvisionError",
    "build_cell_scope",
    "cell_model_binding",
    "model_policy_digest",
    "read_only_budget",
    "render_trusted_config",
    "startup_request_id",
    "tracking_bearer_verifier",
    "write_cell_config",
]
