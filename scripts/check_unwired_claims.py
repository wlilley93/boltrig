#!/usr/bin/env python3
"""Find mechanisms the record NAMES that no production path constructs.

The first check of GOAL-claims-must-be-load-bearing. It exists because of exactly
one defect, and it would have caught it years earlier:

    boltrig/kernel/ratelimit.py said "The production back end is Redis".
    docker-compose.yml attributed "rate-limit + ephemeral counters" to redis.
    api/readiness.py made Redis REQUIRED in production.
    Nothing anywhere constructed RedisCounter.

Every rate limit in the system was therefore per-process and per-boot, and a
kernel restart silently reset the 2FA brute-force bound. Three separate records
asserted a control the deployment did not have, and no gate could tell, because a
docstring is prose and prose is not enforcement.

WHAT IT CHECKS. A class defined under boltrig/ whose NAME IS NEVER USED anywhere
under boltrig/ outside its own `class` statement:
  - not constructed, not subclassed, not passed as an argument, not referenced at
    all. Being a base class or being handed to a framework IS wiring, so those do
    not count as unwired; only a name nothing mentions does. RedisCounter was
    exactly that: one grep, one hit, the definition itself.
  - not exported for callers to construct (absent from __all__), and
  - not a Protocol, ABC, Exception, dataclass-as-record, TypedDict or Enum -
    those are types, not mechanisms, and are meant to be referenced rather than
    built here,
is reported. Being named in a docstring or comment RAISES it from a note to a
failure: an unused class is untidy, but an unused class the record advertises is a
false claim about the running system.

WHAT IT DOES NOT CHECK. It cannot know whether a claim is TRUE, only whether the
thing it names is built. That is the honest limit, and it is still the difference
between the eleven defects in the goal's evidence table and eleven silent ones.

Exit 1 if any unwired-and-advertised class is found, unless it is listed in the
allow file with a reason.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "boltrig"
ALLOW_FILE = ROOT / "docs" / "refactoring" / "unwired-claims-allow.json"

# Types, not mechanisms. Referenced by design; nothing should construct them here.
TYPE_BASES = {
    "Protocol", "ABC", "ABCMeta", "Exception", "BaseException", "TypedDict",
    "Enum", "IntEnum", "StrEnum", "NamedTuple", "BaseModel", "Generic",
}
TYPE_DECORATORS = {"dataclass", "runtime_checkable", "total_ordering"}


def _decorator_names(node: ast.ClassDef) -> set[str]:
    out: set[str] = set()
    for d in node.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if isinstance(target, ast.Name):
            out.add(target.id)
        elif isinstance(target, ast.Attribute):
            out.add(target.attr)
    return out


def _base_names(node: ast.ClassDef) -> set[str]:
    out: set[str] = set()
    for b in node.bases:
        if isinstance(b, ast.Name):
            out.add(b.id)
        elif isinstance(b, ast.Attribute):
            out.add(b.attr)
        elif isinstance(b, ast.Subscript):  # Protocol[T], Generic[T]
            inner = b.value
            if isinstance(inner, ast.Name):
                out.add(inner.id)
            elif isinstance(inner, ast.Attribute):
                out.add(inner.attr)
    return out


def _is_type_not_mechanism(node: ast.ClassDef) -> bool:
    return bool(_base_names(node) & TYPE_BASES) or bool(
        _decorator_names(node) & TYPE_DECORATORS
    )


def main() -> int:
    files = sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)
    sources = {p: p.read_text(encoding="utf-8") for p in files}

    defined: dict[str, Path] = {}
    exported: set[str] = set()
    constructed: set[str] = set()

    for path, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:  # a file that will not parse is another gate's problem
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if not _is_type_not_mechanism(node):
                    defined.setdefault(node.name, path)
                constructed |= _base_names(node)
            elif isinstance(node, ast.Name):
                # Any load of the name is wiring: constructed, subclassed, passed
                # to a framework, or aliased. The defect this gate exists for is a
                # name that appears NOWHERE but its own definition.
                if isinstance(node.ctx, ast.Load):
                    constructed.add(node.id)
            elif isinstance(node, ast.Attribute):
                constructed.add(node.attr)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "__all__":
                        for elt in getattr(node.value, "elts", []):
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                exported.add(elt.value)

    unwired = {n: p for n, p in defined.items() if n not in constructed and n not in exported}
    if not unwired:
        print("PASS: every class the record names is constructed somewhere.")
        return 0

    # Advertised = named in any docstring or comment, anywhere in boltrig/ or in the
    # deployment surface. That is what turns "unused" into "a false claim".
    prose: list[tuple[str, str]] = []
    for path, text in sources.items():
        for m in re.finditer(r"#.*|\"\"\"(?:.|\n)*?\"\"\"", text):
            prose.append((str(path.relative_to(ROOT)), m.group(0)))
    for extra in ("docker-compose.yml", ".env.example"):
        p = ROOT / extra
        if p.exists():
            prose.append((extra, p.read_text(encoding="utf-8")))

    allow: dict[str, str] = {}
    if ALLOW_FILE.exists():
        allow = json.loads(ALLOW_FILE.read_text(encoding="utf-8")).get("allow", {})

    findings: list[tuple[str, str, str]] = []
    for name, path in sorted(unwired.items()):
        where = [src for src, blob in prose if name in blob]
        if not where:
            continue  # unused, but nothing claims it exists: not this gate's business
        if name in allow:
            continue
        findings.append((name, str(path.relative_to(ROOT)), ", ".join(sorted(set(where))[:3])))

    if not findings:
        print(f"PASS: {len(unwired)} unconstructed class(es), none advertised by the record.")
        return 0

    print("FAIL: the record names a mechanism no production path constructs.\n")
    for name, path, where in findings:
        print(f"  {name}")
        print(f"    defined : {path}")
        print(f"    claimed : {where}")
        print("    Either wire it, delete it, or add it to")
        print(f"    {ALLOW_FILE.relative_to(ROOT)} with a reason.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
