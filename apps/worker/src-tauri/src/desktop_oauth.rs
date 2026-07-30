//! Native OAuth-return foundation.
//!
//! Providers must redirect to a kernel-owned HTTPS callback first. After the
//! kernel has exchanged any provider authorization code, it may return only an
//! opaque state plus opaque result handle to this custom scheme. Provider
//! codes, access tokens, refresh tokens and identity tokens are deliberately
//! not accepted by this boundary.

use std::sync::Mutex;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, Runtime};
use time::{format_description::well_known::Rfc3339, Duration, OffsetDateTime};
use url::Url;

const CALLBACK_SCHEME: &str = "boltrig-worker";
const CALLBACK_HOST: &str = "oauth";
const CALLBACK_PATH: &str = "/callback";
const CALLBACK_URI: &str = "boltrig-worker://oauth/callback";
const MAX_PENDING_LIFETIME: Duration = Duration::minutes(20);

#[derive(Clone, Debug)]
struct PendingReturn {
    integration_id: String,
    state: String,
    expires_at: OffsetDateTime,
}

#[derive(Clone, Debug)]
struct CompletedReturn {
    integration_id: String,
    state: String,
    status: &'static str,
    result: Option<String>,
}

#[derive(Debug)]
struct RuntimeState {
    readiness: &'static str,
    reason: Option<&'static str>,
    pending: Option<PendingReturn>,
    completed: Option<CompletedReturn>,
}

impl Default for RuntimeState {
    fn default() -> Self {
        Self {
            readiness: "unavailable",
            reason: Some("deep_link_not_initialized"),
            pending: None,
            completed: None,
        }
    }
}

#[derive(Default)]
pub struct OAuthReturnRuntime {
    state: Mutex<RuntimeState>,
}

#[derive(Clone, Debug, Serialize)]
pub struct OAuthReturnReadiness {
    state: &'static str,
    callback_uri: &'static str,
    provider_exchange: &'static str,
    reason: Option<&'static str>,
}

#[derive(Clone, Debug, Serialize)]
pub struct OAuthReturnEvent {
    status: &'static str,
    integration_id: String,
    provider_exchange: &'static str,
}

#[derive(Clone, Debug, Serialize)]
pub struct OAuthReturnView {
    status: &'static str,
    integration_id: String,
    state: String,
    result: Option<String>,
    provider_exchange: &'static str,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ParsedReturn {
    state: String,
    status: &'static str,
    result: Option<String>,
}

fn is_opaque(value: &str, minimum: usize, maximum: usize) -> bool {
    (minimum..=maximum).contains(&value.len())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~'))
}

fn valid_integration_id(value: &str) -> bool {
    (1..=100).contains(&value.len())
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'-' | b'_' | b'.')
        })
}

fn parse_callback(url: &Url) -> Result<ParsedReturn, &'static str> {
    if url.scheme() != CALLBACK_SCHEME
        || url.host_str() != Some(CALLBACK_HOST)
        || url.path() != CALLBACK_PATH
        || url.port().is_some()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err("oauth_return_route_invalid");
    }

    let mut state = None;
    let mut result = None;
    let mut error = None;
    for (name, value) in url.query_pairs() {
        match name.as_ref() {
            "state" if state.is_none() => state = Some(value.into_owned()),
            "result" if result.is_none() => result = Some(value.into_owned()),
            "error" if error.is_none() => error = Some(value.into_owned()),
            "code" | "access_token" | "refresh_token" | "id_token" => {
                return Err("provider_secret_in_native_return")
            }
            _ => return Err("oauth_return_query_invalid"),
        }
    }

    let state = state.ok_or("oauth_return_state_missing")?;
    if !is_opaque(&state, 32, 512) {
        return Err("oauth_return_state_invalid");
    }
    match (result, error) {
        (Some(result), None) if is_opaque(&result, 16, 512) => Ok(ParsedReturn {
            state,
            status: "authorization_returned",
            result: Some(result),
        }),
        (None, Some(error)) if error == "access_denied" => Ok(ParsedReturn {
            state,
            status: "denied",
            result: None,
        }),
        (Some(_), None) => Err("oauth_return_result_invalid"),
        (None, Some(_)) => Err("oauth_return_error_invalid"),
        _ => Err("oauth_return_outcome_invalid"),
    }
}

impl OAuthReturnRuntime {
    pub fn readiness(&self) -> OAuthReturnReadiness {
        let Ok(state) = self.state.lock() else {
            return OAuthReturnReadiness {
                state: "unavailable",
                callback_uri: CALLBACK_URI,
                provider_exchange: "unavailable",
                reason: Some("deep_link_state_unavailable"),
            };
        };
        OAuthReturnReadiness {
            state: state.readiness,
            callback_uri: CALLBACK_URI,
            provider_exchange: "unavailable",
            reason: state.reason,
        }
    }

    fn set_registration(&self, ready: bool) {
        if let Ok(mut state) = self.state.lock() {
            state.readiness = if ready { "ready" } else { "unavailable" };
            state.reason = if ready {
                None
            } else {
                Some("deep_link_registration_failed")
            };
            if !ready {
                state.pending = None;
                state.completed = None;
            }
        }
    }

    pub fn arm(
        &self,
        integration_id: &str,
        opaque_state: &str,
        expires_at: &str,
    ) -> Result<(), String> {
        if !valid_integration_id(integration_id) {
            return Err("oauth_integration_invalid".to_string());
        }
        if !is_opaque(opaque_state, 32, 512) {
            return Err("oauth_state_invalid".to_string());
        }
        let expires_at = OffsetDateTime::parse(expires_at, &Rfc3339)
            .map_err(|_| "oauth_expiry_invalid".to_string())?;
        let now = OffsetDateTime::now_utc();
        if expires_at <= now || expires_at > now + MAX_PENDING_LIFETIME {
            return Err("oauth_expiry_invalid".to_string());
        }
        let mut state = self
            .state
            .lock()
            .map_err(|_| "deep_link_state_unavailable".to_string())?;
        if state.readiness != "ready" {
            return Err(state.reason.unwrap_or("deep_link_unavailable").to_string());
        }
        state.pending = Some(PendingReturn {
            integration_id: integration_id.to_string(),
            state: opaque_state.to_string(),
            expires_at,
        });
        state.completed = None;
        Ok(())
    }

    fn correlate(&self, parsed: ParsedReturn, now: OffsetDateTime) -> Option<OAuthReturnEvent> {
        let mut runtime = self.state.lock().ok()?;
        if runtime.readiness != "ready" {
            return None;
        }
        let pending = runtime.pending.as_ref()?;
        if pending.expires_at <= now || pending.state != parsed.state {
            return None;
        }
        let integration_id = pending.integration_id.clone();
        runtime.pending = None;
        runtime.completed = Some(CompletedReturn {
            integration_id: integration_id.clone(),
            state: parsed.state,
            status: parsed.status,
            result: parsed.result,
        });
        Some(OAuthReturnEvent {
            status: parsed.status,
            integration_id,
            provider_exchange: "unavailable",
        })
    }

    pub fn take(
        &self,
        integration_id: &str,
        expected_state: &str,
    ) -> Result<Option<OAuthReturnView>, String> {
        let mut runtime = self
            .state
            .lock()
            .map_err(|_| "deep_link_state_unavailable".to_string())?;
        let Some(completed) = runtime.completed.as_ref() else {
            return Ok(None);
        };
        if completed.integration_id != integration_id || completed.state != expected_state {
            return Err("oauth_return_correlation_mismatch".to_string());
        }
        let completed = runtime.completed.take().expect("checked above");
        Ok(Some(OAuthReturnView {
            status: completed.status,
            integration_id: completed.integration_id,
            state: completed.state,
            result: completed.result,
            provider_exchange: "unavailable",
        }))
    }

    pub fn cancel(&self, integration_id: &str, expected_state: &str) -> Result<(), String> {
        let mut runtime = self
            .state
            .lock()
            .map_err(|_| "deep_link_state_unavailable".to_string())?;
        let matches_pending = runtime.pending.as_ref().is_some_and(|pending| {
            pending.integration_id == integration_id && pending.state == expected_state
        });
        if !matches_pending {
            return Err("oauth_return_correlation_mismatch".to_string());
        }
        runtime.pending = None;
        runtime.completed = None;
        Ok(())
    }
}

fn handle_urls<R: Runtime>(app: &AppHandle<R>, urls: &[Url]) -> Result<(), String> {
    let runtime = app.state::<OAuthReturnRuntime>();
    for url in urls {
        let Ok(parsed) = parse_callback(url) else {
            continue;
        };
        let Some(event) = runtime.correlate(parsed, OffsetDateTime::now_utc()) else {
            continue;
        };
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.show();
            let _ = window.set_focus();
        }
        app.emit("boltrig://oauth-return", event)
            .map_err(|_| "oauth_return_event_failed".to_string())?;
    }
    Ok(())
}

pub fn configure<R: Runtime>(app: &mut tauri::App<R>) {
    use tauri_plugin_deep_link::DeepLinkExt;

    let registration_ready = {
        #[cfg(any(target_os = "linux", all(debug_assertions, windows)))]
        {
            app.deep_link().register_all().is_ok()
        }
        #[cfg(not(any(target_os = "linux", all(debug_assertions, windows))))]
        {
            true
        }
    };
    app.state::<OAuthReturnRuntime>()
        .set_registration(registration_ready);
    if !registration_ready {
        return;
    }

    if let Ok(Some(urls)) = app.deep_link().get_current() {
        let _ = handle_urls(app.handle(), &urls);
    }
    let handle = app.handle().clone();
    app.deep_link().on_open_url(move |event| {
        let _ = handle_urls(&handle, &event.urls());
    });
}

#[cfg(test)]
mod tests {
    use super::{parse_callback, OAuthReturnRuntime, ParsedReturn, CALLBACK_URI};
    use time::{Duration, OffsetDateTime};
    use url::Url;

    fn opaque(value: char, length: usize) -> String {
        std::iter::repeat_n(value, length).collect()
    }

    #[test]
    fn callback_accepts_only_kernel_brokered_state_and_result() {
        let state = opaque('s', 48);
        let result = opaque('r', 48);
        let parsed = parse_callback(
            &Url::parse(&format!("{CALLBACK_URI}?state={state}&result={result}")).unwrap(),
        )
        .unwrap();
        assert_eq!(
            parsed,
            ParsedReturn {
                state,
                status: "authorization_returned",
                result: Some(result),
            }
        );
    }

    #[test]
    fn callback_rejects_provider_secrets_and_ambiguous_shapes() {
        let state = opaque('s', 48);
        for query in [
            format!("state={state}&code=provider-code"),
            format!("state={state}&access_token=provider-token"),
            format!(
                "state={state}&result={}&result={}",
                opaque('r', 32),
                opaque('x', 32)
            ),
            format!("state={state}&error=server_error"),
            format!("state={state}&result={}#fragment", opaque('r', 32)),
        ] {
            assert!(
                parse_callback(&Url::parse(&format!("{CALLBACK_URI}?{query}")).unwrap()).is_err()
            );
        }
        assert!(parse_callback(
            &Url::parse(&format!(
                "boltrig-worker://oauth/other?state={state}&result={}",
                opaque('r', 32)
            ))
            .unwrap()
        )
        .is_err());
    }

    #[test]
    fn correlation_is_exact_ephemeral_and_one_take() {
        let runtime = OAuthReturnRuntime::default();
        runtime.set_registration(true);
        let state = opaque('s', 48);
        let result = opaque('r', 48);
        let expiry = (OffsetDateTime::now_utc() + Duration::minutes(5))
            .format(&time::format_description::well_known::Rfc3339)
            .unwrap();
        runtime.arm("tickets", &state, &expiry).unwrap();
        assert!(runtime
            .correlate(
                ParsedReturn {
                    state: opaque('x', 48),
                    status: "authorization_returned",
                    result: Some(result.clone()),
                },
                OffsetDateTime::now_utc(),
            )
            .is_none());
        assert!(runtime
            .correlate(
                ParsedReturn {
                    state: state.clone(),
                    status: "authorization_returned",
                    result: Some(result.clone()),
                },
                OffsetDateTime::now_utc(),
            )
            .is_some());
        assert!(runtime.take("other", &state).is_err());
        let taken = runtime.take("tickets", &state).unwrap().unwrap();
        assert_eq!(taken.result, Some(result));
        assert!(runtime.take("tickets", &state).unwrap().is_none());
    }
}
