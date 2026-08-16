"""The committed registered catalogue stays broad without widening any run.

This is a breadth floor, not a blanket grant. The MCP face still intersects the
tenant ceiling and the run's selected grants, and every call still traverses the
dispatcher. The point is to stop a refactor or packaging change from silently
shipping a tiny agent platform while a large external benchmark appears richer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boltrig.api.bootstrap import _seed_default
from boltrig.fleet.infrastructure.codex_kernel_tools_phase import MAX_KERNEL_TOOLS
from boltrig.kernel import Kernel
from boltrig.store import InMemoryStore

_REPO = Path(__file__).resolve().parents[2]
_SURFACE = _REPO / "tests" / "fixtures" / "registered-verb-surface.txt"
_REFERENCE_BREADTH_FLOOR = 40


def _rows() -> tuple[tuple[str, str, str], ...]:
    rows: list[tuple[str, str, str]] = []
    for raw in _SURFACE.read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        assert len(parts) == 3, f"malformed registered tool row: {raw!r}"
        rows.append((parts[0], parts[1], parts[2]))
    assert rows, "the registered tool surface cannot pass vacuously"
    return tuple(rows)


@pytest.mark.security
@pytest.mark.invariant("FR-MCP-04")
async def test_offline_default_kernel_boot_exceeds_the_reference_tool_count() -> None:
    store = InMemoryStore()
    await _seed_default(Kernel(store))
    names = {verb.id for verb in await store.list_all_verbs("default")}

    assert len(names) >= _REFERENCE_BREADTH_FLOOR
    assert {
        "skill.search",
        "skill.describe",
        "skill.load",
        "web.fetch",
        "work.list",
        "work.get",
    } <= names


@pytest.mark.security
@pytest.mark.invariant("FR-MCP-04")
def test_registered_catalogue_exceeds_the_broad_agent_tool_floor() -> None:
    rows = _rows()
    names = {verb for verb, _adapter, _runtime in rows}
    first_party_non_control = {
        verb
        for verb, _adapter, runtime in rows
        if runtime != "mcp" and not verb.startswith("control.")
    }

    assert len(names) >= _REFERENCE_BREADTH_FLOOR
    assert len(first_party_non_control) >= _REFERENCE_BREADTH_FLOOR
    assert MAX_KERNEL_TOOLS >= _REFERENCE_BREADTH_FLOOR

    required_capabilities = {
        "bounded device files": {
            "device.file.list",
            "device.file.read",
            "device.file.write",
        },
        "bounded device execution": {"device.command.run"},
        "browser and web": {
            "browser.tab.open",
            "browser.navigate",
            "browser.snapshot",
            "browser.inspect",
            "browser.click",
            "browser.type",
            "browser.scroll",
            "browser.tabs.list",
            "web.fetch",
        },
        "questions": {"chat.ask_user"},
        "skills": {"skill.search", "skill.load", "skill.describe"},
        "work lifecycle": {
            "control.work.create",
            "control.work.assign",
            "control.work.status",
        },
        "workflow automation": {
            "control.workflow.execute",
            "control.workflow.schedule",
            "control.workflow.trigger",
        },
        "memory": {"memory.remember", "memory.recall", "memory.forget"},
        "knowledge": {"knowledge.search", "knowledge.asset.get"},
        "communications": {"channel.send", "email.send"},
        "external MCP lifecycle": {
            "control.mcp_server.register",
            "control.mcp_server.probe",
            "control.mcp_server.activate",
        },
    }
    missing = {
        category: sorted(expected - names)
        for category, expected in required_capabilities.items()
        if not expected <= names
    }
    assert not missing, f"kernel tool capability families regressed: {missing}"


@pytest.mark.security
@pytest.mark.invariant("FR-MCP-04")
def test_catalogue_breadth_does_not_turn_into_a_blanket_run_grant() -> None:
    """The benchmark is capacity: shipped skills must remain explicit selections."""

    import yaml

    skills = sorted((_REPO / "libraries" / "skills").rglob("*.yaml"))
    assert len(skills) >= 5
    offences: list[str] = []
    for path in skills:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        grants = doc.get("tool_grants") or []
        if "*" in grants:
            offences.append(str(path.relative_to(_REPO)))
    assert not offences, f"shipped skills use a blanket tool grant: {offences}"

    decomposition = yaml.safe_load(
        (_REPO / "libraries/skills/analysis/base-decomposition.yaml").read_text(encoding="utf-8")
    )
    assert {"work.get", "work.list"} <= set(decomposition["tool_grants"])
