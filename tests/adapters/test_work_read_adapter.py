from __future__ import annotations

import pytest

from boltrig.kernel.work_read_adapter import build_work_read_adapter
from boltrig.api.agent_tool_bootstrap import register_agent_support
from boltrig.kernel import Kernel
from boltrig.models import GrantSet, InvocationContext, WorkItem, WorkStatus
from boltrig.store import InMemoryStore

T = "tenant-a"


def _context(*, workspace: str = "workspace-a", departments: list[str] | None = None):
    scope = {"all": True} if departments is None else {"departments": departments}
    return InvocationContext(
        tenant_id=T,
        workspace_id=workspace,
        actor="agent-a",
        grants=GrantSet.of(["work.list", "work.get"]),
        extra={"principal_role": "member", "principal_scope": scope},
    )


async def _seed(store: InMemoryStore) -> None:
    for item in (
        WorkItem(
            "a",
            T,
            "internal",
            "Visible legal work",
            1.0,
            True,
            owner_member="legal",
            workspace_id="workspace-a",
        ),
        WorkItem(
            "b",
            T,
            "internal",
            "Hidden finance work",
            1.0,
            True,
            owner_member="finance",
            workspace_id="workspace-a",
        ),
        WorkItem(
            "c",
            T,
            "internal",
            "Other workspace",
            1.0,
            True,
            owner_member="legal",
            workspace_id="workspace-b",
        ),
        WorkItem(
            "d",
            T,
            "internal",
            "Completed",
            1.0,
            True,
            status=WorkStatus.DONE,
            owner_member="legal",
            workspace_id="workspace-a",
            raw={"secret": "not projected"},
            result={"private": True},
        ),
    ):
        await store.create_work_item(item)


@pytest.mark.invariant("FR-MCP-04")
async def test_work_reads_are_workspace_department_scoped_and_bounded() -> None:
    store = InMemoryStore()
    await _seed(store)
    adapter = build_work_read_adapter(store)
    context = _context(departments=["legal"])

    listed = await adapter.execute("work.list", {"limit": 10}, None, context)
    assert listed.ok
    assert [item["id"] for item in listed.output["items"]] == ["a", "d"]
    assert all("raw" not in item and "result" not in item for item in listed.output["items"])
    assert listed.output["next_cursor"] is None

    done = await adapter.execute("work.list", {"status": "done"}, None, context)
    assert [item["id"] for item in done.output["items"]] == ["d"]

    hidden = await adapter.execute("work.get", {"item_id": "b"}, None, context)
    cross_workspace = await adapter.execute("work.get", {"item_id": "c"}, None, context)
    assert not hidden.ok and hidden.error.error_class.value == "not_found"
    assert not cross_workspace.ok and cross_workspace.error.error_class.value == "not_found"


@pytest.mark.invariant("FR-MCP-04")
async def test_work_reader_declares_agent_facing_read_tools() -> None:
    store = InMemoryStore()
    await register_agent_support(Kernel(store), T)

    verbs = await store.list_verbs(T, "work")
    assert {verb.id for verb in verbs} == {"work.get", "work.list"}
    assert all(verb.consequence.value == "low" for verb in verbs)
    assert all(verb.input_schema.get("additionalProperties") is False for verb in verbs)
