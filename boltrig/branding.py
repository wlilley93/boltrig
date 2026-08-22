"""What this deployment calls itself (SPEC: the Opbox Agents surface).

Boltrig ships two ways and they are the same build: alone, as the product in
its own right, and as the engine beneath a UI that provisions it. The name
follows the second case - where the Opbox addon is active the product presents
as **Opbox Agents**, and where it is not it presents as **Boltrig**.

WHY THIS IS DERIVED FROM THE ADDON AND NOT FROM A BUILD FLAG. Decision 0035
holds that deployment shape is expressed by what is provisioned rather than by
flags, and the estate has already paid for the other approach:
``NEXT_PUBLIC_USE_KERNEL_CHAT`` is baked at build time, no build path ever
passed it, and every shipped image silently ran the retired chat path. A name
compiled into a bundle fails the same way and is invisible until someone looks
at the screen. ``active_addons()`` is the same signal the harness, the adapter
id and the consequence hint already read, so the surface cannot disagree with
the runtime about which product it is.

THE MARK DOES NOT VARY. Both names carry the same wordmark face and the same
dashed-ring mark with a live core, and the core pulses on both. Only the word
changes, because only the word is what differs.
"""

from __future__ import annotations

from boltrig.addons import active_addons

BOLTRIG = "Boltrig"
OPBOX_AGENTS = "Opbox Agents"

# The addon whose presence renames the product. One name, spelled once: the
# adapter id, the harness and this all key off the same registered addon, so a
# rename there cannot leave the branding pointing at a name nobody activates.
_OPBOX_ADDON = "opbox"


def product_name(addons: tuple | None = None) -> str:
    """The name this deployment presents under."""
    active = active_addons() if addons is None else addons
    return OPBOX_AGENTS if any(a.name == _OPBOX_ADDON for a in active) else BOLTRIG


def product_identity(addons: tuple | None = None) -> dict[str, object]:
    """The whole of what a surface needs to brand itself.

    ``pulse`` is unconditionally true and is reported rather than assumed, so
    the client has one source for it instead of a second copy of the policy.
    A person's motion preference still wins in CSS; this is the product's
    intent, not an override of the reader's.
    """
    return {"product_name": product_name(addons), "pulse": True}
