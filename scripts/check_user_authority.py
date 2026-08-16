#!/usr/bin/env python3
"""Every active user must resolve to usable authority. Run against a live tenant.

WHY THIS EXISTS. On one deployment, a client's own account could log in, had a
password, and read ``role=admin``.
It also had zero authority. Two independent causes, either one fatal, both silent:

  * its ``scope`` was ``{}``. Grants derive from SCOPE, not from role
    (``grants_for_scope``), so ``{}`` yields ``allow=()`` and every verb is denied -
    while ``role`` still read ``admin``. It LOOKED like an administrator and had no
    authority at all. It had been provisioned ``source=invitation``, and the
    invitation carried no scope;
  * its role, ``admin``, was absent from ``chat.skills_by_role`` and
    ``default_skills`` was ``[]``, so it loaded no skills either.

Every turn that user took had zero tools. Nothing in the log or the ledger said so.
It simply looked like the agent was useless, which is the worst way for a client to
meet a defect.

Fail-closed is right. Fail-SILENT is the bug, and it is invisible precisely because
nothing errors: the turn completes, the agent apologises, and the record shows a
turn that did nothing wrong.

WHAT IT CHECKS, per active user:
  1. ``scope`` resolves to a NON-EMPTY grant set. This is the field authority
     actually comes from. Checking org/workspace membership instead would be the
     wrong signal: a missing workspace row applies no NARROWING
     (``effective_grants_for_request``), it does not zero the grants.
  2. the role maps to a non-empty skill set via chat.skills_by_role, falling back
     to chat.default_skills (else: no tools)
  3. every skill named for that role actually exists in the store (a missing skill
     is skipped fail-closed at turn time, so a role can be mapped and still empty)
  4. ROLE/SCOPE DIVERGENCE is called out by name: a user whose role implies
     authority while its scope grants none is the exact shape of this defect.

Usage:
    DSN=... MANIFEST=/app/manifest.yaml python3 check_user_authority.py

Exits non-zero when any active user would get no tools.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys


def _norm(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


async def main() -> int:
    import asyncpg  # imported here so --help works without the driver
    import yaml

    from boltrig.identity.rbac import grants_for_scope

    dsn = os.environ.get("DSN") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("check_user_authority: set DSN or DATABASE_URL", file=sys.stderr)
        return 2
    manifest_path = os.environ.get("MANIFEST", "/app/manifest.yaml")
    try:
        chat = (yaml.safe_load(open(manifest_path).read()) or {}).get("chat") or {}
    except OSError as exc:
        print(f"check_user_authority: cannot read {manifest_path}: {exc}", file=sys.stderr)
        return 2
    by_role: dict = chat.get("skills_by_role") or {}
    default_skills: list = chat.get("default_skills") or []

    conn = await asyncpg.connect(_norm(dsn))
    try:
        users = await conn.fetch(
            "select id, role, status, scope from users where status = 'active'"
        )
        org = {r["user_id"] for r in await conn.fetch("select user_id from org_members")}
        ws = {r["user_id"] for r in await conn.fetch("select user_id from workspace_members")}
        known_skills = {r["id"] for r in await conn.fetch("select id from skills")}
    finally:
        await conn.close()

    print(f"users(active)={len(users)} org_members={len(org)} workspace_members={len(ws)}")
    print(f"skills_by_role roles: {sorted(by_role)}   default_skills: {default_skills}")

    failures: list[str] = []
    for u in users:
        uid, role = u["id"], u["role"]
        problems = []
        scope = u["scope"]
        if isinstance(scope, str):
            scope = json.loads(scope or "{}")
        grants = grants_for_scope(scope or {})
        if not grants.allow:
            problems.append(
                f"scope={scope!r} grants NOTHING (grants come from scope, not role) "
                f"- role reads {role!r}, which diverges from its actual authority"
            )
        named = list(by_role.get(role, default_skills))
        resolvable = [s for s in named if s in known_skills]
        if not named:
            problems.append(f"role {role!r} is not in skills_by_role and default_skills is empty")
        elif not resolvable:
            problems.append(f"role {role!r} names {named} but none exist in the store")
        mark = "FAIL" if problems else "ok  "
        notes = []
        if uid not in org:
            notes.append("no org membership")
        if uid not in ws:
            notes.append("no workspace membership")
        extra = f"  ({', '.join(notes)})" if notes else ""
        print(
            f"  [{mark}] {uid:<32} role={role:<12} "
            f"grants={len(grants.allow)} skills={resolvable}{extra}"
        )
        for p in problems:
            print(f"          {p}")
        if problems:
            failures.append(uid)

    if failures:
        print(f"\nFAIL: {len(failures)} active user(s) would get NO TOOLS: {', '.join(failures)}")
        print("A turn by these users completes, apologises, and records nothing wrong.")
        return 1
    print("\nPASS: every active user resolves to usable authority.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
