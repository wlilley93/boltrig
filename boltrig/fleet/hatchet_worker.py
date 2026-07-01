"""A live Hatchet worker serving the Boltrig durable tasks (Beat 5).

Run as a process: ``python -m boltrig.fleet.hatchet_worker`` (needs the HATCHET_*
env + a reachable engine). Serves the three registered tasks (boltrig-invoke /
boltrig-work-item / boltrig-workflow-run); the worker-owned kernel + org pump
are built lazily inside the first task body, on the worker's running loop, by
the default bootstrap (hatchet_app._default_bootstrap, mirroring api/worker.py).
"""

from __future__ import annotations


def main() -> None:
    from .hatchet_app import build_hatchet_app

    hatchet, workflows = build_hatchet_app()
    worker = hatchet.worker(
        "boltrig-live", slots=4, durable_slots=4, workflows=list(workflows.values())
    )
    worker.start()


if __name__ == "__main__":
    main()
