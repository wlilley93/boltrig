use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use ed25519_dalek::SigningKey;
use rand_core::OsRng;
use serde::Serialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

use crate::device_protocol::{
    expires_within, validate_verifier, verify_lease, AgentApi, ApiError, ClaimResponse,
    DeviceLease, EnrollmentResponse, ReceiptSubmission,
};
use crate::device_roots::{
    delete_root, execute, load_root, new_root, store_root, DeviceBuffers, ExecutionOutcome,
    NativePayloadView, NativeRootView,
};
use crate::session::{
    load_agent, remove_agent, require_api_origin, save_agent, valid_identifier, LeaseVerifier,
    PendingClaim, StoredDeviceAgent,
};

const POLL_INTERVAL: Duration = Duration::from_secs(3);
const ROTATE_WITHIN_SECONDS: i64 = 15 * 60;

pub(crate) struct DeviceRuntime {
    api: AgentApi,
    pub(crate) buffers: DeviceBuffers,
    cycle_active: AtomicBool,
    mutation_gate: tokio::sync::Mutex<()>,
}

#[derive(Debug, Serialize)]
pub(crate) struct EnrollmentView {
    device_id: String,
    label: String,
    public_key_fingerprint: String,
    session_expires_at: String,
    lease_verifier_key_id: String,
}

#[derive(Clone, Debug, Serialize)]
pub(crate) struct AgentStatus {
    state: &'static str,
    device_id: Option<String>,
    root_ids: Vec<String>,
    reason: Option<String>,
}

impl DeviceRuntime {
    pub(crate) fn new() -> Result<Self, String> {
        Ok(Self {
            api: AgentApi::new()?,
            buffers: DeviceBuffers::default(),
            cycle_active: AtomicBool::new(false),
            mutation_gate: tokio::sync::Mutex::new(()),
        })
    }
}

pub(crate) async fn complete_enrollment(
    app: &AppHandle,
    runtime: &DeviceRuntime,
    api_origin: String,
    authorization_code: String,
    expected_verifier: LeaseVerifier,
) -> Result<EnrollmentView, String> {
    let _guard = runtime.mutation_gate.lock().await;
    let origin = require_api_origin(&api_origin)?;
    validate_authorization_code(&authorization_code)?;
    validate_verifier(&expected_verifier)?;
    if load_agent()?.is_some() {
        let replace = app
            .dialog()
            .message(
                "Replace this Worker's enrolled device identity? Existing local root bindings \
                 will be removed and must be selected again.",
            )
            .title("Replace enrolled Boltrig device")
            .kind(MessageDialogKind::Warning)
            .buttons(MessageDialogButtons::YesNo)
            .blocking_show();
        if !replace {
            return Err("device_reenrollment_declined".to_string());
        }
        clear_agent_and_roots()?;
        runtime.buffers.clear()?;
    }
    let signing = SigningKey::generate(&mut OsRng);
    let public = signing.verifying_key().to_bytes();
    let response = runtime
        .api
        .complete_enrollment(
            &origin,
            &authorization_code,
            &URL_SAFE_NO_PAD.encode(public),
        )
        .await
        .map_err(|error| error.code().to_string())?;
    validate_enrollment_response(&response, &expected_verifier, &public)?;
    let agent = StoredDeviceAgent {
        version: 2,
        api_origin: origin,
        device_id: response.device.id.clone(),
        device_private_seed: URL_SAFE_NO_PAD.encode(signing.to_bytes()),
        session_token: response.session_token.clone(),
        session_expires_at: response.session_expires_at.clone(),
        lease_verifier: response.lease_verifier.clone(),
        root_ids: Vec::new(),
        pending_claim: None,
    };
    save_agent(&agent)?;
    emit_status(app, "enrolled", Some(agent.device_id.clone()), None);
    Ok(EnrollmentView {
        device_id: response.device.id,
        label: response.device.label,
        public_key_fingerprint: response.device.public_key_fingerprint,
        session_expires_at: response.session_expires_at,
        lease_verifier_key_id: response.lease_verifier.key_id,
    })
}

pub(crate) fn status() -> Result<AgentStatus, String> {
    match load_agent() {
        Ok(Some(agent)) => Ok(AgentStatus {
            state: "enrolled",
            device_id: Some(agent.device_id),
            root_ids: agent.root_ids,
            reason: None,
        }),
        Ok(None) => Ok(AgentStatus {
            state: "unenrolled",
            device_id: None,
            root_ids: Vec::new(),
            reason: None,
        }),
        Err(reason) => Ok(AgentStatus {
            state: "reenrollment_required",
            device_id: None,
            root_ids: Vec::new(),
            reason: Some(reason),
        }),
    }
}

pub(crate) async fn clear(runtime: &DeviceRuntime) -> Result<(), String> {
    let _guard = runtime.mutation_gate.lock().await;
    clear_agent_and_roots()?;
    runtime.buffers.clear()
}

pub(crate) async fn bind_root(
    app: &AppHandle,
    runtime: &DeviceRuntime,
    root_id: String,
    scope: String,
    command_enabled: bool,
) -> Result<Option<NativeRootView>, String> {
    let _guard = runtime.mutation_gate.lock().await;
    if !valid_identifier(&root_id) || !matches!(scope.as_str(), "read" | "read_write") {
        return Err("invalid_device_root".to_string());
    }
    let mut agent = load_agent()?.ok_or_else(|| "device_not_enrolled".to_string())?;
    let Some(folder) = app.dialog().file().blocking_pick_folder() else {
        return Ok(None);
    };
    let path = folder
        .into_path()
        .map_err(|_| "device_root_path_unavailable".to_string())?;
    if command_enabled {
        let approved = app
            .dialog()
            .message(
                "Allow signed argv-only command leases in this folder? Every command is still \
                 shown in a native confirmation and requires its own server approval.",
            )
            .title("Enable Boltrig commands for this root")
            .kind(MessageDialogKind::Warning)
            .buttons(MessageDialogButtons::YesNo)
            .blocking_show();
        if !approved {
            return Err("native_command_enable_declined".to_string());
        }
    }
    let root = new_root(
        agent.api_origin.clone(),
        agent.device_id.clone(),
        root_id.clone(),
        path,
        scope.clone(),
        command_enabled,
    )?;
    store_root(&root)?;
    if !agent.root_ids.contains(&root_id) {
        if agent.root_ids.len() >= 64 {
            delete_root(&agent.api_origin, &agent.device_id, &root_id)?;
            return Err("too_many_device_roots".to_string());
        }
        agent.root_ids.push(root_id.clone());
        if let Err(error) = save_agent(&agent) {
            let _ = delete_root(&agent.api_origin, &agent.device_id, &root_id);
            return Err(error);
        }
    }
    Ok(Some(NativeRootView {
        root_id,
        scope,
        command_enabled,
    }))
}

pub(crate) async fn unbind_root(runtime: &DeviceRuntime, root_id: String) -> Result<(), String> {
    let _guard = runtime.mutation_gate.lock().await;
    if !valid_identifier(&root_id) {
        return Err("invalid_device_root".to_string());
    }
    let mut agent = load_agent()?.ok_or_else(|| "device_not_enrolled".to_string())?;
    delete_root(&agent.api_origin, &agent.device_id, &root_id)?;
    agent.root_ids.retain(|item| item != &root_id);
    save_agent(&agent)
}

pub(crate) fn stage_write(
    runtime: &DeviceRuntime,
    content_digest: String,
    bytes: Vec<u8>,
) -> Result<NativePayloadView, String> {
    if load_agent()?.is_none() {
        return Err("device_not_enrolled".to_string());
    }
    runtime.buffers.stage_write(&content_digest, bytes)
}

pub(crate) fn take_read(
    runtime: &DeviceRuntime,
    lease_id: String,
) -> Result<Option<Vec<u8>>, String> {
    runtime.buffers.take_read(&lease_id)
}

pub(crate) async fn run_loop(app: AppHandle) {
    loop {
        let runtime = app.state::<DeviceRuntime>();
        if runtime
            .cycle_active
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
        {
            if let Err(reason) = run_cycle(&app, &runtime).await {
                emit_status(&app, "degraded", None, Some(reason));
            }
            runtime.cycle_active.store(false, Ordering::Release);
        }
        tokio::time::sleep(POLL_INTERVAL).await;
    }
}

async fn run_cycle(app: &AppHandle, runtime: &DeviceRuntime) -> Result<(), String> {
    let _guard = runtime.mutation_gate.lock().await;
    let Some(mut agent) = load_agent()? else {
        return Ok(());
    };
    if expires_within(&agent.session_expires_at, 0).unwrap_or(true) {
        invalidate_agent(app, runtime, "device_session_expired")?;
        return Ok(());
    }
    if agent.pending_claim.is_some() {
        settle_persisted_claim(app, runtime, &mut agent).await?;
        if agent.pending_claim.is_some() {
            return Ok(());
        }
    }
    if expires_within(&agent.session_expires_at, ROTATE_WITHIN_SECONDS).unwrap_or(true) {
        match runtime
            .api
            .rotate(&agent.api_origin, &agent.device_id, &agent.session_token)
            .await
        {
            Ok(rotated) => {
                if expires_within(&rotated.session_expires_at, 0).unwrap_or(true) {
                    invalidate_agent(app, runtime, "invalid_rotated_session")?;
                    return Ok(());
                }
                agent.session_token = rotated.session_token;
                agent.session_expires_at = rotated.session_expires_at;
                save_agent(&agent)?;
            }
            Err(ApiError::Unauthorized) => {
                invalidate_agent(app, runtime, "device_session_rejected")?;
                return Ok(());
            }
            Err(error) => {
                emit_status(
                    app,
                    "degraded",
                    Some(agent.device_id.clone()),
                    Some(error.code().to_string()),
                );
                return Ok(());
            }
        }
    }
    let leases = match runtime
        .api
        .pending(&agent.api_origin, &agent.device_id, &agent.session_token)
        .await
    {
        Ok(leases) => leases,
        Err(ApiError::Unauthorized) => {
            invalidate_agent(app, runtime, "device_revoked_or_session_rejected")?;
            return Ok(());
        }
        Err(error) => {
            emit_status(
                app,
                "degraded",
                Some(agent.device_id.clone()),
                Some(error.code().to_string()),
            );
            return Ok(());
        }
    };
    for lease in leases {
        if let Err(reason) = process_lease(app, runtime, &mut agent, lease).await {
            if reason == "device_session_rejected" {
                return Ok(());
            }
            emit_status(
                app,
                "lease_refused",
                Some(agent.device_id.clone()),
                Some(reason),
            );
        }
        if agent.pending_claim.is_some() {
            break;
        }
    }
    if agent.pending_claim.is_some() {
        return Ok(());
    }
    emit_status(app, "online", Some(agent.device_id), None);
    Ok(())
}

async fn process_lease(
    app: &AppHandle,
    runtime: &DeviceRuntime,
    agent: &mut StoredDeviceAgent,
    lease: DeviceLease,
) -> Result<(), String> {
    let action = verify_lease(&lease, &agent.device_id, &agent.lease_verifier)?;
    let claim = match runtime
        .api
        .claim(
            &agent.api_origin,
            &agent.device_id,
            &agent.session_token,
            &lease,
        )
        .await
    {
        Ok(claim) => claim,
        Err(ApiError::Unauthorized) => {
            invalidate_agent(app, runtime, "device_session_rejected")?;
            return Err("device_session_rejected".to_string());
        }
        Err(error) => return Err(error.code().to_string()),
    };
    validate_claim(&claim, &lease, agent)?;
    agent.pending_claim = Some(PendingClaim {
        lease_id: lease.id.clone(),
        claim_token: claim.claim_token,
        terminal_status: None,
        receipt: None,
    });
    if let Err(error) = save_agent(agent) {
        agent.pending_claim = None;
        return Err(error);
    }
    let outcome = match load_root(&agent.api_origin, &agent.device_id, &lease.root_id) {
        Ok(Some(root)) => execute(app, &runtime.buffers, &root, &lease, action).await,
        Ok(None) => failed("device_root_not_bound"),
        Err(_) => failed("device_root_rebind_required"),
    };
    let terminal_status = outcome.status.to_string();
    let receipt = outcome.receipt;
    if let Some(pending) = agent.pending_claim.as_mut() {
        pending.terminal_status = Some(terminal_status.clone());
        pending.receipt = Some(receipt.clone());
    }
    save_agent(agent)?;
    let _ = app.emit(
        "boltrig://device-lease-terminal",
        json!({
            "lease_id": lease.id,
            "root_id": lease.root_id,
            "verb": lease.verb,
            "status": terminal_status,
            "receipt": receipt,
        }),
    );
    settle_persisted_claim(app, runtime, agent).await
}

async fn settle_persisted_claim(
    app: &AppHandle,
    runtime: &DeviceRuntime,
    agent: &mut StoredDeviceAgent,
) -> Result<(), String> {
    let Some(mut pending) = agent.pending_claim.clone() else {
        return Ok(());
    };
    if pending.terminal_status.is_none() || pending.receipt.is_none() {
        pending.terminal_status = Some("failed".to_string());
        pending.receipt = Some(json!({"code": "agent_restart_after_claim_uncertain"}));
        agent.pending_claim = Some(pending.clone());
        save_agent(agent)?;
    }
    let status = pending
        .terminal_status
        .as_deref()
        .ok_or_else(|| "invalid_pending_claim".to_string())?;
    let receipt = pending
        .receipt
        .as_ref()
        .ok_or_else(|| "invalid_pending_claim".to_string())?;
    match runtime
        .api
        .receipt(
            &agent.api_origin,
            &agent.device_id,
            &agent.session_token,
            ReceiptSubmission {
                lease_id: &pending.lease_id,
                claim_token: &pending.claim_token,
                status,
                receipt,
            },
        )
        .await
    {
        Ok(()) | Err(ApiError::Conflict) | Err(ApiError::Rejected) => {
            agent.pending_claim = None;
            save_agent(agent)?;
            Ok(())
        }
        Err(ApiError::Unauthorized) => {
            invalidate_agent(app, runtime, "device_session_rejected")?;
            agent.pending_claim = None;
            Ok(())
        }
        Err(error) => {
            emit_status(
                app,
                "receipt_pending",
                Some(agent.device_id.clone()),
                Some(error.code().to_string()),
            );
            Ok(())
        }
    }
}

fn validate_claim(
    claim: &ClaimResponse,
    issued: &DeviceLease,
    agent: &StoredDeviceAgent,
) -> Result<(), String> {
    if claim.lease.id != issued.id
        || claim.lease.signature != issued.signature
        || claim.lease.status != "claimed"
        || claim.claim_token.is_empty()
        || claim.claim_token.len() > 16_384
        || !claim
            .claim_token
            .bytes()
            .all(|byte| byte.is_ascii_graphic())
        || expires_within(&claim.claim_expires_at, 0).unwrap_or(true)
    {
        return Err("invalid_claim_response".to_string());
    }
    let mut envelope = claim.lease.clone();
    envelope.status = "issued".to_string();
    verify_lease(&envelope, &agent.device_id, &agent.lease_verifier)?;
    Ok(())
}

fn validate_authorization_code(value: &str) -> Result<(), String> {
    if value.is_empty() || value.len() > 4096 || !value.bytes().all(|byte| byte.is_ascii_graphic())
    {
        return Err("invalid_enrollment_code".to_string());
    }
    Ok(())
}

fn validate_enrollment_response(
    response: &EnrollmentResponse,
    expected_verifier: &LeaseVerifier,
    device_public_key: &[u8; 32],
) -> Result<(), String> {
    validate_verifier(&response.lease_verifier)?;
    if response.status != "ok"
        || !valid_identifier(&response.device.id)
        || &response.lease_verifier != expected_verifier
        || response.device.public_key_fingerprint != hex::encode(Sha256::digest(device_public_key))
        || expires_within(&response.session_expires_at, 0).unwrap_or(true)
        || response.device.revoked_at.is_some()
    {
        return Err("invalid_enrollment_response".to_string());
    }
    // Parse every projected field even though only the safe summary is returned.
    if response.device.label.is_empty()
        || response.device.label.len() > 100
        || response.device.label.chars().any(char::is_control)
        || response.device.presence != "offline"
        || response.device.availability_mode != "unlocked_session"
        || !response.device.roots.is_empty()
        || response.device.last_seen_at.is_some()
    {
        return Err("invalid_enrollment_response".to_string());
    }
    Ok(())
}

fn clear_agent_and_roots() -> Result<(), String> {
    match load_agent() {
        Ok(Some(agent)) => {
            // Keep the agent record until every referenced root credential is
            // gone so a keychain failure remains safely retryable.
            for root_id in agent.root_ids {
                delete_root(&agent.api_origin, &agent.device_id, &root_id)?;
            }
            remove_agent()
        }
        Ok(None) => Ok(()),
        // A malformed or unreadable agent record cannot safely enumerate its
        // roots. Removing the known fixed agent credential restores the UI and
        // permits a fresh enrollment without exposing any root path.
        Err(_) => remove_agent(),
    }
}

fn invalidate_agent(app: &AppHandle, runtime: &DeviceRuntime, reason: &str) -> Result<(), String> {
    clear_agent_and_roots()?;
    runtime.buffers.clear()?;
    emit_status(app, "reenrollment_required", None, Some(reason.to_string()));
    Ok(())
}

fn emit_status(
    app: &AppHandle,
    state: &'static str,
    device_id: Option<String>,
    reason: Option<String>,
) {
    let root_ids = device_id
        .as_deref()
        .and_then(|expected| {
            load_agent()
                .ok()
                .flatten()
                .filter(|agent| agent.device_id == expected)
                .map(|agent| agent.root_ids)
        })
        .unwrap_or_default();
    let _ = app.emit(
        "boltrig://device-agent-status",
        AgentStatus {
            state,
            device_id,
            root_ids,
            reason,
        },
    );
}

fn failed(code: &str) -> ExecutionOutcome {
    ExecutionOutcome {
        status: "failed",
        receipt: json!({"code": code}),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn enrollment_validation_pins_the_exact_bootstrap_verifier_and_public_key() {
        let signing = SigningKey::generate(&mut OsRng);
        let lease_signing = SigningKey::generate(&mut OsRng);
        let lease_public = lease_signing.verifying_key().to_bytes();
        let verifier = LeaseVerifier {
            algorithm: "Ed25519".to_string(),
            key_id: hex::encode(Sha256::digest(lease_public)),
            public_key: URL_SAFE_NO_PAD.encode(lease_public),
        };
        let response = EnrollmentResponse {
            status: "ok".to_string(),
            device: crate::device_protocol::DeviceView {
                id: "device_1".to_string(),
                label: "Laptop".to_string(),
                public_key_fingerprint: hex::encode(Sha256::digest(
                    signing.verifying_key().to_bytes(),
                )),
                presence: "offline".to_string(),
                availability_mode: "unlocked_session".to_string(),
                roots: Vec::new(),
                last_seen_at: None,
                revoked_at: None,
            },
            session_token: "opaque".to_string(),
            session_expires_at: (time::OffsetDateTime::now_utc() + time::Duration::hours(1))
                .format(&time::format_description::well_known::Rfc3339)
                .unwrap(),
            lease_verifier: verifier.clone(),
        };
        assert!(validate_enrollment_response(
            &response,
            &verifier,
            &signing.verifying_key().to_bytes()
        )
        .is_ok());
        let mut wrong = verifier.clone();
        wrong.key_id = "0".repeat(64);
        assert!(validate_enrollment_response(
            &response,
            &wrong,
            &signing.verifying_key().to_bytes()
        )
        .is_err());
    }

    #[test]
    fn authorization_codes_are_bounded_and_never_accept_whitespace() {
        assert!(validate_authorization_code("opaque-code").is_ok());
        assert!(validate_authorization_code("").is_err());
        assert!(validate_authorization_code("contains space").is_err());
        assert!(validate_authorization_code(&"x".repeat(4097)).is_err());
    }
}
