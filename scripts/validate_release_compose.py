"""Validate the fully merged digest-addressed Boltrig Compose model."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

# "pi-sidecar" was the fifth entry until the Pi lane was retired
# ([2026] VJS-PC 20 L1). It is not merely unpinned now, it does not exist: the
# loop below fails on a MISSING service as loudly as on an unpinned one, so a
# stale entry here would break every release rather than pass quietly.
FIRST_PARTY_SERVICES = ("kernel", "fleet-worker", "ui", "backup")
_DIGEST_IMAGE = re.compile(r"^[^\s@=]+@sha256:[0-9a-f]{64}$")


def validate_release_compose(document: dict[str, Any], *, secure: bool) -> None:
    """Reject builds, mutable images, source-mounted backup code, or exposed models."""
    services = document.get("services")
    if not isinstance(services, dict):
        raise ValueError("merged Compose model has no services mapping")
    for name in FIRST_PARTY_SERVICES:
        service = services.get(name)
        if not isinstance(service, dict):
            raise ValueError(f"merged Compose model has no {name} service")
        if service.get("build") is not None:
            raise ValueError(f"release service {name} still has a build definition")
        image = service.get("image")
        if not isinstance(image, str) or not _DIGEST_IMAGE.fullmatch(image):
            raise ValueError(f"release service {name} is not pinned by image digest")

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
