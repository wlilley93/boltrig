# Pre-arc preflight: tool availability log

Captured 2026-07-01 for arc-1. Per the preflight rule "if a tool is unavailable,
write a stub artefact noting the skip; do not block the wave."

## Available + run (deterministic wave 4a)

| Tool | Status | Artefact |
|---|---|---|
| ruff | ran | `ruff.json` (2 findings) |
| bandit | ran | `bandit.json` (0 HIGH, 2 MED, 10 LOW) |
| semgrep (p/python) | ran | `semgrep.json` (0 findings) |
| pip-audit | ran | `pip-audit.txt` (0 PyPI vulns) |
| atomize (AST substitute) | ran | `atomize.json` (structural metrics) |
| API surface capture | ran | `../api-surface-snapshots/round-1-routes.txt` (72 routes) |

## Unavailable / broken (substituted or skipped)

| Tool | Status | Handling |
|---|---|---|
| vibeclean | BROKEN (`ModuleNotFoundError: vibeclean`) | Substituted by `atomize_scan.py` (stdlib AST + McCabe): file LOC, function length, cyclomatic complexity, nesting depth, param count. Same structural-floor metrics, deterministic, no external dep. |
| vibescan | BROKEN (no output, exits silently) | Its constituent scanners (bandit, pip-audit, semgrep) are run directly above; equivalent coverage for this Python repo. |
| radon | missing | Complexity computed in `atomize_scan.py` (McCabe via AST). |
| mypy / tsc | n/a | Boltrig is Python; ruff is the configured static check (no mypy configured). |
| prisma validate / npm audit | n/a | No JS/Prisma stack. |
| SOC 2 ripgrep script | not authored | `scripts/audit-soc2-compliance.sh` does not exist. SOC 2 obligations are real (multi-tenant, SSO, audit, encryption) but the tribal-knowledge script is a documented gap, not proof of absence. `PREFLIGHT.SECURITY_SUITE_REQUIRED` left default. |
| ui-* scanners | n/a | Boltrig kernel has no UI surface in scope (the marketing site + console are separate Next.js trees not in this repo's `boltrig/` package). |

## vibeaudit (LLM deep scan, wave 4b)

Not dispatched as a subprocess. The 13-section security-methodology reasoning was
performed by the orchestrating agent directly over the repo (full read access),
which is the same reasoning `vibeaudit --deep` delegates to a CLI session. Output
is folded into `findings.md` under the `methodology` source. Rationale: spawning a
`claude` CLI subprocess from inside this session is the wrong context and gains no
coverage over a direct read.
