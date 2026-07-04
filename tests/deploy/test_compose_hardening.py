"""Deploy hardening lint (M8/M9/M10, SEC-70/SEC-71).

Offline assertions over the compose manifests - no docker required. They pin the
audit fixes so they cannot silently regress (the SEC-48/SEC-64 deploy-lint
pattern):

  - M8: Hatchet's engine (plaintext gRPC + API) and its unauthenticated dashboard
    must not publish on 0.0.0.0 in the base compose (loopback-only), and the
    secure overlay must drop their host ports entirely (ports: []).
  - M9: POSTGRES_PASSWORD must have no literal default (compose required-var form)
    so the stack refuses to start unset, and the Hatchet DSN must interpolate the
    password rather than hardcode boltrig:boltrig.
  - M10: a scheduled backup sidecar ships in the base compose, profile-gated so
    the dev stack is unaffected, running scripts/backup.sh.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# Docker Compose supports !override / !reset merge tags (compose v2.24+). PyYAML
# does not know them by default, so register a passthrough constructor for our
# offline lint so that `ports: !override []` parses as an empty list.
def _compose_tag_constructor(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


yaml.SafeLoader.add_constructor("!override", _compose_tag_constructor)
yaml.SafeLoader.add_constructor("!reset", _compose_tag_constructor)


_REPO = Path(__file__).resolve().parents[2]
_BASE = _REPO / "docker-compose.yml"
_SECURE = _REPO / "deploy" / "compose.secure.yml"

_HATCHET_SERVICES = ("hatchet-engine", "hatchet-dashboard")


def _base() -> dict:
    return yaml.safe_load(_BASE.read_text())


def _secure() -> dict:
    return yaml.safe_load(_SECURE.read_text())


def _host_ports(service: dict) -> list[str]:
    return [str(p) for p in (service.get("ports") or [])]


@pytest.mark.security
@pytest.mark.invariant("SEC-70")
def test_hatchet_ports_are_loopback_only_in_base_compose():
    # M8: no Hatchet service may publish a host port on all interfaces. Every
    # published mapping must be explicitly bound to 127.0.0.1, so the cleartext
    # control plane + the unauthenticated dashboard are not LAN-reachable on a
    # multi-homed host by default.
    services = _base()["services"]
    for name in _HATCHET_SERVICES:
        ports = _host_ports(services[name])
        assert ports, f"{name} declares no ports (expected loopback-bound host ports)"
        for entry in ports:
            assert entry.startswith("127.0.0.1:"), f"{name} publishes {entry!r} not on loopback"


@pytest.mark.security
@pytest.mark.invariant("SEC-70")
def test_secure_overlay_drops_hatchet_host_ports():
    # M8: the secure overlay removes the Hatchet host ports entirely (reachable
    # only over the compose network), matching how it already strips kernel/ui.
    services = _secure()["services"]
    for name in _HATCHET_SERVICES:
        assert name in services, f"secure overlay has no {name} override"
        assert services[name].get("ports") == [], f"{name} host ports not dropped in secure overlay"


@pytest.mark.security
@pytest.mark.invariant("SEC-70")
def test_postgres_password_has_no_literal_default():
    # M9: POSTGRES_PASSWORD uses the compose required-var form (:?), so the stack
    # refuses to start unset - never a baked boltrig:boltrig default.
    services = _base()["services"]
    pw = str(services["postgres"]["environment"]["POSTGRES_PASSWORD"])
    assert pw.startswith("${POSTGRES_PASSWORD:?"), f"POSTGRES_PASSWORD has a default: {pw!r}"
    # And the Hatchet DSN interpolates the password instead of hardcoding it.
    dsn = str(services["hatchet-engine"]["environment"]["DATABASE_URL"])
    assert "${POSTGRES_PASSWORD}" in dsn, f"Hatchet DSN does not interpolate the password: {dsn!r}"
    assert "boltrig:boltrig" not in dsn, f"Hatchet DSN hardcodes credentials: {dsn!r}"


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_sidecar_ships_profile_gated():
    # M10: a scheduled backup sidecar ships in the base compose but is profile-
    # gated ("backup") so the default dev stack is unaffected; it runs
    # scripts/backup.sh and writes to a mounted backups dir.
    svc = _base()["services"].get("backup")
    assert svc is not None, "no backup sidecar in docker-compose.yml"
    assert "backup" in (svc.get("profiles") or []), "backup sidecar is not profile-gated"
    mounts = " ".join(str(v) for v in (svc.get("volumes") or []))
    assert "scripts/backup.sh" in mounts, "backup sidecar does not mount scripts/backup.sh"
    assert "/backups" in mounts, "backup sidecar has no backups mount"
    # the script exists and is shell-shaped (a shebang).
    script = _REPO / "scripts" / "backup.sh"
    assert script.exists(), "scripts/backup.sh missing"
    assert script.read_text().startswith("#!"), "backup.sh has no shebang"
