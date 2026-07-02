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

from boltrig.api.bootstrap import build_kernel_async
from boltrig.fleet.chat import ChatService
from boltrig.kernel.app import create_app


def _chat_factory(kernel):
    # No turn executor: the contract under test is the degraded deterministic
    # reply, not a model turn (boltrig/fleet/chat.py::ChatService._drive).
    return ChatService(kernel.store, kernel.events, turn_executor=None)


app = create_app(kernel_factory=build_kernel_async, chat_factory=_chat_factory)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("BOLTRIG_E2E_KERNEL_PORT", "8791")),
        log_level="warning",
    )
