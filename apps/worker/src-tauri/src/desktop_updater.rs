//! Signed desktop update boundary.
//!
//! Release trust is compiled into the desktop binary. The webview can ask the
//! native shell to use that exact configuration, but it cannot provide an
//! endpoint, public key, package URL, signature, or installer bytes.

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
};

use serde::Serialize;
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Runtime};
use tauri_plugin_updater::{Update, UpdaterExt};
use url::Url;

const COMPILED_ENDPOINT: Option<&str> = option_env!("BOLTRIG_UPDATER_ENDPOINT");
const COMPILED_PUBLIC_KEY: Option<&str> = option_env!("BOLTRIG_UPDATER_PUBLIC_KEY");

#[derive(Default)]
pub struct UpdateRuntime {
    pending: Mutex<Option<Update>>,
    installed: AtomicBool,
}

#[derive(Clone, Debug)]
struct UpdaterTrust {
    endpoint: Url,
    public_key: String,
    endpoint_origin: String,
    public_key_fingerprint: String,
    target: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct UpdateReadiness {
    state: &'static str,
    current_version: &'static str,
    target: Option<String>,
    endpoint_origin: Option<String>,
    public_key_fingerprint: Option<String>,
    reason: Option<&'static str>,
}

#[derive(Clone, Debug, Serialize)]
pub struct UpdateCheck {
    status: &'static str,
    current_version: String,
    version: Option<String>,
    notes: Option<String>,
    published_at: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum UpdateProgress {
    Started { content_length: Option<u64> },
    Progress { chunk_length: usize },
    DownloadFinished,
}

fn bounded_notes(value: Option<String>) -> Option<String> {
    value.map(|notes| notes.chars().take(4_000).collect())
}

fn trust_from_values(
    endpoint: Option<&str>,
    public_key: Option<&str>,
    target: Option<String>,
) -> Result<UpdaterTrust, &'static str> {
    let endpoint = endpoint
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or("updater_endpoint_not_configured")?;
    let public_key = public_key
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or("updater_public_key_not_configured")?;
    let endpoint = Url::parse(endpoint).map_err(|_| "updater_endpoint_invalid")?;
    if endpoint.scheme() != "https"
        || endpoint.host_str().is_none()
        || !endpoint.username().is_empty()
        || endpoint.password().is_some()
        || endpoint.fragment().is_some()
    {
        return Err("updater_endpoint_not_https");
    }
    let target = target.ok_or("updater_target_unsupported")?;
    let endpoint_origin = endpoint.origin().ascii_serialization();
    let public_key_fingerprint = hex::encode(Sha256::digest(public_key.as_bytes()));
    Ok(UpdaterTrust {
        endpoint,
        public_key: public_key.to_string(),
        endpoint_origin,
        public_key_fingerprint,
        target,
    })
}

fn compiled_trust() -> Result<UpdaterTrust, &'static str> {
    trust_from_values(
        COMPILED_ENDPOINT,
        COMPILED_PUBLIC_KEY,
        tauri_plugin_updater::target(),
    )
}

pub fn readiness() -> UpdateReadiness {
    match compiled_trust() {
        Ok(trust) => UpdateReadiness {
            state: "ready",
            current_version: env!("CARGO_PKG_VERSION"),
            target: Some(trust.target),
            endpoint_origin: Some(trust.endpoint_origin),
            public_key_fingerprint: Some(trust.public_key_fingerprint),
            reason: None,
        },
        Err(reason) => UpdateReadiness {
            state: "unavailable",
            current_version: env!("CARGO_PKG_VERSION"),
            target: tauri_plugin_updater::target(),
            endpoint_origin: None,
            public_key_fingerprint: None,
            reason: Some(reason),
        },
    }
}

async fn available_update<R: Runtime>(app: &AppHandle<R>) -> Result<Option<Update>, String> {
    let trust = compiled_trust().map_err(str::to_string)?;
    app.updater_builder()
        .endpoints(vec![trust.endpoint])
        .map_err(|_| "updater_configuration_invalid".to_string())?
        .pubkey(trust.public_key)
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .map_err(|_| "updater_configuration_invalid".to_string())?
        .check()
        .await
        .map_err(|_| "update_check_failed".to_string())
}

pub async fn check<R: Runtime>(
    app: &AppHandle<R>,
    runtime: &UpdateRuntime,
) -> Result<UpdateCheck, String> {
    match available_update(app).await? {
        Some(update) => {
            let result = UpdateCheck {
                status: "available",
                current_version: update.current_version.clone(),
                version: Some(update.version.clone()),
                notes: bounded_notes(update.body.clone()),
                published_at: update.date.map(|value| value.to_string()),
            };
            *runtime
                .pending
                .lock()
                .map_err(|_| "update_state_unavailable".to_string())? = Some(update);
            runtime.installed.store(false, Ordering::SeqCst);
            Ok(result)
        }
        None => {
            *runtime
                .pending
                .lock()
                .map_err(|_| "update_state_unavailable".to_string())? = None;
            runtime.installed.store(false, Ordering::SeqCst);
            Ok(UpdateCheck {
                status: "current",
                current_version: env!("CARGO_PKG_VERSION").to_string(),
                version: None,
                notes: None,
                published_at: None,
            })
        }
    }
}

pub async fn install(
    runtime: &UpdateRuntime,
    expected_version: &str,
    on_event: tauri::ipc::Channel<UpdateProgress>,
) -> Result<(), String> {
    let expected_version = expected_version.trim();
    if expected_version.is_empty() || expected_version.len() > 128 {
        return Err("update_version_invalid".to_string());
    }
    let update = runtime
        .pending
        .lock()
        .map_err(|_| "update_state_unavailable".to_string())?
        .take()
        .ok_or_else(|| "update_check_required".to_string())?;
    if update.version != expected_version {
        return Err("update_version_changed".to_string());
    }
    let started = Mutex::new(false);
    let progress = on_event.clone();
    update
        .download_and_install(
            move |chunk_length, content_length| {
                if let Ok(mut emitted) = started.lock() {
                    if !*emitted {
                        let _ = progress.send(UpdateProgress::Started { content_length });
                        *emitted = true;
                    }
                }
                let _ = progress.send(UpdateProgress::Progress { chunk_length });
            },
            move || {
                let _ = on_event.send(UpdateProgress::DownloadFinished);
            },
        )
        .await
        .map_err(|_| "update_install_failed".to_string())?;
    runtime.installed.store(true, Ordering::SeqCst);
    Ok(())
}

pub fn take_restart_ready(runtime: &UpdateRuntime) -> Result<(), String> {
    if !runtime.installed.swap(false, Ordering::SeqCst) {
        return Err("update_restart_not_ready".to_string());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{trust_from_values, UpdateProgress};

    #[test]
    fn release_trust_requires_a_fixed_https_endpoint_and_public_key() {
        assert_eq!(
            trust_from_values(None, Some("key"), Some("linux".to_string())).unwrap_err(),
            "updater_endpoint_not_configured"
        );
        assert_eq!(
            trust_from_values(
                Some("http://releases.example.test/latest.json"),
                Some("key"),
                Some("linux".to_string()),
            )
            .unwrap_err(),
            "updater_endpoint_not_https"
        );
        assert_eq!(
            trust_from_values(
                Some("https://releases.example.test/latest.json"),
                None,
                Some("linux".to_string()),
            )
            .unwrap_err(),
            "updater_public_key_not_configured"
        );
    }

    #[test]
    fn release_trust_projects_only_safe_readiness_evidence() {
        let trust = trust_from_values(
            Some("https://releases.example.test/{{target}}/{{arch}}/{{current_version}}"),
            Some("trusted public key material"),
            Some("linux".to_string()),
        )
        .unwrap();
        assert_eq!(trust.endpoint.scheme(), "https");
        assert_eq!(trust.endpoint_origin, "https://releases.example.test");
        assert_eq!(trust.public_key_fingerprint.len(), 64);
        assert_ne!(trust.public_key_fingerprint, trust.public_key);
    }

    #[test]
    fn download_completion_event_does_not_claim_signature_verification() {
        assert_eq!(
            serde_json::to_value(UpdateProgress::DownloadFinished).unwrap(),
            serde_json::json!({"event": "download_finished"})
        );
    }
}
