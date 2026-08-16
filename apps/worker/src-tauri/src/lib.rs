//! Boltrig Worker desktop shell.
//!
//! The signed desktop owns two native boundaries: an enrolled, lease-driven
//! device executor and a private local Codex App Server over stdio. The latter
//! is the desktop chat runtime; it has no listener and does not receive Boltrig
//! integration credentials. The web build keeps using the hosted Fleet.

mod camera_discovery;
mod camera_protocol;
mod desktop_account;
mod desktop_oauth;
mod desktop_updater;
mod device_agent;
mod device_protocol;
mod device_roots;
mod local_agent;
mod local_agent_protocol;
mod materialized;
mod session;

use std::path::PathBuf;
use std::time::Duration;

use tauri::Manager;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

use materialized::MaterializedArtifacts;

#[tauri::command]
async fn desktop_account_login(
    app: tauri::AppHandle,
    email: String,
    password: String,
) -> Result<desktop_account::AccountResponse, String> {
    desktop_account::login(&app, email, password).await
}

#[tauri::command]
async fn desktop_account_challenge(
    app: tauri::AppHandle,
    challenge_token: String,
    code: String,
) -> Result<desktop_account::AccountResponse, String> {
    desktop_account::challenge(&app, challenge_token, code).await
}

#[tauri::command]
async fn desktop_account_refresh(
    app: tauri::AppHandle,
) -> Result<desktop_account::AccountResponse, String> {
    desktop_account::refresh(&app).await
}

#[tauri::command]
async fn desktop_account_logout(
    app: tauri::AppHandle,
) -> Result<desktop_account::AccountResponse, String> {
    desktop_account::logout(&app).await
}

#[tauri::command]
async fn desktop_api_request(
    app: tauri::AppHandle,
    method: String,
    path: String,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
) -> Result<tauri::ipc::Response, String> {
    desktop_account::api_request(&app, method, path, headers, body).await
}

#[tauri::command]
fn camera_discover(
    runtime: tauri::State<'_, camera_discovery::CameraRuntime>,
) -> Result<camera_discovery::CameraDiscoveryStatus, String> {
    runtime.refresh()
}

#[tauri::command]
fn camera_status(
    runtime: tauri::State<'_, camera_discovery::CameraRuntime>,
) -> Result<camera_discovery::CameraDiscoveryStatus, String> {
    runtime.status()
}

#[tauri::command]
fn camera_verify_snapshot(
    runtime: tauri::State<'_, camera_discovery::CameraRuntime>,
    camera_id: String,
) -> Result<camera_discovery::CameraVerification, String> {
    runtime.verify_snapshot(&camera_id)
}

#[tauri::command]
fn camera_verify_ptz(
    runtime: tauri::State<'_, camera_discovery::CameraRuntime>,
    camera_id: String,
) -> Result<camera_discovery::CameraVerification, String> {
    runtime.verify_ptz(&camera_id)
}

#[tauri::command]
fn camera_validate_lease(
    runtime: tauri::State<'_, camera_discovery::CameraRuntime>,
    lease: camera_protocol::CameraLease,
    expected_device_id: String,
    verifier: session::LeaseVerifier,
) -> Result<camera_discovery::CameraLeaseValidation, String> {
    runtime.validate_lease(lease, &expected_device_id, &verifier)
}

const MAX_ARTIFACT_BYTES: usize = 100 * 1024 * 1024;

#[tauri::command]
async fn complete_device_enrollment(
    app: tauri::AppHandle,
    runtime: tauri::State<'_, device_agent::DeviceRuntime>,
    api_origin: String,
    authorization_code: String,
    expected_verifier: session::LeaseVerifier,
) -> Result<device_agent::EnrollmentView, String> {
    let api_origin = desktop_account::require_configured_origin(&api_origin)?;
    device_agent::complete_enrollment(
        &app,
        &runtime,
        api_origin,
        authorization_code,
        expected_verifier,
    )
    .await
}

#[tauri::command]
async fn clear_device_session(
    runtime: tauri::State<'_, device_agent::DeviceRuntime>,
) -> Result<(), String> {
    local_agent::reset_posture()?;
    device_agent::clear(&runtime).await
}

#[tauri::command]
async fn device_agent_status() -> Result<device_agent::AgentStatus, String> {
    // macOS may ask the user to re-authorize Keychain access after an app
    // update. Never perform that synchronous Security.framework call on the
    // Tauri event loop: the authorization sheet itself needs the event loop.
    tokio::time::timeout(
        Duration::from_secs(15),
        tauri::async_runtime::spawn_blocking(device_agent::status),
    )
    .await
    .map_err(|_| "device_agent_status_timeout".to_string())?
    .map_err(|_| "device_agent_status_unavailable".to_string())?
}

#[tauri::command]
async fn bind_device_root(
    app: tauri::AppHandle,
    runtime: tauri::State<'_, device_agent::DeviceRuntime>,
    root_id: String,
    scope: String,
    command_enabled: bool,
) -> Result<Option<device_roots::NativeRootView>, String> {
    device_agent::bind_root(&app, &runtime, root_id, scope, command_enabled).await
}

#[tauri::command]
async fn unbind_device_root(
    runtime: tauri::State<'_, device_agent::DeviceRuntime>,
    root_id: String,
) -> Result<(), String> {
    device_agent::unbind_root(&runtime, root_id).await
}

#[tauri::command]
fn stage_device_write(
    runtime: tauri::State<'_, device_agent::DeviceRuntime>,
    content_digest: String,
    bytes: Vec<u8>,
) -> Result<device_roots::NativePayloadView, String> {
    device_agent::stage_write(&runtime, content_digest, bytes)
}

#[tauri::command]
fn take_device_read_result(
    runtime: tauri::State<'_, device_agent::DeviceRuntime>,
    lease_id: String,
) -> Result<Option<Vec<u8>>, String> {
    device_agent::take_read(&runtime, lease_id)
}

#[tauri::command]
async fn local_agent_status(
    app: tauri::AppHandle,
    runtime: tauri::State<'_, local_agent::LocalAgentRuntime>,
) -> Result<local_agent::LocalAgentStatus, String> {
    Ok(runtime.status(&app).await)
}

#[tauri::command]
fn local_agent_roots() -> Result<Vec<local_agent::LocalAgentRoot>, String> {
    local_agent::roots()
}

#[tauri::command]
fn local_agent_posture() -> Result<local_agent::LocalAgentPostureView, String> {
    local_agent::posture()
}

#[tauri::command]
async fn put_local_agent_posture(
    app: tauri::AppHandle,
    runtime: tauri::State<'_, local_agent::LocalAgentRuntime>,
    posture: local_agent_protocol::ApprovalPosture,
    confirm: Option<String>,
) -> Result<local_agent::LocalAgentPostureView, String> {
    runtime.set_posture(&app, posture, confirm).await
}

#[tauri::command]
async fn run_local_agent_turn(
    app: tauri::AppHandle,
    runtime: tauri::State<'_, local_agent::LocalAgentRuntime>,
    request: local_agent_protocol::LocalTurnRequest,
    on_event: tauri::ipc::Channel<local_agent_protocol::LocalAgentEvent>,
) -> Result<local_agent_protocol::LocalTurnOutcome, String> {
    let version = app.package_info().version.to_string();
    local_agent::run_turn(&app, &runtime, request, on_event, &version).await
}

#[tauri::command]
async fn stop_local_agent_turn(
    runtime: tauri::State<'_, local_agent::LocalAgentRuntime>,
) -> Result<(), String> {
    local_agent::stop(&runtime).await
}

fn safe_name(value: &str) -> String {
    let leaf = PathBuf::from(value)
        .file_name()
        .and_then(|item| item.to_str())
        .unwrap_or("artifact")
        .chars()
        .filter(|ch| !ch.is_control() && *ch != '/' && *ch != '\\')
        .take(180)
        .collect::<String>();
    if leaf.is_empty() {
        "artifact".to_string()
    } else {
        leaf
    }
}

/// Materialize bytes the authenticated HTTP client has already downloaded.
/// The user selects the destination in a native dialog; the command accepts no
/// destination path from an agent or web payload.
#[tauri::command]
async fn materialize_artifact(
    app: tauri::AppHandle,
    registry: tauri::State<'_, MaterializedArtifacts>,
    suggested_name: String,
    bytes: Vec<u8>,
) -> Result<Option<String>, String> {
    if bytes.len() > MAX_ARTIFACT_BYTES {
        return Err("artifact_too_large".to_string());
    }
    let (sender, receiver) = tokio::sync::oneshot::channel();
    app.dialog()
        .file()
        .set_file_name(safe_name(&suggested_name))
        .save_file(move |path| {
            let _ = sender.send(path);
        });
    // The dialog is not window-modal and stays open for as long as the user
    // leaves it open. Awaiting the selection yields the runtime worker instead
    // of parking it, so the device agent's poll and rotation loop keeps running
    // behind an open dialog.
    let Some(path) = receiver.await.map_err(|_| "dialog_closed".to_string())? else {
        return Ok(None);
    };
    let destination = PathBuf::from(path.to_string());
    std::fs::write(&destination, bytes).map_err(|_| "artifact_write_failed".to_string())?;
    registry.remember(destination).map(Some)
}

#[tauri::command]
fn open_materialized_artifact(
    app: tauri::AppHandle,
    registry: tauri::State<'_, MaterializedArtifacts>,
    handle: String,
) -> Result<(), String> {
    let path = registry.resolve(&handle)?;
    app.opener()
        .open_path(path.to_string_lossy().into_owned(), None::<String>)
        .map_err(|_| "artifact_open_failed".to_string())
}

#[tauri::command]
fn reveal_materialized_artifact(
    app: tauri::AppHandle,
    registry: tauri::State<'_, MaterializedArtifacts>,
    handle: String,
) -> Result<(), String> {
    let path = registry.resolve(&handle)?;
    app.opener()
        .reveal_item_in_dir(path)
        .map_err(|_| "artifact_reveal_failed".to_string())
}

#[tauri::command]
fn desktop_update_readiness(app: tauri::AppHandle) -> desktop_updater::UpdateReadiness {
    desktop_updater::readiness(app.package_info().version.to_string())
}

#[tauri::command]
async fn check_desktop_update(
    app: tauri::AppHandle,
    runtime: tauri::State<'_, desktop_updater::UpdateRuntime>,
) -> Result<desktop_updater::UpdateCheck, String> {
    desktop_updater::check(&app, &runtime).await
}

#[tauri::command]
async fn install_desktop_update(
    runtime: tauri::State<'_, desktop_updater::UpdateRuntime>,
    expected_version: String,
    on_event: tauri::ipc::Channel<desktop_updater::UpdateProgress>,
) -> Result<(), String> {
    desktop_updater::install(&runtime, &expected_version, on_event).await
}

#[tauri::command]
fn restart_desktop_after_update(
    app: tauri::AppHandle,
    runtime: tauri::State<'_, desktop_updater::UpdateRuntime>,
) -> Result<(), String> {
    desktop_updater::take_restart_ready(&runtime)?;
    app.request_restart();
    Ok(())
}

#[tauri::command]
fn desktop_oauth_return_readiness(
    runtime: tauri::State<'_, desktop_oauth::OAuthReturnRuntime>,
) -> desktop_oauth::OAuthReturnReadiness {
    runtime.readiness()
}

#[tauri::command]
fn arm_desktop_oauth_return(
    runtime: tauri::State<'_, desktop_oauth::OAuthReturnRuntime>,
    integration_id: String,
    state: String,
    expires_at: String,
) -> Result<(), String> {
    runtime.arm(&integration_id, &state, &expires_at)
}

#[tauri::command]
fn take_desktop_oauth_return(
    runtime: tauri::State<'_, desktop_oauth::OAuthReturnRuntime>,
    integration_id: String,
    expected_state: String,
) -> Result<Option<desktop_oauth::OAuthReturnView>, String> {
    runtime.take(&integration_id, &expected_state)
}

#[tauri::command]
fn cancel_desktop_oauth_return(
    runtime: tauri::State<'_, desktop_oauth::OAuthReturnRuntime>,
    integration_id: String,
    expected_state: String,
) -> Result<(), String> {
    runtime.cancel(&integration_id, &expected_state)
}

pub fn run() {
    let runtime = device_agent::DeviceRuntime::new()
        .expect("Boltrig Worker device HTTP client failed to initialize");
    let camera_runtime = camera_discovery::CameraRuntime::new();
    tauri::Builder::default()
        .manage(runtime)
        .manage(camera_runtime)
        .manage(local_agent::LocalAgentRuntime::new())
        .manage(MaterializedArtifacts::default())
        .manage(desktop_updater::UpdateRuntime::default())
        .manage(desktop_oauth::OAuthReturnRuntime::default())
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_opener::Builder::new()
                .open_js_links_on_click(false)
                .build(),
        )
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            desktop_oauth::configure(app);
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(device_agent::run_loop(handle));
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(camera_discovery::run_loop(handle));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            complete_device_enrollment,
            desktop_account_login,
            desktop_account_challenge,
            desktop_account_refresh,
            desktop_account_logout,
            desktop_api_request,
            clear_device_session,
            device_agent_status,
            camera_discover,
            camera_status,
            camera_verify_snapshot,
            camera_verify_ptz,
            camera_validate_lease,
            bind_device_root,
            unbind_device_root,
            stage_device_write,
            take_device_read_result,
            local_agent_status,
            local_agent_roots,
            local_agent_posture,
            put_local_agent_posture,
            run_local_agent_turn,
            stop_local_agent_turn,
            materialize_artifact,
            open_materialized_artifact,
            reveal_materialized_artifact,
            desktop_update_readiness,
            check_desktop_update,
            install_desktop_update,
            restart_desktop_after_update,
            desktop_oauth_return_readiness,
            arm_desktop_oauth_return,
            take_desktop_oauth_return,
            cancel_desktop_oauth_return,
        ])
        .run(tauri::generate_context!())
        .expect("Boltrig Worker failed to start");
}
