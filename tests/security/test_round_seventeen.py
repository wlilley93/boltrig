"""Round Seventeen - container runtime hardening (INF-01, SEC-64).

A deploy-lint that pins the hardening so it cannot silently regress (the SEC-48
pattern). Runtime verification (the containers actually start read-only) needs a
live docker host and is a Principal/ops step.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]

# Our first-party app containers (run our code) must be hardened.
_APP_SERVICES = ("kernel", "fleet-worker")


@pytest.mark.security
@pytest.mark.invariant("SEC-64")
def test_app_containers_are_hardened():
    compose = yaml.safe_load((_REPO / "docker-compose.yml").read_text())
    services = compose["services"]
    for name in _APP_SERVICES:
        svc = services[name]
        assert svc.get("read_only") is True, f"{name} not read_only"
        assert "ALL" in (svc.get("cap_drop") or []), f"{name} does not drop ALL caps"
        assert any("no-new-privileges" in o for o in (svc.get("security_opt") or [])), name
        assert svc.get("pids_limit"), f"{name} has no pids_limit"
        assert svc.get("mem_limit"), f"{name} has no mem_limit"
        # read-only needs a writable tmpfs for /tmp
        assert any("/tmp" in t for t in (svc.get("tmpfs") or [])), f"{name} has no tmpfs /tmp"


@pytest.mark.security
@pytest.mark.invariant("SEC-64")
def test_app_images_run_non_root():
    # every first-party Dockerfile must declare a non-root USER (INF-01).
    for df in ("deploy/kernel.Dockerfile", "deploy/fleet.Dockerfile"):
        text = (_REPO / df).read_text()
        users = re.findall(r"^USER\s+(\S+)", text, re.MULTILINE)
        assert users, f"{df} declares no USER (runs as root)"
        assert users[-1] not in {"root", "0"}, f"{df} final USER is root"
