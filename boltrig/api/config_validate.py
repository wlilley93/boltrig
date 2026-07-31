"""``boltrig config-validate`` - parse a manifest with the SHIPPING code (task #59).

THE FINDING THIS EXISTS FOR. Rolling prod from alembic 0040 to 0066 the database
pre-flight was genuinely thorough - 26 migrations AST-classified, the one
destructive op measured against live data, the whole chain rehearsed against a
restore - and the deploy still crash-looped, on
``SpawnRuleValidationError: spawn_rules[0] is missing required fields: priority``.
Every check had been about SCHEMA. The manifest is the other half of what the
process needs to boot, and it has none of the schema's machinery: no version
chain, no recorded head, no parity gate. A required field with no default is a
breaking change to every deployment's config, and it shipped with no notice.

So: parse each target's manifest with the code that will read it, and exit
non-zero on rejection. Run it with the CANDIDATE IMAGE before swapping:

    docker run --rm -v /path/to/manifest.yaml:/m.yaml:ro <image> \\
        boltrig config-validate /m.yaml

That one command turns the crash-loop class into a pre-flight failure, which is
the whole fix and it is small.

WHAT "VALID" MEANS HERE: ``load_manifest`` accepts it - the same call
``bootstrap`` makes at boot, including ``${ENV}`` interpolation and every frozen
dataclass's validation (spawn rules included, which is the exact rejection that
crash-looped prod). It does NOT mean the deployment will work: credentials may
be wrong, endpoints unreachable. Those are the doctor's and readiness's jobs.
This answers only "will the process get past config", which is precisely the
question nothing answered on 2026-07-31.

ENV INTERPOLATION AND THE FALSE-RED TRAP. ``${VAR}`` references resolve against
THIS process's environment. Run inside the candidate image with the target's env
file (``--env-file``) for the truest answer; run bare, a manifest can fail on an
unset variable that IS set in production. That failure direction is safe (a
false red, never a false green) and the message names the variable.
"""

from __future__ import annotations

import sys


def main(path: str) -> int:
    target = (path or "").strip()
    if not target:
        print("config-validate: a manifest path is required", file=sys.stderr)
        return 2
    from boltrig.config import load_manifest

    try:
        manifest = load_manifest(target)
    except FileNotFoundError:
        print(f"config-validate: no manifest at {target}", file=sys.stderr)
        return 2
    except Exception as exc:
        # The exception TYPE is part of the answer: SpawnRuleValidationError vs
        # a YAML parse error vs a missing env var want different fixes.
        print(
            f"config-validate: REFUSED - the shipping loader rejects {target}:\n"
            f"  {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    print(
        f"config-validate: OK - {target} parses with this build "
        f"(tenant={manifest.tenant_id}, adapters={len(manifest.adapters)}, "
        f"spawn_rules={len(manifest.spawn_rules)})"
    )
    return 0
