"""A live Hatchet worker serving the Nankle workflows (P1-1).

Run as a process: ``python -m nankle.fleet.hatchet_worker`` (needs the HATCHET_*
env + a reachable engine). Serves both the plain ``ping`` workflow and the
durable HITL backbone.
"""

from __future__ import annotations


def main() -> None:
    from .hatchet_app import build_hatchet_app

    hatchet, workflows = build_hatchet_app()
    worker = hatchet.worker(
        "nankle-live", slots=4, durable_slots=4, workflows=list(workflows.values())
    )
    worker.start()


if __name__ == "__main__":
    main()
