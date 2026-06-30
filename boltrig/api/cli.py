"""The ``boltrig`` command line. Thin front door over the entrypoints.

    boltrig serve [--host H --port P]   start the kernel API
    boltrig worker                      start a fleet worker
    boltrig smoke                       run the offline in-process smoke test
    boltrig check-invariants            run the invariant-binding gate (K-29/K-30)
    boltrig version                     print the version
"""

from __future__ import annotations

import argparse
import os
import runpy
import sys

from boltrig import __version__


def _repo_script(name: str) -> str | None:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(here, "scripts", name)
    return path if os.path.exists(path) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="boltrig")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="start the kernel API")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("worker", help="start a fleet worker")
    sub.add_parser("smoke", help="offline in-process smoke test")
    sub.add_parser("check-invariants", help="run the invariant-binding gate")
    sub.add_parser("version", help="print version")

    args = parser.parse_args(argv)

    if args.cmd == "version":
        print(__version__)
        return 0
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("boltrig.api.asgi:app", host=args.host, port=args.port)
        return 0
    if args.cmd == "worker":
        from .worker import main as worker_main

        worker_main()
        return 0
    if args.cmd in ("smoke", "check-invariants"):
        script = _repo_script("smoke.py" if args.cmd == "smoke" else "check_invariants.py")
        if not script:
            print(f"script for '{args.cmd}' not found", file=sys.stderr)
            return 2
        runpy.run_path(script, run_name="__main__")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
