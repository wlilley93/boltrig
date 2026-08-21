"""Rebind .vds/ledgers/routes.yaml to the route manifest it is the ledger OF.

The gate asserts `ledger == source` after both are parsed, so this is a format
translation and nothing else: the manifest is the authority and the ledger is
its canonical YAML output. Regenerated rather than hand-edited because the
contentDigest witnesses the content, and a hand edit that misses one field
produces a ledger that parses, passes review and witnesses the wrong tree.

THE ROOT IS DERIVED FROM THIS FILE, NEVER TYPED. It was hardcoded to an absolute
path naming ONE worktree (/home/jellytot/boltrig-fixtree). Several worktrees
share this git dir, so running the script from any other one silently rebound
that worktree's ledger against this worktree's manifest and reported success:
the run looks identical either way, and the damage lands in a tree nobody is
looking at. Anchoring on __file__ makes the script operate on the checkout it
was invoked from, which is the only checkout the caller can reason about.
"""
import json
import pathlib

import yaml

root = pathlib.Path(__file__).resolve().parent.parent
src = root / "docs/design/evidence/2026-08-11-console-parity/current/vds-route-manifest.json"
dst = root / ".vds/ledgers/routes.yaml"

manifest = json.loads(src.read_text())
before = yaml.safe_load(dst.read_text())

# Key order is the manifest's, so a diff of the ledger reads like a diff of the
# manifest rather than an alphabetical reshuffle.
text = yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False,
                      width=10**6, allow_unicode=True)
dst.write_text(text)

after = yaml.safe_load(dst.read_text())
assert after == manifest, "ledger does not round-trip to its source"
changed = [k for k in manifest if before.get(k) != manifest[k]]
print("rebound fields:", changed or "(none)")
