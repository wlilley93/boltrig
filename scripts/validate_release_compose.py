"""Validate the fully merged digest-addressed Boltrig Compose model."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# `scripts/` is not a package and this file is run as a PATH, not a module, so
# sys.path[0] is scripts/ and not the checkout root - which is the only reason
# the first-party import below could not resolve. Nothing here needs installing:
# boltrig.release_mode is pure stdlib and ships in the tree, and `import boltrig`
# from the repo root works on a bare interpreter. Adding the root to the path is
# what keeps "no dependency install needed" true for the compose-validate job,
# without duplicating the one definition of the admitted release modes that
# boltrig/release_mode.py exists to be.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from boltrig.release_mode import RELEASE_MODE_ENV, validate_release_mode  # noqa: E402

# "pi-sidecar" was the fifth entry until the Pi lane was retired
# ([2026] VJS-PC 20 L1). It is not merely unpinned now, it does not exist: the
# loop below fails on a MISSING service as loudly as on an unpinned one, so a
# stale entry here would break every release rather than pass quietly.
FIRST_PARTY_SERVICES = (
    "kernel",
    "fleet-worker",
    "hatchet-worker",
    "worker-ui",
    "backup",
)
_UNADMITTED_CHANNEL_SERVICES = frozenset({"channel-gateway", "whatsapp-bridge"})
_DIGEST_IMAGE = re.compile(r"^[^\s@=]+@sha256:[0-9a-f]{64}$")


def _reject_unadmitted_channels(services: dict[str, Any]) -> None:
    active = []
    for name, service in services.items():
        profiles = service.get("profiles", ()) if isinstance(service, dict) else ()
        if name in _UNADMITTED_CHANNEL_SERVICES or "channels" in profiles:
            active.append(name)
    if active:
        rendered = ", ".join(sorted(active))
        raise ValueError(
            "release channels posture is not admitted: channel-gateway/"
            "whatsapp-bridge are not release-digest images and no secure provider "
            f"egress is shipped (active: {rendered})"
        )


def _validate_release_mode_binding(services: dict[str, Any]) -> None:
    bound_modes: dict[str, str] = {}
    for name in ("kernel", "fleet-worker", "hatchet-worker"):
        service = services.get(name)
        environment = service.get("environment") if isinstance(service, dict) else None
        value = environment.get(RELEASE_MODE_ENV) if isinstance(environment, dict) else None
        try:
            if not isinstance(value, str):
                raise ValueError("release mode binding is not text")
            bound_modes[name] = validate_release_mode(value)
        except ValueError as exc:
            raise ValueError(
                f"release service {name} has no exact {RELEASE_MODE_ENV} binding"
            ) from exc
    if len(set(bound_modes.values())) != 1:
        raise ValueError("release services disagree on BOLTRIG_RELEASE_MODE")


def validate_release_compose(document: dict[str, Any], *, secure: bool) -> None:
    """Reject unshipped services, mutable code, or exposed sensitive models."""
    services = document.get("services")
    if not isinstance(services, dict):
        raise ValueError("merged Compose model has no services mapping")
    _reject_unadmitted_channels(services)
    for name in FIRST_PARTY_SERVICES:
        service = services.get(name)
        if not isinstance(service, dict):
            raise ValueError(f"merged Compose model has no {name} service")
        if service.get("build") is not None:
            raise ValueError(f"release service {name} still has a build definition")
        image = service.get("image")
        if not isinstance(image, str) or not _DIGEST_IMAGE.fullmatch(image):
            raise ValueError(f"release service {name} is not pinned by image digest")
    _validate_release_mode_binding(services)
    if services["hatchet-worker"]["image"] != services["fleet-worker"]["image"]:
        raise ValueError("release Hatchet worker does not use the fleet-worker image digest")
    hatchet_worker = services["hatchet-worker"]
    healthcheck = hatchet_worker.get("healthcheck")
    health_test = healthcheck.get("test") if isinstance(healthcheck, dict) else None
    rendered_health_test = " ".join(health_test) if isinstance(health_test, list) else str(health_test or "")
    if "127.0.0.1:8001/health" not in rendered_health_test:
        raise ValueError("release Hatchet worker has no listener-heartbeat healthcheck")
    worker_environment = hatchet_worker.get("environment")
    if not isinstance(worker_environment, dict) or str(
        worker_environment.get("HATCHET_CLIENT_WORKER_HEALTHCHECK_ENABLED", "")
    ).lower() != "true":
        raise ValueError("release Hatchet worker health server is not enabled")

    backup_volumes = services["backup"].get("volumes") or []
    if any(volume.get("target") == "/usr/local/bin/backup.sh" for volume in backup_volumes):
        raise ValueError("release backup service replaces signed code with a source mount")

    local_model_ports = services.get("local-model", {}).get("ports") or []
    if secure:
        if local_model_ports:
            raise ValueError("secure release publishes the sensitive local-model port")
    elif not local_model_ports or any(
        port.get("host_ip") != "127.0.0.1" for port in local_model_ports
    ):
        raise ValueError("base release local-model ports must be loopback-only")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secure", action="store_true")
    args = parser.parse_args()
    try:
        document = json.load(sys.stdin)
        validate_release_compose(document, secure=args.secure)
    except (json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print("merged release Compose model valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
