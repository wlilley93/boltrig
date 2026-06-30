"""Round Six - Pi runtime: continuity, model gateway, egress (SEC-46..49).

The pi lane is the only agentic runtime. These bind the new guarantees:
  SEC-46  conversation continuity is deterministic + append-only (prefix stable)
          and adds no authority (it composes only persisted text).
  SEC-47  the model gateway binds per CONVERSATION (not run), pins a conversation
          to one model across turns, and never re-routes sensitive data.
  SEC-48  the Pi sidecar's network egress is ENFORCED by the deploy manifests
          (sandbox-only; internal in the secure overlay), not merely documented.
  SEC-49  continuity is scope-safe: only the caller's own tenant/conversation
          history is ever composed into a prompt.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
import yaml

from nankle.fleet.chat import ChatService, build_turn_executor
from nankle.fleet.continuity import compose_turn_task, render_transcript
from nankle.fleet.model_gateway import ModelGateway, apply_gateway
from nankle.kernel.events import EventRelay
from nankle.models import (
    ConversationMessage,
    GrantSet,
    MessageRole,
    ModelEndpoint,
    TenantPermissions,
)
from nankle.store import InMemoryStore

T = "acme"
_REPO = Path(__file__).resolve().parents[2]


def _msg(role: MessageRole, content: str) -> ConversationMessage:
    return ConversationMessage(id=content, conversation_id="c", tenant_id=T, role=role, content=content)


# --------------------------------------------------------------------------- #
# SEC-46  continuity is deterministic + append-only (prefix stable)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-46")
def test_continuity_is_deterministic_and_append_only():
    turn1 = [_msg(MessageRole.USER, "hello")]
    after_reply = turn1 + [_msg(MessageRole.ASSISTANT, "hi there")]
    turn2 = after_reply + [_msg(MessageRole.USER, "follow up")]

    r1 = render_transcript(turn1)
    r2 = render_transcript(turn2)

    # deterministic: identical input renders identically
    assert render_transcript(turn1) == r1
    # append-only: an earlier turn's render is a prefix of a later turn's render.
    # This is the property the upstream gateway cache relies on (gap 3.2).
    assert r2.startswith(r1)
    assert "hello" in r1 and "follow up" in r2 and "follow up" not in r1
    # no history => exactly the bare current message (pre-continuity behaviour)
    assert compose_turn_task([], "just this") == "just this"
    # the composed task is only the message text - no grants/tokens/credentials
    assert "grant" not in r2.lower() and "token" not in r2.lower()


# --------------------------------------------------------------------------- #
# SEC-47  the gateway binds per conversation, pins one model, skips sensitive
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-47")
def test_gateway_binds_per_conversation_not_run():
    gw = ModelGateway(ttl_seconds=900)
    base = ModelEndpoint(id="ep", tenant_id=T, kind="openai", model="model-A", base_url="https://provider")

    # Turn 1 of conversation c1 binds model-A and routes through the gateway.
    ep1 = apply_gateway(base, gateway_url="http://gw:9000", binding=gw,
                        conversation_id="c1", sensitive=False)
    assert ep1.base_url == "http://gw:9000" and ep1.model == "model-A"

    # Turn 2 (a NEW run, would otherwise resolve model-B) stays pinned to model-A
    # because the binding key is the conversation, not the run.
    other = ModelEndpoint(id="ep", tenant_id=T, kind="openai", model="model-B", base_url="https://provider")
    ep2 = apply_gateway(other, gateway_url="http://gw:9000", binding=gw,
                        conversation_id="c1", sensitive=False)
    assert ep2.model == "model-A"  # pinned across turns -> warm cache

    # A different conversation gets its own binding.
    ep_c2 = apply_gateway(other, gateway_url="http://gw:9000", binding=gw,
                          conversation_id="c2", sensitive=False)
    assert ep_c2.model == "model-B"


@pytest.mark.security
@pytest.mark.invariant("SEC-47")
def test_gateway_never_reroutes_sensitive_and_is_inert_when_unset():
    gw = ModelGateway(ttl_seconds=900)
    local = ModelEndpoint(id="loc", tenant_id=T, kind="vllm", model="m", base_url="http://local:8000",
                          data_class="sensitive")
    # Sensitive data must reach its local endpoint directly - never the gateway.
    routed = apply_gateway(local, gateway_url="http://gw:9000", binding=gw,
                           conversation_id="c1", sensitive=True)
    assert routed is local  # unchanged, residency preserved (SEC-43)

    # No gateway configured => the seam is inert (behaviour identical to before).
    std = ModelEndpoint(id="ep", tenant_id=T, kind="openai", model="m", base_url="https://provider")
    assert apply_gateway(std, gateway_url=None, binding=gw,
                         conversation_id="c1", sensitive=False) is std


# --------------------------------------------------------------------------- #
# SEC-48  the deploy manifests ENFORCE sidecar egress (not just documented)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-48")
def test_pi_sidecar_egress_is_enforced_in_manifests():
    base = yaml.safe_load((_REPO / "docker-compose.yml").read_text())
    services = base["services"]
    sidecar_nets = set(services["pi-sidecar"].get("networks") or [])

    # The sidecar sits on the sandbox network ONLY - not the default app network,
    # so it cannot reach postgres/redis/the rest, only the kernel MCP face.
    assert sidecar_nets == {"sandbox"}, sidecar_nets
    # postgres is NOT on sandbox -> the sidecar has no path to the database.
    pg_nets = set(services["postgres"].get("networks") or ["default"])
    assert "sandbox" not in pg_nets
    # the kernel bridges both so MCP is reachable from the sandbox.
    assert "sandbox" in set(services["kernel"].get("networks") or [])
    # the sandbox network is actually declared at the top level (a real network).
    assert "sandbox" in base["networks"]

    # The secure overlay makes the sandbox internal: true => no arbitrary egress.
    secure = yaml.safe_load((_REPO / "deploy" / "compose.secure.yml").read_text())
    assert secure["networks"]["sandbox"]["internal"] is True


# --------------------------------------------------------------------------- #
# SEC-49  continuity is scope-safe: only the caller's own conversation composes
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-49")
async def test_continuity_only_composes_the_callers_own_conversation():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    captured: list[str] = []

    async def spawn(tenant_id, task, skills, prefer, context, *, partial_on_budget=True):
        captured.append(task)
        return {"summary": "ok"}

    spawner = types.SimpleNamespace(spawn=spawn)
    kernel = types.SimpleNamespace(store=store)
    chat = ChatService(store, EventRelay(),
                       turn_executor=build_turn_executor(kernel, spawner, continuity=True))

    async def turn(user, message, conv_id=None):
        cid = conv_id
        async for e in chat.handle_turn(tenant_id=T, user_id=user, role="engineer",
                                        message=message, conversation_id=cid):
            if e["type"] == "message_start":
                cid = e["conversation_id"]
        return cid

    # alice has her own conversation; bob has a separate one with secret content.
    a = await turn("alice", "alice first")
    await turn("bob", "BOB SECRET")
    await turn("alice", "alice second", conv_id=a)

    # alice's continuing turn composed HER history and never bob's conversation.
    last = captured[-1]
    assert "alice first" in last and "alice second" in last
    assert "BOB SECRET" not in last
