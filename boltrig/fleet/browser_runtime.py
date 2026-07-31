"""Whether this deployment runs the fleet image's Chromium at all.

Chromium is the largest attack surface the fleet image carries. It runs headless
with ``--no-sandbox`` behind a loopback CDP port for the whole life of the worker,
and it is the package the fleet's standing HIGH advisories are filed against - the
sandbox-escape class in particular, which ``--no-sandbox`` disables the defence
for by construction. Until 2026-07-31 the entrypoint started it unconditionally,
so every tenant ran a permanent unsandboxed browser whether or not it had ever
asked for browser automation. Classical Visas was one: six governed browser verbs
registered, zero invocations ever, and a Chromium up since boot.

Three consumers must answer this question the SAME way or the deployment breaks:
the entrypoint that STARTS the browser, the heartbeat that PROBES it, and the
readiness gate that REQUIRES it. A gate demanding a tool the entrypoint stopped
starting is an outage, so the answer lives here once and all three import it.

The predicate itself is the manifest's, not a second copy: it delegates to
``needs_browser_cli``, the same three-limb test the doctor uses (a
``stack.browser_automation`` of ``browser_cli``, a truthy ``browser_cli.enabled``,
or a ``browser-cli`` entry under ``adapters``).

An unreadable or absent manifest answers FALSE, and that direction is deliberate.
The cost of a false negative is a loud failure the first time somebody asks for a
browser. The cost of a false positive is an unsandboxed browser running for months
on a tenant that never asked for one, which is exactly the state this replaces.
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("boltrig.fleet.browser_runtime")

DEFAULT_MANIFEST_PATH = "/app/manifest.yaml"

__all__ = ["DEFAULT_MANIFEST_PATH", "browser_automation_wanted", "main"]


def _manifest_path(manifest_path: str | None) -> str:
    if manifest_path is not None:
        return manifest_path.strip()
    return (os.environ.get("BOLTRIG_MANIFEST") or DEFAULT_MANIFEST_PATH).strip()


def browser_automation_wanted(manifest_path: str | None = None) -> bool:
    """True iff the tenant's manifest declares browser automation, per
    ``needs_browser_cli``.

    Never raises. A missing file, unparseable YAML or a manifest ``load_manifest``
    rejects all answer False - see the module docstring for why that is the safe
    direction rather than the convenient one.
    """
    path = _manifest_path(manifest_path)
    if not path or not os.path.isfile(path):
        log.info("browser automation disabled: no manifest at %s", path or "(unset)")
        return False
    try:
        from boltrig.api.doctor_stack_state import needs_browser_cli
        from boltrig.config.manifest import load_manifest

        return bool(needs_browser_cli(load_manifest(path)))
    except Exception:
        # No exception detail: a manifest carries ${ENV} interpolations and a
        # loader error can quote them. The posture is the fact worth logging.
        log.warning("browser automation disabled: manifest at %s is unreadable", path)
        return False


def main(argv: list[str] | None = None) -> int:
    """``python -m boltrig.fleet.browser_runtime`` - exit 0 iff wanted.

    The exit code IS the answer, so the shell entrypoint needs no parsing and no
    string comparison: ``if python -m boltrig.fleet.browser_runtime; then ...``.
    """
    args = sys.argv[1:] if argv is None else argv
    path = args[0] if args else None
    return 0 if browser_automation_wanted(path) else 1


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
