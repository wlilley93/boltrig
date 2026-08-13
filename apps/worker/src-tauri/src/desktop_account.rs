//! Native bootstrap for the human account session used by the packaged UI.
//!
//! WKWebView does not persist third-party `Set-Cookie` headers issued to the
//! `tauri://localhost` page. Login and second-factor completion therefore use
//! one narrow native POST path, pinned to the API origin compiled into the
//! signed app. The session secret is installed directly into WebKit's cookie
//! store and is never returned to JavaScript.

use std::collections::BTreeMap;
use std::time::Duration;

use cookie::{Cookie, SameSite};
use reqwest::header::{
    HeaderMap, HeaderName, HeaderValue, ACCEPT_ENCODING, COOKIE, ORIGIN, SET_COOKIE,
};
use reqwest::{redirect::Policy, Client, Method, Response, Url};
use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Manager, WebviewWindow};

use crate::session::require_api_origin;

const SESSION_COOKIE: &str = "boltrig_session";
const CSRF_COOKIE: &str = "boltrig_csrf";
const MAX_AUTH_RESPONSE_BYTES: usize = 64 * 1024;
const MAX_EMAIL_BYTES: usize = 320;
const MAX_PASSWORD_BYTES: usize = 4096;
const MAX_CHALLENGE_BYTES: usize = 1024;
const MAX_CODE_BYTES: usize = 256;
const MAX_API_PATH_BYTES: usize = 8192;
const MAX_API_REQUEST_BYTES: usize = 25 * 1024 * 1024;
const MAX_API_RESPONSE_BYTES: usize = 32 * 1024 * 1024;
const MAX_API_HEADERS: usize = 16;
const API_HEADER_TIMEOUT: Duration = Duration::from_secs(30);
const API_BODY_TIMEOUT: Duration = Duration::from_secs(65);
const API_ENVELOPE_MAGIC: &[u8; 4] = b"BAPI";

const PUBLIC_ACCOUNT_PATHS: &[&str] = &[
    "/v1/auth/accept-invite",
    "/v1/auth/password-reset/confirm",
    "/v1/auth/password-reset/request",
];

#[derive(Debug, Serialize)]
pub(crate) struct AccountResponse {
    pub(crate) http_status: u16,
    pub(crate) body: Value,
}

#[derive(Debug, Serialize)]
struct DesktopApiHead {
    status: u16,
    status_text: String,
    headers: Vec<(String, String)>,
}

pub(crate) fn configured_api_origin() -> Result<String, String> {
    let value = option_env!("BOLTRIG_DESKTOP_API_ORIGIN").unwrap_or("");
    require_api_origin(value).map_err(|_| "desktop_api_origin_not_configured".to_string())
}

pub(crate) fn require_configured_origin(value: &str) -> Result<String, String> {
    let configured = configured_api_origin()?;
    let supplied = require_api_origin(value)?;
    if supplied != configured {
        return Err("desktop_api_origin_mismatch".to_string());
    }
    Ok(configured)
}

fn desktop_origin(window: &WebviewWindow) -> Result<&'static str, String> {
    let url = window
        .url()
        .map_err(|_| "desktop_webview_origin_unavailable".to_string())?;
    match (url.scheme(), url.host_str()) {
        ("tauri", Some("localhost")) => Ok("tauri://localhost"),
        ("https", Some("tauri.localhost")) => Ok("https://tauri.localhost"),
        _ => Err("desktop_webview_origin_invalid".to_string()),
    }
}

fn account_client() -> Result<Client, String> {
    Client::builder()
        .redirect(Policy::none())
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(20))
        .user_agent("boltrig-worker-account/0.1")
        .build()
        .map_err(|_| "desktop_account_client_unavailable".to_string())
}

fn api_client() -> Result<Client, String> {
    Client::builder()
        .redirect(Policy::none())
        .connect_timeout(Duration::from_secs(5))
        .user_agent("boltrig-worker-api/0.1")
        .build()
        .map_err(|_| "desktop_api_client_unavailable".to_string())
}

fn input(value: &str, maximum: usize, reason: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > maximum
        || value.chars().any(|character| character.is_control())
    {
        return Err(reason.to_string());
    }
    Ok(())
}

async fn bounded_body(mut response: Response) -> Result<Value, String> {
    let mut body = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| "desktop_account_response_unavailable".to_string())?
    {
        if body.len().saturating_add(chunk.len()) > MAX_AUTH_RESPONSE_BYTES {
            return Err("desktop_account_response_too_large".to_string());
        }
        body.extend_from_slice(&chunk);
    }
    let value: Value = serde_json::from_slice(&body)
        .map_err(|_| "desktop_account_response_invalid".to_string())?;
    if !value.is_object() {
        return Err("desktop_account_response_invalid".to_string());
    }
    Ok(value)
}

fn response_cookie(header: &str, domain: &str) -> Result<Cookie<'static>, String> {
    let mut cookie = Cookie::parse(header.to_owned())
        .map_err(|_| "desktop_account_cookie_invalid".to_string())?
        .into_owned();
    if !matches!(cookie.name(), SESSION_COOKIE | CSRF_COOKIE)
        || cookie.secure() != Some(true)
        || cookie.same_site() != Some(SameSite::None)
        || cookie.path() != Some("/")
        || cookie.max_age().is_none()
        || (cookie.name() == SESSION_COOKIE && cookie.http_only() != Some(true))
        || (cookie.name() == CSRF_COOKIE && cookie.http_only() == Some(true))
    {
        return Err("desktop_account_cookie_invalid".to_string());
    }
    cookie.set_domain(domain.to_owned());
    Ok(cookie)
}

fn install_response_cookies(
    window: &WebviewWindow,
    origin: &str,
    headers: &[String],
    body: &Value,
) -> Result<(), String> {
    if headers.is_empty() {
        return Ok(());
    }
    let domain = Url::parse(origin)
        .ok()
        .and_then(|url| url.host_str().map(str::to_owned))
        .ok_or_else(|| "desktop_api_origin_not_configured".to_string())?;
    let mut cookies = BTreeMap::new();
    for header in headers {
        let cookie = response_cookie(header, &domain)?;
        if cookies.insert(cookie.name().to_owned(), cookie).is_some() {
            return Err("desktop_account_cookie_invalid".to_string());
        }
    }
    if cookies.len() != 2
        || !cookies.contains_key(SESSION_COOKIE)
        || !cookies.contains_key(CSRF_COOKIE)
        || body.get("csrf_token").and_then(Value::as_str)
            != cookies.get(CSRF_COOKIE).map(Cookie::value)
    {
        return Err("desktop_account_cookie_invalid".to_string());
    }
    // Install the non-authoritative CSRF value first. If the session-cookie
    // write fails, the browser still has no new account authority.
    let csrf_cookie = cookies
        .remove(CSRF_COOKIE)
        .ok_or_else(|| "desktop_account_cookie_invalid".to_string())?;
    let session_cookie = cookies
        .remove(SESSION_COOKIE)
        .ok_or_else(|| "desktop_account_cookie_invalid".to_string())?;
    window
        .set_cookie(csrf_cookie)
        .map_err(|_| "desktop_account_cookie_write_failed".to_string())?;
    window
        .set_cookie(session_cookie)
        .map_err(|_| "desktop_account_cookie_write_failed".to_string())
}

fn session_headers(window: &WebviewWindow, origin: &str) -> Result<(String, String), String> {
    let url = Url::parse(origin).map_err(|_| "desktop_api_origin_not_configured".to_string())?;
    let mut values = BTreeMap::new();
    for cookie in window
        .cookies_for_url(url)
        .map_err(|_| "desktop_account_cookie_read_failed".to_string())?
    {
        if matches!(cookie.name(), SESSION_COOKIE | CSRF_COOKIE)
            && values
                .insert(cookie.name().to_owned(), cookie.value().to_owned())
                .is_some()
        {
            return Err("desktop_account_cookie_invalid".to_string());
        }
    }
    let session = values
        .remove(SESSION_COOKIE)
        .ok_or_else(|| "desktop_account_session_missing".to_string())?;
    let csrf = values
        .remove(CSRF_COOKIE)
        .ok_or_else(|| "desktop_account_session_missing".to_string())?;
    input(&session, 16_384, "desktop_account_cookie_invalid")?;
    input(&csrf, 16_384, "desktop_account_cookie_invalid")?;
    Ok((
        format!("{SESSION_COOKIE}={session}; {CSRF_COOKIE}={csrf}"),
        csrf,
    ))
}

fn remove_session_cookies(window: &WebviewWindow, origin: &str) -> Result<(), String> {
    let url = Url::parse(origin).map_err(|_| "desktop_api_origin_not_configured".to_string())?;
    for cookie in window
        .cookies_for_url(url)
        .map_err(|_| "desktop_account_cookie_read_failed".to_string())?
    {
        if matches!(cookie.name(), SESSION_COOKIE | CSRF_COOKIE) {
            window
                .delete_cookie(cookie)
                .map_err(|_| "desktop_account_cookie_delete_failed".to_string())?;
        }
    }
    Ok(())
}

fn exact_api_url(origin: &str, path: &str) -> Result<Url, String> {
    if path.len() > MAX_API_PATH_BYTES
        || !(path == "/v1" || path.starts_with("/v1/"))
        || path.contains('#')
    {
        return Err("desktop_api_path_invalid".to_string());
    }
    let expected =
        Url::parse(origin).map_err(|_| "desktop_api_origin_not_configured".to_string())?;
    let url = Url::parse(&format!("{origin}{path}"))
        .map_err(|_| "desktop_api_path_invalid".to_string())?;
    if url.scheme() != expected.scheme()
        || url.host_str() != expected.host_str()
        || url.port_or_known_default() != expected.port_or_known_default()
        || url.username() != ""
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err("desktop_api_path_invalid".to_string());
    }
    Ok(url)
}

fn api_method(value: &str) -> Result<Method, String> {
    let method = Method::from_bytes(value.as_bytes())
        .map_err(|_| "desktop_api_method_invalid".to_string())?;
    if matches!(
        method,
        Method::GET | Method::POST | Method::PUT | Method::PATCH | Method::DELETE
    ) {
        Ok(method)
    } else {
        Err("desktop_api_method_invalid".to_string())
    }
}

fn api_headers(values: Vec<(String, String)>) -> Result<HeaderMap, String> {
    if values.len() > MAX_API_HEADERS {
        return Err("desktop_api_headers_invalid".to_string());
    }
    let mut headers = HeaderMap::new();
    for (name, value) in values {
        let name = name.to_ascii_lowercase();
        if !matches!(
            name.as_str(),
            "accept" | "content-type" | "x-boltrig-approval-id" | "x-boltrig-csrf"
        ) || value.len() > 8192
            || value.chars().any(char::is_control)
        {
            return Err("desktop_api_headers_invalid".to_string());
        }
        let name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|_| "desktop_api_headers_invalid".to_string())?;
        let value =
            HeaderValue::from_str(&value).map_err(|_| "desktop_api_headers_invalid".to_string())?;
        if headers.insert(name, value).is_some() {
            return Err("desktop_api_headers_invalid".to_string());
        }
    }
    Ok(headers)
}

fn safe_response_headers(response: &Response) -> Vec<(String, String)> {
    [
        "content-type",
        "content-length",
        "content-disposition",
        "etag",
    ]
    .into_iter()
    .filter_map(|name| {
        response
            .headers()
            .get(name)
            .and_then(|value| value.to_str().ok())
            .map(|value| (name.to_string(), value.to_string()))
    })
    .collect()
}

async fn bounded_api_body(mut response: Response) -> Result<Vec<u8>, String> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_API_RESPONSE_BYTES as u64)
    {
        return Err("desktop_api_response_too_large".to_string());
    }
    tokio::time::timeout(API_BODY_TIMEOUT, async move {
        let mut body = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| "desktop_api_response_unavailable".to_string())?
        {
            if body.len().saturating_add(chunk.len()) > MAX_API_RESPONSE_BYTES {
                return Err("desktop_api_response_too_large".to_string());
            }
            body.extend_from_slice(&chunk);
        }
        Ok(body)
    })
    .await
    .map_err(|_| "desktop_api_response_timeout".to_string())?
}

fn api_envelope(head: &DesktopApiHead, body: Vec<u8>) -> Result<Vec<u8>, String> {
    let metadata =
        serde_json::to_vec(head).map_err(|_| "desktop_api_response_invalid".to_string())?;
    let metadata_length =
        u32::try_from(metadata.len()).map_err(|_| "desktop_api_response_invalid".to_string())?;
    let mut envelope = Vec::with_capacity(8 + metadata.len() + body.len());
    envelope.extend_from_slice(API_ENVELOPE_MAGIC);
    envelope.extend_from_slice(&metadata_length.to_le_bytes());
    envelope.extend_from_slice(&metadata);
    envelope.extend_from_slice(&body);
    Ok(envelope)
}

pub(crate) async fn api_request(
    app: &AppHandle,
    method: String,
    path: String,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
) -> Result<tauri::ipc::Response, String> {
    if body.len() > MAX_API_REQUEST_BYTES {
        return Err("desktop_api_request_too_large".to_string());
    }
    let origin = configured_api_origin()?;
    let url = exact_api_url(&origin, &path)?;
    let method = api_method(&method)?;
    if method == Method::GET && !body.is_empty() {
        return Err("desktop_api_request_invalid".to_string());
    }
    let mut headers = api_headers(headers)?;
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "desktop_webview_unavailable".to_string())?;
    let webview_origin = desktop_origin(&window)?;
    let is_public = method == Method::POST && PUBLIC_ACCOUNT_PATHS.contains(&url.path());
    if is_public {
        headers.remove("x-boltrig-csrf");
    } else {
        let (cookies, csrf) = session_headers(&window, &origin)?;
        if let Some(supplied) = headers.get("x-boltrig-csrf") {
            if supplied.as_bytes() != csrf.as_bytes() {
                return Err("desktop_api_csrf_mismatch".to_string());
            }
        }
        headers.insert(
            COOKIE,
            HeaderValue::from_str(&cookies)
                .map_err(|_| "desktop_account_cookie_invalid".to_string())?,
        );
        if matches!(
            method,
            Method::POST | Method::PUT | Method::PATCH | Method::DELETE
        ) {
            headers.insert(
                "x-boltrig-csrf",
                HeaderValue::from_str(&csrf)
                    .map_err(|_| "desktop_account_cookie_invalid".to_string())?,
            );
        }
    }
    headers.insert(ORIGIN, HeaderValue::from_static(webview_origin));
    headers.insert(ACCEPT_ENCODING, HeaderValue::from_static("identity"));
    let response = tokio::time::timeout(
        API_HEADER_TIMEOUT,
        api_client()?
            .request(method, url)
            .headers(headers)
            .body(body)
            .send(),
    )
    .await
    .map_err(|_| "desktop_api_request_timeout".to_string())?
    .map_err(|_| "desktop_api_request_unavailable".to_string())?;
    let status = response.status();
    let head = DesktopApiHead {
        status: status.as_u16(),
        status_text: status.canonical_reason().unwrap_or("").to_string(),
        headers: safe_response_headers(&response),
    };
    let body = bounded_api_body(response).await?;
    Ok(tauri::ipc::Response::new(api_envelope(&head, body)?))
}

async fn post(
    app: &AppHandle,
    path: &'static str,
    body: Value,
    authenticated: bool,
    install_cookies: bool,
) -> Result<AccountResponse, String> {
    let origin = configured_api_origin()?;
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "desktop_webview_unavailable".to_string())?;
    let mut request = account_client()?
        .post(format!("{origin}{path}"))
        .header(ORIGIN, desktop_origin(&window)?)
        .header(ACCEPT_ENCODING, "identity")
        .json(&body);
    if authenticated {
        let (cookies, csrf) = session_headers(&window, &origin)?;
        request = request
            .header(COOKIE, cookies)
            .header("x-boltrig-csrf", csrf);
    }
    let response = request
        .send()
        .await
        .map_err(|_| "desktop_account_request_unavailable".to_string())?;
    let status = response.status();
    let set_cookies = response
        .headers()
        .get_all(SET_COOKIE)
        .iter()
        .map(|value| {
            value
                .to_str()
                .map(str::to_owned)
                .map_err(|_| "desktop_account_cookie_invalid".to_string())
        })
        .collect::<Result<Vec<_>, _>>()?;
    let response_body = bounded_body(response).await?;
    if install_cookies && status.is_success() {
        install_response_cookies(&window, &origin, &set_cookies, &response_body)?;
    }
    Ok(AccountResponse {
        http_status: status.as_u16(),
        body: response_body,
    })
}

pub(crate) async fn login(
    app: &AppHandle,
    email: String,
    password: String,
) -> Result<AccountResponse, String> {
    input(email.trim(), MAX_EMAIL_BYTES, "invalid_desktop_login")?;
    input(&password, MAX_PASSWORD_BYTES, "invalid_desktop_login")?;
    post(
        app,
        "/v1/auth/login",
        json!({"email": email.trim(), "password": password}),
        false,
        true,
    )
    .await
}

pub(crate) async fn challenge(
    app: &AppHandle,
    challenge_token: String,
    code: String,
) -> Result<AccountResponse, String> {
    input(
        &challenge_token,
        MAX_CHALLENGE_BYTES,
        "invalid_desktop_challenge",
    )?;
    input(code.trim(), MAX_CODE_BYTES, "invalid_desktop_challenge")?;
    post(
        app,
        "/v1/auth/2fa/challenge",
        json!({"challenge_token": challenge_token, "code": code.trim()}),
        false,
        true,
    )
    .await
}

pub(crate) async fn refresh(app: &AppHandle) -> Result<AccountResponse, String> {
    post(app, "/v1/auth/refresh", json!({}), true, true).await
}

pub(crate) async fn logout(app: &AppHandle) -> Result<AccountResponse, String> {
    let response = post(app, "/v1/auth/logout", json!({}), true, false).await?;
    if response.http_status < 400 {
        let origin = configured_api_origin()?;
        let window = app
            .get_webview_window("main")
            .ok_or_else(|| "desktop_webview_unavailable".to_string())?;
        remove_session_cookies(&window, &origin)?;
    }
    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn server_cookie_is_rebound_only_to_the_compiled_origin_host() {
        let session = response_cookie(
            "boltrig_session=opaque; HttpOnly; Max-Age=3600; Path=/; SameSite=None; Secure",
            "dev.boltrig.io",
        )
        .unwrap();
        assert_eq!(session.domain(), Some("dev.boltrig.io"));
        assert_eq!(session.name(), SESSION_COOKIE);
        assert_eq!(session.http_only(), Some(true));
        assert_eq!(session.same_site(), Some(SameSite::None));

        assert!(response_cookie(
            "other=opaque; HttpOnly; Max-Age=3600; Path=/; SameSite=None; Secure",
            "dev.boltrig.io",
        )
        .is_err());
        assert!(response_cookie(
            "boltrig_session=opaque; HttpOnly; Max-Age=3600; Path=/; SameSite=Strict; Secure",
            "dev.boltrig.io",
        )
        .is_err());
    }

    #[test]
    fn credential_fields_are_bounded_before_network_use() {
        assert!(input("owner@example.test", MAX_EMAIL_BYTES, "bad").is_ok());
        assert!(input("", MAX_EMAIL_BYTES, "bad").is_err());
        assert!(input("line\nbreak", MAX_EMAIL_BYTES, "bad").is_err());
        assert!(input(
            &"x".repeat(MAX_PASSWORD_BYTES + 1),
            MAX_PASSWORD_BYTES,
            "bad"
        )
        .is_err());
    }

    #[test]
    fn desktop_api_is_pinned_to_v1_and_safe_headers() {
        let origin = "https://dev.boltrig.io";
        assert_eq!(
            exact_api_url(origin, "/v1/devices?limit=10")
                .unwrap()
                .as_str(),
            "https://dev.boltrig.io/v1/devices?limit=10"
        );
        assert!(exact_api_url(origin, "/healthz").is_err());
        assert!(exact_api_url(origin, "//attacker.invalid/v1/devices").is_err());
        assert!(exact_api_url(origin, "/v1/devices#fragment").is_err());

        assert!(api_headers(vec![(
            "x-boltrig-approval-id".to_string(),
            "approval-1".to_string(),
        )])
        .is_ok());
        assert!(api_headers(vec![(
            "authorization".to_string(),
            "Bearer exposed".to_string(),
        )])
        .is_err());
        assert!(api_headers(vec![(
            "cookie".to_string(),
            "boltrig_session=exposed".to_string(),
        )])
        .is_err());
    }

    #[test]
    fn desktop_api_envelope_is_versioned_bounded_binary() {
        let head = DesktopApiHead {
            status: 200,
            status_text: "OK".to_string(),
            headers: vec![("content-type".to_string(), "application/json".to_string())],
        };
        let envelope = api_envelope(&head, br#"{"status":"ok"}"#.to_vec()).unwrap();
        assert_eq!(&envelope[..4], API_ENVELOPE_MAGIC);
        let metadata_length = u32::from_le_bytes(envelope[4..8].try_into().unwrap()) as usize;
        let metadata: Value = serde_json::from_slice(&envelope[8..8 + metadata_length]).unwrap();
        assert_eq!(metadata["status"], 200);
        assert_eq!(&envelope[8 + metadata_length..], br#"{"status":"ok"}"#);
    }
}
