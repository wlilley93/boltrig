//! Camera-specific signed lease verification.
//!
//! Camera leases are not `DeviceLease`s: they have no root, no path, no argv,
//! and no command executor.  Verification ends at a semantic PTZ action.  A
//! platform backend must still prove the bound descriptor and local capability
//! before it can perform a write.

use std::collections::BTreeMap;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use ed25519_dalek::{Signature, Verifier};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;

use crate::session::{valid_identifier, LeaseVerifier};

const MAX_ANGLE_MILLIDEGREES: i64 = 360_000_000;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CameraLease {
    pub(crate) version: u8,
    pub(crate) id: String,
    pub(crate) tenant_id: String,
    pub(crate) device_id: String,
    pub(crate) camera_id: String,
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

#[derive(Debug, PartialEq)]
pub(crate) enum ValidatedCameraAction {
    PtzGet {
        descriptor_fingerprint: String,
    },
    PtzSet {
        descriptor_fingerprint: String,
        pan_millidegrees: i64,
        tilt_millidegrees: i64,
    },
}

pub(crate) fn verify_lease(
    lease: &CameraLease,
    expected_device_id: &str,
    verifier: &LeaseVerifier,
) -> Result<ValidatedCameraAction, String> {
    if lease.version != 1
        || lease.status != "issued"
        || lease.device_id != expected_device_id
        || lease.signing_key_id != verifier.key_id
        || !valid_identifier(&lease.id)
        || !valid_identifier(&lease.device_id)
        || !valid_camera_id(&lease.camera_id)
        || !valid_identifier(&lease.approval_id)
        || lease.tenant_id.is_empty()
        || lease.tenant_id.len() > 256
        || lease.owner_id.is_empty()
        || lease.owner_id.len() > 256
    {
        return Err("invalid_camera_lease_envelope".to_string());
    }
    let action = validate_action(&lease.verb, &lease.action)?;
    let expected_digest = action_digest(lease)?;
    if !constant_time_eq(expected_digest.as_bytes(), lease.action_digest.as_bytes()) {
        return Err("camera_lease_action_digest_mismatch".to_string());
    }
    let issued_at = parse_time(&lease.issued_at)?;
    let expires_at = parse_time(&lease.expires_at)?;
    let now = OffsetDateTime::now_utc();
    if expires_at <= now
        || expires_at <= issued_at
        || expires_at - issued_at > time::Duration::minutes(3)
        || issued_at > now + time::Duration::seconds(30)
    {
        return Err("camera_lease_expired_or_invalid".to_string());
    }
    let signature_bytes = URL_SAFE_NO_PAD
        .decode(&lease.signature)
        .map_err(|_| "invalid_camera_lease_signature".to_string())?;
    let signature = Signature::from_slice(&signature_bytes)
        .map_err(|_| "invalid_camera_lease_signature".to_string())?;
    crate::device_protocol::validate_verifier(verifier)?
        .verify(&canonical_lease_bytes(lease)?, &signature)
        .map_err(|_| "invalid_camera_lease_signature".to_string())?;
    Ok(action)
}

fn validate_action(verb: &str, action: &Value) -> Result<ValidatedCameraAction, String> {
    let object = action
        .as_object()
        .ok_or_else(|| "invalid_camera_action".to_string())?;
    match verb {
        "camera.ptz.get" => {
            exact_keys(object, &["descriptor_fingerprint"])?;
            Ok(ValidatedCameraAction::PtzGet {
                descriptor_fingerprint: fingerprint(object.get("descriptor_fingerprint"))?,
            })
        }
        "camera.ptz.set" => {
            exact_keys(
                object,
                &[
                    "descriptor_fingerprint",
                    "pan_millidegrees",
                    "tilt_millidegrees",
                ],
            )?;
            let pan = signed_integer(object.get("pan_millidegrees"))?;
            let tilt = signed_integer(object.get("tilt_millidegrees"))?;
            if !(-MAX_ANGLE_MILLIDEGREES..=MAX_ANGLE_MILLIDEGREES).contains(&pan)
                || !(-MAX_ANGLE_MILLIDEGREES..=MAX_ANGLE_MILLIDEGREES).contains(&tilt)
            {
                return Err("invalid_camera_action".to_string());
            }
            Ok(ValidatedCameraAction::PtzSet {
                descriptor_fingerprint: fingerprint(object.get("descriptor_fingerprint"))?,
                pan_millidegrees: pan,
                tilt_millidegrees: tilt,
            })
        }
        _ => Err("unsupported_camera_verb".to_string()),
    }
}

fn exact_keys(object: &Map<String, Value>, expected: &[&str]) -> Result<(), String> {
    let actual = object.keys().map(String::as_str).collect::<Vec<_>>();
    if actual.len() != expected.len() || expected.iter().any(|key| !actual.contains(key)) {
        return Err("invalid_camera_action".to_string());
    }
    Ok(())
}

fn fingerprint(value: Option<&Value>) -> Result<String, String> {
    let value = value
        .and_then(Value::as_str)
        .ok_or_else(|| "invalid_camera_action".to_string())?;
    if value.len() != 64 || !is_lower_hex(value) {
        return Err("invalid_camera_action".to_string());
    }
    Ok(value.to_string())
}

fn signed_integer(value: Option<&Value>) -> Result<i64, String> {
    value
        .and_then(Value::as_i64)
        .ok_or_else(|| "invalid_camera_action".to_string())
}

fn valid_camera_id(value: &str) -> bool {
    value.len() == 39
        && value.starts_with("camera_")
        && value[7..].bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn action_digest(lease: &CameraLease) -> Result<String, String> {
    let action = lease
        .action
        .as_object()
        .ok_or_else(|| "invalid_camera_action".to_string())?;
    let mut params = Map::new();
    params.insert("camera_id".to_string(), json!(lease.camera_id));
    params.insert("device_id".to_string(), json!(lease.device_id));
    for (key, value) in action {
        params.insert(key.clone(), value.clone());
    }
    let payload = json!({
        "version": 1,
        "noun": "camera",
        "verb": lease.verb,
        "params": params,
    });
    Ok(hex::encode(Sha256::digest(canonical_json(&payload)?)))
}

fn canonical_lease_bytes(lease: &CameraLease) -> Result<Vec<u8>, String> {
    canonical_json(&json!({
        "version": lease.version,
        "id": lease.id,
        "tenant_id": lease.tenant_id,
        "device_id": lease.device_id,
        "camera_id": lease.camera_id,
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
    OffsetDateTime::parse(value, &Rfc3339).map_err(|_| "invalid_camera_lease_time".to_string())
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

    #[test]
    fn camera_actions_have_no_root_or_command_fields() {
        assert!(validate_action(
            "camera.ptz.set",
            &json!({
                "descriptor_fingerprint": "a".repeat(64),
                "pan_millidegrees": 1,
                "tilt_millidegrees": -1,
            })
        )
        .is_ok());
        assert!(validate_action(
            "camera.ptz.set",
            &json!({
                "descriptor_fingerprint": "a".repeat(64),
                "pan_millidegrees": 1,
                "tilt_millidegrees": -1,
                "root_id": "root_1",
            })
        )
        .is_err());
    }

    #[test]
    fn rust_matches_python_camera_action_digest_fixture() {
        let lease = CameraLease {
            version: 1,
            id: "lease_1".to_string(),
            tenant_id: "tenant".to_string(),
            device_id: "device_1".to_string(),
            camera_id: "camera_".to_string() + &"a".repeat(32),
            owner_id: "alice".to_string(),
            verb: "camera.ptz.set".to_string(),
            action: json!({
                "descriptor_fingerprint": "b".repeat(64),
                "pan_millidegrees": 36000,
                "tilt_millidegrees": 0,
            }),
            action_digest: String::new(),
            approval_id: "approval_1".to_string(),
            issued_at: "2030-01-02T03:04:05+00:00".to_string(),
            expires_at: "2030-01-02T03:06:05+00:00".to_string(),
            signing_key_id: "c".repeat(64),
            signature: String::new(),
            status: "issued".to_string(),
        };
        assert_eq!(
            action_digest(&lease).unwrap(),
            "9aaeb146f7b4c30da06150636f4a092e3b6b7dfbb10a0537b1e72d48ff8ae83b"
        );
    }
}
