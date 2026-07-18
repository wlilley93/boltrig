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
    if node.value in {"", "null", "~"}:
        return None
    return loader.construct_scalar(node)


yaml.SafeLoader.add_constructor("!override", _compose_tag_constructor)
yaml.SafeLoader.add_constructor("!reset", _compose_tag_constructor)


_REPO = Path(__file__).resolve().parents[2]
_BASE = _REPO / "docker-compose.yml"
_SECURE = _REPO / "deploy" / "compose.secure.yml"
_RELEASE = _REPO / "deploy" / "compose.release.yml"

_HATCHET_SERVICES = ("hatchet-engine", "hatchet-dashboard")


def _base() -> dict:
    return yaml.safe_load(_BASE.read_text())


def _text(path: str) -> str:
    return (_REPO / path).read_text()


def _secure() -> dict:
    return yaml.safe_load(_SECURE.read_text())


def _release() -> dict:
    return yaml.safe_load(_RELEASE.read_text())


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
def test_local_model_port_is_loopback_only_and_removed_from_secure_compose():
    ports = _host_ports(_base()["services"]["local-model"])
    assert ports
    assert all(port.startswith("127.0.0.1:") for port in ports)
    assert _secure()["services"]["local-model"].get("ports") == []


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


@pytest.mark.invariant("FR-OPS-02")
def test_compose_validation_is_clean_checkout_safe():
    compose_text = _text("docker-compose.yml")
    makefile = _text("Makefile")

    assert "env_file: ${BOLTRIG_ENV_FILE:-.env}" in compose_text
    assert "COMPOSE_VALIDATE_ENV ?= .env.example" in makefile
    assert "BOLTRIG_ENV_FILE=$(COMPOSE_VALIDATE_ENV)" in makefile
    assert "POSTGRES_PASSWORD=$(COMPOSE_VALIDATE_POSTGRES_PASSWORD)" in makefile


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
    dockerfile = _text("deploy/backup.Dockerfile")
    assert 'CMD ["/usr/local/bin/backup-loop.sh"]' in dockerfile
    assert "backup-healthcheck" in dockerfile
    assert "run failed (retrying next interval)" not in dockerfile


@pytest.mark.security
@pytest.mark.invariant("FR-HOST-09")
@pytest.mark.invariant("FR-HOST-11")
@pytest.mark.invariant("FR-RUN-17")
def test_herdr_opencode_state_is_stack_owned_in_compose():
    services = _base()["services"]
    kernel = services["kernel"]
    fleet = services["fleet-worker"]

    assert kernel["environment"]["BOLTRIG_HERDR_HOME"].endswith("/var/lib/boltrig/herdr}")
    assert fleet["environment"]["BOLTRIG_OPENCODE_HOME"].endswith(
        "/var/lib/boltrig/opencode}"
    )
    assert fleet["environment"]["BOLTRIG_BROWSER_CLI_HOME"].endswith(
        "/var/lib/boltrig/browser-cli}"
    )
    assert fleet["environment"]["BOLTRIG_BROWSER_CLI_BIN"].endswith(
        "/usr/local/bin/browser-use}"
    )
    mounts = [*kernel.get("volumes", ()), *fleet.get("volumes", ())]
    joined = " ".join(str(mount) for mount in mounts)
    assert "herdr_data:/var/lib/boltrig/herdr" in joined
    assert "opencode_data:/var/lib/boltrig/opencode" in joined
    assert "browser_cli_data:/var/lib/boltrig/browser-cli" in joined
    assert "~/.config" not in joined
    assert "~/.local" not in joined
    assert "/.opencode" not in joined


@pytest.mark.security
@pytest.mark.invariant("FR-HOST-09")
@pytest.mark.invariant("FR-RUN-17")
def test_herdr_opencode_state_roots_are_owned_by_service_user_in_images():
    kernel_dockerfile = _text("deploy/kernel.Dockerfile")
    fleet_dockerfile = _text("deploy/fleet.Dockerfile")

    assert "install -d -o boltrig -g boltrig" in kernel_dockerfile
    assert "/var/lib/boltrig/herdr/home" in kernel_dockerfile
    assert "/var/lib/boltrig/herdr/config" in kernel_dockerfile
    assert "/var/lib/boltrig/herdr/data" in kernel_dockerfile
    assert "/var/lib/boltrig/herdr/state" in kernel_dockerfile

    assert "install -d -o boltrig -g boltrig" in fleet_dockerfile
    assert "/var/lib/boltrig/opencode/home" in fleet_dockerfile
    assert "/var/lib/boltrig/opencode/config/opencode" in fleet_dockerfile
    assert "/var/lib/boltrig/opencode/data" in fleet_dockerfile
    assert "/var/lib/boltrig/opencode/state" in fleet_dockerfile


@pytest.mark.security
@pytest.mark.invariant("FR-HOST-11")
def test_browser_cli_state_roots_are_stack_owned():
    fleet_dockerfile = _text("deploy/fleet.Dockerfile")
    env_example = _text(".env.example")
    lock = _text("deploy/browser-cli-requirements.txt")

    assert "BOLTRIG_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli" in env_example
    assert "BOLTRIG_BROWSER_CLI_BIN=/usr/local/bin/browser-use" in env_example
    assert "BROWSER_CLI_URL" not in env_example
    assert "--python-platform linux" in lock
    assert "browser-use==0.13.3" in lock
    assert "0756dd726837fa7c0f0aa02eae2c47a93c3d02ef7dba980c8dae9077d8a0157d" in lock
    assert "/opt/boltrig/browser-cli/bin/pip install" in fleet_dockerfile
    assert "--no-deps" in fleet_dockerfile
    assert "--require-hashes" in fleet_dockerfile
    # chromium/tini install UNPINNED from apt: exact Debian version pins rot out of
    # the bookworm pool on every security bump and break the build (apt exit 100).
    # Still apt-provided from the stack image, never a runtime download (the sibling
    # test_browser_cli_never_relies_on_a_runtime_browser_download guards that).
    assert "apt-get install -y --no-install-recommends" in fleet_dockerfile
    assert "\n        chromium \\" in fleet_dockerfile
    assert "\n        tini \\" in fleet_dockerfile
    # bubblewrap is Codex's sandbox prerequisite (also in the kernel image); apt from
    # the stack image, never a runtime download.
    assert "\n        bubblewrap &&" in fleet_dockerfile
    assert "fleet-entrypoint" in fleet_dockerfile
    assert "boltrig-browser-smoke" in fleet_dockerfile
    assert "/usr/local/bin/browser-use" in fleet_dockerfile
    assert "install -d -o boltrig -g boltrig" in fleet_dockerfile
    assert "/var/lib/boltrig/browser-cli/home" in fleet_dockerfile
    assert "/var/lib/boltrig/browser-cli/config" in fleet_dockerfile
    assert "/var/lib/boltrig/browser-cli/data" in fleet_dockerfile
    assert "/var/lib/boltrig/browser-cli/state" in fleet_dockerfile
    assert "/var/lib/boltrig/browser-cli/cache" in fleet_dockerfile


@pytest.mark.security
@pytest.mark.invariant("FR-HOST-11")
def test_browser_cli_never_relies_on_a_runtime_browser_download():
    fleet_dockerfile = _text("deploy/fleet.Dockerfile")
    entrypoint = _text("scripts/fleet-entrypoint.sh")

    assert "uvx playwright install" not in fleet_dockerfile
    assert "playwright install" not in fleet_dockerfile
    assert "--remote-debugging-address=127.0.0.1" in entrypoint
    assert "--remote-debugging-port=9222" in entrypoint
    assert "browser-use" in entrypoint


@pytest.mark.security
@pytest.mark.invariant("SEC-136")
def test_backup_credentials_are_excluded_from_git_and_image_contexts():
    for path in (".gitignore", ".dockerignore"):
        ignored = _text(path)
        assert "deploy/rclone/" in ignored
        assert "**/rclone.conf" in ignored


@pytest.mark.security
@pytest.mark.invariant("IAC-002")
def test_python_images_do_not_invoke_unlocked_build_isolation():
    for path in ("deploy/kernel.Dockerfile", "deploy/fleet.Dockerfile"):
        dockerfile = _text(path)
        assert "pip install --no-deps ." not in dockerfile
        assert "COPY boltrig/ /app/boltrig/" in dockerfile


@pytest.mark.security
@pytest.mark.invariant("FR-HOST-13")
def test_browser_cli_cloud_policy_is_stack_prefixed_in_deploy_config():
    compose_text = _text("docker-compose.yml")
    env_example = _text(".env.example")

    assert "BROWSER_USE_API_KEY" not in compose_text
    assert "BROWSER_USE_PROFILE_ID" not in compose_text
    assert "BOLTRIG_BROWSER_CLOUD_POLICY=disabled" in env_example
    assert "BOLTRIG_BROWSER_CLOUD_API_KEY=" in env_example
    assert "BOLTRIG_BROWSER_CLOUD_PROFILE_ID=" in env_example
    assert "BROWSER_USE_API_KEY" not in env_example
    assert "BROWSER_USE_PROFILE_ID" not in env_example


@pytest.mark.security
@pytest.mark.invariant("FR-HOST-10")
@pytest.mark.invariant("FR-RUN-18")
def test_herdr_opencode_clis_ship_inside_first_party_images():
    kernel_dockerfile = _text("deploy/kernel.Dockerfile")
    fleet_dockerfile = _text("deploy/fleet.Dockerfile")

    assert "ARG HERDR_VERSION=0.7.3" in kernel_dockerfile
    assert "HERDR_LINUX_AMD64_SHA256=" in kernel_dockerfile
    assert "github.com/ogulcancelik/herdr/releases/download" in kernel_dockerfile
    assert "/usr/local/bin/herdr" in kernel_dockerfile
    assert "herdr --version" in kernel_dockerfile
    assert "~/.local/bin" not in kernel_dockerfile

    assert "ARG OPENCODE_VERSION=1.17.16" in fleet_dockerfile
    assert "OPENCODE_LINUX_AMD64_SHA256=" in fleet_dockerfile
    assert "opencode-linux-x64-baseline" in fleet_dockerfile
    assert "/usr/local/bin/opencode" in fleet_dockerfile
    assert "opencode --version" in fleet_dockerfile
    assert "~/.opencode/bin" not in fleet_dockerfile


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_publishes_only_scanned_signed_digest_images_with_sboms():
    workflow = _text(".github/workflows/release.yml")

    for image in (
        "deploy/kernel.Dockerfile",
        "deploy/fleet.Dockerfile",
        "ui/Dockerfile",
        "services/pi_sidecar/Dockerfile",
        "deploy/backup.Dockerfile",
    ):
        assert f"dockerfile: {image}" in workflow
    assert '- "v*"' in workflow
    assert "types: [published]" not in workflow
    assert "group: boltrig-release" in workflow
    assert "environment: release" in workflow
    assert "git merge-base --is-ancestor" in workflow
    assert 'gh release create "$RELEASE_TAG"' in workflow
    assert "--draft --verify-tag --generate-notes" in workflow
    assert "id-token: write" in workflow
    assert "packages: write" in workflow
    assert "ignore-unfixed: true" in workflow
    assert "severity: HIGH,CRITICAL" in workflow
    assert "format: cyclonedx" in workflow
    assert "^sha256:[0-9a-f]{64}$" in workflow
    assert "CANDIDATE_TAG: candidate-" in workflow
    assert 'docker push "$candidate_ref"' in workflow
    assert 'cosign sign --yes "$IMAGE_REF"' in workflow
    assert 'cosign attest --yes --type cyclonedx --predicate "$SBOM_FILE"' in workflow
    assert "cosign verify-attestation" in workflow
    assert 'gh release upload "$RELEASE_TAG"' in workflow
    assert "release-evidence/boltrig-images.env" in workflow
    for variable in (
        "BOLTRIG_KERNEL_IMAGE",
        "BOLTRIG_FLEET_IMAGE",
        "BOLTRIG_UI_IMAGE",
        "BOLTRIG_PI_SIDECAR_IMAGE",
        "BOLTRIG_BACKUP_IMAGE",
    ):
        assert variable in workflow
    assert "--clobber" not in workflow
    assert "docker buildx imagetools create" in workflow
    assert 'gh release edit "$RELEASE_TAG"' in workflow
    assert "--draft=false" in workflow
    assert workflow.index("cosign verify-attestation") < workflow.index(
        "docker buildx imagetools create"
    )
    assert workflow.index("docker buildx imagetools create") < workflow.index(
        'gh release edit "$RELEASE_TAG"'
    )
    assert "sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6" in workflow


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_requires_canonical_success_for_the_exact_commit():
    workflow = _text(".github/workflows/release.yml")

    gate = "Require canonical CI and security success for the exact release commit"
    assert "actions: read" in workflow
    assert gate in workflow
    assert "X-GitHub-Api-Version: 2022-11-28" in workflow
    assert 'actions/workflows/$workflow_file/runs' in workflow
    assert '-f branch="$DEFAULT_BRANCH"' in workflow
    assert '-f head_sha="$RELEASE_COMMIT"' in workflow
    assert "require_successful_workflow ci.yml 'ci / quality'" in workflow
    assert "require_successful_workflow security.yml 'security / Security gate'" in workflow
    assert workflow.index(gate) < workflow.index('gh release create "$RELEASE_TAG"')


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_compose_uses_only_required_digest_images_without_builds():
    services = _release()["services"]
    variables = {
        "kernel": "BOLTRIG_KERNEL_IMAGE",
        "fleet-worker": "BOLTRIG_FLEET_IMAGE",
        "ui": "BOLTRIG_UI_IMAGE",
        "pi-sidecar": "BOLTRIG_PI_SIDECAR_IMAGE",
        "backup": "BOLTRIG_BACKUP_IMAGE",
    }
    for service, variable in variables.items():
        config = services[service]
        assert config.get("build") is None
        assert config["image"].startswith(f"${{{variable}:?")
        assert config["pull_policy"] == "always"

    backup_mounts = " ".join(services["backup"]["volumes"])
    assert "scripts/backup.sh" not in backup_mounts
    makefile = _text("Makefile")
    assert "scripts/validate_release_images.py" in makefile
    assert "-f deploy/compose.release.yml" in makefile
    assert "up -d --no-build" in makefile
