"""The promotion subsystem is gone, and the harvest leg beside it is not.

[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001, directives D3 and D4. The
court refused to pick a trigger that would WRITE a workflow-promotion record,
because no production path READ one: `WorkflowLibrary.match` is reachable only
from `select_or_generate_workflow`, which nothing in production calls. Every
candidate producer was therefore equally inert, and the order of work is to retire
the consumer first. D3 deleted the whole write side; D4 protected the one thing in
the same module that IS wired.

These are structural pins, not behavioural ones, and that is deliberate: a
behavioural test cannot fail for code that no longer exists. What can regress is
somebody reintroducing the machinery, or deleting the harvest leg beside it while
clearing the rest away. Both are cheap to catch by reading the tree.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "boltrig"

# The five names D3 deleted. `_clamp` and `_state_base` went with promotion.py but
# are not listed: `_clamp` is a plain-enough helper name that another module may
# legitimately want it, so pinning it would be a name collision waiting to happen.
_DELETED = (
    "WorkflowPromoter",
    "reuse_weight",
    "apply_promotion_signal",
    "WorkflowPromotion",
    "PromotionState",
)


def _sources() -> list[Path]:
    files = sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)
    # A scan that silently matched nothing would pass forever; make the sweep prove
    # it actually read the tree.
    assert len(files) > 50, f"only {len(files)} sources scanned under boltrig/"
    return files


@pytest.mark.security
def test_promotion_machinery_is_absent_from_the_tree():
    """D3: none of the five deleted names is defined or referenced under boltrig/.

    Definition and reference are both checked, and by AST rather than by text, so a
    docstring or comment that MENTIONS the retirement (this repository's records do)
    is not mistaken for the thing coming back. What would fail this is a `class
    WorkflowPromoter`, a `def reuse_weight`, an import of `WorkflowPromotion`, or
    any expression naming one of them.
    """
    offenders: list[str] = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            found: str | None = None
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                found = node.name if node.name in _DELETED else None
            elif isinstance(node, ast.Name):
                found = node.id if node.id in _DELETED else None
            elif isinstance(node, ast.Attribute):
                found = node.attr if node.attr in _DELETED else None
            elif isinstance(node, ast.alias):
                bound = node.asname or node.name.rsplit(".", 1)[-1]
                found = bound if bound in _DELETED else None
            if found:
                rel = path.relative_to(ROOT).as_posix()
                offenders.append(f"{rel}:{getattr(node, 'lineno', 0)}: {found}")
    assert offenders == [], (
        "the workflow-promotion machinery is back under boltrig/:\n  "
        + "\n  ".join(offenders)
        + "\n[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D3 retired it, and "
        "its forbidden clause 4 bars rebuilding it as a stored state with a writer "
        "and a trigger. If reuse ranking is wanted, DERIVE it from the eval cases "
        "and their runs, pinned by the definition digest. Route to court."
    )


@pytest.mark.security
def test_harvest_reuse_signal_keeps_both_of_its_call_sites():
    """D4: harvest_reuse_signal survives D3, wired at exactly its two call sites.

    The order forbids deleting it or either call site under cover of the promotion
    retirement, so this names both files and asserts the call is really there - an
    import alone would not be wiring, which is the whole point the same ruling makes
    about re-exports.
    """
    call_sites = (
        SRC / "api" / "bootstrap.py",          # HITL verdict -> endorsement / block
        SRC / "kernel" / "account_profile_routes.py",  # regenerate supersedes a reply
    )
    for path in call_sites:
        assert path.exists(), f"{path} is gone; D4 protects its call site"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        called = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "harvest_reuse_signal"
            for node in ast.walk(tree)
        )
        rel = path.relative_to(ROOT).as_posix()
        assert called, (
            f"{rel} no longer CALLS harvest_reuse_signal. "
            "[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D4 keeps this leg "
            "and both its call sites: it is wired, it has a live consumer, and it "
            "was expressly carved out of the D3 deletion."
        )


@pytest.mark.security
def test_regenerate_still_dispatches_memory_improve_through_the_kernel():
    """D4, the behavioural half at the access-routes call site.

    Structure is not dispatch. This drives the real regenerate route end to end and
    watches the chokepoint: the supersede must still reach ``memory.improve`` through
    ``kernel.invoke``, carrying only a signal word and a target - no grant, no scope,
    no tier (COUNTY 5). The HITL call site's twin is
    ``test_self_improvement_competence.py::test_only_approval_verdicts_are_harvested_as_reuse_signals``.
    """
    import asyncio

    from fastapi.testclient import TestClient

    from boltrig.fleet.chat import ChatService
    from boltrig.kernel import Kernel
    from boltrig.kernel.app import create_app
    from boltrig.kernel.events import EventRelay
    from boltrig.store import InMemoryStore

    tenant = "acme"

    def _executor(reply: str):
        async def run(*, run_id, relay, **kw):
            relay.publish(run_id, {"type": "text_delta", "delta": reply})

        return run

    store, relay = InMemoryStore(), EventRelay()
    seed = ChatService(store, relay, turn_executor=_executor("first answer"))

    async def _seed():
        async for _ in seed.handle_turn(
            tenant_id=tenant, user_id="alice", role="engineer", message="the question"
        ):
            pass
        conv = (await store.list_conversations(tenant, "alice"))[0]
        return conv, await store.list_messages(tenant, conv.id)

    conv, msgs = asyncio.run(_seed())
    chat = ChatService(store, relay, turn_executor=_executor("regenerated"))
    kernel = Kernel(store)
    seen: list[tuple[str, str, dict]] = []
    real_invoke = kernel.invoke

    async def recording_invoke(noun, verb, params, context, **kwargs):
        seen.append((noun, verb, params))
        return await real_invoke(noun, verb, params, context, **kwargs)

    kernel.invoke = recording_invoke  # type: ignore[method-assign]
    client = TestClient(create_app(kernel, chat_service=chat, platform={}))

    res = client.post(
        f"/v1/me/conversations/{conv.id}/messages/{msgs[1].id}/regenerate",
        headers={
            "x-boltrig-tenant": tenant, "x-boltrig-subject": "alice",
            "x-boltrig-role": "engineer", "x-boltrig-grants": "",
            "x-boltrig-departments": "",
        },
    )
    assert res.status_code == 200

    improves = [(n, v, p) for n, v, p in seen if v == "memory.improve"]
    assert len(improves) == 1, (
        "the regenerate path stopped dispatching memory.improve through the kernel; "
        "D4 keeps this leg live"
    )
    _, _, params = improves[0]
    assert set(params) == {"signal", "target"}  # no grant / scope / tier, ever
    assert params["signal"] == "regenerate_superseded:regression"
    assert params["target"] == msgs[1].id
