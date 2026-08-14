use std::collections::HashSet;
use std::sync::{Mutex, MutexGuard, OnceLock};

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use url::{Host, Url};

pub(crate) const KEYRING_SERVICE: &str = "io.boltrig.worker";
const KEYRING_ACCOUNT: &str = "device-session";
const SESSION_VERSION: u8 = 2;
const MAX_SESSION_BYTES: usize = 24_576;
const MAX_TOKEN_BYTES: usize = 16_384;
const MAX_ROOTS: usize = 64;

#[derive(Default)]
struct AgentCache {
    value: Option<Result<Option<StoredDeviceAgent>, String>>,
}

impl AgentCache {
    fn get_or_load(
        &mut self,
        load: impl FnOnce() -> Result<Option<StoredDeviceAgent>, String>,
    ) -> Result<Option<StoredDeviceAgent>, String> {
        if let Some(value) = &self.value {
            return value.clone();
        }
        let value = load();
        self.value = Some(value.clone());
        value
    }

    fn replace(&mut self, value: Result<Option<StoredDeviceAgent>, String>) {
        self.value = Some(value);
    }
}

static AGENT_CACHE: OnceLock<Mutex<AgentCache>> = OnceLock::new();

fn agent_cache() -> MutexGuard<'static, AgentCache> {
    AGENT_CACHE
        .get_or_init(|| Mutex::new(AgentCache::default()))
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LeaseVerifier {
    pub(crate) algorithm: String,
    pub(crate) key_id: String,
    pub(crate) public_key: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PendingClaim {
    pub(crate) lease_id: String,
    pub(crate) claim_token: String,
    pub(crate) terminal_status: Option<String>,
    pub(crate) receipt: Option<Value>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct StoredDeviceAgent {
    pub(crate) version: u8,
    pub(crate) api_origin: String,
    pub(crate) device_id: String,
    pub(crate) device_private_seed: String,
    pub(crate) session_token: String,
    pub(crate) session_expires_at: String,
    pub(crate) lease_verifier: LeaseVerifier,
    #[serde(default)]
    pub(crate) root_ids: Vec<String>,
    pub(crate) pending_claim: Option<PendingClaim>,
    #[serde(default)]
    pub(crate) pending_camera_claim: Option<PendingClaim>,
}

fn is_loopback(host: Option<Host<&str>>) -> bool {
    match host {
        Some(Host::Domain("localhost")) => true,
        Some(Host::Ipv4(address)) => address.is_loopback(),
        Some(Host::Ipv6(address)) => address.is_loopback(),
        _ => false,
    }
}

pub(crate) fn normalize_api_origin(value: &str) -> Result<String, String> {
    if value.is_empty() {
        return Ok("same-origin".to_string());
    }
    let parsed = Url::parse(value).map_err(|_| "invalid_api_origin".to_string())?;
    if !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
        || !matches!(parsed.path(), "" | "/")
    {
        return Err("invalid_api_origin".to_string());
    }
    if parsed.scheme() != "https" && !(parsed.scheme() == "http" && is_loopback(parsed.host())) {
        return Err("insecure_api_origin".to_string());
    }
    Ok(parsed.origin().ascii_serialization())
}

pub(crate) fn require_api_origin(value: &str) -> Result<String, String> {
    let origin = normalize_api_origin(value)?;
    if origin == "same-origin" {
        return Err("device_agent_api_origin_required".to_string());
    }
    Ok(origin)
}

pub(crate) fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

fn validate_token(token: &str) -> Result<(), String> {
    if token.is_empty()
        || token.len() > MAX_TOKEN_BYTES
        || !token.bytes().all(|byte| byte.is_ascii_graphic())
    {
        return Err("invalid_device_session".to_string());
    }
    Ok(())
}

fn validate_record(record: &StoredDeviceAgent) -> Result<(), String> {
    let unique_roots = record.root_ids.iter().collect::<HashSet<_>>();
    if record.version != SESSION_VERSION
        || !valid_identifier(&record.device_id)
        || record.root_ids.len() > MAX_ROOTS
        || unique_roots.len() != record.root_ids.len()
        || record.root_ids.iter().any(|root| !valid_identifier(root))
    {
        return Err("device_session_reenrollment_required".to_string());
    }
    require_api_origin(&record.api_origin)?;
    validate_token(&record.session_token)?;
    let private_seed = URL_SAFE_NO_PAD
        .decode(&record.device_private_seed)
        .map_err(|_| "device_session_reenrollment_required".to_string())?;
    let verifier_public = URL_SAFE_NO_PAD
        .decode(&record.lease_verifier.public_key)
        .map_err(|_| "device_session_reenrollment_required".to_string())?;
    if private_seed.len() != 32
        || record.session_expires_at.len() > 64
        || record.lease_verifier.algorithm != "Ed25519"
        || record.lease_verifier.key_id.len() != 64
        || verifier_public.len() != 32
        || hex::encode(Sha256::digest(&verifier_public)) != record.lease_verifier.key_id
    {
        return Err("device_session_reenrollment_required".to_string());
    }
    if let Some(claim) = &record.pending_claim {
        validate_pending_claim(claim)?;
    }
    if let Some(claim) = &record.pending_camera_claim {
        validate_pending_claim(claim)?;
    }
    Ok(())
}

fn validate_pending_claim(claim: &PendingClaim) -> Result<(), String> {
    let valid_receipt_state = match (&claim.terminal_status, &claim.receipt) {
        (None, None) => true,
        (Some(_), Some(receipt)) => {
            receipt.is_object()
                && serde_json::to_vec(receipt)
                    .map(|encoded| encoded.len() <= 32_000)
                    .unwrap_or(false)
        }
        _ => false,
    };
    if !valid_identifier(&claim.lease_id)
        || validate_token(&claim.claim_token).is_err()
        || !valid_receipt_state
        || !matches!(
            claim.terminal_status.as_deref(),
            None | Some("completed") | Some("failed")
        )
    {
        return Err("device_session_reenrollment_required".to_string());
    }
    Ok(())
}

pub(crate) fn encode_agent(record: &StoredDeviceAgent) -> Result<String, String> {
    validate_record(record)?;
    let encoded =
        serde_json::to_string(record).map_err(|_| "device_session_encode_failed".to_string())?;
    if encoded.len() > MAX_SESSION_BYTES {
        return Err("device_session_too_large".to_string());
    }
    Ok(encoded)
}

pub(crate) fn decode_agent(value: &str) -> Result<StoredDeviceAgent, String> {
    if value.len() > MAX_SESSION_BYTES {
        return Err("device_session_reenrollment_required".to_string());
    }
    let record: StoredDeviceAgent = serde_json::from_str(value)
        .map_err(|_| "device_session_reenrollment_required".to_string())?;
    validate_record(&record)?;
    Ok(record)
}

fn session_entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT)
        .map_err(|_| "os_keychain_unavailable".to_string())
}

fn load_agent_from_keychain() -> Result<Option<StoredDeviceAgent>, String> {
    match session_entry()?.get_password() {
        Ok(stored) => decode_agent(&stored).map(Some),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(_) => Err("os_keychain_read_failed".to_string()),
    }
}

pub(crate) fn load_agent() -> Result<Option<StoredDeviceAgent>, String> {
    // Startup has several legitimate consumers (account bridge, local-agent
    // projection, and the background device loop). Hold one process-local
    // single-flight lock across the first Keychain read so macOS presents at
    // most one authorization prompt for this credential. Cache failures too:
    // a denied prompt stays denied until restart instead of immediately asking
    // again from the next consumer.
    agent_cache().get_or_load(load_agent_from_keychain)
}

pub(crate) fn save_agent(record: &StoredDeviceAgent) -> Result<(), String> {
    let stored = encode_agent(record)?;
    session_entry()?
        .set_password(&stored)
        .map_err(|_| "os_keychain_write_failed".to_string())?;
    agent_cache().replace(Ok(Some(record.clone())));
    Ok(())
}

pub(crate) fn remove_agent() -> Result<(), String> {
    match session_entry()?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => {
            agent_cache().replace(Ok(None));
            Ok(())
        }
        Err(_) => Err("os_keychain_delete_failed".to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record() -> StoredDeviceAgent {
        let verifier_public = [3_u8; 32];
        StoredDeviceAgent {
            version: SESSION_VERSION,
            api_origin: "https://kernel.boltrig.io".to_string(),
            device_id: "device_1".to_string(),
            device_private_seed: URL_SAFE_NO_PAD.encode([2_u8; 32]),
            session_token: "opaque.device-session".to_string(),
            session_expires_at: "2026-07-30T12:00:00+00:00".to_string(),
            lease_verifier: LeaseVerifier {
                algorithm: "Ed25519".to_string(),
                key_id: hex::encode(Sha256::digest(verifier_public)),
                public_key: URL_SAFE_NO_PAD.encode(verifier_public),
            },
            root_ids: vec!["root_1".to_string()],
            pending_claim: None,
            pending_camera_claim: None,
        }
    }

    #[test]
    fn startup_consumers_share_one_session_read_and_mutations_refresh_it() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        use std::sync::Arc;

        let cache = Arc::new(Mutex::new(AgentCache::default()));
        let reads = Arc::new(AtomicUsize::new(0));
        let threads = (0..8)
            .map(|_| {
                let cache = Arc::clone(&cache);
                let reads = Arc::clone(&reads);
                std::thread::spawn(move || {
                    cache
                        .lock()
                        .unwrap()
                        .get_or_load(|| {
                            reads.fetch_add(1, Ordering::SeqCst);
                            Ok(Some(record()))
                        })
                        .unwrap()
                        .unwrap()
                        .device_id
                })
            })
            .collect::<Vec<_>>();
        for thread in threads {
            assert_eq!(thread.join().unwrap(), "device_1");
        }
        assert_eq!(reads.load(Ordering::SeqCst), 1);

        cache.lock().unwrap().replace(Ok(None));
        assert!(cache
            .lock()
            .unwrap()
            .get_or_load(|| panic!("a cached mutation must not reread Keychain"))
            .unwrap()
            .is_none());
    }

    #[test]
    fn agent_record_round_trips_with_origin_verifier_and_no_legacy_shape() {
        let encoded = encode_agent(&record()).unwrap();
        let decoded = decode_agent(&encoded).unwrap();
        assert_eq!(decoded.api_origin, "https://kernel.boltrig.io");
        assert_eq!(decoded.lease_verifier.algorithm, "Ed25519");
        assert_eq!(
            decode_agent("legacy-token").unwrap_err(),
            "device_session_reenrollment_required"
        );
    }

    #[test]
    fn origin_rejects_credentials_paths_and_non_loopback_http() {
        for invalid in [
            "http://boltrig.io",
            "https://user:password@boltrig.io",
            "https://boltrig.io/v1",
            "https://boltrig.io/?tenant=x",
            "file:///tmp/socket",
        ] {
            assert!(normalize_api_origin(invalid).is_err(), "{invalid}");
        }
        assert_eq!(
            require_api_origin("http://127.0.0.1:8000").unwrap(),
            "http://127.0.0.1:8000"
        );
        assert_eq!(
            require_api_origin("http://[::1]:8000").unwrap(),
            "http://[::1]:8000"
        );
        assert!(require_api_origin("").is_err());
    }

    #[test]
    fn malformed_or_overwide_records_fail_closed() {
        let mut value = record();
        value.root_ids = (0..=MAX_ROOTS)
            .map(|index| format!("root_{index}"))
            .collect();
        assert!(encode_agent(&value).is_err());
        let mut value = record();
        value.session_token = "contains space".to_string();
        assert!(encode_agent(&value).is_err());
        let mut value = record();
        value.lease_verifier.algorithm = "RSA".to_string();
        assert!(encode_agent(&value).is_err());
        let mut value = record();
        value.root_ids.push("root_1".to_string());
        assert!(encode_agent(&value).is_err());
        let mut value = record();
        value.pending_claim = Some(PendingClaim {
            lease_id: "lease_1".to_string(),
            claim_token: "opaque".to_string(),
            terminal_status: Some("completed".to_string()),
            receipt: None,
        });
        assert!(encode_agent(&value).is_err());
    }
}
