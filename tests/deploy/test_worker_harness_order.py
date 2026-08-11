"""Runtime-image hygiene and CI gating for the Worker.

These two guarantees were bound to the retired `ui/` frontend by
tests/deploy/test_ui_harness_order.py, which went with it. The subject moved;
the requirement did not. The Worker is now the only tenant-facing browser image,
so it inherits both directives — and without this file the court's order would
be enforced by nothing at all, which is exactly what the order-directives gate
exists to catch.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "apps/worker/Dockerfile"
CI = ROOT / ".github/workflows/ci.yml"


def test_the_worker_build_is_a_gating_ci_job() -> None:
    """[2026] VJS-COUNTY 2 D4.

    "A gating CI job running the smoke as a required status check." Present is
    not enough — the job has to be one the gate REFUSES to pass without.
    """
    ci = CI.read_text(encoding="utf-8")
    assert "worker-build:" in ci, "the worker build job is gone from CI"
    assert "- worker-build" in ci, (
        "no gate job lists worker-build in `needs`, so it could fail without "
        "blocking anything - COUNTY 2 D4 required a REQUIRED check"
    )
    assert 'needs.worker-build.result' in ci, (
        "the gate job does not assert worker-build's result, so it is merely "
        "sequenced after it rather than gated on it"
    )


def test_the_worker_runtime_image_is_nginx_and_dist_only() -> None:
    """[2026] VJS-COUNTY 2 D5.

    "Prove runtime image hygiene - nginx plus dist only - and keep
    ignore-scripts in the docker build stage."
    """
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "--ignore-scripts" in dockerfile, (
        "the build stage no longer passes --ignore-scripts, so any dependency's "
        "install hook runs with the build's privileges"
    )

    stages = dockerfile.split("FROM ")
    runtime = stages[-1]
    assert runtime.lstrip().startswith("nginx:"), (
        f"the runtime stage is not nginx: {runtime.splitlines()[0]}"
    )
    for line in runtime.splitlines():
        if line.startswith("COPY --from="):
            source = line.split()[1].split("=", 1)[1] if "=" in line.split()[1] else line.split()[2]
            source = line.split()[2] if not source.startswith("/") else source
            assert source.rstrip("/").endswith("dist"), (
                f"the runtime image copies {source} out of the build stage; "
                "COUNTY 2 D5 required dist ONLY, so a tenant-facing image never "
                "carries the toolchain"
            )
