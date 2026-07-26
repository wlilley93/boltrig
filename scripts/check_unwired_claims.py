#!/usr/bin/env python3
"""Find mechanisms the record NAMES that no production path uses.

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

WHAT IT CHECKS, PART 1 - CLASSES. A class defined under boltrig/ whose NAME IS
NEVER USED anywhere under boltrig/ outside its own `class` statement:
  - not constructed, not subclassed, not passed as an argument, not referenced at
    all. Being a base class or being handed to a framework IS wiring, so those do
    not count as unwired; only a name nothing mentions does. RedisCounter was
    exactly that: one grep, one hit, the definition itself.
  - not exported for callers to construct (absent from __all__), and
  - not a Protocol, ABC, Exception, dataclass-as-record, TypedDict or Enum -
    those are types, not mechanisms, and are meant to be referenced rather than
    built here,
is reported.

WHAT IT CHECKS, PART 2 - FUNCTIONS (2026-07-26). The class rule left the larger
half of the same defect uncovered, and the Tier 0 claim inventory found seven
live instances in one sweep. The worst:

    boltrig/kernel/credentials.py: "Swept with the run's other refs on terminal
    (``sweep_run_scoped``)". Four more modules named it as THE lifecycle seam,
    three of them quantifying - "its only caller is the org pump". The true
    caller count was ZERO. Every chat turn sealed the caller's live external
    bearer at rest and nothing ever deleted it: 29 rows on one client tenant
    after a single day of light use.

    boltrig/kernel/hitl.py: "The dispatch gate uses ``consume_if_approved``",
    "durable resume itself is exactly-once via ``consume_if_approved``". The gate
    calls consume_approved_by. The wrapper could be deleted, or its null-verb
    hardening changed, and three records would still describe a control.

So: a function or method defined under boltrig/ that no production path
references, and that the prose names in CODE-QUOTED form, is reported the same
way. Four exclusions, each because the reference is real but invisible to a
name search:
  - a DECORATED function. The decorator is the wiring: a route handler, a
    Hatchet task and a @property are all called by something that never spells
    the name.
  - a method OVERRIDING a framework base (any base class not defined under
    boltrig/). Starlette calls SecurityHeadersMiddleware.dispatch; no boltrig
    code ever will.
  - dunders, which the interpreter calls.
  - a name reached through getattr/hasattr/setattr with a literal string, which
    is how the executor seam finds register_task.

CODE-QUOTED is the load-bearing narrowing. Matching bare words made "consume",
"dispatch", "push" and "stop" look advertised because English uses them; a
docstring that writes ``sweep_run_scoped`` is naming a symbol, and only that is
a claim. A qualified prefix counts too - ``db.execute_write`` names
execute_write.

WHAT IT DOES NOT CHECK. It cannot know whether a claim is TRUE, only whether the
thing it names is reached. A function with one caller in a lane that never runs
still passes here - that is the honest limit, and it is still the difference
between the eleven defects in the goal's evidence table and eleven silent ones.

Exit 1 if any unwired-and-advertised name is found, unless it is listed in the
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

_PROSE_RE = re.compile(r"#.*|\"\"\"(?:.|\n)*?\"\"\"")


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


def _claim_pattern(name: str) -> re.Pattern[str]:
    """Prose that NAMES the symbol, as opposed to prose that uses the word.

    ``name``, `name`, :func:`name`, :meth:`Class.name`, ``db.name`` all count. A
    bare occurrence does not: "the pump will consume the item" is a sentence, not
    a claim about ``consume``."""
    e = re.escape(name)
    return re.compile(rf"``[\w.]*{e}``|`[\w.]*{e}`|:(?:func|meth|attr):`[^`]*{e}`")


def _collect(sources: dict[Path, str]) -> tuple[dict, dict, set[str], set[str]]:
    """Return (classes defined, functions defined, every referenced name, __all__)."""
    classes: dict[str, Path] = {}
    functions: dict[str, Path] = {}
    referenced: set[str] = set()
    exported: set[str] = set()
    local_classes: set[str] = set()

    for path, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:  # a file that will not parse is another gate's problem
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                local_classes.add(node.name)

    for path, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        # Methods of a class that extends something we did not define are called
        # by whatever we extended. Starlette calls .dispatch; we never do.
        framework_methods: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # TYPE_BASES are typing constructs, not frameworks: nothing calls
                # back into a Protocol's methods, so its declarations are OUR
                # contract and stay in scope. Only a real external base (a
                # Starlette middleware, an SDK client) excuses an override.
                if _base_names(node) - local_classes - TYPE_BASES:
                    framework_methods |= {
                        b.name
                        for b in node.body
                        if isinstance(b, ast.FunctionDef | ast.AsyncFunctionDef)
                    }

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if not _is_type_not_mechanism(node):
                    classes.setdefault(node.name, path)
                referenced |= _base_names(node)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                name = node.name
                if node.decorator_list:  # the decorator IS the wiring
                    continue
                if name.startswith("__") and name.endswith("__"):
                    continue
                if name in framework_methods:
                    continue
                functions.setdefault(name, path)
            elif isinstance(node, ast.Name):
                # Any load of the name is wiring: constructed, subclassed, passed
                # to a framework, or aliased. The defect this gate exists for is a
                # name that appears NOWHERE but its own definition.
                if isinstance(node.ctx, ast.Load):
                    referenced.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced.add(node.attr)
            elif isinstance(node, ast.Import | ast.ImportFrom):
                for alias in node.names:
                    referenced.add(alias.name.split(".")[-1])
                    if alias.asname:
                        referenced.add(alias.asname)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in {
                    "getattr", "hasattr", "setattr",
                }:
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            referenced.add(arg.value)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "__all__":
                        for elt in getattr(node.value, "elts", []):
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                exported.add(elt.value)

    return classes, functions, referenced, exported


def main() -> int:
    files = sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)
    sources = {p: p.read_text(encoding="utf-8") for p in files}

    classes, functions, referenced, exported = _collect(sources)

    unwired: dict[str, tuple[str, Path]] = {}
    for name, path in classes.items():
        if name not in referenced and name not in exported:
            unwired[name] = ("class", path)
    for name, path in functions.items():
        if name not in referenced and name not in exported and name not in unwired:
            unwired[name] = ("function", path)

    if not unwired:
        print("PASS: every name the record uses is reached somewhere.")
        return 0

    # Advertised = named in CODE-QUOTED form in any docstring or comment, anywhere
    # in boltrig/ or in the deployment surface. That is what turns "unused" into
    # "a false claim".
    prose: list[tuple[str, str]] = []
    for path, text in sources.items():
        for m in _PROSE_RE.finditer(text):
            prose.append((str(path.relative_to(ROOT)), m.group(0)))
    for extra in ("docker-compose.yml", ".env.example"):
        p = ROOT / extra
        if p.exists():
            prose.append((extra, p.read_text(encoding="utf-8")))

    allow: dict[str, str] = {}
    if ALLOW_FILE.exists():
        allow = json.loads(ALLOW_FILE.read_text(encoding="utf-8")).get("allow", {})

    findings: list[tuple[str, str, str, str]] = []
    for name, (kind, path) in sorted(unwired.items()):
        if name in allow:
            continue
        pattern = _claim_pattern(name)
        where = sorted({src for src, blob in prose if pattern.search(blob)})
        if not where:
            continue  # unused, but nothing claims it exists: not this gate's business
        findings.append((name, kind, str(path.relative_to(ROOT)), ", ".join(where[:4])))

    if not findings:
        print(f"PASS: {len(unwired)} unreached name(s), none advertised by the record.")
        return 0

    print("FAIL: the record names a mechanism no production path reaches.\n")
    for name, kind, path, where in findings:
        print(f"  {name}  ({kind})")
        print(f"    defined : {path}")
        print(f"    claimed : {where}")
        print("    Either wire it, delete it, or add it to")
        print(f"    {ALLOW_FILE.relative_to(ROOT)} with a reason.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
