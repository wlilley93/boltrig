"""The Opbox addon: everything boltrig knows about Opbox, in one place.

Active only where ``BOLTRIG_ADDONS`` names ``opbox`` - i.e. on a tenant that
provisioned a boltrig from an Opbox. A boltrig shipping alone loads this module
(so the name resolves) and activates none of it.

The three contributions, and the measured reason each exists:

1. ``adapter_id`` - the consumed-server noun whose session bearer a chat turn
   seals per-run. It had been ``os.environ.get("BOLTRIG_OBO_ADAPTER_ID", "opbox")``
   duplicated in ``fleet/chat.py`` and ``fleet/spawn.py``: two copies, both
   defaulting a generic boltrig to an Opbox-shaped name.

2. ``consequence_hint`` - Opbox's kernel MCP door declares no ``consequence``
   field. Its ``tools/list`` projection (opbox-kernel
   ``kernel/src/mcp/tools.rs::verb_to_tool``) emits name/description/inputSchema
   only, carrying the risk class inside the description metadata run as
   ``riskClass=READ|WRITE|SENSITIVE|MONEY|DESTRUCTIVE`` (uppercase, from
   ``RiskClass::as_str``). READ maps low, the rest high (FR-MCP-03). That regex
   lived in ``adapters/mcp_consumer``, a module every boltrig ships.

3. ``harness`` - the Opbox-specific tool guidance. Every verb named below was
   verified present in the live Classical Visas registry on 2026-07-28 before
   being written here; ``find_tools`` and ``expand_tools`` were NOT registered
   there and are deliberately absent. A harness that names a tool the tenant does
   not have teaches the model to call something that will only ever be rejected.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from boltrig.models.registry import Consequence

from . import Addon, AddonRequirement, register

_RISK = re.compile(r"\briskClass=(READ|WRITE|SENSITIVE|MONEY|DESTRUCTIVE)\b")
_RISK_HIGH = frozenset({"WRITE", "SENSITIVE", "MONEY", "DESTRUCTIVE"})

ADAPTER_ID = "opbox"
VERSION = "1.0.0"


def risk_class_hint(tool: Mapping[str, object]) -> str | None:
    """Opbox risk_class -> consequence: the structured field, else the description token."""

    value = tool.get("riskClass") or tool.get("risk_class")
    if not (isinstance(value, str) and value):
        match = _RISK.search(str(tool.get("description") or ""))
        value = match.group(1) if match else ""
    risk = value.upper()
    if risk == "READ":
        return Consequence.LOW.value
    return Consequence.HIGH.value if risk in _RISK_HIGH else None


# Grounded in what actually went wrong on the client's system, not in what an
# integration guide would say. The by-number rule exists because the model called
# ``opbox.get_matter`` with ``{"number": "MAT-0002"}`` fifteen times running while
# ``opbox.get_matter_by_number`` sat in the same offered set.
HARNESS = (
    "Opbox tools reach the firm's own records: matters, files, emails, entities "
    "and people. Two rules about identifiers, because getting them wrong is the "
    "most common way these calls fail. A DISPLAY number (like MAT-0002) is not an "
    "internal id: pass it to the tool whose name ends in _by_number, or search for "
    "the record first and read the id off the result. Never invent an id, and never "
    "pass a display number to a tool that asks for an id. "
    "Your visible tool list may be a ranked subset of what you are authorised to "
    "call. If the tool you need is not listed, call opbox.describe_tools to look it "
    "up by name before concluding that you cannot do the work."
)


ADDON = register(
    Addon(
        name="opbox",
        version=VERSION,
        harness=HARNESS,
        adapter_id=ADAPTER_ID,
        consequence_hint=risk_class_hint,
        requirements=(
            AddonRequirement(
                id="opbox-adapter",
                kind="adapter",
                ref=ADAPTER_ID,
            ),
        ),
    )
)


__all__ = ["ADAPTER_ID", "ADDON", "HARNESS", "VERSION", "risk_class_hint"]
