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
    # only over the compose network), matching how it already strips kernel/Worker.
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
    assert "$(COMPOSE) --profile channels -f docker-compose.yml config --quiet" in makefile


@pytest.mark.security
@pytest.mark.invariant("SEC-70")
def test_whatsapp_session_mount_resolves_to_the_declared_named_volume() -> None:
    document = _base()
    mounts = document["services"]["whatsapp-bridge"]["volumes"]

    assert mounts == ["whatsapp_session:/data"]
    assert "whatsapp_session" in document["volumes"]


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

    services = _base()["services"]
    assert services["hatchet-engine"]["volumes"] == ["hatchet_config:/config"]
    assert (
        "${HATCHET_DATABASE_NAME:-hatchet}"
        in services["backup"]["environment"]["BACKUP_DATABASES"]
    )
    assert (
        "${HATCHET_DATABASE_NAME:-hatchet}"
        in services["hatchet-engine"]["environment"]["DATABASE_URL"]
    )
    release_backup = _release()["services"]["backup"]
    assert release_backup["environment"]["BACKUP_STATE_DIR"] == "/backup-state"
    release_mounts = " ".join(release_backup["volumes"])
    assert "hatchet_config:/backup-state/hatchet-config:ro" in release_mounts
    assert "knowledge_data:/backup-state/knowledge:ro" in release_mounts
    assert "manifest.yaml:/backup-state/deployment/manifest.yaml:ro" in release_mounts
    assert "libraries:/backup-state/deployment/libraries:ro" in release_mounts


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_fresh_postgres_boot_creates_the_separate_hatchet_database() -> None:
    postgres = _base()["services"]["postgres"]
    mounts = " ".join(postgres["volumes"])
    assert (
        "deploy/postgres-init-hatchet.sh:"
        "/docker-entrypoint-initdb.d/00-hatchet-db.sh:ro" in mounts
    )
    assert (
        postgres["environment"]["HATCHET_DATABASE_NAME"]
        == "${HATCHET_DATABASE_NAME:-hatchet}"
    )

    initializer = _REPO / "deploy" / "postgres-init-hatchet.sh"
    assert initializer.stat().st_mode & 0o111
    text = initializer.read_text()
    assert "createdb" in text
    assert '"$POSTGRES_USER"' in text
    assert '"$hatchet_database"' in text


@pytest.mark.security
@pytest.mark.invariant("FR-HOST-09")
@pytest.mark.invariant("FR-HOST-11")
@pytest.mark.invariant("FR-RUN-17")
def test_herdr_opencode_state_is_stack_owned_in_compose():
    services = _base()["services"]
    kernel = services["kernel"]
    fleet = services["fleet-worker"]
    hatchet = services["hatchet-worker"]

    assert kernel["environment"]["BOLTRIG_HERDR_HOME"].endswith("/var/lib/boltrig/herdr}")
    assert fleet["environment"]["BOLTRIG_OPENCODE_HOME"].endswith(
        "/var/lib/boltrig/opencode}"
    )
    fleet_browser_home = fleet["environment"]["BOLTRIG_BROWSER_CLI_HOME"]
    hatchet_browser_home = hatchet["environment"]["BOLTRIG_BROWSER_CLI_HOME"]
    assert fleet_browser_home.endswith("/var/lib/boltrig/browser-cli/fleet-worker}")
    assert hatchet_browser_home.endswith("/var/lib/boltrig/browser-cli/hatchet-worker}")
    assert fleet_browser_home != hatchet_browser_home
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


@pytest.mark.invariant("KNO-04")
def test_knowledge_and_bundled_cognee_have_stack_owned_persistent_storage():
    kernel = _base()["services"]["kernel"]
    environment = kernel["environment"]
    mounts = " ".join(str(mount) for mount in kernel.get("volumes", ()))
    dockerfile = _text("deploy/kernel.Dockerfile")
    lock = _text("requirements-lock.txt")

    assert environment["BOLTRIG_KNOWLEDGE_VAULT"].endswith(
        "/var/lib/boltrig/knowledge}"
    )
    assert environment["BOLTRIG_COGNEE_ROOT"].endswith("/var/lib/boltrig/cognee}")
    assert "knowledge_data:/var/lib/boltrig/knowledge" in mounts
    assert "cognee_data:/var/lib/boltrig/cognee" in mounts
    assert "/var/lib/boltrig/knowledge" in dockerfile
    assert "/var/lib/boltrig/cognee" in dockerfile
    assert "cognee==" in lock


@pytest.mark.security
@pytest.mark.invariant("FR-HOST-11")
def test_browser_cli_state_roots_are_stack_owned():
    fleet_dockerfile = _text("deploy/fleet.Dockerfile")
    env_example = _text(".env.example")
    lock = _text("deploy/browser-cli-requirements.txt")

    assert (
        "BOLTRIG_FLEET_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli/fleet-worker"
        in env_example
    )
    assert (
        "BOLTRIG_HATCHET_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli/hatchet-worker"
        in env_example
    )
    assert "BOLTRIG_BROWSER_CLI_BIN=/usr/local/bin/browser-use" in env_example
    assert "BROWSER_CLI_URL" not in env_example
    assert "--python-platform linux" in lock
    # DERIVED, not restated. This named `browser-use==0.13.3` and one of its hashes
    # as literals, so a routine version bump broke a test about STATE ROOTS - the
    # exact defect the retired pi-sidecar lock test recorded in its own comment:
    # restating a version makes the test a second place to maintain it, and the
    # second place is the one that goes stale.
    #
    # The property is that the lock installs the version the SOURCE pins, at a real
    # hash. Which version that is belongs to browser-cli-requirements.in.
    source = _text("deploy/browser-cli-requirements.in")
    pinned = [ln.strip() for ln in source.splitlines()
              if ln.strip().startswith("browser-use==")]
    assert len(pinned) == 1, f"browser-cli-requirements.in must pin browser-use once: {pinned}"
    name, _, version = pinned[0].partition("==")
    assert f"\n{name}=={version}" in f"\n{lock}", (
        f"{name} is pinned to {version} in the .in and the lock does not install that "
        "version. The lock was not recompiled, so the image ships the old release."
    )
    # every pin carries hashes, which is what makes --require-hashes below mean something
    assert lock.count("--hash=sha256:") > 100, "the lock is not hash-generated"
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
        "apps/worker/Dockerfile",
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
    assert "actions/attest@a1948c3f048ba23858d222213b7c278aabede763" in workflow
    assert "push-to-registry: true" in workflow
    assert "provenance-${{ matrix.image }}.intoto.json" in workflow
    assert "gh attestation verify" in workflow
    assert "--signer-workflow" in workflow
    assert "--source-digest" in workflow
    assert "https://slsa.dev/provenance/v1" in workflow
    assert 'gh release upload "$RELEASE_TAG"' in workflow
    assert "release-evidence/boltrig-images.env" in workflow
    for variable in (
        "BOLTRIG_KERNEL_IMAGE",
        "BOLTRIG_FLEET_IMAGE",
        "BOLTRIG_WORKER_UI_IMAGE",
        "BOLTRIG_BACKUP_IMAGE",
    ):
        assert variable in workflow
    assert "--clobber" not in workflow
    # Anchor on the step's NAME, not on the command it happens to run. These
    # assertions previously named `docker buildx imagetools create`, which pinned an
    # implementation that was actively WRONG: imagetools can only emit a manifest
    # index, so it re-wrapped each signed candidate and published a digest cosign had
    # never signed. A test that pins the mechanism cannot tell you the mechanism is
    # the defect. What matters is the property below.
    promote = "Promote verified digests to immutable public tags"
    assert promote in workflow
    assert 'gh release edit "$RELEASE_TAG"' in workflow
    assert "--draft=false" in workflow
    assert workflow.index("cosign verify-attestation") < workflow.index(promote)
    assert workflow.index(promote) < workflow.index('gh release edit "$RELEASE_TAG"')

    # The property: whatever the public tag ends up resolving to must be the digest
    # that was scanned, signed and attested - asserted by the workflow itself, and
    # asserted here so the assertion cannot be dropped.
    assert 'test "$promoted_digest" = "$digest"' in workflow
    # And promotion must prove the bytes it is about to publish hash to that digest
    # BEFORE publishing them, so a registry that returned anything else stops the run.
    assert 'fetched="sha256:$(sha256sum manifest.bin | cut -d\' \' -f1)"' in workflow
    assert 'if [ "$fetched" != "$digest" ]; then' in workflow
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
        "hatchet-worker": "BOLTRIG_FLEET_IMAGE",
        "worker-ui": "BOLTRIG_WORKER_UI_IMAGE",
        "backup": "BOLTRIG_BACKUP_IMAGE",
    }
    for service, variable in variables.items():
        config = services[service]
        assert config.get("build") is None
        assert config["image"].startswith(f"${{{variable}:?")
        assert config["pull_policy"] == "always"

    for service in ("kernel", "fleet-worker", "hatchet-worker"):
        assert services[service]["environment"]["BOLTRIG_RELEASE_MODE"].startswith(
            "${BOLTRIG_RELEASE_MODE:?"
        )

    backup_mounts = " ".join(services["backup"]["volumes"])
    assert "scripts/backup.sh" not in backup_mounts
    hatchet_worker = _base()["services"]["hatchet-worker"]
    assert hatchet_worker["environment"]["HATCHET_CLIENT_WORKER_HEALTHCHECK_ENABLED"] == "true"
    assert "127.0.0.1:8001/health" in " ".join(hatchet_worker["healthcheck"]["test"])
    makefile = _text("Makefile")
    assert "scripts/validate_release_images.py" in makefile
    assert "scripts/verify_release_supply_chain.py" in makefile
    assert "scripts/validate_release_runtime.py" in makefile
    assert "--env-file $(RELEASE_ENV) --manifest $(RELEASE_MANIFEST)" in makefile
    assert "boltrig.api.cli doctor --env-file $(RELEASE_ENV)" not in makefile
    assert "-f deploy/compose.release.yml" in makefile
    assert "up -d --no-build" in makefile
