#!/usr/bin/env python3
"""Make every REFERENCE in prose resolve. Tier 2 of GOAL-claims-must-be-load-bearing.

Tier 2 is "make drift fail": renaming or deleting a thing must break every record
that still names it. The named incident is SEC-24 - an ORDER pointed at a test
that had since been renamed, so the order was enforceable by nothing, and the
drift sat in the record for ninety minutes because no check could see it. A
reference is the cheapest claim to write and the one that rots first: the thing
it names moves, and the sentence stays.

Four instances of exactly that shape were live in the tree this gate was written
against, and none of them was findable by reading:

    boltrig/emotion/relay.py:3 opens "Supersedes
    ``boltrig/observability/orb_presence.py``". That file was deleted by the very
    commit that added the relay. The one sentence telling a reader why the module
    exists points at nothing they can open.

    docs/FEATURE-CATALOGUE-AUDIT-2026-07-21.md:50 marks "Signed channel intake"
    VERIFIED and cites tests/security/test_channel_gateway.py as the evidence.
    That file was split into _routes.py and _roundtrip.py. The audit's proof is a
    filename. SEC-24 again, in a document whose entire purpose is proof.

    docs/DEFINITION-OF-DONE-round-three.md and -four cite
    boltrig/kernel/platform_routes.py, which became a package in commit 960546a.

    docs/findings/2026-07-25-service-gated-verification.md:33 calls
    HATCHET_CLIENT_HOST_PORT "the part that is easy to miss and cost the most
    time here". Nothing in the tree reads that variable. A finding whose whole
    subject is the setup step people get wrong ships a setup step that is inert.

WHAT IT CHECKS. Four kinds of reference, in prose across boltrig/**/*.py
(comments + docstrings), docs/**/*.md, README.md, Makefile, .env.example,
docker-compose*.yml, .vjs/orders/*.yaml and scripts/*.py:

  1. repo-relative file paths     -> the file must exist
  2. pytest node ids a.py::test_b -> the file must exist AND define that test
  3. `make <target>`              -> the Makefile must declare that target
  4. boltrig-shaped env vars      -> the name must appear OUTSIDE prose: in
     (BOLTRIG_/POSTGRES_/HATCHET_/     source, .env.example, compose, the
      REDIS_, or named in .env.example) Makefile, CI workflows or shell scripts

Rule 4 is the one that catches a knob after its code is gone: the name survives
in the doc that told you to export it, and a reader cannot tell a variable that
does nothing from one that does.

WHY IT SCANS THE HISTORICAL RECORD. docs/findings/, docs/decisions/ and .vjs/
describe past states, and the tempting move is to exempt them by directory. That
would exempt precisely the records Tier 2 exists for - an ORDER is the strongest
claim in the repository and SEC-24 was an order, and the HATCHET_CLIENT_HOST_PORT
defect above is in a findings file. So they are scanned, and the exemption is
SEMANTIC instead: a reference sitting in a negated or past-tense clause ("there
is no `scripts/audit-soc2-compliance.sh`", "that bypass has been REVERTED") is a
correct record of an absence, and a gate that reddens on it only teaches people
to write vaguer prose. The window is the SENTENCE around the reference,
reconstructed across wrapped lines, never the file: one "was removed" three
paragraphs up must not launder a broken reference below it.

That exemption does NOT apply to live source under boltrig/ and scripts/. A
docstring in shipping code describes what runs NOW, not what used to; if it needs
to say what it replaced it must name something a reader can still open. That
asymmetry is the whole reason relay.py:3 is a defect while the identical
sentence in a dated finding would not be.

WHAT IT DOES NOT SCAN, deliberately:
  - docs/proposals/, docs/design/, docs/prompts/, docs/requirements/. Every one
    is forward-looking or imported: a cutover map, a surface sketch, an agent
    prompt template, a third-party build spec. Their references are
    SPECIFICATIONS for files that do not exist yet, and requiring them to resolve
    would mean building the thing before you were allowed to describe it. Cost of
    the carve-out, stated plainly: their many correct references go unenforced.
  - symbols (function and class names). Rule 1 resolves paths, not identifiers;
    boltrig/store/postgres.py:547 naming the removed `_still_leased` helper is
    out of scope for this gate, not exempted by it.
  - anything under node_modules/, .venv/, .claude/worktrees/ or backups/ -
    vendored, generated, or runtime output, none of it our record to keep honest.
  - THIS FILE. It quotes, verbatim, the broken references it exists to find:
    boltrig/observability/orb_presence.py and tests/security/test_channel_gateway.py
    appear above precisely because they do not resolve. Scanning it would leave
    the gate permanently red on its own evidence, or force the evidence out of
    the docstring - and naming the real incident is the point of writing one.
    Every OTHER file under scripts/ is scanned, live-source rules and all.

WHAT IT DOES NOT CHECK. Whether a claim is TRUE - only whether the thing it names
can be found. A docstring may point at a file that exists and still describe it
wrongly. That is the honest limit, and it is still the difference between drift
that fails the build and drift that waits to be read.

Exit 1 if any reference does not resolve, unless it is in ALLOW with a reason.

Usage:  python scripts/check_prose_references.py
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

# ---------------------------------------------------------------------------
# scope
# ---------------------------------------------------------------------------

PROSE_GLOBS: tuple[tuple[str, str], ...] = (
    ("boltrig", "**/*.py"),
    ("docs", "**/*.md"),
    ("scripts", "*.py"),
    (".vjs/orders", "*.yaml"),
)
PROSE_FILES: tuple[str, ...] = (
    "README.md",
    "Makefile",
    ".env.example",
    "docker-compose.yml",
    "docker-compose.override.yml",
)

# Forward-looking or imported: see WHAT IT DOES NOT SCAN above.
SKIP_PREFIXES: tuple[str, ...] = (
    "docs/proposals/",
    "docs/design/",
    "docs/prompts/",
    "docs/requirements/",
)
SKIP_PARTS = {"__pycache__", "node_modules", ".venv", ".git", ".claude", "backups"}

# Live source: a comment here describes the running system, so the past-tense
# exemption does not apply (see the relay.py:3 case in the docstring).
LIVE_SOURCE_PREFIXES: tuple[str, ...] = ("boltrig/", "scripts/")

# ---------------------------------------------------------------------------
# rules 1 + 2: file paths and pytest node ids
# ---------------------------------------------------------------------------

# A token is only treated as a repo path if its first segment is one of these.
# Anchoring on a fixed list of SOURCE roots is what keeps the gate usable:
# without it "read/write", "and/or", every URL path and every docker image tag in
# the docs becomes a candidate file. backups/ is excluded on purpose - it holds
# pg_dump OUTPUT, so docs/backup-restore.md correctly names backups/boltrig.dump
# as a file the command is about to create.
PATH_ROOTS = {
    ".github", ".vjs", "boltrig", "deploy", "docs", "libraries", "migrations",
    "schemas", "scripts", "sdks", "services", "site", "tests", "ui",
}

_PATH_RE = re.compile(
    r"(?<![\w/.-])(?:\./)?"
    r"(?P<path>[A-Za-z0-9_.][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)+)"
    r"(?P<node>::[A-Za-z0-9_:]+)?"
)
_TEST_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.M)

# ---------------------------------------------------------------------------
# rule 3: make targets
# ---------------------------------------------------------------------------

# Only a BACKTICKED `make x`, or a line beginning with make inside a code block /
# indented command, counts. A bare `make\s+\w+` match would read English: the
# tree contains "make the doctor green by weakening real production
# requirements" and "make the ancestry walk deterministic", and a gate that
# reports `make the` twice on its first run never gets a second.
_MAKE_BACKTICK_RE = re.compile(r"`\s*(?:[A-Z][A-Z0-9_]*=\S+\s+)*make\s+(?P<t>[a-z][a-z0-9-]*)")
_MAKE_COMMAND_RE = re.compile(
    r"(?:^|\$\s)\s*(?:[A-Z][A-Z0-9_]*=\S+\s+)*make\s+(?P<t>[a-z][a-z0-9-]*)", re.M
)
_MAKE_TARGET_RE = re.compile(r"^([a-zA-Z0-9_-]+)\s*:(?!=)", re.M)
_MAKE_PHONY_RE = re.compile(r"^\.PHONY:(.*)$", re.M)

# ---------------------------------------------------------------------------
# rule 4: environment variables
# ---------------------------------------------------------------------------

_ENV_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]{4,})(?![A-Za-z0-9_])")
ENV_PREFIXES = ("BOLTRIG_", "POSTGRES_", "HATCHET_", "REDIS_")
_ENV_ASSIGN_RE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]{4,})=", re.M)

# ---------------------------------------------------------------------------
# negation / past tense
# ---------------------------------------------------------------------------

_NEGATION_RE = re.compile(
    r"\b(?:no|not|never|none|nothing|nowhere|cannot|can't|don't|doesn't|isn't|"
    r"aren't|wasn't|weren't|without|removed|remove|removing|deleted|delete|"
    r"deleting|dropped|drop|gone|absent|missing|retired|retire|replaced|"
    r"reverted|renamed|obsolete|former|formerly|earlier|previously|used to|"
    r"no longer|instead of|had been|was|were|until|before|old|stale|legacy|"
    r"deprecated|unlike|rather than|neither|nor)\b",
    re.I,
)
# "supersedes" is deliberately NOT a marker. It reads as an active present-tense
# claim about a thing the reader is invited to go and compare against, which is
# exactly what relay.py:3 does and exactly why that line is a defect. "superseded
# BY x" - where the surviving thing is x - is already covered by "was"/"replaced".

# The imperative mood is a TASK, not a claim. Every findings document ends in a
# "Deferred followups" list, and docs/refactoring/arc-1/pre-arc/findings.md:130
# reads "- Author `scripts/audit-soc2-compliance.sh` (SOC 2 evidence gap)" - an
# item that is CORRECT precisely because the file does not exist. The verb must
# sit immediately before the reference (articles and quoting allowed, nothing
# else), so this cannot excuse a stale path merely for sharing a sentence with
# the word "add".
_PROSPECTIVE_RE = re.compile(
    r"\b(?:author|create|write|introduce|add|draft|stub|scaffold|generate)\s+"
    r"(?:a\s+|an\s+|the\s+|new\s+)*[`'\"(]*$",
    re.I,
)

# ---------------------------------------------------------------------------
# exemptions: explicit, few, each with its reason
# ---------------------------------------------------------------------------

ALLOW: dict[tuple[str, str], str] = {
    (
        "docs/decisions/0013-emotion-addon.md",
        "boltrig/observability/orb_presence.py",
    ): (
        "The ADR's Context section records the world as it stood on 2026-07-18, and "
        "the decision it records is to delete that module. An ADR is a dated "
        "instrument: editing it to resolve would falsify the record."
    ),
    (
        "docs/extension-contract.md",
        "libraries/skills/renewal/adgm.yaml",
    ): (
        "An illustrative example of PROJECT content - a tenant's own skill file - "
        "inside a yaml fence. This repository does not and should not ship it."
    ),
    ("*", "HATCHET_CLIENT_HOST_PORT"): (
        "A hatchet-python SDK variable, not a boltrig knob. The findings doc names it "
        "in an operator repro for pointing a live test at a running engine, and the "
        "SDK reads it directly, so nothing in this tree does or should. Deleting the "
        "line would break the reproduction it exists to give."
    ),
    ("*", "BOLTRIG_CHAT_PATS"): (
        "An OPBOX environment variable (opbox src/lib/ai/boltrig-chat.ts, tier-2 PAT "
        "resolution), named in boltrig docs because they describe the opbox side of "
        "the chat cutover. Nothing in this tree reads it, and nothing should."
    ),
}


# ---------------------------------------------------------------------------
# prose extraction
# ---------------------------------------------------------------------------


class Unit:
    """A contiguous run of prose, plus what is needed to place a match in it.

    ``is_code`` marks a fenced block or an indented command - somewhere a
    ``make x`` at the start of a line is a command rather than a verb."""

    __slots__ = ("text", "start_line", "is_code")

    def __init__(self, text: str, start_line: int, is_code: bool = False) -> None:
        self.text = text
        self.start_line = start_line
        self.is_code = is_code

    def line_of(self, offset: int) -> int:
        return self.start_line + self.text.count("\n", 0, offset)


def _paragraphs(lines: list[str], first_line: int, *, fences: bool) -> list[Unit]:
    """Group consecutive non-blank lines so a wrapped sentence stays one sentence.

    Without this the negation window is a single physical line, and a docs file
    that says "It was worked around with a temporary `X` bypass" across a line
    break gets reported - the negation is on line 65 and the reference on 66."""
    units: list[Unit] = []
    buf: list[str] = []
    buf_start = first_line
    in_fence = False
    for i, line in enumerate(lines, start=first_line):
        if fences and line.lstrip().startswith(("```", "~~~")):
            if buf:
                units.append(Unit("\n".join(buf), buf_start, in_fence))
                buf = []
            in_fence = not in_fence
            buf_start = i + 1
            continue
        if not line.strip():
            if buf:
                units.append(Unit("\n".join(buf), buf_start, in_fence))
                buf = []
            buf_start = i + 1
            continue
        if not buf:
            buf_start = i
        buf.append(line)
    if buf:
        units.append(Unit("\n".join(buf), buf_start, in_fence))
    return units


def _python_units(text: str) -> list[Unit]:
    """Comments and docstrings only - Python code is not prose."""
    units: list[Unit] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                units.append(Unit(tok.string, tok.start[0]))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    try:
        tree = ast.parse(text)
    except SyntaxError:  # a file that will not parse is another gate's problem
        return units
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            continue
        first = node.body[0]
        start = getattr(first, "lineno", 1)
        units.extend(_paragraphs(doc.splitlines(), start, fences=False))
    return units


def prose_units(path: Path) -> list[Unit]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".py":
        return _python_units(text)
    # Markdown, VJS orders, the Makefile, .env.example and compose are prose end
    # to end. Their fenced command blocks are included on purpose: an operator
    # copies those lines, so a stale path or a dead export in one is a live
    # defect, and the HATCHET_CLIENT_HOST_PORT case is exactly such a block.
    return _paragraphs(text.splitlines(), 1, fences=path.suffix == ".md")


# ---------------------------------------------------------------------------
# negation window
# ---------------------------------------------------------------------------

_BOUNDARY_RE = re.compile(r"[.;:!?]|\n(?=\s*(?:[-*|#>]|\d+[.)]))")


def _sentence(text: str, start: int, end: int) -> str:
    left = 0
    for m in _BOUNDARY_RE.finditer(text, 0, start):
        left = m.end()
    right = len(text)
    m = _BOUNDARY_RE.search(text, end)
    if m:
        right = m.start()
    return text[left:right]


# ---------------------------------------------------------------------------
# the non-prose corpus: where a name has to appear to be real
# ---------------------------------------------------------------------------

CODE_GLOBS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("boltrig", ("**/*.py",)),
    ("tests", ("**/*.py", "**/*.yaml", "**/*.env", "**/*.sh")),
    ("scripts", ("**/*.py", "**/*.sh")),
    ("services", ("**/*.py", "**/*.sh", "**/*.yml", "**/*.yaml", "**/*.ts", "**/*.js")),
    ("deploy", ("**/*.yml", "**/*.yaml", "**/*.sh", "**/*.txt", "**/*.conf")),
    ("migrations", ("**/*.py",)),
    (".github", ("**/*.yml", "**/*.yaml")),
    ("ui", ("src/**/*.ts", "src/**/*.tsx", "*.ts", "*.json")),
    ("site", ("src/**/*.ts", "src/**/*.tsx", "*.ts", "*.json")),
    ("sdks", ("**/src/**/*.ts", "**/*.py")),
)
CODE_FILES = (
    "Makefile", ".env.example", "docker-compose.yml", "docker-compose.override.yml",
    "alembic.ini", "pyproject.toml", "genesis.sh", "manifest.example.yaml",
)


def _strip_hash_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def _docstring_positions(text: str) -> set[tuple[int, int]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    out: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, holders) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            out.add((first.value.lineno, first.value.col_offset))
    return out


def _python_code_only(text: str) -> str:
    """The file with comments AND docstrings removed.

    Dropping the docstrings matters and forgetting it is not hypothetical: while
    this gate was being written, its own module docstring - which quotes
    HATCHET_CLIENT_HOST_PORT as the defect it exists to catch - reached the
    corpus through scripts/*.py and quietly resolved that very reference. Prose
    that validates prose is the whole failure mode here, and a checker is not
    exempt from it. String LITERALS stay: os.environ["BOLTRIG_X"] is how a knob
    is actually read, and rule 4 depends on seeing it."""
    docstrings = _docstring_positions(text)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text
    return " ".join(
        t.string
        for t in toks
        if t.type != tokenize.COMMENT
        and not (t.type == tokenize.STRING and t.start in docstrings)
    )


def build_code_corpus() -> str:
    """Every place a name can be REAL: source, config, CI, shell, compose.

    Comments are stripped, because a comment is prose and prose is what is on
    trial - a knob that only two docstrings agree exists is the defect rule 4
    was written for."""
    chunks: list[str] = []
    for base, patterns in CODE_GLOBS:
        root = ROOT / base
        if not root.is_dir():
            continue
        for pattern in patterns:
            for p in root.glob(pattern):
                if not p.is_file() or (set(p.parts) & SKIP_PARTS):
                    continue
                if p.resolve() == SELF:
                    # This file names knobs (HATCHET_CLIENT_HOST_PORT,
                    # BOLTRIG_CHAT_PATS) only to say they are not wired. Letting
                    # its own text into the corpus would make every one of them
                    # resolve against the gate that reports them.
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
                if p.suffix == ".py":
                    text = _python_code_only(text)
                elif p.suffix in {".sh", ".yml", ".yaml", ".env", ".conf"}:
                    text = _strip_hash_comments(text)
                elif p.suffix in {".ts", ".tsx", ".js"}:
                    text = _BLOCK_COMMENT_RE.sub(" ", text)  # JSDoc is prose too
                chunks.append(text)
    for name in CODE_FILES:
        p = ROOT / name
        if p.is_file():
            chunks.append(_strip_hash_comments(p.read_text(encoding="utf-8", errors="replace")))
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


def makefile_targets() -> set[str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    targets = set(_MAKE_TARGET_RE.findall(text))
    for m in _MAKE_PHONY_RE.finditer(text):
        targets |= set(m.group(1).split())
    return targets


def env_example_names() -> set[str]:
    p = ROOT / ".env.example"
    if not p.is_file():
        return set()
    return set(_ENV_ASSIGN_RE.findall(p.read_text(encoding="utf-8")))


def _looks_like_repo_path(candidate: str) -> bool:
    if not candidate or any(c in candidate for c in "$*{}<>|@"):
        return False
    if ".." in candidate or candidate.startswith("/"):
        return False
    if candidate.split("/", 1)[0] not in PATH_ROOTS:
        return False
    return "." in candidate.rsplit("/", 1)[-1]  # a file, not a directory


def iter_prose_files() -> list[Path]:
    out: list[Path] = []
    for base, pattern in PROSE_GLOBS:
        root = ROOT / base
        if not root.is_dir():
            continue
        out.extend(sorted(root.glob(pattern)))
    for name in PROSE_FILES:
        out.append(ROOT / name)
    keep: list[Path] = []
    for p in out:
        if not p.is_file() or (set(p.parts) & SKIP_PARTS):
            continue
        if p.resolve() == SELF:  # see WHAT IT DOES NOT SCAN
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(SKIP_PREFIXES):
            continue
        keep.append(p)
    return keep


def main() -> int:
    files = iter_prose_files()
    targets = makefile_targets()
    env_declared = env_example_names()
    corpus = build_code_corpus()
    test_defs: dict[Path, set[str]] = {}

    findings: list[tuple[str, str, str, str]] = []  # kind, where, reference, why
    checked = {"path": 0, "node-id": 0, "make": 0, "env": 0}

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        live = rel.startswith(LIVE_SOURCE_PREFIXES)

        for unit in prose_units(path):
            text = unit.text

            def excused(start: int, end: int) -> bool:
                # Live source describes what runs now; only the historical record
                # gets the past-tense and imperative exemptions.
                if live:
                    return False
                if _NEGATION_RE.search(_sentence(text, start, end)):
                    return True
                return bool(_PROSPECTIVE_RE.search(text[max(0, start - 48):start]))

            # --- 1 + 2: file paths and pytest node ids ----------------------
            for m in _PATH_RE.finditer(text):
                filepart = m.group("path").rstrip(".,);:`'\"")
                node = m.group("node")
                if not _looks_like_repo_path(filepart):
                    continue
                checked["node-id" if node else "path"] += 1
                if excused(m.start(), m.end()):
                    continue
                where = f"{rel}:{unit.line_of(m.start())}"
                target = ROOT / filepart
                if not target.exists():
                    findings.append(("path", where, filepart, "no such file in the tree"))
                    continue
                if node:
                    name = node.lstrip(":").split("::")[-1]
                    if target not in test_defs:
                        body = target.read_text(encoding="utf-8", errors="replace")
                        test_defs[target] = set(_TEST_DEF_RE.findall(body))
                    if name not in test_defs[target]:
                        findings.append(
                            ("node-id", where, filepart + node,
                             f"{filepart} defines no {name}")
                        )

            # --- 3: make targets --------------------------------------------
            patterns = [_MAKE_BACKTICK_RE]
            if unit.is_code or path.name in {"Makefile", ".env.example"}:
                patterns.append(_MAKE_COMMAND_RE)
            for pattern in patterns:
                for m in pattern.finditer(text):
                    t = m.group("t")
                    checked["make"] += 1
                    if excused(m.start(), m.end()):
                        continue
                    if t not in targets:
                        findings.append(
                            ("make", f"{rel}:{unit.line_of(m.start())}", f"make {t}",
                             "no such target in the Makefile")
                        )

            # --- 4: environment variables ------------------------------------
            for m in _ENV_RE.finditer(text):
                name = m.group(1)
                if not (name.startswith(ENV_PREFIXES) or name in env_declared):
                    continue
                checked["env"] += 1
                if name in env_declared or name in corpus:
                    continue
                if excused(m.start(), m.end()):
                    continue
                findings.append(
                    ("env", f"{rel}:{unit.line_of(m.start())}", name,
                     "read by nothing outside prose")
                )

    # exemptions, then dedupe identical (kind, where, reference)
    kept: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    exempted = 0
    for kind, where, ref, why in findings:
        file_part = where.rsplit(":", 1)[0]
        if (file_part, ref) in ALLOW or ("*", ref) in ALLOW:
            exempted += 1
            continue
        key = (kind, where, ref)
        if key in seen:
            continue
        seen.add(key)
        kept.append((kind, where, ref, why))

    print("Prose reference resolution")
    print("-" * 100)
    print(f"{'kind':<9}{'where':<58}reference")
    print("-" * 100)
    for kind, where, ref, _why in kept:
        print(f"{kind:<9}{where:<58}{ref}")
    if not kept:
        print("(none)")
    print("-" * 100)
    print(
        f"prose_files={len(files)}  paths={checked['path']}  "
        f"node_ids={checked['node-id']}  make={checked['make']}  "
        f"env={checked['env']}  allowed={exempted}  unresolved={len(kept)}"
    )

    if kept:
        print("\nUNRESOLVED references:")
        for kind, where, ref, why in kept:
            print(f"  - {where}")
            print(f"      {kind}: {ref}")
            print(f"      {why}")
        print(
            "\nEither fix the reference, say plainly that the thing is gone, or add\n"
            "it to ALLOW in this script with a reason."
        )
        print("\nRESULT: FAIL - a record names something that cannot be found.")
        return 1
    print("\nRESULT: PASS - every reference in prose resolves.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
