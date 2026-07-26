#!/usr/bin/env python3
"""The gate-coverage gate: a gate that runs on nothing protects nothing.

GOAL-claims-must-be-load-bearing, applied to the gates themselves. Two claims in
this repository are load-bearing, both are prose today, and both are false:

  (a) `make compose-validate` says "Validate base and secure Compose
      configurations". It loads THREE manifests: docker-compose.yml,
      deploy/compose.secure.yml and deploy/compose.release.yml. There are SIX
      compose manifests. deploy/compose.dev.yml is what genesis.sh:23 and
      scripts/dev-up.sh:14 actually bring the dev box up with, and neither it,
      nor deploy/compose.inprocess.yml, nor deploy/compose.opbox-link.yml is an
      input to any `docker compose config` run anywhere in the Makefile. A
      manifest nothing validates is a manifest that breaks on the box, at
      `up -d`, in front of whoever is deploying. tests/deploy/
      test_compose_hardening.py pins the same three and no more, so the offline
      suite does not close the gap either.

      NOTE ON PARSING. Three of these overlays use the Compose merge tags
      `!override` / `!reset`. A plain yaml.safe_load REFUSES them (the tests keep
      a custom PyYAML constructor to get around it), so this gate does not read
      the YAML at all: it asserts the Makefile NAMES each manifest as an input to
      a `docker compose ... config` step and leaves the actual validation to the
      one tool that can do it. Deriving the claim from the Makefile text is the
      point - nothing here is restated, so nothing here can rot.

  (b) Makefile:205 calls `quality` "the complete local release gate", and
      .github/workflows/ci.yml:146 says "Each parallel job invokes the same
      component target used by `make quality`". Both sentences are wrong the same
      way: `migration-parity` and `doctor-fixture` are prerequisites of `quality`
      and appear in NO workflow job. A green required check therefore certifies
      less than the sentence next to it promises.

WHAT IT CHECKS. Both assertions are DERIVED - globbed and parsed, never listed
here - so adding a seventh compose manifest or a ninth `quality` prerequisite
fails this gate on the commit that adds it, not months later on a tenant's box.

  (a) glob deploy/compose*.yml + the root docker-compose.yml, parse every
      Makefile recipe, and require each manifest to appear as a `-f` input to
      some recipe that invokes $(COMPOSE) with the `config` subcommand.
  (b) parse the `quality` prerequisite list out of the Makefile and every
      `run:` line out of .github/workflows/, and require each prerequisite to be
      invoked - directly, or transitively via every one of its own prerequisites
      (which is how `security-source` is covered: the workflow runs its five
      components by name rather than the aggregate).

WHAT IT DOES NOT CHECK. Whether the validation is any good, or whether a covered
target passes. Only that the input reaches the gate and the gate reaches CI.

The root docker-compose.override.yml is deliberately NOT required: .gitignore:54
ignores it, it is a per-machine file, and CI has no copy to validate.

Usage:  python scripts/check_gate_coverage.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
WORKFLOWS = ROOT / ".github" / "workflows"

# The target whose prerequisite list claims to be "the complete local release gate".
RELEASE_GATE_TARGET = "quality"

_RULE_RE = re.compile(r"^([A-Za-z0-9_.%/-]+(?:\s+[A-Za-z0-9_.%/-]+)*)\s*:(?!=)(.*)$")
_JOB_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")


# --------------------------------------------------------------------------- #
# Makefile
# --------------------------------------------------------------------------- #
def read_makefile() -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """Return (target -> prerequisites, [(target, joined recipe command), ...]).

    Recipe lines are TAB-indented and continue across a trailing backslash; the
    compose validation steps are five and six lines long, so a per-line reader
    would see `-f docker-compose.yml` and `config` as unrelated facts."""
    prereqs: dict[str, list[str]] = {}
    recipes: list[tuple[str, str]] = []
    target: str | None = None
    pending: list[str] = []

    def flush() -> None:
        if pending and target is not None:
            recipes.append((target, " ".join(pending)))
        pending.clear()

    for raw in MAKEFILE.read_text(encoding="utf-8").splitlines():
        if raw.startswith("\t"):
            body = raw[1:].strip()
            if not pending:
                # make's recipe prefixes (@ silent, - ignore-errors, + always-run)
                # are only meaningful at the START of a command. Stripping them
                # from a CONTINUATION line eats the leading `-f` of
                #     -f docker-compose.yml -f deploy/compose.release.yml \
                # and silently drops a manifest from the validated set - this gate
                # reporting a file as covered when it is not is the exact defect it
                # exists to catch, one level up.
                body = body.lstrip("@-+")
            if body.endswith("\\"):
                pending.append(body[:-1].strip())
                continue
            pending.append(body)
            flush()
            continue
        flush()
        line = raw.split("#", 1)[0].rstrip()
        if not line or line[0].isspace():
            continue
        match = _RULE_RE.match(line)
        if not match:
            continue
        names = match.group(1).split()
        if any(name.startswith(".") for name in names):
            continue  # .PHONY and friends are directives, not targets
        deps = match.group(2).split()
        for name in names:
            prereqs.setdefault(name, [])
            prereqs[name].extend(d for d in deps if d not in prereqs[name])
        target = names[-1]
    flush()
    return prereqs, recipes


def _flag_values(tokens: list[str], flags: tuple[str, ...]) -> list[str]:
    return [tokens[i + 1] for i, tok in enumerate(tokens[:-1]) if tok in flags]


def compose_validation_inputs(recipes: list[tuple[str, str]]) -> dict[str, set[str]]:
    """Map each compose manifest to the Makefile targets that `config`-validate it.

    A validation step is a recipe command that runs $(COMPOSE) with `config` as a
    subcommand. `release-up` runs $(COMPOSE) ... pull / up -d, which loads the
    manifests but validates nothing: a broken overlay there is discovered by
    changing the running deployment, which is the failure mode, not the check."""
    validated: dict[str, set[str]] = {}
    for target, command in recipes:
        tokens = command.split()
        if "$(COMPOSE)" not in tokens or "config" not in tokens:
            continue
        for value in _flag_values(tokens, ("-f", "--file")):
            validated.setdefault(value, set()).add(target)
    return validated


def compose_manifests() -> list[str]:
    """Every manifest a deployment can be brought up with, as repo-relative paths."""
    found = {p.relative_to(ROOT).as_posix() for p in (ROOT / "deploy").glob("compose*.yml")}
    base = ROOT / "docker-compose.yml"
    if base.exists():
        found.add("docker-compose.yml")
    return sorted(found)


# --------------------------------------------------------------------------- #
# Workflows
# --------------------------------------------------------------------------- #
def workflow_make_targets(known: set[str]) -> dict[str, set[tuple[str, str]]]:
    """Map each make target invoked in CI to the {(workflow, job)} that invoke it.

    Only tokens that are DECLARED Makefile targets are collected, so
    `make python-audit sast iac-scan PY=python` yields three targets and no
    variable assignments, without this file holding a list of what to ignore."""
    invoked: dict[str, set[tuple[str, str]]] = {}
    if not WORKFLOWS.is_dir():
        return invoked
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        name = path.stem
        job = "<top-level>"
        in_jobs = False
        block_indent: int | None = None
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.rstrip()
            stripped = line.strip()
            indent = len(line) - len(line.lstrip(" "))
            if line.startswith("jobs:"):
                in_jobs, job = True, "<top-level>"
                continue
            if in_jobs and _JOB_RE.match(line):
                job = _JOB_RE.match(line).group(1)  # type: ignore[union-attr]
                block_indent = None
            if block_indent is not None:
                # inside a `run: |` block scalar: it ends at the first line that
                # is not more-indented than the `run:` key itself.
                if stripped and indent <= block_indent:
                    block_indent = None
                else:
                    _collect(stripped, known, invoked, name, job)
                    continue
            if stripped.startswith("run:") or stripped.startswith("- run:"):
                rest = stripped.split("run:", 1)[1].strip()
                if rest in {"|", ">", "|-", ">-", "|+", ">+"}:
                    block_indent = indent
                else:
                    _collect(rest, known, invoked, name, job)
    return invoked


def _collect(
    command: str,
    known: set[str],
    invoked: dict[str, set[tuple[str, str]]],
    workflow: str,
    job: str,
) -> None:
    if not re.search(r"(^|[;&|(\s])make(\s|$)", command):
        return
    for token in command.split():
        if token in known:
            invoked.setdefault(token, set()).add((workflow, job))


def resolve_coverage(
    target: str,
    prereqs: dict[str, list[str]],
    invoked: dict[str, set[tuple[str, str]]],
    seen: frozenset[str] = frozenset(),
) -> str | None:
    """Where CI runs `target`, or None. Empty string is never returned.

    Transitive on purpose. `security-source` is an aggregate of five gates and
    the security workflow runs all five by name; requiring the aggregate's own
    name would report a gap that does not exist. An aggregate is covered exactly
    when every component it aggregates is."""
    if target in seen:
        return None
    where = invoked.get(target)
    if where:
        return ", ".join(f"{wf}/{job}" for wf, job in sorted(where))
    deps = prereqs.get(target) or []
    if not deps:
        return None
    resolved = [resolve_coverage(d, prereqs, invoked, seen | {target}) for d in deps]
    if all(resolved):
        return "via " + ", ".join(f"{d} ({r})" for d, r in zip(deps, resolved))
    return None


# --------------------------------------------------------------------------- #
def main() -> int:
    if not MAKEFILE.exists():
        print(f"FAIL: missing {MAKEFILE.relative_to(ROOT)}", file=sys.stderr)
        return 1

    prereqs, recipes = read_makefile()
    validated = compose_validation_inputs(recipes)
    manifests = compose_manifests()
    invoked = workflow_make_targets(set(prereqs))

    print("Compose manifests validated by `docker compose config` in the Makefile")
    print("-" * 78)
    print(f"{'manifest':<34}{'status':<14}validated by")
    print("-" * 78)
    unvalidated: list[str] = []
    for manifest in manifests:
        targets = validated.get(manifest)
        if targets:
            print(f"{manifest:<34}{'ok':<14}{', '.join(sorted(targets))}")
        else:
            unvalidated.append(manifest)
            print(f"{manifest:<34}{'UNVALIDATED':<14}-")
    print("-" * 78)

    gate_prereqs = prereqs.get(RELEASE_GATE_TARGET, [])
    print(f"\n`make {RELEASE_GATE_TARGET}` components reached by a CI workflow")
    print("-" * 78)
    print(f"{'component':<20}{'status':<14}run by")
    print("-" * 78)
    uncovered: list[str] = []
    for component in gate_prereqs:
        where = resolve_coverage(component, prereqs, invoked)
        if where:
            print(f"{component:<20}{'COVERED':<14}{where}")
        else:
            uncovered.append(component)
            print(f"{component:<20}{'UNCOVERED':<14}-")
    print("-" * 78)
    print(
        f"manifests={len(manifests)}  unvalidated={len(unvalidated)}  "
        f"components={len(gate_prereqs)}  uncovered={len(uncovered)}"
    )

    if not gate_prereqs:
        print(
            f"\nRESULT: FAIL - no `{RELEASE_GATE_TARGET}` target in the Makefile; "
            "this gate is checking nothing.",
            file=sys.stderr,
        )
        return 1

    if unvalidated:
        print("\nUNVALIDATED compose manifests (no `docker compose config` step loads them):")
        for manifest in unvalidated:
            print(f"  - {manifest}")
        print("  Add each as a `-f` input to a compose-validate step in the Makefile.")
    if uncovered:
        print(f"\nUNCOVERED `{RELEASE_GATE_TARGET}` components (in no workflow `run:` line):")
        for component in uncovered:
            print(f"  - {component}")
        print("  Either run the target in a CI job, or stop calling the aggregate complete.")

    if unvalidated or uncovered:
        print("\nRESULT: FAIL - a gate input or a release-gate component is unreached.")
        return 1
    print("\nRESULT: PASS - every compose manifest is validated and every "
          f"`{RELEASE_GATE_TARGET}` component runs in CI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
