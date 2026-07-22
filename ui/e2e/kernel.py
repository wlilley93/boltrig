"""Boot the real kernel for the UI e2e smoke ([2026] VJS-COUNTY 2).

Hermetic by construction: no DATABASE_URL means the in-memory store; no
production signal means create_app defaults to the header-trusting dev
principal resolver (the same auth the UI dev flow uses, x-boltrig-* headers
from ui/src/identity.ts); and the ChatService is built with NO turn executor,
so a chat turn streams the deterministic "(no runtime configured)" reply
(boltrig/fleet/chat.py). No model keys, no credentials, no egress.

Launched by playwright.config.ts (webServer) with cwd = ui/, so the repo root
is two levels up; it is put at the front of sys.path so this worktree's
boltrig package wins over any editable install pointing elsewhere.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import uvicorn
from fastapi import Request

from boltrig.api.bootstrap import build_kernel_async, wire_hitl_resume
from boltrig.fleet import LocalDurableExecutor
from boltrig.fleet.hatchet_app import register_boltrig_tasks
from boltrig.fleet.chat import ChatService
from boltrig.kernel.app import create_app
from boltrig.models import HITLType, Urgency, WorkflowDefinition, WorkflowSource
from boltrig.workflows import WorkflowLibrary


def _chat_factory(kernel):
    # No turn executor: the contract under test is the degraded deterministic
    # reply, not a model turn (boltrig/fleet/chat.py::ChatService._drive).
    return ChatService(kernel.store, kernel.events, turn_executor=None)


async def _kernel_factory():
    """Wire the deterministic local workflow lane used by the canvas smoke."""
    kernel = await build_kernel_async()
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    wire_hitl_resume(kernel, executor=executor)
    workflows = WorkflowLibrary(kernel.store, executor=executor, kernel=kernel)
    control = kernel.loader.peek("default", "control")
    if control is None:
        raise RuntimeError("e2e control adapter is not registered")
    control.set_workflows(workflows)
    return kernel


app = create_app(kernel_factory=_kernel_factory, chat_factory=_chat_factory)


@app.post("/v1/_e2e/seed-hitl")
async def seed_hitl(request: Request) -> dict[str, str]:
    """Create one credential-free approval for the browser confirmation flow."""
    req = await request.app.state.kernel.hitl.create(
        tenant_id="default",
        run_id="e2e-approval-run",
        type=HITLType.APPROVAL,
        urgency=Urgency.BLOCKING,
        question="Approve the e2e outbound update?",
        context="The e2e requester wants to perform ticket.update.",
        options=["approve", "reject"],
        assignee="dev",
        verb="ticket.update",
        requested_by="e2e-requester",
        request_fingerprint="e2e-approval-fingerprint",
    )
    return {"id": req.id}


@app.post("/v1/_e2e/seed-workflow")
async def seed_workflow(request: Request) -> dict[str, str]:
    """Create a deterministic two-step graph for the live-canvas smoke."""
    workflow = WorkflowDefinition(
        id="e2e-live-workflow",
        tenant_id="default",
        version="1.0.0",
        source=WorkflowSource.PRECREATED,
        definition={
            "steps": [
                {
                    "id": "prepare",
                    "parents": [],
                    "action": "ticket.create",
                    "params": {"title": "Prepare release"},
                },
                {
                    "id": "publish",
                    "parents": ["prepare"],
                    "action": "ticket.create",
                    "params": {"title": "Publish release"},
                },
            ]
        },
        intent_tags=["e2e"],
    )
    await request.app.state.kernel.store.upsert_workflow(workflow)
    return {"id": workflow.id}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("BOLTRIG_E2E_KERNEL_PORT", "8791")),
        log_level="warning",
    )
