#!/usr/bin/env python3
"""Re-register a BUILTIN adapter's verbs so a declarative spec change lands.

A builtin adapter's VerbSpec data (consequence, schemas, description, rate
limit) is authored in code but SERVED from the store. `_rehydrate_store_adapters`
only rebuilds live instances it can reconstruct honestly, and a builtin row is
not one of them, so a builtin registered into a tenant once keeps its ORIGINAL
verb rows forever - a later code change never reaches that tenant.

That matters for calibration: `[2026] VJS-APPEAL 1` (LJ-2) says a
mis-classified verb is fixed as DATA, and `scripts/calibration-audit.py` reads
the STORE. So after changing a builtin's VerbSpec, run this against each tenant
that has the adapter registered, or the code says HIGH while the kernel still
gates on LOW.

It goes through `Kernel.register_adapter`, the same seam boot uses - no SQL, so
nouns, bindings and rate limits stay consistent with the specs.

Usage:
  scripts/resync-builtin-verbs.py ms_graph                 # session tenant
  scripts/resync-builtin-verbs.py ms_graph --tenant acme
  scripts/resync-builtin-verbs.py ms_graph --dry-run       # report, change nothing
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect


def _load_builtin(name: str):
    """The builtin adapter instance for ``name`` (module under adapters.builtin)."""
    module = importlib.import_module(f"boltrig.adapters.builtin.{name}")
    build = getattr(module, "build", None)
    if build is None:
        raise SystemExit(f"boltrig.adapters.builtin.{name} exposes no build()")
    return build()


async def _run(name: str, tenant: str, dry_run: bool) -> int:
    from boltrig.api.bootstrap import build_store
    from boltrig.kernel import Kernel
    from boltrig.store.postgres import set_current_tenant

    adapter = _load_builtin(name)
    specs = {spec.verb_id: spec for spec in adapter.describe()}
    store = await build_store()
    try:
        set_current_tenant(tenant)
        stored = {v.id: v for v in await store.list_verbs(tenant)}
        drift = [
            (vid, stored[vid].consequence.value, spec.consequence)
            for vid, spec in specs.items()
            if vid in stored and stored[vid].consequence.value != spec.consequence
        ]
        missing = sorted(vid for vid in specs if vid not in stored)
        print(f"{name} -> tenant '{tenant}': {len(specs)} declared verb(s), "
              f"{len(drift)} with drifted consequence, {len(missing)} not in the store.")
        for vid, was, now in sorted(drift):
            print(f"    {vid}: store={was} -> code={now}")
        for vid in missing:
            print(f"    {vid}: absent from the store (will be registered)")
        if dry_run:
            print("  --dry-run: nothing written.")
            return 0
        if not drift and not missing:
            print("  already in sync; nothing to write.")
            return 0
        kernel = Kernel(store)
        registered = await kernel.register_adapter(tenant, adapter)
        print(f"  re-registered {len(registered)} verb(s) through the kernel seam.")
        return 0
    finally:
        close = getattr(store, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-register a builtin adapter's verbs.")
    parser.add_argument("adapter", help="builtin module name, e.g. ms_graph")
    parser.add_argument("--tenant", default=None, help="tenant (default: session tenant)")
    parser.add_argument("--dry-run", action="store_true", help="report drift, write nothing")
    args = parser.parse_args(argv)
    from boltrig.config import load_settings

    tenant = args.tenant or load_settings().session_tenant or "default"
    return asyncio.run(_run(args.adapter, tenant, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
