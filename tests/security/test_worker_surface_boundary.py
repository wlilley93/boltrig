"""Static shipment boundaries for decision 0021's Worker client."""

from pathlib import Path
import plistlib

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "apps" / "worker"


@pytest.mark.invariant("SEC-WRK-01")
def test_worker_ships_no_openworker_agent_server_or_provider_secret_path():
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore").lower()
        for path in (WORKER / "src").rglob("*")
        if path.is_file()
    )
    rust = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (WORKER / "src-tauri" / "src").glob("*.rs")
    )
    config = (WORKER / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8").lower()

    for forbidden in (
        "openworker-server",
        "aisuite",
        "openai_api_key",
        "anthropic_api_key",
        "provider_api_key",
        "externalbin",
        "binaries/sidecar",
    ):
        assert forbidden not in source
        assert forbidden not in rust
        assert forbidden not in config


@pytest.mark.invariant("SEC-WRK-01")
def test_desktop_native_boundary_has_no_arbitrary_path_or_command_primitive():
    rust_files = {
        path.name: path.read_text(encoding="utf-8")
        for path in (WORKER / "src-tauri" / "src").glob("*.rs")
    }
    rust = "\n".join(rust_files.values())
    config = (WORKER / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    assert "materialize_artifact" in rust
    assert ".save_file(" in rust
    assert "destination:" not in rust
    assert "#[tauri::command]\nfn run_command" not in rust
    assert "std::process::Command" not in rust
    assert "open_materialized_artifact" in rust
    assert "reveal_materialized_artifact" in rust
    assert "registry.resolve(&handle)" in rust
    assert "open_path(path" in rust
    assert "open_path(handle" not in rust
    assert "reveal_item_in_dir(path)" in rust
    assert "reveal_item_in_dir(handle)" not in rust
    client = (WORKER / "src" / "client.ts").read_text(encoding="utf-8")
    capabilities = (
        WORKER / "src-tauri" / "capabilities" / "default.json"
    ).read_text(encoding="utf-8")
    assert "accessToken" not in client
    assert "device_session_token" not in rust_files["lib.rs"]
    assert "dialog:allow-save" not in capabilities
    # The only native process seam is inside the signed device-lease executor:
    # the pinned verifier and exact canonical envelope are checked before the
    # claim, and a command additionally needs an opaque native root whose user
    # opted into commands plus a per-invocation native confirmation. No Tauri
    # command accepts argv, an executable, a cwd, or a caller-supplied path.
    agent = rust_files["device_agent.rs"]
    protocol = rust_files["device_protocol.rs"]
    roots = rust_files["device_roots.rs"]
    lib = rust_files["lib.rs"]
    assert agent.index("verify_lease(&lease") < agent.index(".claim(")
    assert "validate_verifier(verifier)?" in protocol
    assert ".verify(&canonical_lease_bytes(lease)?" in protocol
    assert roots.index('if !root.command_enabled') < roots.index("Command::new(executable)")
    assert roots.index(".blocking_show()") < roots.index("Command::new(executable)")
    assert "tokio::process::Command" in roots
    assert "command_shell_refused" in roots
    for forbidden_export in (
        "run_command",
        "execute_command",
        "spawn_command",
        "command_argv",
        "command_cwd",
    ):
        assert f"#[tauri::command]\nfn {forbidden_export}" not in lib
    assert "connect-src 'self' https: wss:" not in config
    assert "https://*.boltrig.io" in config


@pytest.mark.invariant("SEC-WRK-01")
def test_desktop_updater_accepts_no_webview_release_trust_or_unsigned_path():
    native = (
        WORKER / "src-tauri" / "src" / "desktop_updater.rs"
    ).read_text(encoding="utf-8")
    lib = (
        WORKER / "src-tauri" / "src" / "lib.rs"
    ).read_text(encoding="utf-8")
    wrapper = (WORKER / "src" / "desktop.ts").read_text(encoding="utf-8")
    surface = (
        WORKER / "src" / "components" / "DesktopUpdater.tsx"
    ).read_text(encoding="utf-8")
    config = (
        WORKER / "src-tauri" / "tauri.conf.json"
    ).read_text(encoding="utf-8")

    assert 'option_env!("BOLTRIG_UPDATER_ENDPOINT")' in native
    assert 'option_env!("BOLTRIG_UPDATER_PUBLIC_KEY")' in native
    assert 'endpoint.scheme() != "https"' in native
    assert ".pubkey(trust.public_key)" in native
    assert ".download_and_install(" in native
    assert "if update.version != expected_version" in native
    assert ".pending" in native
    assert "update_check_required" in native
    assert "update_restart_not_ready" in native
    assert "update.download_url" not in surface
    assert "download_url" not in surface.lower()
    assert "public_key:" not in surface.lower()
    assert '"createUpdaterArtifacts": true' in config
    assert "dangerousInsecureTransportProtocol" not in config
    for command in (
        "desktop_update_readiness",
        "check_desktop_update",
        "install_desktop_update",
        "restart_desktop_after_update",
    ):
        assert command in lib
        assert command in wrapper


@pytest.mark.invariant("SEC-WRK-01")
def test_desktop_oauth_return_accepts_only_kernel_brokered_opaque_results():
    native = (
        WORKER / "src-tauri" / "src" / "desktop_oauth.rs"
    ).read_text(encoding="utf-8")
    lib = (WORKER / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    wrapper = (WORKER / "src" / "desktop.ts").read_text(encoding="utf-8")
    surface = (
        WORKER / "src" / "components" / "IntegrationsView.tsx"
    ).read_text(encoding="utf-8")
    config = (
        WORKER / "src-tauri" / "tauri.conf.json"
    ).read_text(encoding="utf-8")
    capabilities = (
        WORKER / "src-tauri" / "capabilities" / "default.json"
    ).read_text(encoding="utf-8")

    assert '"schemes": ["boltrig-worker"]' in config
    assert "tauri_plugin_deep_link::init()" in lib
    assert "tauri_plugin_single_instance::init" in lib
    assert "register_all()" in native
    assert 'url.scheme() != CALLBACK_SCHEME' in native
    assert 'url.host_str() != Some(CALLBACK_HOST)' in native
    assert "url.path() != CALLBACK_PATH" in native
    assert '"code" | "access_token" | "refresh_token" | "id_token"' in native
    assert "provider_secret_in_native_return" in native
    assert "pending.state != parsed.state" in native
    assert "deep-link:deny-get-current" in capabilities
    assert "window.location.assign" not in surface
    assert "provider exchange is not configured" in surface.lower()
    for command in (
        "desktop_oauth_return_readiness",
        "arm_desktop_oauth_return",
        "take_desktop_oauth_return",
        "cancel_desktop_oauth_return",
    ):
        assert command in lib
        assert command in wrapper
    oauth_wrapper = wrapper[
        wrapper.index("export interface DesktopOAuthReturnReadiness"):
        wrapper.index("function apiOrigin")
    ]
    for forbidden in (
        "authorization_url",
        "access_token",
        "refresh_token",
        "id_token",
        "code",
    ):
        assert f"{forbidden}:" not in oauth_wrapper


@pytest.mark.invariant("WRK-01")
def test_worker_and_operator_decision_is_landed_with_attribution():
    decision = ROOT / "docs" / "decisions" / "0021-worker-primary-surface-and-realtime-voice.md"
    text = decision.read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "**Worker**" in text and "**Operator**" in text
    assert "realtime_voice" in text
    assert "f96ad4c8e6865f0aec519681a3717b6bcdd81546" in text
    assert "MIT License" in notices
    assert "Copyright (c) 2024 Andrew Ng" in notices


@pytest.mark.invariant("WRK-01")
def test_worker_candidate_image_preserves_operator_subpath_without_cutover():
    dockerfile = (WORKER / "Dockerfile").read_text(encoding="utf-8")
    nginx = (WORKER / "nginx.conf").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    vite = (ROOT / "ui" / "vite.config.ts").read_text(encoding="utf-8")

    assert 'profiles: ["worker"]' in compose
    assert "worker-ui:" in compose
    assert "COPY --from=worker-build" in dockerfile
    assert "COPY --from=operator-build" in dockerfile
    assert "ENV BOLTRIG_UI_BASE=/operator/" in dockerfile
    assert 'process.env.BOLTRIG_UI_BASE || "/"' in vite
    assert "absolute_redirect off;" in nginx
    assert "location /operator/" in nginx
    assert "try_files $uri $uri/ /operator/index.html;" in nginx


@pytest.mark.invariant("WRK-02")
def test_worker_primary_cutover_is_explicit_edge_only_and_reversible():
    overlay = (ROOT / "deploy" / "compose.worker-primary.yml").read_text(
        encoding="utf-8"
    )
    caddy = (ROOT / "deploy" / "Caddyfile.example").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    # The ordinary Caddy posture remains Operator. Only selecting the overlay
    # changes the server-side upstream; no browser redirect or data migration is
    # part of the cutover.
    assert "{$BOLTRIG_FRONTEND_UPSTREAM:ui:80}" in caddy
    assert "BOLTRIG_FRONTEND_UPSTREAM: worker-ui:80" in overlay
    assert "profiles: !reset []" in overlay
    assert "ports: !override []" in overlay
    assert overlay.count('BOLTRIG_PRODUCTION: "1"') == 2
    assert overlay.count("Worker-primary production requires REDIS_URL") == 2

    # The maintained Operator stays packaged under /operator and its standalone
    # image is retained behind an explicit rollback profile.
    assert 'profiles: ["operator-standalone"]' in overlay
    assert "worker-primary-validate:" in makefile
    assert "worker-primary-up:" in makefile


@pytest.mark.invariant("WRK-02")
def test_worker_is_a_signed_digest_pinned_first_party_release_image():
    release = (ROOT / "deploy" / "compose.release.yml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    validator = (ROOT / "scripts" / "validate_release_images.py").read_text(
        encoding="utf-8"
    )

    assert "BOLTRIG_WORKER_UI_IMAGE" in release
    assert "BOLTRIG_WORKER_UI_IMAGE" in validator
    assert "image: worker-ui" in workflow
    assert "apps/worker/Dockerfile" in workflow


@pytest.mark.invariant("WRK-03")
def test_worker_built_artifact_has_a_gating_browser_and_accessibility_acceptance():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    config = (ROOT / "ui" / "playwright.worker.config.ts").read_text(
        encoding="utf-8"
    )
    smoke = (ROOT / "ui" / "e2e-worker" / "worker.spec.ts").read_text(
        encoding="utf-8"
    )

    assert "worker-e2e:" in makefile
    assert "playwright.worker.config.ts" in makefile
    assert "pnpm --dir ../apps/worker run build" in config
    assert "127.0.0.1" in config
    assert 'projects: [{ name: "chromium"' in config
    assert "AxeBuilder" in smoke
    assert "serious" in smoke and "critical" in smoke
    assert "Worker chat streams through the governed kernel" in smoke
    assert "worker-e2e:" in workflow
    assert "needs.worker-e2e.result" in workflow


@pytest.mark.invariant("WRK-04")
def test_worker_preserves_audit_anchor_evidence_and_labels_its_strength():
    sdk_types = (ROOT / "sdks" / "web" / "src" / "types.ts").read_text(
        encoding="utf-8"
    )
    operate = (
        WORKER / "src" / "components" / "OperationsView.tsx"
    ).read_text(encoding="utf-8")

    assert "anchor?: AuditAnchorEvidence | null;" in sdk_types
    for field in (
        "seq_start: number;",
        "seq_end: number;",
        "anchored_at: string;",
        "is_dev_fallback: boolean;",
    ):
        assert field in sdk_types
    assert "Intact · unanchored" in operate
    assert "Intact · local fallback" in operate
    assert "Intact · externally anchored" in operate
    assert "no conclusion was inferred" in operate


@pytest.mark.invariant("WRK-05")
def test_worker_parity_includes_every_non_http_lifecycle_dimension():
    parity = (ROOT / "docs" / "WORKER-PARITY.md").read_text(encoding="utf-8")
    section = parity.split("## Non-HTTP completeness audit", 1)[1].split(
        "## Intentionally Operator-only", 1
    )[0]
    rows = {
        line.split("|", 2)[1].strip(): line
        for line in section.splitlines()
        if line.startswith("| ") and not line.startswith("|---")
    }
    rows.pop("Non-HTTP subsystem", None)
    expected = {
        "Durable fleet hierarchy, Chief of Staff and departments",
        "Codex provider and model-policy wiring in durable fleet processes",
        "Spawn rules and classification",
        "Prompts, skills and department briefs",
        "HITL, approval and escalation policy",
        "Privacy, retention and compliance recovery",
        "Network and egress policy",
        "Runtime add-ons",
        "Capability invocation",
        "Channel-to-agent exposure",
        "Codex rollout and runtime admission",
        "Memory projection delivery",
        "Scheduled workflows and worker janitors",
        "Audit anchors",
        "Backup and disaster recovery",
    }

    assert expected <= set(rows)
    assert all(
        any(kind in rows[name] for kind in ("gap", "deployment-only", "complete"))
        for name in expected
    )
    for dimension in ("discover", "configure", "operate", "observe", "recover"):
        assert f"**{dimension}**" in section
    assert (
        "A flat agent profile, saved cron string, parsed policy field"
        in " ".join(section.split())
    )


@pytest.mark.invariant("SEC-WRK-05")
def test_worker_edge_allows_same_origin_voice_without_opening_browser_capabilities():
    caddy = (ROOT / "deploy" / "Caddyfile.example").read_text(encoding="utf-8")
    nginx = (WORKER / "nginx.conf").read_text(encoding="utf-8")
    with (WORKER / "src-tauri" / "Info.plist").open("rb") as source:
        macos_bundle = plistlib.load(source)

    for source in (caddy, nginx):
        assert "X-Content-Type-Options" in source and "nosniff" in source
        assert "X-Frame-Options" in source and "DENY" in source
        assert "Referrer-Policy" in source and "no-referrer" in source
        assert "camera=()" in source
        assert "geolocation=()" in source
        assert "microphone=(self)" in source
        assert "connect-src 'self'" in source
        assert "connect-src 'self' https: wss:" not in source
        assert "object-src 'none'" in source
        assert "frame-ancestors 'none'" in source
    assert macos_bundle["NSMicrophoneUsageDescription"] == (
        "Boltrig Worker uses the microphone only while you are participating "
        "in a voice call."
    )


@pytest.mark.invariant("SEC-WRK-13")
def test_worker_renders_closed_conversations_as_restore_only():
    shell = (WORKER / "src" / "components" / "Shell.tsx").read_text(encoding="utf-8")
    chat = (WORKER / "src" / "components" / "ChatView.tsx").read_text(encoding="utf-8")
    controls = (
        WORKER / "src" / "components" / "ConversationControls.tsx"
    ).read_text(encoding="utf-8")
    sdk = (ROOT / "sdks" / "web" / "src" / "client.ts").read_text(encoding="utf-8")

    assert 'conversation.status === "closed"' in shell
    assert 'data-status="closed"' in shell
    assert "restoreMyConversation" in shell and "onConversationRestored" in shell
    assert 'conversationStatus === "closed"' in chat
    assert 'closed={conversationStatus === "closed"}' in chat
    assert 'status === "closed"' in controls
    assert "Restore conversation" in controls
    assert "/restore`" in sdk
