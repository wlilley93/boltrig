#!/usr/bin/env python3
"""The health-claim gate: nothing may report healthy while unable to serve.

GOAL-claims-must-be-load-bearing, item 3 ("Status tells the truth"). This one is
not hypothetical and it was not cheap: a client tenant sat at `/readyz` 503 for
about FORTY MINUTES on an Alembic head mismatch while `docker ps` said `healthy`
the whole time, and the orchestrator - which restarts and gates rollout on that
signal - had no reason to act. The kernel healthcheck probes `/healthz`, which
boltrig/kernel/app.py:389 answers from `k.loader.health_snapshot()`: a cached
adapter posture that awaits no I/O and knows nothing about Postgres, Redis, the
schema head, the control plane or the stack tools. All of those live in
boltrig/api/readiness.py behind `/readyz`, and the string `readyz` appears ZERO
times in docker-compose.yml and zero times under deploy/.

The fleet-worker healthcheck is the same defect in a purer form: it is
`python -c "import boltrig"`. That command proves an interpreter can import a
module. It passes in a container whose pump died on boot, whose database is
unreachable, and whose Codex runtime never came up. A test that cannot fail for
any reason the operator cares about is not a health check, it is a claim.

WHAT IT CHECKS. For every FIRST-PARTY service (one this repo builds) declaring a
healthcheck, in docker-compose.yml and every deploy/compose*.yml overlay:

  - if the healthcheck probes an HTTP path, find the source file INSIDE that
    service's own build context that registers that path. If the same file also
    registers a readiness path (/readyz, /ready, /readiness), the healthcheck is
    probing liveness on an application that HAS readiness -> FAIL. If no source
    registers the probed path, or the app that serves it has no readiness route,
    the service has no readiness surface and is left alone.
  - if the healthcheck probes no HTTP path at all, the gate cannot see it consult
    readiness, so the service must carry an entry in
    docs/refactoring/health-claim-exemptions.json giving an owner and a REASON
    (the shape of docs/refactoring/structural-exemptions.json). An exemption that
    has expired, that names a service with no finding, or that gives no reason is
    itself a failure: a stale waiver is another claim nobody checks.

Both halves are DERIVED. The readiness surface is discovered by parsing route
registrations out of the source the service actually builds - not from a list in
this file - so deleting `/readyz` or adding a readiness route to a sidecar
changes this gate's verdict on the next run, and a new first-party service with a
healthcheck is enrolled the moment its compose block is written.

ON PARSING COMPOSE. This reads only the four keys it needs (build, image,
healthcheck.test, build.context) with an indentation scanner, because three of
the overlays carry the `!override` / `!reset` merge tags that a stdlib YAML
reader cannot take and this gate ships stdlib-only. Full-manifest validity is
`docker compose config`'s job; check_gate_coverage.py is what makes sure every
manifest reaches it.

WHAT IT DOES NOT CHECK. Whether the readiness endpoint is itself honest, and
whether a service without a readiness surface OUGHT to have one. fleet-worker is
the live example: it runs `python -m boltrig.api.worker`, a delegation pump with
no HTTP listener at all, so there is no endpoint for a healthcheck to consult. It
is not exempt from the goal - it already publishes a signed, short-lived
stack-tool receipt to Redis that the kernel's /readyz consumes
(boltrig/fleet/stack_tool_health.py), so a truthful check is buildable - but it
IS the case the exemption file exists for.

Usage:  python scripts/check_health_claims.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_guard import require_scanned  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXEMPTIONS = ROOT / "docs" / "refactoring" / "health-claim-exemptions.json"

# A path that answers "can I serve traffic", as opposed to "am I still running".
READINESS_PATHS = re.compile(r"^/(?:readyz|ready|readiness)/?$", re.IGNORECASE)

# First-party = this repo builds the image. `image:` alone is a third-party pin
# (postgres, redis, caddy, hatchet, ...) whose healthcheck is theirs, not ours.
FIRST_PARTY_IMAGE = "boltrig/"

SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".conf"}
# Not shipped in any image: build output, vendored dependencies, and the test
# doubles (a FastAPI app stood up in tests/ is not what the container runs). Any
# DOT-directory is skipped too - .venv, .mypy_cache, and in particular
# .claude/worktrees, an agent worktree that puts a SECOND copy of the whole repo
# inside the repo and would otherwise be cited as the file serving the route.
SKIP_DIRS = {
    "__pycache__", "node_modules", "dist", "build", "coverage",
    "site-packages", "tests", "test", "e2e",
}

_ROUTE_PATTERNS = (
    # FastAPI / Flask decorators: @app.get("/readyz"), @router.post('/x')
    re.compile(
        r"""@\w+(?:\.\w+)*\.(?:get|post|put|patch|delete|head|route|api_route)"""
        r"""\(\s*(['"])(/[^'"]*)\1"""
    ),
    # Programmatic registration: app.add_api_route("/readyz", ...)
    re.compile(r"""add_(?:api_)?route\(\s*(['"])(/[^'"]*)\1"""),
    # Express / node: app.get('/health', ...)
    re.compile(r"""\b(?:app|router|server)\.(?:get|post|put|all|use)\(\s*(['"`])(/[^'"`]*)\1"""),
    # nginx: location = /healthz {   /   location /v1/ {
    re.compile(r"""^\s*location\s+(?:=\s*)?(?P<one>/\S*)\s*\{""", re.MULTILINE),
)

# Evidence that a non-HTTP test at least touches the service's own surface. Its
# absence is what makes `python -c "import boltrig"` vacuous rather than merely
# shallow: the command names no host, no port and no endpoint.
_SERVING_HINTS = re.compile(
    r"\b(?:curl|wget|nc|netcat|socat|pg_isready|redis-cli|healthcheck\.sh|"
    r"localhost|127\.0\.0\.1|0\.0\.0\.0)\b"
)


# --------------------------------------------------------------------------- #
# Compose
# --------------------------------------------------------------------------- #
def _strip_tag(value: str) -> str:
    """Drop a Compose merge tag (`!override [] `, `!reset null`) from a scalar."""
    return re.sub(r"^![A-Za-z_][\w-]*\s*", "", value.strip()).strip()


def _flow_list(value: str) -> list[str]:
    inner = value.strip()[1:-1]
    out = []
    for part in inner.split(","):
        part = part.strip()
        if len(part) >= 2 and part[0] in "\"'" and part[-1] == part[0]:
            part = part[1:-1]
        if part:
            out.append(part)
    return out


def parse_services(path: Path) -> dict[str, dict]:
    """Extract {service: {build, context, image, test, test_line}} from a manifest.

    Deliberately partial - see the module docstring. It reads the `services:`
    mapping only, so the top-level `x-app-hardening` anchor, `networks:` and
    `volumes:` cannot be mistaken for services."""
    services: dict[str, dict] = {}
    service: str | None = None
    key: str | None = None      # the current indent-4 key
    sub: str | None = None      # `test` while reading its block list
    in_services = False

    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))

        if indent == 0:
            in_services = stripped == "services:"
            service = key = sub = None
            continue
        if not in_services:
            continue
        if indent == 2 and not stripped.startswith("-") and stripped.endswith(":"):
            service = stripped[:-1].strip()
            services.setdefault(
                service,
                {"build": False, "context": None, "image": None, "test": None, "test_line": 0},
            )
            key = sub = None
            continue
        if service is None:
            continue
        if indent == 4 and not stripped.startswith("-"):
            key, sub = None, None
            name, _, value = stripped.partition(":")
            key = name.strip()
            value = _strip_tag(value)
            if key == "image":
                services[service]["image"] = value
            elif key == "build":
                services[service]["build"] = True
                if value and value not in {"null", "~"}:
                    services[service]["context"] = value
            continue
        if indent == 6 and key == "build" and stripped.startswith("context:"):
            services[service]["context"] = _strip_tag(stripped.split(":", 1)[1])
            continue
        if indent == 6 and key == "healthcheck" and not stripped.startswith("-"):
            name, _, value = stripped.partition(":")
            sub = name.strip()
            value = _strip_tag(value)
            if sub == "test":
                services[service]["test_line"] = number
                if value.startswith("["):
                    services[service]["test"] = " ".join(_flow_list(value))
                elif value:
                    services[service]["test"] = value
                else:
                    services[service]["test"] = ""
            continue
        if indent >= 8 and sub == "test" and stripped.startswith("- "):
            item = stripped[2:].strip()
            if len(item) >= 2 and item[0] in "\"'" and item[-1] == item[0]:
                item = item[1:-1]
            current = services[service]["test"] or ""
            services[service]["test"] = f"{current} {item}".strip()
    return services


def compose_files() -> list[Path]:
    found = sorted((ROOT / "deploy").glob("compose*.yml"))
    base = ROOT / "docker-compose.yml"
    manifests = ([base] if base.exists() else []) + found
    # Scanning zero manifests would make "every health signal consults readiness"
    # vacuously true, which is the reading a truncated checkout produces.
    return list(require_scanned(manifests, "compose manifests to check healthchecks in"))


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
def routes_in(directory: Path) -> dict[Path, set[str]]:
    """Map each source file under `directory` to the HTTP paths it registers."""
    table: dict[Path, set[str]] = {}
    if not directory.is_dir():
        return table
    for parent, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
        )
        for filename in sorted(filenames):
            path = Path(parent) / filename
            if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            paths: set[str] = set()
            for pattern in _ROUTE_PATTERNS:
                for match in pattern.finditer(text):
                    groups = match.groupdict()
                    paths.add(groups["one"] if groups.get("one") else match.group(2))
            if paths:
                table[path] = paths
    return table


def probed_paths(test: str) -> list[str]:
    """Every HTTP path the healthcheck command dereferences."""
    out = []
    for url in re.findall(r"https?://[^\s'\"`)\\]+", test):
        path = urlsplit(url).path or "/"
        if path not in out:
            out.append(path)
    return out


# --------------------------------------------------------------------------- #
# Exemptions
# --------------------------------------------------------------------------- #
def _rel(path: Path) -> str:
    """Repo-relative when it can be, absolute when it cannot (tests point elsewhere)."""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def load_exemptions() -> tuple[dict[str, dict], list[str]]:
    if not EXEMPTIONS.exists():
        return {}, []
    try:
        data = json.loads(EXEMPTIONS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, [f"{_rel(EXEMPTIONS)} does not parse: {exc}"]
    entries = data.get("exemptions", {})
    problems: list[str] = []
    valid: dict[str, dict] = {}
    today = date.today()
    for name, entry in sorted(entries.items()):
        if not isinstance(entry, dict) or not str(entry.get("reason", "")).strip():
            problems.append(
                f"{name}: exemption gives no reason (a blank waiver is a blank claim)"
            )
            continue
        if not str(entry.get("owner", "")).strip():
            problems.append(f"{name}: exemption names no owner")
            continue
        expires = str(entry.get("expires", "")).strip()
        if expires:
            try:
                if date.fromisoformat(expires) < today:
                    problems.append(
                        f"{name}: exemption expired on {expires}; renew it or fix the check"
                    )
                    continue
            except ValueError:
                problems.append(f"{name}: expires={expires!r} is not an ISO date")
                continue
        valid[name] = entry
    return valid, problems


# --------------------------------------------------------------------------- #
def main() -> int:
    manifests = compose_files()
    if not manifests:
        print("FAIL: no compose manifests found", file=sys.stderr)
        return 1

    exempt, exempt_problems = load_exemptions()

    merged: dict[str, dict] = {}
    occurrences: list[tuple[str, Path, dict]] = []
    for manifest in manifests:
        for name, spec in parse_services(manifest).items():
            entry = merged.setdefault(
                name, {"build": False, "context": None, "image": None}
            )
            entry["build"] = entry["build"] or spec["build"]
            entry["context"] = entry["context"] or spec["context"]
            entry["image"] = entry["image"] or spec["image"]
            if spec["test"] is not None:
                occurrences.append((name, manifest, spec))

    route_cache: dict[Path, dict[Path, set[str]]] = {}
    findings: list[tuple[str, str, str]] = []
    waived: set[str] = set()
    rows: list[tuple[str, str, str, str]] = []

    for name, manifest, spec in occurrences:
        info = merged[name]
        image = info["image"] or ""
        first_party = info["build"] or image.startswith(FIRST_PARTY_IMAGE)
        where = f"{manifest.relative_to(ROOT).as_posix()}:{spec['test_line']}"
        if not first_party:
            rows.append((name, where, "third-party", "skipped"))
            continue

        test = spec["test"] or ""
        paths = probed_paths(test)
        if any(READINESS_PATHS.match(p) for p in paths):
            rows.append((name, where, "readiness", "ok"))
            continue

        if not paths:
            vacuous = not _SERVING_HINTS.search(test)
            detail = (
                "the test names no host, port or endpoint of its own service, so it "
                "cannot distinguish serving from process-exists"
                if vacuous
                else "the test probes no HTTP path, so this gate cannot see it consult readiness"
            )
            # Waive AFTER deriving the finding, never before: an exemption that
            # short-circuits the check can outlive the thing it waives, which is
            # the same defect one level up.
            if name in exempt:
                waived.add(name)
                rows.append((name, where, "no-http", "exempt"))
                continue
            rows.append((name, where, "no-http", "FAIL"))
            findings.append((name, where, f"{detail}: {test.strip()!r}"))
            continue

        context = ROOT / (info["context"] or ".")
        try:
            context = context.resolve()
            context.relative_to(ROOT)
        except (OSError, ValueError):
            context = ROOT
        if context not in route_cache:
            route_cache[context] = routes_in(context)
        table = route_cache[context]

        serving: list[tuple[Path, set[str]]] = [
            (path, registered)
            for path, registered in table.items()
            if registered & set(paths)
        ]
        with_readiness = [
            (path, registered)
            for path, registered in serving
            if any(READINESS_PATHS.match(p) for p in registered)
        ]
        if with_readiness:
            path, registered = with_readiness[0]
            ready = sorted(p for p in registered if READINESS_PATHS.match(p))
            if name in exempt:
                waived.add(name)
                rows.append((name, where, ", ".join(paths), "exempt"))
                continue
            rows.append((name, where, ", ".join(paths), "FAIL"))
            findings.append((
                name,
                where,
                f"probes {', '.join(paths)} (liveness) while "
                f"{path.relative_to(ROOT).as_posix()} also serves {', '.join(ready)}",
            ))
        elif serving:
            rows.append((name, where, ", ".join(paths), "ok (no readiness route)"))
        else:
            rows.append((name, where, ", ".join(paths), "ok (no route source found)"))

    print("Container health signals vs the readiness their application serves")
    print("-" * 92)
    print(f"{'service':<20}{'declared at':<34}{'probes':<22}status")
    print("-" * 92)
    for name, where, probe, status in rows:
        print(f"{name:<20}{where:<34}{probe[:21]:<22}{status}")
    print("-" * 92)
    checked = sum(1 for row in rows if row[2] != "third-party")
    print(
        f"manifests={len(manifests)}  healthchecks={len(rows)}  first_party={checked}  "
        f"findings={len(findings)}  exemptions={len(exempt)}"
    )

    if findings:
        print(
            "\nHEALTHY-BUT-UNABLE-TO-SERVE "
            "(a health signal that cannot go red for a real outage):"
        )
        for name, where, detail in findings:
            print(f"  - {name} ({where})")
            print(f"      {detail}")
        print(
            f"\n  Point the healthcheck at readiness, or record why it cannot be in\n"
            f"  {_rel(EXEMPTIONS)} with an owner and a reason."
        )
    if exempt_problems:
        print("\nEXEMPTION FILE PROBLEMS:")
        for problem in exempt_problems:
            print(f"  - {problem}")

    stale = sorted(set(exempt) - waived)
    if stale:
        print("\nSTALE EXEMPTIONS (nothing left to waive; delete them):")
        for name in stale:
            print(f"  - {name}")

    if findings or exempt_problems or stale:
        print("\nRESULT: FAIL - a service can report healthy while unable to serve.")
        return 1
    print("\nRESULT: PASS - every first-party health signal consults readiness or is "
          "recorded as unable to.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
