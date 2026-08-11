use std::collections::BTreeMap;
use std::time::Duration;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use reqwest::{redirect::Policy, Client, Response, StatusCode};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;

use crate::camera_protocol::CameraLease;
use crate::session::{valid_identifier, LeaseVerifier};

const MAX_RESPONSE_BYTES: usize = 256 * 1024;
const MAX_FILE_BYTES: u64 = 100 * 1024 * 1024;
const MAX_PATH_BYTES: usize = 1024;
const MAX_ARG_BYTES: usize = 4096;
const MAX_ARGS: usize = 64;

#[derive(Clone, Debug)]
pub(crate) enum ApiError {
    Unauthorized,
    Conflict,
    Rejected,
    Transport,
    InvalidResponse,
}

impl ApiError {
    pub(crate) fn code(&self) -> &'static str {
        match self {
            Self::Unauthorized => "device_session_rejected",
            Self::Conflict => "device_claim_conflict",
            Self::Rejected => "device_api_rejected",
            Self::Transport => "device_api_unavailable",
            Self::InvalidResponse => "invalid_device_api_response",
        }
    }
}

#[derive(Clone)]
pub(crate) struct AgentApi {
    client: Client,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct DeviceView {
    pub(crate) id: String,
    pub(crate) label: String,
    pub(crate) public_key_fingerprint: String,
    pub(crate) presence: String,
    pub(crate) availability_mode: String,
    pub(crate) roots: Vec<Value>,
    pub(crate) last_seen_at: Option<String>,
    pub(crate) revoked_at: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct EnrollmentResponse {
    pub(crate) status: String,
    pub(crate) device: DeviceView,
    pub(crate) session_token: String,
    pub(crate) session_expires_at: String,
    pub(crate) lease_verifier: LeaseVerifier,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct DeviceLease {
    pub(crate) version: u8,
    pub(crate) id: String,
    pub(crate) tenant_id: String,
    pub(crate) device_id: String,
    pub(crate) root_id: String,
    pub(crate) owner_id: String,
    pub(crate) verb: String,
    pub(crate) action: Value,
    pub(crate) action_digest: String,
    pub(crate) approval_id: String,
    pub(crate) issued_at: String,
    pub(crate) expires_at: String,
    pub(crate) signing_key_id: String,
    pub(crate) signature: String,
    pub(crate) status: String,
}

#[derive(Debug)]
pub(crate) enum ValidatedAction {
    Read {
        relative_path: String,
        max_bytes: u64,
    },
    Write {
        relative_path: String,
        content_digest: String,
        byte_size: u64,
        overwrite: bool,
    },
    Command {
        argv: Vec<String>,
        cwd_relative: Option<String>,
        timeout_seconds: u64,
    },
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PendingResponse {
    leases: Vec<DeviceLease>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ClaimResponse {
    pub(crate) lease: DeviceLease,
    pub(crate) claim_token: String,
    pub(crate) claim_expires_at: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CameraClaimResponse {
    pub(crate) lease: CameraLease,
    pub(crate) claim_token: String,
    pub(crate) claim_expires_at: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CameraPendingResponse {
    leases: Vec<CameraLease>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RotateResponse {
    pub(crate) session_token: String,
    pub(crate) session_expires_at: String,
}

pub(crate) struct ReceiptSubmission<'a> {
    pub(crate) lease_id: &'a str,
    pub(crate) claim_token: &'a str,
    pub(crate) status: &'a str,
    pub(crate) receipt: &'a Value,
}

impl AgentApi {
    pub(crate) fn new() -> Result<Self, String> {
        let client = Client::builder()
            .redirect(Policy::none())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(20))
            .user_agent("boltrig-worker-device-agent/0.1")
            .build()
            .map_err(|_| "device_http_client_unavailable".to_string())?;
        Ok(Self { client })
    }

    pub(crate) async fn complete_enrollment(
        &self,
        origin: &str,
        authorization_code: &str,
        device_public_key: &str,
    ) -> Result<EnrollmentResponse, ApiError> {
        let response = self
            .client
            .post(endpoint(origin, "/v1/device-agent/enrollment/complete"))
            .json(&json!({
                "authorization_code": authorization_code,
                "device_public_key": device_public_key,
            }))
            .send()
            .await
            .map_err(|_| ApiError::Transport)?;
        decode_success(response).await
    }

    pub(crate) async fn pending(
        &self,
        origin: &str,
        device_id: &str,
        token: &str,
    ) -> Result<Vec<DeviceLease>, ApiError> {
        let response = self
            .client
            .get(endpoint(
                origin,
                &format!("/v1/device-agent/{device_id}/leases"),
            ))
            .bearer_auth(token)
            .send()
            .await
            .map_err(|_| ApiError::Transport)?;
        decode_success::<PendingResponse>(response)
            .await
            .map(|body| body.leases)
    }

    pub(crate) async fn claim(
        &self,
        origin: &str,
        device_id: &str,
        token: &str,
        lease: &DeviceLease,
    ) -> Result<ClaimResponse, ApiError> {
        let response = self
            .client
            .post(endpoint(
                origin,
                &format!("/v1/device-agent/{device_id}/leases/{}/claim", lease.id),
            ))
            .bearer_auth(token)
            .json(&json!({"signature": lease.signature}))
            .send()
            .await
            .map_err(|_| ApiError::Transport)?;
        decode_success(response).await
    }

    pub(crate) async fn publish_camera_binding(
        &self,
        origin: &str,
        device_id: &str,
        token: &str,
        binding: &Value,
    ) -> Result<(), ApiError> {
        let response = self
            .client
            .post(endpoint(
                origin,
                &format!("/v1/device-agent/{device_id}/camera-bindings"),
            ))
            .bearer_auth(token)
            .json(binding)
            .send()
            .await
            .map_err(|_| ApiError::Transport)?;
        let _: Value = decode_success(response).await?;
        Ok(())
    }

    pub(crate) async fn pending_camera(
        &self,
        origin: &str,
        device_id: &str,
        token: &str,
    ) -> Result<Vec<CameraLease>, ApiError> {
        let response = self
            .client
            .get(endpoint(
                origin,
                &format!("/v1/device-agent/{device_id}/camera-leases"),
            ))
            .bearer_auth(token)
            .send()
            .await
            .map_err(|_| ApiError::Transport)?;
        decode_success::<CameraPendingResponse>(response)
            .await
            .map(|body| body.leases)
    }

    pub(crate) async fn claim_camera(
        &self,
        origin: &str,
        device_id: &str,
        token: &str,
        lease: &CameraLease,
    ) -> Result<CameraClaimResponse, ApiError> {
        let response = self
            .client
            .post(endpoint(
                origin,
                &format!(
                    "/v1/device-agent/{device_id}/camera-leases/{}/claim",
                    lease.id
                ),
            ))
            .bearer_auth(token)
            .json(&json!({"signature": lease.signature}))
            .send()
            .await
            .map_err(|_| ApiError::Transport)?;
        decode_success(response).await
    }

    pub(crate) async fn camera_receipt(
        &self,
        origin: &str,
        device_id: &str,
        token: &str,
        submission: ReceiptSubmission<'_>,
    ) -> Result<(), ApiError> {
        let response = self
            .client
            .post(endpoint(
                origin,
                &format!(
                    "/v1/device-agent/{device_id}/camera-leases/{}/receipt",
                    submission.lease_id
                ),
            ))
            .bearer_auth(token)
            .json(&json!({
                "claim_token": submission.claim_token,
                "status": submission.status,
                "receipt": submission.receipt,
            }))
            .send()
            .await
            .map_err(|_| ApiError::Transport)?;
        if response.status().is_success() {
            let _: Value = decode_success(response).await?;
            return Ok(());
        }
        Err(classify_status(response.status()))
    }

    pub(crate) async fn receipt(
        &self,
        origin: &str,
        device_id: &str,
        token: &str,
        submission: ReceiptSubmission<'_>,
    ) -> Result<(), ApiError> {
        let response = self
            .client
            .post(endpoint(
                origin,
                &format!(
                    "/v1/device-agent/{device_id}/leases/{}/receipt",
                    submission.lease_id
                ),
            ))
            .bearer_auth(token)
            .json(&json!({
                "claim_token": submission.claim_token,
                "status": submission.status,
                "receipt": submission.receipt,
            }))
            .send()
            .await
            .map_err(|_| ApiError::Transport)?;
        if response.status().is_success() {
            let _: Value = decode_success(response).await?;
            return Ok(());
        }
        Err(classify_status(response.status()))
    }

    pub(crate) async fn rotate(
        &self,
        origin: &str,
        device_id: &str,
        token: &str,
    ) -> Result<RotateResponse, ApiError> {
        let response = self
            .client
            .post(endpoint(
                origin,
                &format!("/v1/device-agent/{device_id}/session/rotate"),
            ))
            .bearer_auth(token)
            .send()
            .await
            .map_err(|_| ApiError::Transport)?;
        decode_success(response).await
    }
}

fn endpoint(origin: &str, path: &str) -> String {
    format!("{origin}{path}")
}

fn classify_status(status: StatusCode) -> ApiError {
    match status {
        StatusCode::UNAUTHORIZED => ApiError::Unauthorized,
        StatusCode::CONFLICT => ApiError::Conflict,
        _ => ApiError::Rejected,
    }
}

async fn decode_success<T: DeserializeOwned>(mut response: Response) -> Result<T, ApiError> {
    if !response.status().is_success() {
        return Err(classify_status(response.status()));
    }
    if response
        .content_length()
        .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
    {
        return Err(ApiError::InvalidResponse);
    }
    let mut bytes = Vec::with_capacity(
        response
            .content_length()
            .unwrap_or(4096)
            .min(MAX_RESPONSE_BYTES as u64) as usize,
    );
    while let Some(chunk) = response.chunk().await.map_err(|_| ApiError::Transport)? {
        if bytes.len().saturating_add(chunk.len()) > MAX_RESPONSE_BYTES {
            return Err(ApiError::InvalidResponse);
        }
        bytes.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&bytes).map_err(|_| ApiError::InvalidResponse)
}

pub(crate) fn validate_verifier(verifier: &LeaseVerifier) -> Result<VerifyingKey, String> {
    if verifier.algorithm != "Ed25519"
        || verifier.key_id.len() != 64
        || !is_lower_hex(&verifier.key_id)
    {
        return Err("invalid_lease_verifier".to_string());
    }
    let raw = URL_SAFE_NO_PAD
        .decode(&verifier.public_key)
        .map_err(|_| "invalid_lease_verifier".to_string())?;
    let bytes: [u8; 32] = raw
        .try_into()
        .map_err(|_| "invalid_lease_verifier".to_string())?;
    let key = VerifyingKey::from_bytes(&bytes).map_err(|_| "invalid_lease_verifier".to_string())?;
    if hex::encode(Sha256::digest(bytes)) != verifier.key_id {
        return Err("invalid_lease_verifier".to_string());
    }
    Ok(key)
}

pub(crate) fn verify_lease(
    lease: &DeviceLease,
    expected_device_id: &str,
    verifier: &LeaseVerifier,
) -> Result<ValidatedAction, String> {
    if lease.version != 1
        || lease.status != "issued"
        || lease.device_id != expected_device_id
        || lease.signing_key_id != verifier.key_id
        || !valid_identifier(&lease.id)
        || !valid_identifier(&lease.device_id)
        || !valid_identifier(&lease.root_id)
        || !valid_identifier(&lease.approval_id)
        || lease.tenant_id.is_empty()
        || lease.tenant_id.len() > 256
        || lease.owner_id.is_empty()
        || lease.owner_id.len() > 256
    {
        return Err("invalid_lease_envelope".to_string());
    }
    let action = validate_action(&lease.verb, &lease.action)?;
    let expected_digest = action_digest(lease)?;
    if !constant_time_eq(expected_digest.as_bytes(), lease.action_digest.as_bytes()) {
        return Err("lease_action_digest_mismatch".to_string());
    }
    let issued_at = parse_time(&lease.issued_at)?;
    let expires_at = parse_time(&lease.expires_at)?;
    let now = OffsetDateTime::now_utc();
    if expires_at <= now
        || expires_at <= issued_at
        || expires_at - issued_at > time::Duration::minutes(3)
        || issued_at > now + time::Duration::seconds(30)
    {
        return Err("lease_expired_or_invalid".to_string());
    }
    let signature_bytes = URL_SAFE_NO_PAD
        .decode(&lease.signature)
        .map_err(|_| "invalid_lease_signature".to_string())?;
    let signature = Signature::from_slice(&signature_bytes)
        .map_err(|_| "invalid_lease_signature".to_string())?;
    validate_verifier(verifier)?
        .verify(&canonical_lease_bytes(lease)?, &signature)
        .map_err(|_| "invalid_lease_signature".to_string())?;
    Ok(action)
}

fn validate_action(verb: &str, action: &Value) -> Result<ValidatedAction, String> {
    let object = action
        .as_object()
        .ok_or_else(|| "invalid_device_action".to_string())?;
    match verb {
        "device.file.read" => {
            exact_keys(object, &["max_bytes", "relative_path"])?;
            let relative_path = relative_path(string_field(object, "relative_path")?)?;
            let max_bytes = u64_field(object, "max_bytes")?;
            if !(1..=MAX_FILE_BYTES).contains(&max_bytes) {
                return Err("invalid_device_action".to_string());
            }
            Ok(ValidatedAction::Read {
                relative_path,
                max_bytes,
            })
        }
        "device.file.write" => {
            exact_keys(
                object,
                &["byte_size", "content_digest", "overwrite", "relative_path"],
            )?;
            let relative_path = relative_path(string_field(object, "relative_path")?)?;
            let content_digest = string_field(object, "content_digest")?.to_string();
            let byte_size = u64_field(object, "byte_size")?;
            let overwrite = object
                .get("overwrite")
                .and_then(Value::as_bool)
                .ok_or_else(|| "invalid_device_action".to_string())?;
            if byte_size > MAX_FILE_BYTES
                || content_digest.len() != 64
                || !is_lower_hex(&content_digest)
            {
                return Err("invalid_device_action".to_string());
            }
            Ok(ValidatedAction::Write {
                relative_path,
                content_digest,
                byte_size,
                overwrite,
            })
        }
        "device.command.run" => {
            exact_keys(object, &["argv", "cwd_relative", "timeout_seconds"])?;
            let argv_value = object
                .get("argv")
                .and_then(Value::as_array)
                .ok_or_else(|| "invalid_device_action".to_string())?;
            if argv_value.is_empty() || argv_value.len() > MAX_ARGS {
                return Err("invalid_device_action".to_string());
            }
            let mut argv = Vec::with_capacity(argv_value.len());
            for value in argv_value {
                let argument = value
                    .as_str()
                    .ok_or_else(|| "invalid_device_action".to_string())?;
                if argument.is_empty() || argument.len() > MAX_ARG_BYTES || argument.contains('\0')
                {
                    return Err("invalid_device_action".to_string());
                }
                argv.push(argument.to_string());
            }
            let cwd_relative = match object.get("cwd_relative") {
                Some(Value::Null) => None,
                Some(Value::String(value)) => Some(relative_path(value)?),
                _ => return Err("invalid_device_action".to_string()),
            };
            let timeout_seconds = u64_field(object, "timeout_seconds")?;
            if !(1..=300).contains(&timeout_seconds) {
                return Err("invalid_device_action".to_string());
            }
            Ok(ValidatedAction::Command {
                argv,
                cwd_relative,
                timeout_seconds,
            })
        }
        _ => Err("unsupported_device_verb".to_string()),
    }
}

fn exact_keys(object: &Map<String, Value>, expected: &[&str]) -> Result<(), String> {
    let actual = object.keys().map(String::as_str).collect::<Vec<_>>();
    if actual.len() != expected.len() || expected.iter().any(|key| !actual.contains(key)) {
        return Err("invalid_device_action".to_string());
    }
    Ok(())
}

fn string_field<'a>(object: &'a Map<String, Value>, key: &str) -> Result<&'a str, String> {
    object
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| "invalid_device_action".to_string())
}

fn u64_field(object: &Map<String, Value>, key: &str) -> Result<u64, String> {
    object
        .get(key)
        .and_then(Value::as_u64)
        .ok_or_else(|| "invalid_device_action".to_string())
}

pub(crate) fn relative_path(value: &str) -> Result<String, String> {
    if value.is_empty()
        || value.len() > MAX_PATH_BYTES
        || value.contains('\\')
        || value.contains('\0')
        || value.starts_with('/')
        || value
            .split('/')
            .any(|part| part.is_empty() || matches!(part, "." | ".."))
    {
        return Err("invalid_relative_path".to_string());
    }
    Ok(value.to_string())
}

fn action_digest(lease: &DeviceLease) -> Result<String, String> {
    let action = lease
        .action
        .as_object()
        .ok_or_else(|| "invalid_device_action".to_string())?;
    let mut params = Map::new();
    params.insert("device_id".to_string(), json!(lease.device_id));
    params.insert("root_id".to_string(), json!(lease.root_id));
    for (key, value) in action {
        params.insert(key.clone(), value.clone());
    }
    let payload = json!({
        "version": 1,
        "noun": "device",
        "verb": lease.verb,
        "params": params,
    });
    Ok(hex::encode(Sha256::digest(canonical_json(&payload)?)))
}

fn canonical_lease_bytes(lease: &DeviceLease) -> Result<Vec<u8>, String> {
    canonical_json(&json!({
        "version": lease.version,
        "id": lease.id,
        "tenant_id": lease.tenant_id,
        "device_id": lease.device_id,
        "root_id": lease.root_id,
        "owner_id": lease.owner_id,
        "verb": lease.verb,
        "action": lease.action,
        "action_digest": lease.action_digest,
        "approval_id": lease.approval_id,
        "issued_at": lease.issued_at,
        "expires_at": lease.expires_at,
        "signing_key_id": lease.signing_key_id,
    }))
}

fn canonical_json(value: &Value) -> Result<Vec<u8>, String> {
    let mut output = Vec::new();
    write_canonical(value, &mut output)?;
    Ok(output)
}

fn write_canonical(value: &Value, output: &mut Vec<u8>) -> Result<(), String> {
    match value {
        Value::Null => output.extend_from_slice(b"null"),
        Value::Bool(true) => output.extend_from_slice(b"true"),
        Value::Bool(false) => output.extend_from_slice(b"false"),
        Value::Number(number) => output.extend_from_slice(number.to_string().as_bytes()),
        Value::String(string) => output.extend_from_slice(
            serde_json::to_string(string)
                .map_err(|_| "canonical_json_failed".to_string())?
                .as_bytes(),
        ),
        Value::Array(values) => {
            output.push(b'[');
            for (index, item) in values.iter().enumerate() {
                if index > 0 {
                    output.push(b',');
                }
                write_canonical(item, output)?;
            }
            output.push(b']');
        }
        Value::Object(values) => {
            output.push(b'{');
            let sorted = values.iter().collect::<BTreeMap<_, _>>();
            for (index, (key, item)) in sorted.into_iter().enumerate() {
                if index > 0 {
                    output.push(b',');
                }
                write_canonical(&Value::String(key.clone()), output)?;
                output.push(b':');
                write_canonical(item, output)?;
            }
            output.push(b'}');
        }
    }
    Ok(())
}

fn parse_time(value: &str) -> Result<OffsetDateTime, String> {
    OffsetDateTime::parse(value, &Rfc3339).map_err(|_| "invalid_lease_time".to_string())
}

pub(crate) fn expires_within(value: &str, seconds: i64) -> Result<bool, String> {
    Ok(parse_time(value)? <= OffsetDateTime::now_utc() + time::Duration::seconds(seconds))
}

fn is_lower_hex(value: &str) -> bool {
    value
        .bytes()
        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0_u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use rand_core::OsRng;

    fn signed_lease(action: Value, verb: &str) -> (DeviceLease, LeaseVerifier) {
        let signing = SigningKey::generate(&mut OsRng);
        let public = signing.verifying_key().to_bytes();
        let verifier = LeaseVerifier {
            algorithm: "Ed25519".to_string(),
            key_id: hex::encode(Sha256::digest(public)),
            public_key: URL_SAFE_NO_PAD.encode(public),
        };
        let now = OffsetDateTime::now_utc();
        let mut lease = DeviceLease {
            version: 1,
            id: "lease_1".to_string(),
            tenant_id: "tenant".to_string(),
            device_id: "device_1".to_string(),
            root_id: "root_1".to_string(),
            owner_id: "alice".to_string(),
            verb: verb.to_string(),
            action,
            action_digest: String::new(),
            approval_id: "approval_1".to_string(),
            issued_at: now.format(&Rfc3339).unwrap(),
            expires_at: (now + time::Duration::minutes(2)).format(&Rfc3339).unwrap(),
            signing_key_id: verifier.key_id.clone(),
            signature: String::new(),
            status: "issued".to_string(),
        };
        lease.action_digest = action_digest(&lease).unwrap();
        lease.signature = URL_SAFE_NO_PAD.encode(
            signing
                .sign(&canonical_lease_bytes(&lease).unwrap())
                .to_bytes(),
        );
        (lease, verifier)
    }

    #[test]
    fn canonical_signed_read_verifies_and_any_field_tamper_fails() {
        let (lease, verifier) = signed_lease(
            json!({"relative_path": "reports/final.txt", "max_bytes": 4096}),
            "device.file.read",
        );
        assert!(matches!(
            verify_lease(&lease, "device_1", &verifier).unwrap(),
            ValidatedAction::Read { .. }
        ));
        let mut tampered = lease.clone();
        tampered.root_id = "root_2".to_string();
        assert!(verify_lease(&tampered, "device_1", &verifier).is_err());
        let mut tampered = lease.clone();
        tampered.action["relative_path"] = json!("other.txt");
        assert!(verify_lease(&tampered, "device_1", &verifier).is_err());
    }

    #[test]
    fn strict_actions_reject_traversal_shell_strings_and_missing_write_digest() {
        assert!(relative_path("../secret").is_err());
        assert!(relative_path("reports/./secret").is_err());
        assert!(validate_action(
            "device.command.run",
            &json!({"argv": "git status", "cwd_relative": null, "timeout_seconds": 30})
        )
        .is_err());
        assert!(validate_action(
            "device.file.write",
            &json!({
                "relative_path": "output.txt",
                "byte_size": 4,
                "overwrite": false
            })
        )
        .is_err());
    }

    #[test]
    fn verifier_key_id_is_derived_from_the_exact_public_key() {
        let (_, verifier) = signed_lease(
            json!({"relative_path": "safe.txt", "max_bytes": 1}),
            "device.file.read",
        );
        assert!(validate_verifier(&verifier).is_ok());
        let mut wrong = verifier;
        wrong.key_id = "0".repeat(64);
        assert!(validate_verifier(&wrong).is_err());
    }

    #[test]
    fn rust_matches_the_python_kernel_canonical_lease_fixture() {
        let lease = DeviceLease {
            version: 1,
            id: "lease_1".to_string(),
            tenant_id: "tenant".to_string(),
            device_id: "device_1".to_string(),
            root_id: "root_1".to_string(),
            owner_id: "alice".to_string(),
            verb: "device.file.read".to_string(),
            action: json!({
                "relative_path": "reports/é.txt",
                "max_bytes": 4096,
            }),
            action_digest:
                "17f24a92579b6c886440421261b2839acd82c9a4ef7e0d0efde265617e6c670f"
                    .to_string(),
            approval_id: "approval_1".to_string(),
            issued_at: "2030-01-02T03:04:05+00:00".to_string(),
            expires_at: "2030-01-02T03:06:05+00:00".to_string(),
            signing_key_id:
                "56475aa75463474c0285df5dbf2bcab73da651358839e9b77481b2eab107708c"
                    .to_string(),
            signature:
                "R2vgXJUkWxqhp-_8RzLDC6pfVsW-gDGZt7f1KwxQ8TWlOfODxwGgfcrBk7d3c4qrgjWIke79eBB90kG-BMwvDw"
                    .to_string(),
            status: "issued".to_string(),
        };
        assert_eq!(action_digest(&lease).unwrap(), lease.action_digest);
        let canonical = String::from_utf8(canonical_lease_bytes(&lease).unwrap()).unwrap();
        assert_eq!(
            canonical,
            "{\"action\":{\"max_bytes\":4096,\"relative_path\":\"reports/é.txt\"},\
             \"action_digest\":\"17f24a92579b6c886440421261b2839acd82c9a4ef7e0d0efde265617e6c670f\",\
             \"approval_id\":\"approval_1\",\"device_id\":\"device_1\",\
             \"expires_at\":\"2030-01-02T03:06:05+00:00\",\"id\":\"lease_1\",\
             \"issued_at\":\"2030-01-02T03:04:05+00:00\",\"owner_id\":\"alice\",\
             \"root_id\":\"root_1\",\
             \"signing_key_id\":\"56475aa75463474c0285df5dbf2bcab73da651358839e9b77481b2eab107708c\",\
             \"tenant_id\":\"tenant\",\"verb\":\"device.file.read\",\"version\":1}"
        );
        let verifier = LeaseVerifier {
            algorithm: "Ed25519".to_string(),
            key_id: lease.signing_key_id.clone(),
            public_key: "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg".to_string(),
        };
        let signature =
            Signature::from_slice(&URL_SAFE_NO_PAD.decode(&lease.signature).unwrap()).unwrap();
        validate_verifier(&verifier)
            .unwrap()
            .verify(&canonical_lease_bytes(&lease).unwrap(), &signature)
            .unwrap();
    }
}
