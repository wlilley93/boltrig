"""Tests for the trusted read-only Codex proxy provider ([2026] VJS-CC-VJS 1/2/3).

Security-critical: a fail-open in issuance or an upstream-key leak is the
catastrophic failure. These pin the load-bearing directives without running the
live Codex turn (the in-container re-proof runs that on the real box):

  * D1 - the dev/prod wall fails closed BEFORE any admit or issuance.
  * D2 - the supervisor is constructed with auth=None (the child env never carries
    the upstream key).
  * a bearer minted through the ingress issuer verifies via the store verifier, and
    teardown revokes the grant, closes the proxy, and closes the ingress.
  * FINDING #3 - the identity REGISTERED for a cell is derived from the slot it was
    allocated, never read out of the /proc that registration is checking.
  * the rendered config.toml points the cell at the loopback proxy + socket helper.

Option-B delivery (VJS-CC-VJS 3): there is NO bearer file at rest. The per-cell
socket ingress + issuer lifecycle is covered in test_codex_trusted_proxy_ingress.py
and test_codex_trusted_ingress_live.py; the auth.command helper in
test_codex_trusted_proxy_helper.py.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest


from boltrig.fleet.application.model_proxy_grants import PhaseScopedModelProxyGrantBroker
from boltrig.fleet.codex_trusted_wall import CodexTrustedPostureError
from boltrig.fleet.domain import PhaseAssignmentRef, PhaseRef
from boltrig.fleet.domain.model_proxy_scope import ModelProxyCellScope
from boltrig.fleet.infrastructure.cell_slots import slot_for_index
from boltrig.fleet.infrastructure.codex_cell_policy import CodexUpstreamAuth
from boltrig.fleet.infrastructure.codex_cell_policy import sanitized_environment
from boltrig.fleet.infrastructure.codex_cell_supervisor import CodexCellSupervisor
from boltrig.fleet.infrastructure.codex_model_proxy_server import (
    PerCellModelProxyServer,
)
from boltrig.fleet.infrastructure.codex_runtime_config import CodexReasoningEffort
from boltrig.fleet.infrastructure.codex_trusted_proxy_ingress import (
    CapturedCellIdentity,
    CodexTrustedIngress,
    build_ingress_bearer_issuer,
    select_ingress_socket_name,
)
from boltrig.fleet.infrastructure import codex_trusted_proxy_provider as provider_module
from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (
    TrustedProxyCodexPhaseCellProvider,
    TrustedProxyProvisionError,
    _expected_cell_credentials,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (
    GenerationHolder,
    build_cell_scope,
    read_only_budget,
    render_trusted_config,
    tracking_bearer_verifier,
)
from boltrig.fleet.infrastructure.memory_model_proxy_grants import (
    MemoryModelProxyGrantStore,
)
from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (
    LinuxModelProxyPeerAttestor,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
    ModelProxyProcessRegistry,
)
from boltrig.models.execution_scope import OrganisationUserRef

from .codex_process_fakes import make_layout



# --- the environment precondition this whole module needs -------------------
# Every test here drives the trusted-Codex lane, and that lane's ONE available
# boundary is a helper owned by ANOTHER ACCOUNT on a directory chain this account
# cannot write (see codex_cell_boundary's module docstring). `/bin/sh` stands in
# for the baked image helper. Whether that property holds is a fact about the
# MACHINE, not about the code:
#
#   * as root every ancestor is ours, so nothing is proved. test_codex_cell_boundary
#     already skips for exactly this reason ("root can write everything").
#   * on some GitHub-hosted runner images /usr is owned by the RUNNER account, so
#     the same is true at uid 1001 and a root-only guard misses it entirely.
#
# The second case cost real time and produced a false accusation: 25 tests here
# failed on a PR whose entire diff was two TypeScript files, while a PR that DID
# change Python passed 16/16 minutes apart - same code, different runner. A test
# that fails when the machine cannot supply its precondition reports the
# environment as a code defect, and sends whoever reads it hunting their own diff.
#
# So it SKIPS, visibly and with the reason. The cost is honest and worth stating:
# on such a runner this module proves nothing, including the assertions that would
# have passed. That is preferable to a red that means nothing, and the skip names
# the euid so the next reader can check the claim in one command.
def _every_ancestor_is_foreign(path: str) -> bool:
    """True only when EVERY ancestor of ``path`` belongs to another account.

    EVERY, not any, and the difference is the whole bug. `_assert_shared_helper`
    walks `helper_path.parents` and refuses on the FIRST ancestor our euid owns,
    so the precondition has to be the conjunction. An `any` version passed both
    of its checks - green as my own uid, skipped as root - because root is the
    degenerate case where every ancestor is ours and `any` and `all` agree. On a
    runner where /usr is ours but / is root's, `any` found / , declined to skip,
    and the tests failed exactly as before.
    """
    euid = os.geteuid()
    parents = list(Path(path).parents)
    if not parents:
        return False
    for ancestor in parents:
        try:
            if ancestor.stat().st_uid == euid:
                return False
        except OSError:
            return False
    return True


# Two conditions, both of which must hold, so this is a LIST: a second
# `pytestmark = ...` assignment would rebind the name and silently drop
# whichever came first. linux_only covers the kernel facilities; the skipif
# below covers the file-mode boundary these tests rest on.
pytestmark = [
    pytest.mark.linux_only,
    pytest.mark.skipif(
    not _every_ancestor_is_foreign(os.path.realpath("/bin/sh")),
    reason=(
        f"an ancestor of {os.path.realpath('/bin/sh')} is owned by this account "
        f"(euid {os.geteuid()}), so the file-mode boundary the trusted-Codex lane "
        "rests on does not exist here and these tests would prove nothing"
    ),
),
]

_CODEX_BIN = Path("/opt/boltrig/codex/codex")
_CELL_ID = "cell-abc1234567890ab"
_MODEL_ID = "gpt-5.2-codex"
_POLICY_DIGEST = "sha256:" + "b" * 64
# /bin/sh stands in for the baked image helper: root-owned, executable, on a
# directory chain this account cannot write ([2026] VJS-CC-VJS 5 G2).
_TEST_SHARED_HELPER = os.path.realpath("/bin/sh")
_TRUSTED_ENV = {
    "BOLTRIG_DEV_AUTH": "1",
    "BOLTRIG_CODEX_TRUSTED": "1",
    "BOLTRIG_CODEX_AUTH_HELPER": _TEST_SHARED_HELPER,
}


def _assignment() -> PhaseAssignmentRef:
    principal = OrganisationUserRef(tenant_id="tenant-1", user_id="user-1")
    phase = PhaseRef(
        root_run_id="run-1",
        phase_id="run-1-codex",
        principal=principal,
        workspace_id="ws-1",
    )
    return PhaseAssignmentRef(phase=phase, assignment_id="run-1-codex-assignment")


class _FakeSource:
    def __init__(self) -> None:
        self.calls = 0

    async def admit(self, assignment: PhaseAssignmentRef) -> object:
        self.calls += 1
        raise AssertionError("admit must not run when the wall refuses")


class _FakeProbe:
    async def probe(self, client: object, plan: object) -> object:
        raise AssertionError("probe must not run in these tests")


@pytest.fixture
def running_child() -> Iterator[int]:
    """A short-lived real process whose /proc identity is read by the scope."""

    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        yield process.pid
    finally:
        process.kill()
        process.wait(timeout=5)


def _supervisor(auth: CodexUpstreamAuth | None = None) -> CodexCellSupervisor:
    return CodexCellSupervisor(binary=_CODEX_BIN, auth=auth)


def _provider(
    *,
    broker: PhaseScopedModelProxyGrantBroker,
    store: MemoryModelProxyGrantStore,
    client: httpx.AsyncClient,
    source: _FakeSource | None = None,
    supervisor: CodexCellSupervisor | None = None,
    env: dict[str, str] | None = None,
    generation: int = 1,
    ttl_seconds: int = 60,
    registry: ModelProxyProcessRegistry | None = None,
    attestor: LinuxModelProxyPeerAttestor | None = None,
) -> TrustedProxyCodexPhaseCellProvider:
    reg = registry if registry is not None else ModelProxyProcessRegistry()
    att = attestor if attestor is not None else LinuxModelProxyPeerAttestor(reg)
    return TrustedProxyCodexPhaseCellProvider(
        source=source or _FakeSource(),
        supervisor=supervisor or _supervisor(),
        probe=_FakeProbe(),
        broker=broker,
        grant_store=store,
        registry=reg,
        attestor=att,
        stack_root=Path("/tmp"),
        upstream_base_url="http://gateway/v1",
        upstream_key="KERNEL-ONLY-KEY",
        http_client=client,
        generation=generation,
        reasoning_effort=CodexReasoningEffort.HIGH,
        ttl_seconds=ttl_seconds,
        env=env if env is not None else dict(_TRUSTED_ENV),
    )


def _store_broker() -> tuple[MemoryModelProxyGrantStore, PhaseScopedModelProxyGrantBroker]:
    store = MemoryModelProxyGrantStore()
    return store, PhaseScopedModelProxyGrantBroker(store, max_ttl_seconds=120)


# --- D1: the wall fails closed before any provisioning or issuance -----------


async def test_acquire_refuses_before_admit_without_trusted_posture() -> None:
    store, broker = _store_broker()
    source = _FakeSource()
    async with httpx.AsyncClient() as client:
        provider = _provider(
            broker=broker,
            store=store,
            client=client,
            source=source,
            env={"BOLTRIG_CODEX_AUTH_HELPER": _TEST_SHARED_HELPER},
        )
        with pytest.raises(CodexTrustedPostureError):
            await provider.acquire(_assignment())
    assert source.calls == 0
    assert store.snapshot() == ()


# --- D2: the supervisor must be constructed with auth=None -------------------


async def test_supervisor_with_upstream_auth_is_refused_at_construction() -> None:
    store, broker = _store_broker()
    async with httpx.AsyncClient() as client:
        with pytest.raises(TrustedProxyProvisionError, match="auth=None"):
            _provider(
                broker=broker,
                store=store,
                client=client,
                supervisor=_supervisor(CodexUpstreamAuth("upstream-secret-token")),
            )


async def test_provider_holds_an_auth_none_supervisor() -> None:
    store, broker = _store_broker()
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client)
    assert provider._supervisor._auth is None


async def test_provider_requires_an_absolute_stack_root() -> None:
    store, broker = _store_broker()
    reg = ModelProxyProcessRegistry()
    async with httpx.AsyncClient() as client:
        with pytest.raises(TrustedProxyProvisionError, match="stack_root"):
            TrustedProxyCodexPhaseCellProvider(
                source=_FakeSource(),
                supervisor=_supervisor(),
                probe=_FakeProbe(),
                broker=broker,
                grant_store=store,
                registry=reg,
                attestor=LinuxModelProxyPeerAttestor(reg),
                stack_root=Path("relative/root"),
                upstream_base_url="http://gateway/v1",
                upstream_key="KERNEL-ONLY-KEY",
                http_client=client,
            )


# --- issuance + teardown: no bearer file, grant revoked, proxy + ingress closed --


@pytest.mark.skipif(sys.platform != "linux", reason="build_cell_scope reads /proc")
async def test_teardown_revokes_grant_and_closes_proxy_and_ingress(
    tmp_path: Path, running_child: int
) -> None:
    store, broker = _store_broker()
    registry = ModelProxyProcessRegistry()
    attestor = LinuxModelProxyPeerAttestor(registry)
    async with httpx.AsyncClient() as client:
        provider = _provider(
            broker=broker, store=store, client=client, registry=registry, attestor=attestor
        )
        proxy = PerCellModelProxyServer(
            verify_bearer=tracking_bearer_verifier(store, GenerationHolder(1)),
            upstream_base_url="http://gateway/v1",
            upstream_key="KERNEL-ONLY-KEY",
            client=client,
            allowed_model=_MODEL_ID,
        )
        await proxy.start()

        scope = build_cell_scope(_assignment(), _CELL_ID, running_child)
        # The issuer mints only under a LIVE registration (the issuance TOCTOU),
        # so the scope must be registered before a bearer can exist.
        await registry.register(scope, expected_uid=os.getuid(), expected_gid=os.getgid())
        issuer = build_ingress_bearer_issuer(
            broker=broker,
            registry=registry,
            model_id=_MODEL_ID,
            policy_digest=_POLICY_DIGEST,
            budget=read_only_budget(),
            ttl_seconds=60,
            holder=GenerationHolder(1),
            expected_cell_uid=None,
        )
        # The issuer mints a fresh single-cell bearer per attested connection; the
        # first mint bumps the holder to generation 2. No file is ever written.
        bearer = await issuer(scope)
        assert isinstance(bearer, bytes) and bearer
        digest = hashlib.sha256(bearer).hexdigest()
        assert await store.find_active_by_bearer_digest(digest, generation=2) is not None
        assert not any((tmp_path).iterdir())  # nothing at rest under the cell dir

        ingress = CodexTrustedIngress(  # unstarted: aclose is a safe no-op
            registry,
            attestor,
            stack_root=Path("/tmp"),
            boundary=provider._boundary,
        )
        await provider._teardown(proxy, scope, ingress)

        assert proxy._server is None
        assert await store.find_active_by_bearer_digest(digest, generation=2) is None


# --- FINDING #3: the registered identity is the allocation, not the /proc read --


async def _never_issue(attested: ModelProxyCellScope) -> bytes:
    raise AssertionError("no peer connects in these tests")


def test_the_expected_credentials_come_from_the_slot_not_from_proc() -> None:
    """The derivation, on its own: a slot answers with the uid it declares.

    ``slot_for_index`` is pure - it touches no filesystem and reads no /proc - so
    this pins that the expectation is a statement of what the cell MUST be, which is
    the only kind of expectation a check can fail against. Reading it back out of
    the /proc being checked would be a check that cannot fail, and that is precisely
    what the code did on 2026-07-27.
    """

    assert _expected_cell_credentials(slot_for_index(0)) == (20001, 20001)
    assert _expected_cell_credentials(slot_for_index(3)) == (20004, 20004)
    # In-process there is no slot and no drop: the cell is the API's own child.
    assert _expected_cell_credentials(None) == (os.getuid(), os.getgid())


@pytest.mark.skipif(sys.platform != "linux", reason="captures this process /proc identity")
async def test_the_registration_seam_declares_the_slots_identity_not_the_captured_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wiring: _register_spawned_cell must hand the SLOT's ids to the capture.

    The semantics are pinned deterministically against a scripted /proc in
    test_codex_trusted_proxy_ingress.py; what cannot be produced here is a real
    process at uid 20001, so this pins the other half - that the provider derives
    the expectation from the slot it reserved and passes it down. Recording the call
    is the honest way to assert that: if the provider went back to letting the
    capture choose, no expectation would arrive at all.
    """

    recorded: dict[str, int] = {}

    def recording_capture(
        assignment: PhaseAssignmentRef,
        cell_id: str,
        pid: int,
        *,
        expected_uid: int,
        expected_gid: int,
    ) -> CapturedCellIdentity:
        recorded["uid"] = expected_uid
        recorded["gid"] = expected_gid
        return CapturedCellIdentity(
            build_cell_scope(assignment, cell_id, pid), expected_uid, expected_gid
        )

    monkeypatch.setattr(provider_module, "capture_cell_identity", recording_capture)
    store, broker = _store_broker()
    registry = ModelProxyProcessRegistry()
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client, registry=registry)
        ingress = provider._build_ingress()
        try:
            await provider._register_spawned_cell(
                assignment=_assignment(),
                cell_id=_CELL_ID,
                pid=os.getpid(),
                slot=slot_for_index(2),  # uid 20003, which this process is not
                ingress=ingress,
                socket_name=select_ingress_socket_name(),
                issuer=_never_issue,
            )
            live = (await registry.snapshot_live()).registrations
        finally:
            await ingress.aclose()  # revokes, so the snapshot is taken before it

    assert recorded == {"uid": 20003, "gid": 20003}
    # And the declaration is what actually reached the registry, which is the value
    # every later ancestry attestation compares the live process against.
    assert len(live) == 1
    assert (live[0].expected_uid, live[0].expected_gid) == (20003, 20003)


@pytest.mark.skipif(sys.platform != "linux", reason="captures this process /proc identity")
async def test_the_in_process_posture_registers_the_cells_settled_credentials() -> None:
    """The same seam, unpatched, on the posture where the cell really is this uid.

    In-process there is no slot and no drop: the cell is an ordinary child of the
    API and shares its credentials for its whole life, so the API's own ids are both
    the right expectation and what the capture reads. Without this case the checks
    above could be satisfied by a seam that refused everything, which would be an
    outage wearing the costume of a fix.
    """

    store, broker = _store_broker()
    registry = ModelProxyProcessRegistry()
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client, registry=registry)
        ingress = provider._build_ingress()
        try:
            scope = await provider._register_spawned_cell(
                assignment=_assignment(),
                cell_id=_CELL_ID,
                pid=os.getpid(),
                slot=None,
                ingress=ingress,
                socket_name=select_ingress_socket_name(),
                issuer=_never_issue,
            )
            live = (await registry.snapshot_live()).registrations
        finally:
            await ingress.aclose()

    assert scope.pid == os.getpid()
    assert len(live) == 1
    assert (live[0].expected_uid, live[0].expected_gid) == (os.getuid(), os.getgid())


async def test_the_issuer_confirms_the_slots_uid_on_the_per_cell_lane_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The confirming half is wired from the SAME slot the registration declares.

    ``expected_cell_uid`` is what makes the declaration a boundary rather than a
    claim: it is the uid the kernel is asked to confirm on the cell's pid before any
    bearer is minted. None in-process, where the cell shares the API's uid and there
    is nothing per_cell_uid_mode_available does not already answer.
    """

    captured: dict[str, object] = {}

    def recording_builder(**kwargs: object) -> object:
        captured.update(kwargs)
        return _never_issue

    monkeypatch.setattr(provider_module, "build_ingress_bearer_issuer", recording_builder)
    store, broker = _store_broker()
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client)
        provider._build_issuer(_MODEL_ID, GenerationHolder(1), slot_for_index(1))
        assert captured["expected_cell_uid"] == 20002
        provider._build_issuer(_MODEL_ID, GenerationHolder(1), None)
        assert captured["expected_cell_uid"] is None


# --- config: the cell is pointed at the loopback proxy + socket helper --------


def test_config_points_the_cell_at_the_loopback_proxy(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    # G2: the helper is the SHARED root-owned program, never a per-cell file.
    helper = Path(_TEST_SHARED_HELPER)
    composed = render_trusted_config(
        cell_id="cell-001",
        cell_root=tmp_path,
        codex_home=codex_home,
        helper_path=helper,
        helper_sha256="sha256:" + "a" * 64,
        socket_name="@boltrig-mp-0123456789abcdef0123456789abcdef",
        model_id=_MODEL_ID,
        policy_digest="sha256:" + "b" * 64,
        reasoning_effort=CodexReasoningEffort.HIGH,
        proxy_port=45123,
    )
    document = tomllib.loads(composed.config_toml)
    provider = document["model_providers"]["boltrig_model_proxy"]  # type: ignore[index]
    assert provider["base_url"] == "http://127.0.0.1:45123/v1"
    assert provider["wire_api"] == "responses"
    assert provider["auth"]["command"] == helper.as_posix()
    assert provider["auth"]["args"] == [
        "--cell-id",
        "cell-001",
        "--socket",
        "@boltrig-mp-0123456789abcdef0123456789abcdef",
    ]
    assert document["sandbox_mode"] == "read-only"

    # H5 ([2026] VJS-CC-VJS 6): the SAME composed record derives the argv, so the
    # file and the command line cannot disagree about the values that matter. This
    # is the property that makes pinning worth anything: a sibling cell rewriting
    # config.toml still faces the argv, and the argv still says what the file said.
    overrides = dict(
        argument.split("=", 1) for argument in composed.receipt.app_server_arguments[5::2]
    )
    base = "model_providers.boltrig_model_proxy"
    assert overrides[f"{base}.base_url"] == f'"{provider["base_url"]}"'
    assert overrides[f"{base}.auth.command"] == f'"{provider["auth"]["command"]}"'
    assert overrides["sandbox_mode"] == f'"{document["sandbox_mode"]}"'
    assert "cell-001" in overrides[f"{base}.auth.args"]


async def test_write_cell_config_writes_no_executable_into_the_cell_root(
    tmp_path: Path,
) -> None:
    store, broker = _store_broker()
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client)
        codex_home = tmp_path / "codex-home"
        codex_home.mkdir()
        socket_name = "@boltrig-mp-0123456789abcdef0123456789abcdef"
        await provider._write_cell_config(
            cell_id="cell-002",
            cell_root=tmp_path,
            codex_home=codex_home,
            model_id=_MODEL_ID,
            proxy_port=44001,
            socket_name=socket_name,
        )
    # G2: nothing executable is written into the mutable cell root any more; the
    # helper is the one root-owned program on the read-only image mount.
    assert not (tmp_path / "model_auth_helper").exists()
    assert [entry.name for entry in tmp_path.iterdir()] == ["codex-home"]
    document = tomllib.loads((codex_home / "config.toml").read_text())
    provider_block = document["model_providers"]["boltrig_model_proxy"]  # type: ignore[index]
    assert provider_block["base_url"] == "http://127.0.0.1:44001/v1"


# --- [2026] VJS-CC-VJS 4: the four limbs of the effective_tools claim ---------


@pytest.mark.parametrize(
    "granted",
    [frozenset(), frozenset({"update_plan"}), frozenset({"update_plan", "view_image"})],
)
async def test_the_proxy_ceiling_is_derived_from_the_policy_not_a_default(
    granted: frozenset[str],
) -> None:
    """F3 DERIVATION: the ceiling must come from the compiled policy it cites.

    The constructor defaults allowed_tools to empty and fails closed, which means a
    lane that FORGOT to wire the ceiling would look identical to one that wired it.
    A non-empty policy is therefore the load-bearing case: it can only pass if the
    value genuinely travelled from the policy rather than from the default.
    """

    store, broker = _store_broker()
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client)
        proxy = await provider._start_proxy(GenerationHolder(1), granted, _MODEL_ID)
        try:
            assert proxy._allowed_tools == granted
            assert proxy._allowed_model == _MODEL_ID
        finally:
            await proxy.aclose()


def test_the_cell_environment_carries_no_upstream_credential_or_gateway(
    tmp_path: Path,
) -> None:
    """F4 EXCLUSIVITY, limb (b): no credentialed egress is reachable from the cell.

    The court held that "the key is injected server-side" is a statement about
    CREDENTIAL exclusivity and does not by itself prove PATH exclusivity. This pins
    the credential half as a test: the sanitized child environment is exactly five
    variables, and carries neither the upstream key nor any gateway URL, so the cell
    cannot present authority to the gateway directly however it reaches the network.
    """

    environment = sanitized_environment(make_layout(tmp_path), None)

    assert set(environment) == {"CODEX_HOME", "HOME", "LANG", "LC_ALL", "PATH"}
    assert "CODEX_ACCESS_TOKEN" not in environment
    joined = " ".join(environment.values())
    assert "KERNEL-ONLY-KEY" not in joined
    assert "gateway" not in joined and "bifrost" not in joined
    # The sanitized PATH holds no general-purpose fetch tool either.
    assert environment["PATH"] == "/usr/bin:/bin"
