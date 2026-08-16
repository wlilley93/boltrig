"""Static shipment boundaries for decision 0021's Worker client."""

import json
import plistlib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "apps" / "worker"


def _corpus(paths, *, what: str, at_least: int) -> str:
    """Read a globbed corpus, refusing to return an EMPTY one.

    Every assertion below this line is of the form "X is not in the source", and
    a substring is never in an empty string - so a corpus that failed to
    materialise turns the whole test green while proving nothing. This was not
    hypothetical: `apps/worker` was untracked for two days while these tests
    were being written, so on any clean clone `rglob` yielded nothing and the
    negative assertions passed over a corpus of zero bytes.

    Tracking the directory fixed that instance. It does not fix the SHAPE, which
    is the one this repository keeps rediscovering: a check that cannot fail.
    So the corpus itself is asserted, with a floor rather than merely non-empty,
    because one stray file would satisfy "not empty" just as vacuously.
    """
    files = [p for p in paths if p.is_file()]
    assert len(files) >= at_least, (
        f"{what}: found {len(files)} file(s), expected at least {at_least}. "
        "The assertions that follow are all NEGATIVE, so an empty or truncated "
        "corpus would pass them without reading anything. Refusing instead: "
        f"check that {WORKER.relative_to(ROOT)} is present and tracked."
    )
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore").lower() for p in files)


@pytest.mark.invariant("SEC-WRK-01")
def test_the_corpus_guard_refuses_an_absent_or_truncated_source_tree(tmp_path):
    """The guard above, shown failing. Otherwise it is prose about a hazard.

    Three cases, because "not empty" is not the property wanted: a missing
    directory, a directory with too few files to be the real tree, and the
    control that the real tree passes.
    """
    with pytest.raises(AssertionError, match="found 0 file"):
        _corpus((tmp_path / "nothing").rglob("*"), what="a missing tree", at_least=1)

    (tmp_path / "one.ts").write_text("x", encoding="utf-8")
    with pytest.raises(AssertionError, match="found 1 file.*expected at least 20"):
        _corpus(tmp_path.rglob("*"), what="a truncated tree", at_least=20)

    assert _corpus(tmp_path.rglob("*"), what="the control", at_least=1) == "x"


@pytest.mark.invariant("SEC-WRK-01")
def test_worker_ships_no_openworker_agent_server_or_provider_secret_path():
    source = _corpus(
        (WORKER / "src").rglob("*"), what="the Worker web source", at_least=20
    )
    rust = _corpus(
        (WORKER / "src-tauri" / "src").glob("*.rs"),
        what="the Tauri native source",
        at_least=1,
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
def test_desktop_native_process_seams_are_explicit_and_bounded():
    rust_files = {
        path.name: path.read_text(encoding="utf-8")
        for path in (WORKER / "src-tauri" / "src").glob("*.rs")
    }
    rust = "\n".join(rust_files.values())
    desktop_account = rust_files["desktop_account.rs"]
    session = rust_files["session.rs"]
    config = (WORKER / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    config_payload = json.loads(config)
    package_payload = json.loads((WORKER / "package.json").read_text(encoding="utf-8"))
    build_script = (WORKER / "src-tauri" / "build.rs").read_text(encoding="utf-8")
    origin_gate = (
        WORKER / "scripts" / "require-desktop-origin.mjs"
    ).read_text(encoding="utf-8")
    assert "materialize_artifact" in rust
    assert ".save_file(" in rust
    assert "destination:" not in rust
    assert "#[tauri::command]\nfn run_command" not in rust
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
    assert config_payload["app"]["windows"][0]["useHttpsScheme"] is True
    assert config_payload["build"]["beforeBuildCommand"] == "pnpm run build:desktop"
    assert config_payload["build"]["beforeDevCommand"] == "pnpm run dev:desktop"
    assert "require-desktop-origin.mjs" in package_payload["scripts"]["build:desktop"]
    assert "require-desktop-origin.mjs" in package_payload["scripts"]["dev:desktop"]
    assert "rerun-if-env-changed=BOLTRIG_DESKTOP_API_ORIGIN" in build_script
    assert "VITE_API_BASE" in origin_gate
    assert "BOLTRIG_DESKTOP_API_ORIGIN" in origin_gate
    assert "must match exactly" in origin_gate
    assert 'option_env!("BOLTRIG_DESKTOP_API_ORIGIN")' in desktop_account
    assert '"/v1/auth/login"' in desktop_account
    assert '"/v1/auth/2fa/challenge"' in desktop_account
    assert ".set_cookie(" in desktop_account
    assert "SESSION_COOKIE" in desktop_account
    assert "desktop_api_request" in rust_files["lib.rs"]
    assert "exact_api_url" in desktop_account
    assert "MAX_API_REQUEST_BYTES" in desktop_account
    assert "MAX_API_RESPONSE_BYTES" in desktop_account
    assert "API_ENVELOPE_MAGIC" in desktop_account
    assert "desktop_api_start" not in desktop_account
    assert "desktop_api_cancel" not in desktop_account
    assert "session_token" not in desktop_account
    assert "async fn device_agent_status" in rust_files["lib.rs"]
    assert "spawn_blocking(device_agent::status)" in rust_files["lib.rs"]
    assert "static AGENT_CACHE: OnceLock<Mutex<AgentCache>>" in session
    assert "agent_cache().get_or_load(load_agent_from_keychain)" in session
    assert "agent_cache().replace(Ok(Some(record.clone())))" in session
    assert "agent_cache().replace(Ok(None))" in session
    # There are exactly two native process seams. Remote device commands remain
    # signed argv-only leases. The desktop-local agent may launch only the
    # resolved Codex App Server; its webview request carries an opaque root id
    # and prompt, never an executable, argv, cwd or caller-supplied path.
    process_files = {
        name
        for name, text in rust_files.items()
        if "std::process::Command" in text or "tokio::process::Command" in text
    }
    assert process_files == {"device_roots.rs", "local_agent.rs"}
    agent = rust_files["device_agent.rs"]
    protocol = rust_files["device_protocol.rs"]
    roots = rust_files["device_roots.rs"]
    local = rust_files["local_agent.rs"]
    local_protocol = rust_files["local_agent_protocol.rs"]
    lib = rust_files["lib.rs"]
    assert agent.index("verify_lease(&lease") < agent.index(".claim(")
    assert "validate_verifier(verifier)?" in protocol
    assert ".verify(&canonical_lease_bytes(lease)?" in protocol
    assert roots.index('if !root.command_enabled') < roots.index("Command::new(executable)")
    assert roots.index(".blocking_show()") < roots.index("Command::new(executable)")
    assert "tokio::process::Command" in roots
    assert "command_shell_refused" in roots
    assert '.arg("app-server")' in local
    assert "Command::new(binary)" in local
    assert "local_agent_workspace(" in local
    assert "command.env_clear()" in local
    assert 'return Err("local_agent_binary_not_bundled"' in local
    assert "pub(crate) root_id: String" in local_protocol
    for forbidden_local_input in ("executable", "argv", "cwd", "native_path"):
        assert f"pub(crate) {forbidden_local_input}" not in local_protocol
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


@pytest.mark.invariant("SEC-198")
def test_browser_cloud_and_desktop_local_agent_routes_cannot_silently_cross():
    route = (
        WORKER / "src" / "components" / "shell" / "AppRouteSurface.tsx"
    ).read_text(encoding="utf-8")
    directory = (
        WORKER / "src" / "components" / "shell" / "useConversationDirectory.ts"
    ).read_text(encoding="utf-8")
    local_view = (
        WORKER / "src" / "components" / "LocalChatView.tsx"
    ).read_text(encoding="utf-8")
    local_client = (WORKER / "src" / "localAgentClient.ts").read_text(encoding="utf-8")
    local_controller = (
        WORKER / "src" / "components" / "chat" / "useLocalChatController.ts"
    ).read_text(encoding="utf-8")
    approval_surface = (
        WORKER / "src" / "components" / "ApprovalPostureControl.tsx"
    ).read_text(encoding="utf-8")
    native = (WORKER / "src-tauri" / "src" / "local_agent.rs").read_text(
        encoding="utf-8"
    )
    native_protocol = (
        WORKER / "src-tauri" / "src" / "local_agent_protocol.rs"
    ).read_text(encoding="utf-8")
    remote = (WORKER / "src-tauri" / "src" / "device_roots.rs").read_text(
        encoding="utf-8"
    )

    assert "hasDesktopRuntime() ? <LocalChatView" in route
    assert ": <ChatView" in route
    assert "hasDesktopRuntime()" in directory
    assert "listLocalConversations()" in directory
    assert "client.conversationsPage" in directory
    assert 'const LOCAL_PREFIX = "local:"' in local_client
    assert "/v1/chat" not in local_view
    assert "client.streamChat" not in local_view
    assert 'source: "bundled" | "development" | null' in local_client
    request_shape = native_protocol.split(
        "pub(crate) struct LocalTurnRequest", 1
    )[1].split("}", 1)[0]
    assert "approval_posture" not in request_shape
    assert "client.approvalPosture" not in local_controller
    assert 'invoke<LocalAgentPosture>("local_agent_posture")' in local_client
    assert 'invoke<LocalAgentPosture>("put_local_agent_posture"' in local_client
    assert 'runtime === "local"' in approval_surface
    assert "localAgentPosture()" in approval_surface
    assert "putLocalAgentPosture(next)" in approval_surface
    assert 'const LOCAL_POSTURE_ACCOUNT: &str = "local-agent-posture-v1"' in native
    assert 'confirm.as_deref() != Some("full_access")' in native
    assert '.title("Allow full local access?")' in native
    assert "if !cfg!(debug_assertions)" in native
    assert 'source: "bundled"' in native
    assert 'source: "development"' in native
    assert 'source == "bundled" && version != REQUIRED_RELEASE_CODEX_VERSION' in native
    assert "command_shell_refused" in remote


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
    ci_config = (
        WORKER / "src-tauri" / "tauri.ci.conf.json"
    ).read_text(encoding="utf-8")
    ci_config_payload = json.loads(ci_config)
    ci_workflow = (
        ROOT / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")

    assert 'option_env!("BOLTRIG_UPDATER_ENDPOINT")' in native
    assert 'option_env!("BOLTRIG_UPDATER_PUBLIC_KEY")' in native
    assert 'env!("CARGO_PKG_VERSION")' not in native
    assert "app.package_info().version.to_string()" in native
    assert "app.package_info().version.to_string()" in lib
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
    assert '"updater": {' in config
    assert '"pubkey": ""' in config
    # Pull requests prove that every native installer can be bundled without
    # exposing the release signing key. Tagged releases deliberately use the
    # default config above, so they still fail closed unless Tauri can emit and
    # sign updater artifacts with the protected release secret.
    assert ci_config_payload == {
        "$schema": "https://schema.tauri.app/config/2",
        "bundle": {"createUpdaterArtifacts": False},
    }
    # Unsigned pull-request installers must still satisfy the same mandatory
    # origin guard as release builds. They use loopback deliberately so a CI
    # artifact cannot contact production and cannot silently inherit a builder
    # machine's environment.
    assert "BOLTRIG_DESKTOP_API_ORIGIN: http://127.0.0.1:8000" in ci_workflow
    assert "VITE_API_BASE: http://127.0.0.1:8000" in ci_workflow
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
        wrapper.index("export async function clearDesktopSession")
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
def test_worker_only_decision_is_landed_with_attribution():
    decision = ROOT / "docs" / "decisions" / "0021-worker-primary-surface-and-realtime-voice.md"
    text = decision.read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "Worker is the sole first-party browser surface" in text
    assert "there is no second browser client" in text
    assert "realtime_voice" in text
    assert "f96ad4c8e6865f0aec519681a3717b6bcdd81546" in text
    assert "MIT License" in notices
    assert "Copyright (c) 2024 Andrew Ng" in notices


@pytest.mark.invariant("WRK-01")
def test_worker_image_is_the_only_first_party_browser_surface():
    dockerfile = (WORKER / "Dockerfile").read_text(encoding="utf-8")
    nginx = (WORKER / "nginx.conf").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'profiles: ["worker"]' not in compose
    assert "worker-ui:" in compose
    assert "COPY --from=worker-build" in dockerfile
    assert "operator-build" not in dockerfile
    assert "BOLTRIG_UI_BASE" not in dockerfile
    assert "absolute_redirect off;" in nginx
    assert "location = /operator { return 404; }" in nginx
    assert "location ^~ /operator/ { return 404; }" in nginx


@pytest.mark.invariant("WRK-02")
def test_worker_is_the_default_edge_presentation():
    caddy = (ROOT / "deploy" / "Caddyfile.example").read_text(encoding="utf-8")
    assert "{$BOLTRIG_FRONTEND_UPSTREAM:worker-ui:8080}" in caddy
    assert "{$BOLTRIG_FRONTEND_UPSTREAM:ui:80}" not in caddy
    assert not (ROOT / "deploy" / "compose.worker-primary.yml").exists()


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
def test_worker_built_artifact_has_a_gating_build_acceptance():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    package = (WORKER / "package.json").read_text(encoding="utf-8")

    assert "worker-quality" in makefile
    assert "PNPM ?= corepack pnpm" in makefile
    assert "corepack enable" not in makefile
    assert '"build": "tsc && vite build"' in package
    assert '"typecheck": "tsc --noEmit"' in package
    assert "worker-build:" in workflow
    assert "make worker-quality" in workflow


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
        "## Intentionally unavailable in the browser", 1
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
def test_worker_renders_closed_conversations_in_archived_as_restore_only():
    task_list = (
        WORKER / "src" / "components" / "shell" / "TaskList.tsx"
    ).read_text(encoding="utf-8")
    archived = (
        WORKER / "src" / "components" / "settings" / "ArchivedSection.tsx"
    ).read_text(encoding="utf-8")
    chat = (WORKER / "src" / "components" / "ChatView.tsx").read_text(encoding="utf-8")
    controls = (
        WORKER / "src" / "components" / "ConversationControls.tsx"
    ).read_text(encoding="utf-8")
    sdk = (ROOT / "sdks" / "web" / "src" / "client.ts").read_text(encoding="utf-8")

    assert 'conversation.status !== "closed"' in task_list
    assert 'row.status === "closed"' in archived
    assert "restoreMyConversation" in archived
    assert "Bring back" in archived
    assert 'conversationStatus === "closed"' in chat
    assert 'closed={conversationStatus === "closed"}' in chat
    assert 'status === "closed"' in controls
    assert "Restore conversation" in controls
    assert "/restore`" in sdk
