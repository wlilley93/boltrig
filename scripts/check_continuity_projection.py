#!/usr/bin/env python3
"""D6 of [2026] VJS-CC-BOLTRIG-CONTINUITY-TOOL-WORK-001: the prompt boundary, machine-checked.

WHY A STRUCTURAL GATE AND NOT ONLY THE BEHAVIOURAL TESTS. The behavioural tests in
`tests/security/test_continuity_carries_text_only.py` assert what today's code renders. They
cannot assert what tomorrow's code is ALLOWED to read. A future edit that adds one key to the
rendered set, or imports the browser projection and leans on it, would need a test that
happens to seed exactly that field to go red - and the order's whole ratio is that the
allowlist is closed, not that the currently-seeded fields are excluded. That is the
difference between "these values did not appear" and "no other value CAN appear".

So this walks the AST of `boltrig/fleet/continuity.py` and fails on four things, each one a
sentence of the order turned into a check:

  1. the four frozensets do not equal, exactly, the sets the order fixed
     ("the permitted projection must be defined AT the continuity boundary");
  2. `chat_event_projection` is imported
     (forbidden: `importing_chat_event_projection_into_continuity_py`);
  3. any function other than `_tool_work_line` touches `message.events`
     ("one function, one allowlist");
  4. an event dict is subscripted or `.get()` with a string literal outside
     `_TOOL_WORK_READ_FIELDS` ("reading any frame type outside tool_call and tool_result").

WHAT IT DELIBERATELY DOES NOT CLAIM. It is a static check over one file. It cannot prove the
RENDERED string excludes a value that arrives through a variable, and it does not try: that
is what the canary assertions in the behavioural test are for. Two instruments, two
questions. Stating the boundary here rather than leaving it to be discovered, because an
undocumented limit on a gate reads as coverage the gate does not have.

Exit 0 clean, 1 on any violation. Wired into `make check`, whose target list is the one CI runs.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "boltrig" / "fleet" / "continuity.py"

# Fixed by the order's disposition. Changing a value here is changing the order, and the
# order is the thing that says what may reach a model. If a later ruling widens the
# allowlist, this table moves WITH the citation, in the same change.
EXPECTED: dict[str, set[str]] = {
    "_TOOL_WORK_FRAME_TYPES": {"tool_call", "tool_result"},
    "_TOOL_WORK_RENDERED_FIELDS": {"tool", "status"},
    "_TOOL_WORK_READ_FIELDS": {"type", "tool", "status", "call_id"},
    "_TOOL_WORK_STATUSES": {"ok", "error", "degraded", "pending_human"},
}
READER = "_tool_work_line"
EVENTS_ATTR = "events"
BANNED_IMPORT = "chat_event_projection"


def _literal_set(node: ast.AST) -> set[str] | None:
    """The set literal inside `frozenset({...})`, or None if it is not that shape."""
    if not isinstance(node, ast.Call):
        return None
    fn = node.func
    if not (isinstance(fn, ast.Name) and fn.id == "frozenset"):
        return None
    if len(node.args) != 1:
        return None
    try:
        value = ast.literal_eval(node.args[0])
    except (ValueError, TypeError, SyntaxError):
        return None
    return set(value) if isinstance(value, (set, frozenset)) else None


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(TARGET))
    problems: list[str] = []

    # (1) the four allowlists, exactly
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in EXPECTED:
                value = _literal_set(node.value)
                if value is None:
                    problems.append(
                        f"{target.id} is not a literal `frozenset({{...}})`. It must be a "
                        f"literal this gate can read: a computed allowlist is not a closed one."
                    )
                else:
                    found[target.id] = value
    for name, want in EXPECTED.items():
        got = found.get(name)
        if got is None:
            problems.append(f"{name} is missing from {TARGET.name}")
        elif got != want:
            extra, missing = sorted(got - want), sorted(want - got)
            problems.append(
                f"{name} does not match the order. added={extra or '-'} removed={missing or '-'}. "
                f"Widening what reaches a model's prompt requires a ruling, not an edit "
                f"([2026] VJS-CC-BOLTRIG-CONTINUITY-TOOL-WORK-001)."
            )

    # (2) the banned import
    for node in ast.walk(tree):
        mod = None
        if isinstance(node, ast.ImportFrom):
            # BOTH halves. `from . import chat_event_projection` puts nothing in
            # `node.module` and everything in `node.names`, so checking the module alone
            # missed the exact import this gate exists to refuse. Found by seed D7(b),
            # which reported GATE-GREEN on the first run.
            mod = (node.module or "") + " " + " ".join(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            mod = " ".join(a.name for a in node.names)
        if mod and BANNED_IMPORT in mod:
            problems.append(
                f"continuity.py imports {BANNED_IMPORT}. That module is a BROWSER-safety "
                f"projection and bounds nothing for the prompt: its cardinality cap is not "
                f"in it, `_summarise_output` has no cap at all, the same events list carries "
                f"free text on adjacent frame types, and one writer bypasses it entirely. "
                f"A bound declared for another destination is not a bound here."
            )

    # (3) and (4): who touches `.events`, and with which literal keys
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == EVENTS_ATTR
                and fn.name != READER
            ):
                problems.append(
                    f"{fn.name}() reads `.{EVENTS_ATTR}` at line {node.lineno}. Only "
                    f"{READER}() may: one function, one allowlist, so there is a single place "
                    f"to audit and a single place a widening can hide."
                )
        if fn.name != READER:
            continue
        for node in ast.walk(fn):
            key = None
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                key = node.slice.value
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                key = node.args[0].value
            if isinstance(key, str) and key not in EXPECTED["_TOOL_WORK_READ_FIELDS"]:
                problems.append(
                    f"{READER}() reads the key {key!r} at line {node.lineno}, which is not in "
                    f"_TOOL_WORK_READ_FIELDS. Every field crossing this boundary is enumerated; "
                    f"`args_summary` and `result_summary` are refused in whole and in part."
                )

    if problems:
        print("CONTINUITY PROJECTION GATE FAILED", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(
        f"OK: continuity.py holds the four allowlists exactly, does not import "
        f"{BANNED_IMPORT}, confines `.{EVENTS_ATTR}` to {READER}(), and reads no key outside "
        f"{sorted(EXPECTED['_TOOL_WORK_READ_FIELDS'])}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
