"""The governed "ask the user a question" built-in verb (US-CHAT-12).

A turn's agent can call ``chat.ask_user`` to put a clarifying question to the
human and pause for the answer. It is a first-class governed verb, not a parallel
pause mechanism: it runs through the ONE dispatch chokepoint under the caller's
grant ceiling (schema-validated + grant-checked like any verb), creates a HITL
request of kind ``QUESTION``, emits a ``question`` run event, and raises
``PendingHuman`` so the run parks ``AWAITING_HUMAN`` on the EXISTING HITL
machinery. The answer returns through the owner-only fail-closed
``/v1/hitl/{id}/answer`` route (enveloped with ``wrap_untrusted``) and resumes the
run through the ordinary HITL resume wiring - it does not fork a new pause path.

The verb is seeded per tenant by ``apply_manifest`` so discovery and the grant
check apply to it uniformly. Its consequence is LOW: the pause IS its effect, so
it is never routed through the HIGH-consequence approval gate (an approval clears
a gated action; a question only feeds an answer back - the two must never be
interchangeable, H1 / SEC-14).

SEC-181 secure input: with ``secure: true`` + a ``purpose`` label the QUESTION is
marked secure (a flag consumers can render a secure-input affordance from); the
ANSWER never enters the run - the answer route seals it through the credential
seam as a run- and purpose-scoped reference and records the enveloped REFERENCE
as the decision, and verb params carrying that reference are resolved to the
material inside the kernel at the dispatch credential stage only.
"""

from __future__ import annotations

from boltrig.models import (
    Consequence,
    Noun,
    TargetType,
    Verb,
    VerbBinding,
)
from boltrig.store import Store

QUESTIONS_NOUN = "chat"
QUESTIONS_VERB = "chat.ask_user"

# Bounded, value-free schema: a prompt the agent authors plus optional choices.
# ``secure`` + ``purpose`` ask for a value the AGENT never sees (SEC-181): the
# prompt stays ordinary text, but the ANSWER is sealed inside the kernel as a
# run- and purpose-scoped credential reference and only the reference resumes
# the run (see kernel/credentials.py). ``purpose`` is a short bounded label
# (no ``:``/``/`` so it is safe inside the reference shape); it is required with
# ``secure`` and meaningless without it, so the pairing fails schema validation.
QUESTIONS_INPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string", "minLength": 1, "maxLength": 2000},
        "choices": {
            "type": "array",
            "items": {"type": "string", "maxLength": 200},
            "maxItems": 12,
        },
        "secure": {"type": "boolean"},
        "purpose": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[a-z0-9][a-z0-9-]*$",
        },
    },
    "required": ["prompt"],
    "additionalProperties": False,
    "allOf": [
        {  # secure requires a purpose label
            "if": {"properties": {"secure": {"const": True}}, "required": ["secure"]},
            "then": {"required": ["purpose"]},
        },
        {  # a purpose is only meaningful on a secure question
            "if": {"required": ["purpose"]},
            "then": {"properties": {"secure": {"const": True}}, "required": ["secure"]},
        },
    ],
}

# The verb pauses (raises PendingHuman) rather than returning a value, so its
# output schema is empty (no output is ever validated on the pause path).
QUESTIONS_OUTPUT_SCHEMA: dict = {}


async def register_questions_verb(store: Store, tenant_id: str) -> None:
    """Seed the governed ``chat.ask_user`` verb for a tenant (idempotent).

    Registers the noun, the verb (LOW consequence, the pause schema) and a binding
    the chokepoint recognises as the native questions handler. Called from
    ``apply_manifest`` so every seeded tenant carries it; safe to call more than
    once (upserts)."""
    if await store.get_noun(tenant_id, QUESTIONS_NOUN) is None:
        await store.upsert_noun(Noun(id=QUESTIONS_NOUN, tenant_id=tenant_id))
    await store.upsert_verb(
        Verb(
            id=QUESTIONS_VERB,
            tenant_id=tenant_id,
            noun_id=QUESTIONS_NOUN,
            input_schema=QUESTIONS_INPUT_SCHEMA,
            output_schema=QUESTIONS_OUTPUT_SCHEMA,
            description=(
                "Ask one necessary clarifying question, then pause for its answer. "
                "Use this only when the missing choice materially changes the safe "
                "result. When choices are useful, put the recommended one first, "
                "label it '(Recommended)', and keep the options mutually exclusive. "
                "Use secure input with a bounded purpose for a secret the agent must "
                "never receive."
            ),
            consequence=Consequence.LOW,
        )
    )
    # A recognised native binding: the chokepoint intercepts this verb before any
    # adapter/agent dispatch (the pause is handled in-kernel), so the target_ref is
    # a label for the audit row, never a loadable adapter.
    await store.upsert_binding(
        VerbBinding(
            verb_id=QUESTIONS_VERB,
            tenant_id=tenant_id,
            target_type=TargetType.AGENT,
            target_ref="native:questions",
        )
    )
