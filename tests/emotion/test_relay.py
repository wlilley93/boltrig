"""EmotionRelay: downstream-only, content-free, tenant-scoped, fail-safe.

The relay is the ONE seam where the emotion add-on touches the kernel: an
EventRelay subclass whose publish() first does exactly what the base relay
does and only then feeds a read-only affective projection. These tests pin
EMO-1 (dispatch outcomes are identical with the emotion relay attached vs the
plain relay, and no kernel module imports the emotion package), EMO-2 (no
message content ever reaches a snapshot or the phenotype file), EMO-4 (engine
state is tenant-scoped), and the P9 fail-safe posture (a broken engine or an
unwritable path never raises out of publish).
"""

from __future__ import annotations

import ast
import dataclasses
import json
import pathlib
import time
from typing import Any

import fakeredis
import pytest
from fakeredis import aioredis as fake_aioredis

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.emotion.engine import Appraisal, EmotionModel
from boltrig.emotion.relay import EmotionRelay, build_event_relay
from boltrig.emotion.tables import load_emotion_tables
from boltrig.kernel import Kernel
from boltrig.kernel.events import EventRelay
from boltrig.kernel.redis_event_relay import RedisEventRelay
from boltrig.models import GrantSet, SchemaValidationError, TenantPermissions
from boltrig.store import InMemoryStore
from tests.conftest import TENANT, make_ctx

_REPO = pathlib.Path(__file__).resolve().parents[2]
_KERNEL_DIR = _REPO / "boltrig" / "kernel"

_PHENOTYPE_KEYS = {
    "fatigue", "valence", "arousal", "irritation", "attention", "social",
    "buoyancy", "luminosity", "tension",
}


def _tables() -> tuple[EmotionModel, list[Any]]:
    tables = load_emotion_tables()
    assert tables is not None, "the shipped libraries/emotion YAML must load"
    model, rules = tables
    return model, list(rules)


async def _build_kernel(relay: EventRelay) -> Kernel:
    """The conftest kernel recipe, with the relay under test attached."""
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["ticket.*"])))
    kernel = Kernel(store)
    # the composition root picked its own relay at construction; swap in the
    # one under test on both seams the kernel holds
    kernel.events = relay
    kernel.dispatcher._events = relay
    await kernel.register_adapter(TENANT, build_tickets())
    return kernel


def _canon(payload: object, replacements: dict[str, str]) -> str:
    """A canonical JSON string with per-run generated ids normalised away."""
    text = json.dumps(payload, sort_keys=True, default=str)
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _audit_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Audit rows minus the fields that legitimately differ between two runs
    (wall-clock timestamps, latencies, and the hashes derived from them)."""
    normed: list[dict[str, Any]] = []
    for row in rows:
        data = dataclasses.asdict(row)
        for volatile in ("ts", "latency_ms", "hash", "prev_hash"):
            data.pop(volatile, None)
        normed.append(data)
    return normed


def _call_id_placeholders(events: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for event in events:
        call_id = event.get("call_id")
        if isinstance(call_id, str) and call_id not in mapping:
            mapping[call_id] = f"<call-{len(mapping)}>"
    return mapping


def _leaves_are_numbers(obj: object) -> bool:
    """Keys-and-numbers only: every leaf of an emotion document is numeric."""
    if isinstance(obj, dict):
        return all(
            isinstance(k, str) and _leaves_are_numbers(v) for k, v in obj.items()
        )
    return isinstance(obj, (int, float)) and not isinstance(obj, bool)


@pytest.mark.kernel
@pytest.mark.invariant("EMO-1")
async def test_dispatch_outcomes_are_identical_with_and_without_the_emotion_relay(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pin the kernel's OWN relay factory off, so the only emotion relay in
    # play is the one this test attaches explicitly (host-independent)
    monkeypatch.setenv("BOLTRIG_EMOTION", "0")
    monkeypatch.setenv("BOLTRIG_ORB_PRESENCE", "0")
    model, rules = _tables()
    emotion_relay = EmotionRelay(
        model=model,
        rules=rules,
        phenotype_path=tmp_path / "phenotype.json",
        state_path=tmp_path / "state.json",
        tenant=TENANT,
        autostart=False,
    )
    with_emotion = await _build_kernel(emotion_relay)
    without = await _build_kernel(EventRelay())

    async def drive(kernel: Kernel) -> list[dict[str, Any]]:
        ctx = make_ctx(["ticket.create", "ticket.read"], run_id="run-emo")
        results = [
            await kernel.invoke("ticket", "ticket.create", {"title": "Fix login"}, ctx)
        ]
        results.append(
            await kernel.invoke("ticket", "ticket.read", {"id": results[0]["id"]}, ctx)
        )
        with pytest.raises(SchemaValidationError):
            await kernel.invoke("ticket", "ticket.create", {}, ctx)
        results.append(
            await kernel.invoke("ticket", "ticket.create", {"title": "Second"}, ctx)
        )
        return results

    results_a = await drive(with_emotion)
    results_b = await drive(without)

    # generated ticket ids are the only per-run nondeterminism in the results
    repl_a = {results_a[0]["id"]: "<t1>", results_a[2]["id"]: "<t2>"}
    repl_b = {results_b[0]["id"]: "<t1>", results_b[2]["id"]: "<t2>"}
    assert _canon(results_a, repl_a) == _canon(results_b, repl_b)

    audit_a = _audit_rows(await with_emotion.store.audit_query(TENANT))
    audit_b = _audit_rows(await without.store.audit_query(TENANT))
    assert audit_a, "the invoke sequence must have audited"
    assert _canon(audit_a, repl_a) == _canon(audit_b, repl_b)

    events_a = with_emotion.events.snapshot(TENANT, "run-emo")
    events_b = without.events.snapshot(TENANT, "run-emo")
    assert events_a, "dispatch must publish run events through the emotion relay too"
    repl_a.update(_call_id_placeholders(events_a))
    repl_b.update(_call_id_placeholders(events_b))
    assert _canon(events_a, repl_a) == _canon(events_b, repl_b)


@pytest.mark.kernel
@pytest.mark.invariant("EMO-1")
@pytest.mark.invariant("NFR-CONV-03")
def test_emotion_observes_the_shared_redis_relay_without_a_second_backlog(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOLTRIG_EMOTION", "1")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    server = fakeredis.FakeServer()
    backend = RedisEventRelay(
        fakeredis.FakeRedis(server=server, decode_responses=True),
        fake_aioredis.FakeRedis(server=server, decode_responses=True),
        namespace="emotion-shared",
    )

    kernel = Kernel(InMemoryStore(), event_relay=backend)
    assert isinstance(kernel.events, EmotionRelay)
    assert kernel.events.shared is True
    try:
        event = {"type": "tool_call", "status": "running", "call_id": "c1"}
        kernel.events.publish(TENANT, "run-1", event)
        assert kernel.events.snapshot(TENANT, "run-1") == [event]
        assert backend.snapshot(TENANT, "run-1") == [event]
        assert backend.max_seq(TENANT, "run-1") == 1
    finally:
        kernel.events.stop()


@pytest.mark.kernel
@pytest.mark.invariant("EMO-1")
@pytest.mark.invariant("NFR-CONV-03")
def test_broken_emotion_initialization_returns_the_supplied_shared_backend(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOLTRIG_EMOTION", "1")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(
        "boltrig.emotion.relay.load_emotion_tables",
        lambda: (_ for _ in ()).throw(RuntimeError("broken tables")),
    )
    server = fakeredis.FakeServer()
    backend = RedisEventRelay(
        fakeredis.FakeRedis(server=server, decode_responses=True),
        fake_aioredis.FakeRedis(server=server, decode_responses=True),
        namespace="emotion-fallback",
    )

    assert build_event_relay(backend=backend) is backend
    assert backend.shared is True


@pytest.mark.security
@pytest.mark.invariant("EMO-1")
def test_no_kernel_module_imports_the_emotion_package() -> None:
    offenders: list[str] = []
    # An empty glob has no offenders, so "emotion is strictly downstream" would be
    # true of a directory that is not there. EMO-1 is a boundary; a boundary that
    # inspected nothing has not held, it has been skipped.
    kernel_files = sorted(_KERNEL_DIR.rglob("*.py"))
    assert len(kernel_files) > 10, (
        f"scanned nothing meaningful: {_KERNEL_DIR} yielded {len(kernel_files)} files"
    )
    for path in kernel_files:
        if path == _KERNEL_DIR / "__init__.py":
            continue  # the ONE sanctioned seam: the relay factory import
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(
                    a.name.split(".")[:2] == ["boltrig", "emotion"] for a in node.names
                ):
                    offenders.append(str(path.relative_to(_REPO)))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".")[:2] == ["boltrig", "emotion"]:
                    offenders.append(str(path.relative_to(_REPO)))
    assert offenders == [], (
        "emotion is strictly downstream of dispatch; the only kernel touch is "
        "the relay factory seam in boltrig/kernel/__init__.py (EMO-1): "
        + ", ".join(offenders)
    )


@pytest.mark.security
@pytest.mark.invariant("EMO-2")
def test_message_content_never_reaches_snapshots_or_the_phenotype_file(
    tmp_path: pathlib.Path,
) -> None:
    sentinel = "EMO2-SENTINEL-c4a1d0"
    model, rules = _tables()
    phenotype_path = tmp_path / "phenotype.json"
    state_path = tmp_path / "state.json"
    relay = EmotionRelay(
        model=model,
        rules=rules,
        phenotype_path=phenotype_path,
        state_path=state_path,
        tenant=TENANT,
        publish_interval=0.01,
    )
    try:
        relay.publish(TENANT, "run-1", {
            "type": "text_delta", "run_id": "run-1", "text": sentinel,
        })
        relay.publish(TENANT, "run-1", {
            "type": "tool_call", "run_id": "run-1", "noun": "ticket",
            "verb": "ticket.create", "tool": "ticket.create", "call_id": "c1",
            "input": {"title": sentinel}, "args_summary": sentinel,
        })
        relay.publish(TENANT, "run-1", {
            "type": "tool_result", "run_id": "run-1", "call_id": "c1",
            "status": "ok", "output": {"title": sentinel},
            "result_summary": sentinel,
        })
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not (
            phenotype_path.exists() and state_path.exists()
        ):
            time.sleep(0.02)
    finally:
        relay.stop()

    assert phenotype_path.exists(), "the publisher must have written a phenotype"
    assert state_path.exists(), "the publisher must have persisted a snapshot"
    phenotype_text = phenotype_path.read_text(encoding="utf-8")
    state_text = state_path.read_text(encoding="utf-8")
    assert sentinel not in phenotype_text
    assert sentinel not in state_text

    document = json.loads(phenotype_text)
    assert set(document) == {"v", "ts", "phenotype"}
    assert set(document["phenotype"]) == _PHENOTYPE_KEYS
    assert _leaves_are_numbers(document)

    state = json.loads(state_text)
    assert TENANT in state["tenants"]
    assert _leaves_are_numbers(state)


@pytest.mark.security
@pytest.mark.invariant("EMO-4")
def test_tenant_b_events_leave_tenant_a_engine_untouched(
    tmp_path: pathlib.Path,
) -> None:
    model, rules = _tables()
    state_path = tmp_path / "state.json"
    relay = EmotionRelay(
        model=model,
        rules=rules,
        phenotype_path=tmp_path / "phenotype.json",
        state_path=state_path,
        tenant="tenant-a",
        publish_interval=0.01,
    )
    snapshots: dict[str, Any] = {}
    try:
        # one success for tenant A ...
        relay.publish("tenant-a", "run-a", {
            "type": "tool_result", "run_id": "run-a", "call_id": "a1",
            "status": "ok",
        })
        # ... and a hail of failures for tenant B
        for i in range(15):
            relay.publish("tenant-b", "run-b", {
                "type": "tool_result", "run_id": "run-b",
                "call_id": f"b{i}", "status": "error",
            })
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if state_path.exists():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                snapshots = state["tenants"]
                if {"tenant-a", "tenant-b"} <= set(snapshots):
                    break
            time.sleep(0.02)
    finally:
        relay.stop()

    assert {"tenant-a", "tenant-b"} <= set(snapshots), "engines are keyed per tenant"
    emotions_a = snapshots["tenant-a"]["emotions"]
    emotions_b = snapshots["tenant-b"]["emotions"]
    # B's task_error barrage drove B's frustration up; A saw only its one
    # success, so A's frustration stays in the decayed-baseline band and A's
    # satisfaction stays above B's.
    assert emotions_b["frustration"] > 0.5
    assert emotions_a["frustration"] < 0.3
    assert emotions_a["satisfaction"] > emotions_b["satisfaction"]


@pytest.mark.security
@pytest.mark.invariant("P9")
def test_a_broken_engine_or_unwritable_path_never_raises_out_of_publish(
    tmp_path: pathlib.Path,
) -> None:
    _, rules = _tables()
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory should be", encoding="utf-8")
    # a model whose appraisal touches state the model never declared, and
    # persistence paths whose parent is a FILE so every write must fail
    broken = EmotionModel(
        baselines={},
        half_lives_h={},
        need_defaults={},
        need_decay_h={},
        appraisals={
            "task_success": Appraisal(
                emotions={"satisfaction": 0.5}, needs={"purpose": 1.0}
            )
        },
    )
    relay = EmotionRelay(
        model=broken,
        rules=rules,
        phenotype_path=blocker / "phenotype.json",
        state_path=blocker / "state.json",
        tenant=TENANT,
        publish_interval=0.01,
    )
    try:
        events: list[dict[str, Any]] = [
            {"type": "tool_result", "run_id": "run-1", "call_id": "c0",
             "status": "ok"},
            {"type": "tool_result", "run_id": "run-1", "call_id": "c1",
             "status": "error"},
            {"type": "text_delta", "run_id": "run-1", "text": "hi"},
            {"type": "final", "run_id": "run-1"},
        ]
        for event in events:
            relay.publish(TENANT, "run-1", event)  # must never raise (P9)
        time.sleep(0.1)  # let the publisher thread hit the unwritable paths
        # the base relay duties are untouched: every event reached the stream
        assert relay.snapshot(TENANT, "run-1") == events
    finally:
        relay.stop()
    assert not (blocker / "phenotype.json").exists()
