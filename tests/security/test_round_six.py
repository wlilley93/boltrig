"""Round Six - continuity, model gateway, sandbox egress (SEC-46..49).

Written when the Pi lane was the only agentic runtime. Pi is retired
([2026] VJS-PC 20 L1) and every guarantee below outlived it, because none of them
was ever about Pi. These bind them:
  SEC-46  conversation continuity is deterministic + append-only (prefix stable)
          and adds no authority (it composes only persisted text).
  SEC-47  the model gateway binds per CONVERSATION (not run), pins a conversation
          to one model across turns, and never re-routes sensitive data.
  SEC-48  a sandboxed sidecar's network egress is ENFORCED by the deploy manifests
          (sandbox-only; internal in the secure overlay), not merely documented.
  SEC-49  continuity is scope-safe: only the caller's own tenant/conversation
          history is ever composed into a prompt.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
import yaml

from boltrig.fleet.chat import ChatService, build_turn_executor
from boltrig.fleet.continuity import compose_turn_task, render_transcript
from boltrig.fleet.model_gateway import ModelGateway, apply_gateway
from boltrig.kernel.events import EventRelay
from boltrig.models import (
    ConversationMessage,
    GrantSet,
    MessageRole,
    ModelEndpoint,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"
_REPO = Path(__file__).resolve().parents[2]


class _ComposeLoader(yaml.SafeLoader):
    """PyYAML loader that understands Docker Compose merge-control tags."""


def _construct_compose_override(loader: yaml.Loader, node: yaml.Node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_ComposeLoader.add_constructor("!override", _construct_compose_override)


def _compose_yaml(path: Path) -> dict:
    return yaml.load(path.read_text(), Loader=_ComposeLoader)


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


@pytest.mark.invariant("FR-GW-01")
def test_bifrost_is_wired_into_the_stack():
    # The model gateway (Bifrost) is declared in the stack so activation is one
    # genesis/dev bring-up + provider keys, and the documented URL matches the
    # service. Pins the deploy wiring so the seam's target cannot silently drift.
    compose = _compose_yaml(_REPO / "docker-compose.yml")
    bifrost = compose["services"].get("bifrost")
    assert bifrost is not None, "no bifrost service in docker-compose.yml"
    # OpenAI-compatible inside compose on :8080; host admin/API defaults to 8081
    # so it does not collide with the console. A runtime calls
    # {base_url}/chat/completions, so the documented gateway URL includes /v1.
    assert "127.0.0.1:${BIFROST_PORT:-8081}:8080" in bifrost.get("ports", [])
    assert "gateway" in (bifrost.get("profiles") or [])  # opt-in, default stack lean
    assert {"default", "sandbox"} <= set(bifrost.get("networks") or [])
    env = (_REPO / ".env.example").read_text()
    assert "BOLTRIG_MODEL_GATEWAY_URL=http://bifrost:8080/v1" in env
    assert "--profile gateway" in (_REPO / "genesis.sh").read_text()
    assert "--profile gateway" in (_REPO / "scripts" / "dev-up.sh").read_text()


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
# SEC-48  the deploy manifests ENFORCE sandbox egress (not just documented)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-48")
def test_sandbox_network_egress_is_enforced_in_manifests():
    """The sandbox network's isolation, asserted against every service on it.

    This was ``test_pi_sidecar_egress_is_enforced_in_manifests`` and named for a
    service that no longer exists ([2026] VJS-PC 20 L1). The property was never Pi's:
    it is the only assertion anywhere that the sandbox network is INTERNAL in the
    secure overlay and that postgres is unreachable from it. Deleting it with its
    former subject would have dropped that silently, which is why the re-point is a
    rename and a widening rather than a deletion.

    Widened deliberately: it now checks EVERY sandbox-only service rather than one
    named one, so the next sidecar to join the network is covered on the day it is
    added instead of whenever someone remembers to extend this list.
    """
    base = _compose_yaml(_REPO / "docker-compose.yml")
    services = base["services"]

    sandboxed = {
        name: set(svc.get("networks") or ["default"])
        for name, svc in services.items()
        if "sandbox" in (svc.get("networks") or [])
    }
    # Services confined to the sandbox reach the kernel MCP face and the sandbox
    # model peers, and nothing on the default app network.
    confined = {name for name, nets in sandboxed.items() if nets == {"sandbox"}}
    assert confined, "no service is confined to the sandbox network"
    assert "channel-gateway" in confined, sorted(sandboxed)

    # postgres is NOT on sandbox -> nothing confined there has a path to the database.
    pg_nets = set(services["postgres"].get("networks") or ["default"])
    assert "sandbox" not in pg_nets
    # the kernel bridges both so MCP is reachable from the sandbox.
    assert "sandbox" in set(services["kernel"].get("networks") or [])
    # model endpoints/proxies a sandboxed service may call are explicit sandbox peers.
    assert "sandbox" in set(services["bifrost"].get("networks") or [])
    assert "sandbox" in set(services["local-model"].get("networks") or [])
    # the sandbox network is actually declared at the top level (a real network).
    assert "sandbox" in base["networks"]

    # The secure overlay makes the sandbox internal: true => no arbitrary egress.
    secure = _compose_yaml(_REPO / "deploy" / "compose.secure.yml")
    assert secure["networks"]["sandbox"]["internal"] is True
    for service in ("kernel", "ui", "hatchet-engine", "hatchet-dashboard", "bifrost"):
        assert secure["services"][service].get("ports") == []


# --------------------------------------------------------------------------- #
# SEC-49  continuity is scope-safe: only the caller's own conversation composes
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-49")
async def test_continuity_only_composes_the_callers_own_conversation():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    captured: list[str] = []

    async def spawn(tenant_id, task, skills, prefer, context, *,
                    partial_on_budget=True, grant_ceiling=None):
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
