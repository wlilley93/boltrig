"""End-to-end binding for deterministic, authority-neutral spawn rules."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from boltrig.config.admin import AdminConfig
from boltrig.config.spawn_rules import (
    SpawnRuleMatchError,
    SpawnRuleValidationError,
    parse_spawn_rules,
    select_spawn_rule,
)
from boltrig.fleet.result import AgentResult
from boltrig.fleet.spawn import build_spawner
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    AgentCapability,
    DepthExceeded,
    GrantSet,
    InvocationContext,
    Skill,
    SpawnRulePolicyInvalid,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "spawn-policy"


def _rule(
    name: str,
    *,
    priority: int,
    tags: list[str],
    capability: str,
    skills: list[str] | None = None,
    max_depth: int | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "name": name,
        "priority": priority,
        "match": {"intent_tags": tags},
        "capability": capability,
        "skills": skills or [],
    }
    if max_depth is not None:
        value["max_depth"] = max_depth
    return value


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    for name in ("fallback", "routed", "revised"):
        await store.upsert_capability(
            AgentCapability(name, T, "python-script", ["*"], 4, True, "cheap")
        )
    await store.upsert_skill(
        Skill(
            id="analysis/requested",
            tenant_id=T,
            version="1",
            prompt_fragment="Requested.",
            tool_grants=["ticket.read"],
        )
    )
    await store.upsert_skill(
        Skill(
            id="integration/rule-added",
            tenant_id=T,
            version="1",
            prompt_fragment="Rule added.",
            tool_grants=["ticket.write"],
        )
    )
    return Kernel(store)


def _context(*, depth: int = 0) -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        run_id="parent-run",
        depth=depth,
        grants=GrantSet.of(["ticket.read"]),
        actor="head",
        extra={
            "boltrig_spawn_rule": {
                "id": "caller-forgery",
                "capability": "forged",
            }
        },
    )


@pytest.mark.invariant("SEC-194")
def test_spawn_rule_schema_and_priority_are_closed_and_deterministic() -> None:
    with pytest.raises(SpawnRuleValidationError, match="missing required fields: priority"):
        parse_spawn_rules(
            [
                {
                    "name": "missing-priority",
                    "match": {"intent_tags": ["analysis"]},
                    "capability": "routed",
                }
            ]
        )
    with pytest.raises(SpawnRuleValidationError, match="unsupported fields"):
        parse_spawn_rules(
            [
                {
                    **_rule(
                        "unknown-field",
                        priority=1,
                        tags=["analysis"],
                        capability="routed",
                    ),
                    "expression": "task contains secret",
                }
            ]
        )
    with pytest.raises(SpawnRuleValidationError, match="duplicate spawn rule name"):
        parse_spawn_rules(
            [
                _rule("same", priority=1, tags=["analysis"], capability="routed"),
                _rule("same", priority=2, tags=["research"], capability="routed"),
            ]
        )

    rules = parse_spawn_rules(
        [
            _rule("generic", priority=10, tags=["analysis"], capability="fallback"),
            _rule(
                "specific",
                priority=20,
                tags=["analysis", "research"],
                capability="routed",
            ),
        ]
    )
    assert select_spawn_rule(rules, ["research", "analysis"]).name == "specific"

    tied = parse_spawn_rules(
        [
            _rule("alpha", priority=20, tags=["analysis"], capability="fallback"),
            _rule("beta", priority=20, tags=["research"], capability="routed"),
        ]
    )
    with pytest.raises(SpawnRuleMatchError, match="tie at priority 20"):
        select_spawn_rule(tied, ["analysis", "research"])


@pytest.mark.invariant("SEC-194")
async def test_worker_inventory_and_simulator_use_effective_rules_without_executing() -> None:
    kernel = await _kernel()
    rules = parse_spawn_rules(
        [
            _rule(
                "analysis-route",
                priority=50,
                tags=["analysis"],
                capability="routed",
            ),
            _rule(
                "research-route",
                priority=50,
                tags=["research"],
                capability="revised",
            ),
        ]
    )
    client = TestClient(create_app(kernel, platform={"spawn_rules": rules}))
    headers = {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": "org-admin",
    }

    inventory = client.get("/v1/spawn-rules", headers=headers)
    assert inventory.status_code == 200
    policy = inventory.json()["policy"]
    assert policy["state"] == "conflicted"
    assert policy["source"] == "process_start_manifest"
    assert [row["id"] for row in policy["rules"]] == [
        "analysis-route",
        "research-route",
    ]
    assert policy["conflicts"] == [
        {
            "priority": 50,
            "rules": ["analysis-route", "research-route"],
            "example_intent_tags": ["analysis", "research"],
        }
    ]
    assert policy["execution_input"] == "server_trusted_classification_only"

    matched = client.post(
        "/v1/spawn-rules/simulate",
        json={"intent_tags": ["analysis"]},
        headers=headers,
    )
    assert matched.json()["status"] == "matched"
    assert matched.json()["selection"]["id"] == "analysis-route"
    assert matched.json()["input_trust"] == "untrusted_preview_only"
    conflict = client.post(
        "/v1/spawn-rules/simulate",
        json={"intent_tags": ["analysis", "research"]},
        headers=headers,
    )
    assert conflict.json()["status"] == "conflict"
    assert kernel.events.snapshot(T, "parent-run") == []
    assert client.get(
        "/v1/spawn-rules",
        headers={**headers, "x-boltrig-role": "member"},
    ).status_code == 403


@pytest.mark.invariant("SEC-194")
async def test_selected_rule_is_consumed_once_and_receipted_without_widening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = await _kernel()
    rules = parse_spawn_rules(
        [
            _rule(
                "research-route",
                priority=50,
                tags=["analysis", "research"],
                capability="routed",
                skills=["integration/rule-added"],
                max_depth=2,
            )
        ]
    )
    spawner = build_spawner(kernel, spawn_rules=rules)
    reads = 0
    original_list = kernel.store.list_config_revisions

    async def counted_list(*args: Any, **kwargs: Any):
        nonlocal reads
        reads += 1
        return await original_list(*args, **kwargs)

    monkeypatch.setattr(kernel.store, "list_config_revisions", counted_list)
    captured: dict[str, Any] = {}
    published: list[tuple[str, dict[str, Any]]] = []
    original_publish = kernel.events.publish

    def capture_publish(
        tenant_id: str, stream_id: str, event: dict[str, Any]
    ) -> None:
        published.append((stream_id, event))
        original_publish(tenant_id, stream_id, event)

    monkeypatch.setattr(kernel.events, "publish", capture_publish)

    class _Runtime:
        async def run(
            self, prompt: str, context: InvocationContext, *, tools: list[str]
        ) -> AgentResult:
            captured.update(prompt=prompt, context=context, tools=tools)
            return AgentResult.succeeded({"answer": "ok"}, summary="done")

    async def runtime_for(*args: Any, **kwargs: Any) -> _Runtime:
        return _Runtime()

    monkeypatch.setattr(spawner, "_runtime_for", runtime_for)
    result = await spawner.spawn(
        T,
        "investigate",
        ["analysis/requested"],
        {"intent_tags": ["research", "analysis"]},
        _context(),
    )

    expected_receipt = {
        "id": "research-route",
        "priority": 50,
        "matched_intent_tags": ["analysis", "research"],
        "capability": "routed",
        "skills_added": ["integration/rule-added"],
        "max_depth": 2,
    }
    assert reads == 1
    assert result["agent_type"] == "routed"
    assert result["spawn_rule"] == expected_receipt
    assert result["effective_grants"] == ["ticket.read"]
    assert captured["tools"] == ["ticket.read"]
    assert captured["context"].skills_loaded == (
        "analysis/requested",
        "integration/rule-added",
    )
    assert captured["context"].extra["boltrig_spawn_rule"] == expected_receipt
    assert "caller-forgery" not in repr(captured["context"].extra)

    events = await kernel.store.audit_query(T, run_id=result["run_id"])
    assert events[-1].skills_loaded == [
        "analysis/requested",
        "integration/rule-added",
    ]
    assert events[-1].detail["spawn_rule"] == expected_receipt
    opened = [
        event
        for stream_id, event in published
        if stream_id == "parent-run" and event.get("type") == "subagent"
    ]
    assert opened[0]["spawn_rule"] == expected_receipt


@pytest.mark.invariant("SEC-194")
async def test_rule_ties_conflicting_pins_stale_targets_and_depth_fail_closed() -> None:
    kernel = await _kernel()
    ties = parse_spawn_rules(
        [
            _rule("alpha", priority=10, tags=["analysis"], capability="routed"),
            _rule("beta", priority=10, tags=["research"], capability="revised"),
        ]
    )
    with pytest.raises(SpawnRulePolicyInvalid, match="tie at priority 10"):
        await build_spawner(kernel, spawn_rules=ties).spawn(
            T,
            "task",
            [],
            {"intent_tags": ["analysis", "research"]},
            _context(),
        )

    routed = parse_spawn_rules(
        [_rule("route", priority=10, tags=["analysis"], capability="routed")]
    )
    with pytest.raises(SpawnRulePolicyInvalid, match="requested capability"):
        await build_spawner(kernel, spawn_rules=routed).spawn(
            T,
            "task",
            [],
            {"intent_tags": ["analysis"], "capability": "fallback"},
            _context(),
        )

    stale = parse_spawn_rules(
        [_rule("stale", priority=10, tags=["analysis"], capability="withdrawn")]
    )
    with pytest.raises(SpawnRulePolicyInvalid, match="unavailable or incompatible"):
        await build_spawner(kernel, spawn_rules=stale).spawn(
            T, "task", [], {"intent_tags": ["analysis"]}, _context()
        )

    shallow = parse_spawn_rules(
        [
            _rule(
                "shallow",
                priority=10,
                tags=["analysis"],
                capability="routed",
                max_depth=1,
            )
        ]
    )
    with pytest.raises(DepthExceeded, match="exceeds max_depth 1"):
        await build_spawner(kernel, spawn_rules=shallow).spawn(
            T,
            "task",
            [],
            {"intent_tags": ["analysis"]},
            _context(depth=1),
        )


@pytest.mark.invariant("SEC-194")
async def test_governed_revision_replaces_base_policy_and_invalid_edits_do_not_land(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = await _kernel()
    base_doc = [
        _rule("base", priority=10, tags=["analysis"], capability="routed")
    ]
    base = parse_spawn_rules(base_doc)
    admin = AdminConfig(
        kernel.store,
        tenant_id=T,
        doc={"spawn_rules": base_doc},
    )
    invalid = [
        {
            "name": "invalid",
            "match": {"intent_tags": ["analysis"]},
            "capability": "revised",
        }
    ]
    with pytest.raises(SpawnRuleValidationError):
        await admin.update_section("spawn_rules", invalid, "operator")
    assert await admin.history("spawn_rules") == []

    revised = [
        _rule(
            "live-revision",
            priority=80,
            tags=["analysis"],
            capability="revised",
        )
    ]
    await admin.update_section("spawn_rules", revised, "operator")
    assert len(await admin.history("spawn_rules")) == 1

    spawner = build_spawner(kernel, spawn_rules=base)

    class _Runtime:
        async def run(
            self, prompt: str, context: InvocationContext, *, tools: list[str]
        ) -> AgentResult:
            return AgentResult.succeeded({"answer": "ok"}, summary="done")

    async def runtime_for(*args: Any, **kwargs: Any) -> _Runtime:
        return _Runtime()

    monkeypatch.setattr(spawner, "_runtime_for", runtime_for)
    result = await spawner.spawn(
        T, "task", [], {"intent_tags": ["analysis"]}, _context()
    )
    assert result["agent_type"] == "revised"
    assert result["spawn_rule"]["id"] == "live-revision"

    # A corrupt/stale row cannot silently fall back to the manifest snapshot.
    from boltrig.models import ConfigRevision

    await kernel.store.add_config_revision(
        ConfigRevision(
            tenant_id=T,
            kind="manifest_section",
            ref="spawn_rules",
            version="corrupt",
            payload={"section": "spawn_rules", "value": invalid},
            actor="legacy-writer",
        )
    )
    with pytest.raises(SpawnRulePolicyInvalid, match="current spawn-rule policy is invalid"):
        await spawner.spawn(
            T, "task", [], {"intent_tags": ["analysis"]}, _context()
        )
