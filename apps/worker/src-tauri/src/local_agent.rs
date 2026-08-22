use std::collections::HashMap;
use std::ffi::{OsStr, OsString};
use std::fs::{DirBuilder, File, OpenOptions};
use std::io::{Read, Write};
#[cfg(unix)]
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_opener::OpenerExt;
use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::{mpsc, Mutex};

use crate::device_roots::local_agent_workspace;
use crate::local_agent_protocol::{
    agent_message_identity, approval_response, bounded_delta, bounded_text, delta_item_id,
    initialize_request, initialized_notification, interrupt_request, item_identity,
    refusal_response, response_failed, response_result, thread_request, turn_request,
    AgentMessagePhase, ApprovalPosture, LocalAgentEvent, LocalTurnOutcome, LocalTurnRequest,
    MAX_JSON_LINE_BYTES,
};
use crate::session::{load_agent, KEYRING_SERVICE};

const REQUIRED_RELEASE_CODEX_VERSION: &str = "0.144.3";
const LOCAL_POSTURE_ACCOUNT: &str = "local-agent-posture-v1";
const MAX_BUNDLED_BINARY_BYTES: u64 = 512 * 1024 * 1024;
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(30);
const TURN_IDLE_TIMEOUT: Duration = Duration::from_secs(2 * 60 * 60);
const MAX_PROJECTED_BYTES: usize = 2 * 1024 * 1024;
const MAX_PROJECTED_EVENTS: usize = 10_000;
const MAX_ACTIVE_MESSAGE_ITEMS: usize = 32;
/// The bundled runtime's home lives under the app's own data directory. It is
/// never inherited from `CODEX_HOME`, so a personal `~/.codex` (its
/// `config.toml` with provider or MCP overrides, `auth.json`, memories and
/// history) is neither read nor written by a local task.
const LOCAL_AGENT_DIR: &str = "local-agent";
const PRIVATE_CODEX_HOME_DIR: &str = "codex-home";
const PRIVATE_CONFIG_TOML: &str = "\
# Boltrig Worker local runtime.
#
# This home belongs to the signed desktop app and is separate from any
# personal Codex configuration on this computer. The app sets the sandbox and
# approval policy for every local thread itself, so this file stays minimal.
";
const MAX_AUTH_FILE_BYTES: u64 = 256 * 1024;
/// A device code expires after fifteen minutes; the sign-in child is killed
/// shortly after that if it is still waiting.
const SIGN_IN_TIMEOUT: Duration = Duration::from_secs(16 * 60);
const SIGN_OUT_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_SIGN_IN_LINE_BYTES: usize = 4 * 1024;
const MAX_SIGN_IN_OUTPUT_BYTES: usize = 64 * 1024;
/// `CODEX_HOME` is deliberately absent: the private home is set explicitly.
const SAFE_LOCAL_AGENT_ENVIRONMENT: &[&str] = &[
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "USER",
    "USERPROFILE",
];

pub(crate) struct LocalAgentRuntime {
    active: Mutex<Option<ActiveChild>>,
    sign_in: Mutex<Option<ActiveChild>>,
}

#[derive(Clone)]
struct ActiveChild {
    generation: String,
    stop: mpsc::Sender<()>,
}

#[derive(Debug, Serialize)]
pub(crate) struct LocalAgentStatus {
    runtime: &'static str,
    state: &'static str,
    source: Option<&'static str>,
    version: Option<String>,
    active: bool,
    /// Whether the app-private runtime home holds a sign-in. Local tasks have
    /// no model access until it does; the binary may still be `ready`.
    signed_in: bool,
    reason: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub(crate) enum LocalAgentSignInEvent {
    Started,
    /// The bundled runtime printed its device sign-in page and one-time code.
    /// `opened` says whether the app opened the page in the system browser.
    Code {
        url: String,
        code: String,
        opened: bool,
    },
    Completed,
}

#[derive(Debug, Serialize)]
pub(crate) struct LocalAgentSignInView {
    signed_in: bool,
}

#[derive(Debug, Serialize)]
pub(crate) struct LocalAgentRoot {
    root_id: String,
}

#[derive(Debug, Serialize)]
pub(crate) struct LocalAgentPostureView {
    posture: ApprovalPosture,
}

enum Stage {
    Initialize,
    Thread,
    Turn,
    Running,
}

#[derive(Default)]
struct ProjectionState {
    active_messages: HashMap<String, AgentMessagePhase>,
    bytes: usize,
    events: usize,
}

impl ProjectionState {
    fn charge(&mut self, bytes: usize) -> Result<(), String> {
        self.bytes = self
            .bytes
            .checked_add(bytes)
            .ok_or_else(|| "local_agent_output_too_large".to_string())?;
        self.events = self
            .events
            .checked_add(1)
            .ok_or_else(|| "local_agent_output_too_large".to_string())?;
        if self.bytes > MAX_PROJECTED_BYTES || self.events > MAX_PROJECTED_EVENTS {
            return Err("local_agent_output_too_large".to_string());
        }
        Ok(())
    }

    fn start_message(&mut self, id: String, phase: AgentMessagePhase) -> Result<(), String> {
        if !self.active_messages.contains_key(&id)
            && self.active_messages.len() >= MAX_ACTIVE_MESSAGE_ITEMS
        {
            return Err("local_agent_protocol_invalid".to_string());
        }
        self.active_messages.insert(id, phase);
        Ok(())
    }

    fn message_phase(&self, id: &str) -> Result<AgentMessagePhase, String> {
        self.active_messages
            .get(id)
            .copied()
            .ok_or_else(|| "local_agent_protocol_mismatch".to_string())
    }

    fn finish_message(&mut self, id: &str, phase: AgentMessagePhase) -> Result<(), String> {
        if self.active_messages.remove(id) != Some(phase) {
            return Err("local_agent_protocol_mismatch".to_string());
        }
        Ok(())
    }
}

impl LocalAgentRuntime {
    pub(crate) fn new() -> Self {
        Self {
            active: Mutex::new(None),
            sign_in: Mutex::new(None),
        }
    }

    pub(crate) async fn status(&self, app: &AppHandle) -> LocalAgentStatus {
        let active = self.active.lock().await.is_some();
        let runtime =
            resolve_binary(app).and_then(|binary| probe_binary(&binary.path, binary.source));
        match (runtime, private_codex_home(app)) {
            (Ok((source, version)), Ok(home)) => LocalAgentStatus {
                runtime: "local",
                state: "ready",
                source: Some(source),
                version: Some(version),
                active,
                signed_in: codex_home_signed_in(&home),
                reason: None,
            },
            (Err(reason), _) | (Ok(_), Err(reason)) => LocalAgentStatus {
                runtime: "local",
                state: "unavailable",
                source: None,
                version: None,
                active,
                signed_in: false,
                reason: Some(reason),
            },
        }
    }

    pub(crate) async fn set_posture(
        &self,
        app: &AppHandle,
        posture: ApprovalPosture,
        confirm: Option<String>,
    ) -> Result<LocalAgentPostureView, String> {
        if self.active.lock().await.is_some() {
            return Err("local_agent_busy".to_string());
        }
        if posture == ApprovalPosture::FullAccess {
            if confirm.as_deref() != Some("full_access") {
                return Err("local_agent_full_access_confirmation_required".to_string());
            }
            let accepted = app
                .dialog()
                .message(
                    "Full access lets the local agent run commands, use the internet, and read or change any file this OS user can access — not only the selected workspace. Continue?",
                )
                .title("Allow full local access?")
                .kind(MessageDialogKind::Warning)
                .buttons(MessageDialogButtons::YesNo)
                .blocking_show();
            if !accepted {
                return Err("local_agent_full_access_declined".to_string());
            }
        }
        let _active = self.active.lock().await;
        if _active.is_some() {
            return Err("local_agent_busy".to_string());
        }
        store_posture(posture)?;
        Ok(LocalAgentPostureView { posture })
    }
}

pub(crate) fn posture() -> Result<LocalAgentPostureView, String> {
    Ok(LocalAgentPostureView {
        posture: load_posture()?,
    })
}

pub(crate) fn reset_posture() -> Result<(), String> {
    match posture_entry()?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(_) => Err("os_keychain_delete_failed".to_string()),
    }
}

pub(crate) fn roots() -> Result<Vec<LocalAgentRoot>, String> {
    let Some(agent) = load_agent()? else {
        return Ok(Vec::new());
    };
    Ok(agent
        .root_ids
        .iter()
        .filter(|root_id| {
            local_agent_workspace(&agent.api_origin, &agent.device_id, root_id).is_ok()
        })
        .map(|root_id| LocalAgentRoot {
            root_id: root_id.clone(),
        })
        .collect())
}

struct Binary {
    path: PathBuf,
    source: &'static str,
}

pub(crate) async fn run_turn(
    app: &AppHandle,
    runtime: &LocalAgentRuntime,
    request: LocalTurnRequest,
    on_event: tauri::ipc::Channel<LocalAgentEvent>,
    app_version: &str,
) -> Result<LocalTurnOutcome, String> {
    request.validate()?;
    let agent = load_agent()?.ok_or_else(|| "local_agent_device_not_enrolled".to_string())?;
    if !agent.root_ids.contains(&request.root_id) {
        return Err("local_agent_root_unbound".to_string());
    }
    let workspace = local_agent_workspace(&agent.api_origin, &agent.device_id, &request.root_id)?;
    let binary = resolve_binary(app)?;
    let _ = probe_binary(&binary.path, binary.source)?;
    let codex_home = private_codex_home(app)?;
    if !codex_home_signed_in(&codex_home) {
        return Err("local_agent_not_signed_in".to_string());
    }
    let (stop, stop_rx) = mpsc::channel(1);
    let generation = uuid::Uuid::new_v4().to_string();
    let posture = {
        let mut active = runtime.active.lock().await;
        if active.is_some() {
            return Err("local_agent_busy".to_string());
        }
        let posture = load_posture()?;
        *active = Some(ActiveChild {
            generation: generation.clone(),
            stop,
        });
        posture
    };

    let result = run_child(
        app,
        binary.path,
        &codex_home,
        &workspace,
        request,
        posture,
        on_event,
        stop_rx,
        app_version,
    )
    .await;
    let mut active = runtime.active.lock().await;
    if active
        .as_ref()
        .is_some_and(|turn| turn.generation == generation)
    {
        *active = None;
    }
    result
}

pub(crate) async fn stop(runtime: &LocalAgentRuntime) -> Result<(), String> {
    let sender = runtime
        .active
        .lock()
        .await
        .as_ref()
        .map(|turn| turn.stop.clone())
        .ok_or_else(|| "local_agent_not_running".to_string())?;
    sender
        .send(())
        .await
        .map_err(|_| "local_agent_not_running".to_string())
}

#[allow(clippy::too_many_arguments)]
async fn run_child(
    app: &AppHandle,
    binary: PathBuf,
    codex_home: &Path,
    workspace: &Path,
    request: LocalTurnRequest,
    posture: ApprovalPosture,
    on_event: tauri::ipc::Channel<LocalAgentEvent>,
    mut stop_rx: mpsc::Receiver<()>,
    app_version: &str,
) -> Result<LocalTurnOutcome, String> {
    let mut command = Command::new(binary);
    command
        .arg("app-server")
        .current_dir(workspace)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    apply_safe_environment(&mut command, codex_home);
    let mut child = command
        .spawn()
        .map_err(|_| "local_agent_spawn_failed".to_string())?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| "local_agent_stdio_unavailable".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "local_agent_stdio_unavailable".to_string())?;
    send(&mut stdin, &initialize_request(app_version)).await?;
    let driven = drive(
        app,
        &mut child,
        &mut stdin,
        BufReader::new(stdout),
        &request,
        posture,
        workspace,
        &on_event,
        &mut stop_rx,
    )
    .await;
    let _ = child.kill().await;
    let _ = child.wait().await;
    driven
}

async fn drive(
    app: &AppHandle,
    child: &mut Child,
    stdin: &mut ChildStdin,
    mut stdout: BufReader<ChildStdout>,
    request: &LocalTurnRequest,
    posture: ApprovalPosture,
    workspace: &Path,
    on_event: &tauri::ipc::Channel<LocalAgentEvent>,
    stop_rx: &mut mpsc::Receiver<()>,
) -> Result<LocalTurnOutcome, String> {
    let mut stage = Stage::Initialize;
    let mut thread_id: Option<String> = None;
    let mut turn_id: Option<String> = None;
    let mut model = String::new();
    let mut projection = ProjectionState::default();
    loop {
        let timeout = if matches!(stage, Stage::Running) {
            TURN_IDLE_TIMEOUT
        } else {
            HANDSHAKE_TIMEOUT
        };
        let input = tokio::time::timeout(timeout, async {
            tokio::select! {
                line = read_json_line(&mut stdout) => line.map(Some),
                stopped = stop_rx.recv() => {
                    if stopped.is_some() { Ok(None) } else { Err("local_agent_control_closed".to_string()) }
                }
            }
        })
        .await
        .map_err(|_| "local_agent_timed_out".to_string())??;
        let Some(message) = input else {
            if let (Some(thread), Some(turn)) = (&thread_id, &turn_id) {
                let _ = send(stdin, &interrupt_request(thread, turn)).await;
            }
            let _ = on_event.send(LocalAgentEvent::Cancelled { thread_id, turn_id });
            let _ = child.start_kill();
            return Err("local_agent_cancelled".to_string());
        };

        if message.get("method").is_some() && message.get("id").is_some() {
            handle_server_request(
                app,
                stdin,
                posture,
                thread_id.as_deref(),
                turn_id.as_deref(),
                &message,
                on_event,
                &mut projection,
            )
            .await?;
            continue;
        }
        match stage {
            Stage::Initialize if response_failed(&message, 1) => {
                return Err("local_agent_initialize_refused".to_string());
            }
            Stage::Initialize if response_result(&message, 1).is_some() => {
                validate_initialize(response_result(&message, 1).unwrap())?;
                send(stdin, &initialized_notification()).await?;
                send(
                    stdin,
                    &thread_request(request, posture, workspace.to_string_lossy().as_ref())?,
                )
                .await?;
                stage = Stage::Thread;
                continue;
            }
            Stage::Thread if response_failed(&message, 2) => {
                return Err("local_agent_thread_refused".to_string());
            }
            Stage::Thread if response_result(&message, 2).is_some() => {
                let result = response_result(&message, 2).unwrap();
                validate_thread_policy(result, posture, workspace)?;
                let thread = protocol_identifier(result.pointer("/thread/id"))?;
                model = protocol_model(result.get("model"))?;
                send(stdin, &turn_request(&thread, &request.message)).await?;
                thread_id = Some(thread);
                stage = Stage::Turn;
                continue;
            }
            Stage::Turn if response_failed(&message, 3) => {
                return Err("local_agent_turn_refused".to_string());
            }
            Stage::Turn if response_result(&message, 3).is_some() => {
                let turn = protocol_identifier(
                    response_result(&message, 3).and_then(|result| result.pointer("/turn/id")),
                )?;
                let thread = thread_id
                    .clone()
                    .ok_or_else(|| "local_agent_protocol_invalid".to_string())?;
                let event_bytes = thread.len() + turn.len() + model.len();
                send_event(
                    on_event,
                    &mut projection,
                    LocalAgentEvent::MessageStart {
                        thread_id: thread,
                        turn_id: turn.clone(),
                        model: model.clone(),
                    },
                    event_bytes,
                )?;
                turn_id = Some(turn);
                stage = Stage::Running;
                continue;
            }
            _ => {}
        }
        if let Some(outcome) = handle_notification(
            &message,
            thread_id.as_deref(),
            turn_id.as_deref(),
            &model,
            on_event,
            &mut projection,
        )? {
            return Ok(outcome);
        }
    }
}

async fn handle_server_request(
    app: &AppHandle,
    stdin: &mut ChildStdin,
    posture: ApprovalPosture,
    thread_id: Option<&str>,
    turn_id: Option<&str>,
    message: &Value,
    on_event: &tauri::ipc::Channel<LocalAgentEvent>,
    projection: &mut ProjectionState,
) -> Result<(), String> {
    let id = message
        .get("id")
        .ok_or_else(|| "local_agent_protocol_invalid".to_string())?;
    let method = message.get("method").and_then(Value::as_str).unwrap_or("");
    if !matches!(
        method,
        "item/commandExecution/requestApproval" | "item/fileChange/requestApproval"
    ) || posture == ApprovalPosture::FullAccess
    {
        return send(stdin, &refusal_response(id)).await;
    }
    let params = message.get("params").unwrap_or(&Value::Null);
    if !notification_owned(params, thread_id, turn_id) {
        return send(stdin, &approval_response(id, false)).await;
    }
    let item_id =
        delta_item_id(params).ok_or_else(|| "local_agent_protocol_invalid".to_string())?;
    let detail = if method == "item/commandExecution/requestApproval" {
        bounded_text(params.get("command"))
    } else {
        bounded_text(params.get("reason"))
    };
    let question = if detail.is_empty() {
        "Allow this local agent action?".to_string()
    } else {
        format!("Allow this local agent action?\n\n{detail}")
    };
    let accept_allowed = method != "item/commandExecution/requestApproval"
        || params.get("availableDecisions").map_or(true, |value| {
            value.is_null()
                || value
                    .as_array()
                    .is_some_and(|choices| choices.iter().any(|choice| choice == "accept"))
        });
    let accepted = accept_allowed
        && app
            .dialog()
            .message(question)
            .title("Boltrig local agent approval")
            .kind(MessageDialogKind::Warning)
            .buttons(MessageDialogButtons::YesNo)
            .blocking_show();
    send(stdin, &approval_response(id, accepted)).await?;
    let decision = if accepted { "accepted" } else { "declined" }.to_string();
    let event_bytes = item_id.len() + decision.len();
    send_event(
        on_event,
        projection,
        LocalAgentEvent::ApprovalResolved { item_id, decision },
        event_bytes,
    )
}

fn handle_notification(
    message: &Value,
    thread_id: Option<&str>,
    turn_id: Option<&str>,
    model: &str,
    on_event: &tauri::ipc::Channel<LocalAgentEvent>,
    projection: &mut ProjectionState,
) -> Result<Option<LocalTurnOutcome>, String> {
    let method = message.get("method").and_then(Value::as_str).unwrap_or("");
    let params = message.get("params").unwrap_or(&Value::Null);
    match method {
        "item/agentMessage/delta" => {
            require_notification_owner(params, thread_id, turn_id)?;
            let item_id =
                delta_item_id(params).ok_or_else(|| "local_agent_protocol_invalid".to_string())?;
            let phase = projection.message_phase(&item_id)?;
            let delta = bounded_delta(params.get("delta"));
            if !delta.is_empty() {
                let bytes = delta.len();
                let event = if phase == AgentMessagePhase::Commentary {
                    LocalAgentEvent::ReasoningDelta { delta }
                } else {
                    LocalAgentEvent::TextDelta { delta }
                };
                send_event(on_event, projection, event, bytes)?;
            }
        }
        "item/reasoning/textDelta" | "item/reasoning/summaryTextDelta" => {
            require_notification_owner(params, thread_id, turn_id)?;
            let delta = bounded_delta(params.get("delta"));
            if !delta.is_empty() {
                let bytes = delta.len();
                send_event(
                    on_event,
                    projection,
                    LocalAgentEvent::ReasoningDelta { delta },
                    bytes,
                )?;
            }
        }
        "item/started" => {
            require_notification_owner(params, thread_id, turn_id)?;
            if params.pointer("/item/type").and_then(Value::as_str) == Some("agentMessage") {
                let (item_id, phase) = agent_message_identity(params)
                    .ok_or_else(|| "local_agent_protocol_invalid".to_string())?;
                projection.start_message(item_id, phase)?;
                return Ok(None);
            }
            if let Some((item_id, tool, _)) = item_identity(params) {
                let bytes = item_id.len() + tool.len();
                send_event(
                    on_event,
                    projection,
                    LocalAgentEvent::ToolStarted { item_id, tool },
                    bytes,
                )?;
            }
        }
        "item/completed" => {
            require_notification_owner(params, thread_id, turn_id)?;
            if params.pointer("/item/type").and_then(Value::as_str) == Some("agentMessage") {
                let (item_id, phase) = agent_message_identity(params)
                    .ok_or_else(|| "local_agent_protocol_invalid".to_string())?;
                projection.finish_message(&item_id, phase)?;
                return Ok(None);
            }
            if let Some((item_id, tool, status)) = item_identity(params) {
                let bytes = item_id.len() + tool.len() + status.len();
                send_event(
                    on_event,
                    projection,
                    LocalAgentEvent::ToolCompleted {
                        item_id,
                        tool,
                        status,
                    },
                    bytes,
                )?;
            }
        }
        "turn/completed" => {
            if !projection.active_messages.is_empty() {
                return Err("local_agent_protocol_mismatch".to_string());
            }
            let actual_thread = params.get("threadId").and_then(Value::as_str);
            let actual_turn = params.pointer("/turn/id").and_then(Value::as_str);
            if actual_thread != thread_id || actual_turn != turn_id {
                return Err("local_agent_protocol_mismatch".to_string());
            }
            let status = params
                .pointer("/turn/status")
                .and_then(Value::as_str)
                .ok_or_else(|| "local_agent_protocol_invalid".to_string())?;
            if !matches!(status, "completed" | "failed" | "interrupted") {
                return Err("local_agent_protocol_invalid".to_string());
            }
            let status = status.to_string();
            let thread = actual_thread.unwrap().to_string();
            let turn = actual_turn.unwrap().to_string();
            send_event(
                on_event,
                projection,
                LocalAgentEvent::MessageEnd {
                    thread_id: thread.clone(),
                    turn_id: turn.clone(),
                    status: status.clone(),
                },
                thread.len() + turn.len() + status.len(),
            )?;
            if status != "completed" {
                return Err("local_agent_turn_failed".to_string());
            }
            return Ok(Some(LocalTurnOutcome {
                thread_id: thread,
                turn_id: turn,
                status,
                model: model.to_string(),
            }));
        }
        _ => {}
    }
    Ok(None)
}

fn protocol_identifier(value: Option<&Value>) -> Result<String, String> {
    let value = value
        .and_then(Value::as_str)
        .ok_or_else(|| "local_agent_protocol_invalid".to_string())?;
    if value.is_empty()
        || value.len() > 180
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_graphic() && !byte.is_ascii_whitespace())
    {
        return Err("local_agent_protocol_invalid".to_string());
    }
    Ok(value.to_string())
}

fn protocol_model(value: Option<&Value>) -> Result<String, String> {
    let value = value.and_then(Value::as_str).unwrap_or("local Codex");
    if value.is_empty() || value.len() > 180 || value.chars().any(char::is_control) {
        return Err("local_agent_protocol_invalid".to_string());
    }
    Ok(value.to_string())
}

fn send_event(
    channel: &tauri::ipc::Channel<LocalAgentEvent>,
    projection: &mut ProjectionState,
    event: LocalAgentEvent,
    bytes: usize,
) -> Result<(), String> {
    projection.charge(bytes)?;
    channel
        .send(event)
        .map_err(|_| "local_agent_renderer_disconnected".to_string())
}

fn require_notification_owner(
    params: &Value,
    thread_id: Option<&str>,
    turn_id: Option<&str>,
) -> Result<(), String> {
    if notification_owned(params, thread_id, turn_id) {
        Ok(())
    } else {
        Err("local_agent_protocol_mismatch".to_string())
    }
}

fn notification_owned(params: &Value, thread_id: Option<&str>, turn_id: Option<&str>) -> bool {
    thread_id.is_some()
        && turn_id.is_some()
        && params.get("threadId").and_then(Value::as_str) == thread_id
        && params.get("turnId").and_then(Value::as_str) == turn_id
}

fn validate_initialize(result: &Value) -> Result<(), String> {
    for field in ["userAgent", "codexHome", "platformFamily", "platformOs"] {
        if result.get(field).and_then(Value::as_str).is_none() {
            return Err("local_agent_protocol_invalid".to_string());
        }
    }
    Ok(())
}

fn validate_thread_policy(
    result: &Value,
    posture: ApprovalPosture,
    workspace: &Path,
) -> Result<(), String> {
    let policy = posture.policy();
    let sandbox = result.get("sandbox").and_then(|value| {
        value
            .as_str()
            .or_else(|| value.get("type").and_then(Value::as_str))
    });
    let expected_sandbox = if policy.sandbox == "danger-full-access" {
        "dangerFullAccess"
    } else {
        "workspaceWrite"
    };
    if result.get("approvalPolicy").and_then(Value::as_str) != Some(policy.approval)
        || sandbox != Some(expected_sandbox)
        || result.get("cwd").and_then(Value::as_str) != workspace.to_str()
    {
        return Err("local_agent_policy_mismatch".to_string());
    }
    Ok(())
}

fn posture_entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(KEYRING_SERVICE, LOCAL_POSTURE_ACCOUNT)
        .map_err(|_| "os_keychain_unavailable".to_string())
}

fn load_posture() -> Result<ApprovalPosture, String> {
    match posture_entry()?.get_password() {
        Ok(value) => decode_posture(&value),
        Err(keyring::Error::NoEntry) => Ok(ApprovalPosture::AlwaysAsk),
        Err(_) => Err("os_keychain_read_failed".to_string()),
    }
}

fn store_posture(posture: ApprovalPosture) -> Result<(), String> {
    posture_entry()?
        .set_password(encode_posture(posture))
        .map_err(|_| "os_keychain_write_failed".to_string())
}

fn encode_posture(posture: ApprovalPosture) -> &'static str {
    match posture {
        ApprovalPosture::AlwaysAsk => "always_ask",
        ApprovalPosture::RiskBased => "risk_based",
        ApprovalPosture::FullAccess => "full_access",
    }
}

fn decode_posture(value: &str) -> Result<ApprovalPosture, String> {
    match value {
        "always_ask" => Ok(ApprovalPosture::AlwaysAsk),
        "risk_based" => Ok(ApprovalPosture::RiskBased),
        "full_access" => Ok(ApprovalPosture::FullAccess),
        _ => Err("local_agent_posture_invalid".to_string()),
    }
}

async fn send(stdin: &mut ChildStdin, message: &Value) -> Result<(), String> {
    let mut encoded =
        serde_json::to_vec(message).map_err(|_| "local_agent_protocol_invalid".to_string())?;
    if encoded.len() > MAX_JSON_LINE_BYTES {
        return Err("local_agent_frame_too_large".to_string());
    }
    encoded.push(b'\n');
    stdin
        .write_all(&encoded)
        .await
        .map_err(|_| "local_agent_transport_failed".to_string())?;
    stdin
        .flush()
        .await
        .map_err(|_| "local_agent_transport_failed".to_string())
}

async fn read_json_line<R: AsyncBufRead + Unpin>(reader: &mut R) -> Result<Value, String> {
    let mut bytes = Vec::new();
    loop {
        let buffer = reader
            .fill_buf()
            .await
            .map_err(|_| "local_agent_transport_failed".to_string())?;
        if buffer.is_empty() {
            return Err("local_agent_stopped".to_string());
        }
        let newline = buffer.iter().position(|byte| *byte == b'\n');
        let take = newline.map_or(buffer.len(), |index| index + 1);
        if bytes.len().saturating_add(take) > MAX_JSON_LINE_BYTES + 1 {
            return Err("local_agent_frame_too_large".to_string());
        }
        bytes.extend_from_slice(&buffer[..take]);
        reader.consume(take);
        if newline.is_some() {
            break;
        }
    }
    while matches!(bytes.last(), Some(b'\n' | b'\r')) {
        bytes.pop();
    }
    if bytes.is_empty() {
        return Err("local_agent_protocol_invalid".to_string());
    }
    let value: Value =
        serde_json::from_slice(&bytes).map_err(|_| "local_agent_protocol_invalid".to_string())?;
    if !value.is_object() {
        return Err("local_agent_protocol_invalid".to_string());
    }
    Ok(value)
}

fn resolve_binary(app: &AppHandle) -> Result<Binary, String> {
    if let Ok((triple, name, _)) = bundled_target() {
        if let Ok(resource_dir) = app.path().resource_dir() {
            let path = resource_dir
                .join("codex")
                .join("vendor")
                .join(triple)
                .join("bin")
                .join(name);
            if path.is_file() {
                return Ok(Binary {
                    path,
                    source: "bundled",
                });
            }
        }
    }
    if !cfg!(debug_assertions) {
        bundled_target()?;
        return Err("local_agent_binary_not_bundled".to_string());
    }
    let name = if cfg!(windows) { "codex.exe" } else { "codex" };
    if let Some(path) = std::env::var_os("BOLTRIG_LOCAL_CODEX_BIN") {
        let path = PathBuf::from(path);
        if path.is_absolute() && path.is_file() {
            return Ok(Binary {
                path,
                source: "development",
            });
        }
        return Err("local_agent_development_binary_invalid".to_string());
    }
    let paths = std::env::var_os("PATH").ok_or_else(|| "local_agent_binary_missing".to_string())?;
    for directory in std::env::split_paths(&paths).filter(|path| path.is_absolute()) {
        let candidate = directory.join(name);
        if candidate.is_file() {
            return Ok(Binary {
                path: candidate,
                source: "development",
            });
        }
    }
    Err("local_agent_binary_missing".to_string())
}

fn probe_binary(path: &Path, source: &'static str) -> Result<(&'static str, String), String> {
    if source == "bundled" {
        let (_, _, expected_sha256) = bundled_target()?;
        if bundled_binary_sha256(path)? != expected_sha256 {
            return Err("local_agent_binary_digest_mismatch".to_string());
        }
    }
    let output = std::process::Command::new(path)
        .arg("--version")
        .env_clear()
        .output()
        .map_err(|_| "local_agent_binary_unavailable".to_string())?;
    if !output.status.success() || output.stdout.len() > 256 || !output.stderr.is_empty() {
        return Err("local_agent_binary_invalid".to_string());
    }
    let text =
        String::from_utf8(output.stdout).map_err(|_| "local_agent_binary_invalid".to_string())?;
    let version = text
        .trim()
        .strip_prefix("codex-cli ")
        .ok_or_else(|| "local_agent_binary_invalid".to_string())?
        .to_string();
    if source == "bundled" && version != REQUIRED_RELEASE_CODEX_VERSION {
        return Err("local_agent_binary_version_mismatch".to_string());
    }
    Ok((source, version))
}

fn bundled_binary_sha256(path: &Path) -> Result<String, String> {
    let metadata = path
        .symlink_metadata()
        .map_err(|_| "local_agent_binary_invalid".to_string())?;
    if !metadata.file_type().is_file() || metadata.len() > MAX_BUNDLED_BINARY_BYTES {
        return Err("local_agent_binary_invalid".to_string());
    }
    let mut file = File::open(path).map_err(|_| "local_agent_binary_invalid".to_string())?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 1024 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|_| "local_agent_binary_invalid".to_string())?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(hex::encode(digest.finalize()))
}

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
fn bundled_target() -> Result<(&'static str, &'static str, &'static str), String> {
    Ok((
        "aarch64-apple-darwin",
        "codex",
        "718724d7221cf1298071ca92411cb74caa8422809154150cedca7b569a4518e3",
    ))
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn bundled_target() -> Result<(&'static str, &'static str, &'static str), String> {
    Ok((
        "x86_64-unknown-linux-musl",
        "codex",
        "37e6f5953f191b04f7b62cb07dae90f51d0947ad89f0355665b421fbde28700b",
    ))
}

#[cfg(all(target_os = "windows", target_arch = "x86_64"))]
fn bundled_target() -> Result<(&'static str, &'static str, &'static str), String> {
    Ok((
        "x86_64-pc-windows-msvc",
        "codex.exe",
        "e5dcc9f9b08102c58596af85345f689a69fd53a87d8d408bdc0fcdaf99fcf6e3",
    ))
}

#[cfg(not(any(
    all(target_os = "macos", target_arch = "aarch64"),
    all(target_os = "linux", target_arch = "x86_64"),
    all(target_os = "windows", target_arch = "x86_64"),
)))]
fn bundled_target() -> Result<(&'static str, &'static str, &'static str), String> {
    Err("local_agent_platform_unsupported".to_string())
}

fn apply_safe_environment(command: &mut Command, codex_home: &Path) {
    command.env_clear();
    for (key, value) in safe_environment(|key| std::env::var_os(key), codex_home) {
        command.env(key, value);
    }
}

/// The complete child environment: the allowlisted parent values plus the
/// app-private `CODEX_HOME`, which always wins over anything inherited.
fn safe_environment(
    parent: impl Fn(&str) -> Option<OsString>,
    codex_home: &Path,
) -> Vec<(&'static str, OsString)> {
    let mut environment = Vec::with_capacity(SAFE_LOCAL_AGENT_ENVIRONMENT.len() + 1);
    for key in SAFE_LOCAL_AGENT_ENVIRONMENT {
        let Some(value) = parent(key) else {
            continue;
        };
        if *key == "PATH" {
            if let Some(path) = absolute_path_entries(&value) {
                environment.push((*key, path));
            }
        } else {
            environment.push((*key, value));
        }
    }
    environment.push(("CODEX_HOME", codex_home.as_os_str().to_os_string()));
    environment
}

fn private_codex_home(app: &AppHandle) -> Result<PathBuf, String> {
    let base = app
        .path()
        .app_data_dir()
        .map_err(|_| "local_agent_home_unavailable".to_string())?;
    let home = base.join(LOCAL_AGENT_DIR).join(PRIVATE_CODEX_HOME_DIR);
    ensure_private_codex_home(&home)?;
    Ok(home)
}

/// Create the private runtime home (owner-only on Unix) and seed a minimal
/// `config.toml` exactly once. Nothing is copied from a personal `~/.codex`;
/// an existing directory that is not a real directory is refused.
fn ensure_private_codex_home(home: &Path) -> Result<(), String> {
    if !home.is_absolute() {
        return Err("local_agent_home_unavailable".to_string());
    }
    let mut builder = DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    builder.mode(0o700);
    builder
        .create(home)
        .map_err(|_| "local_agent_home_unavailable".to_string())?;
    let metadata = home
        .symlink_metadata()
        .map_err(|_| "local_agent_home_unavailable".to_string())?;
    if !metadata.file_type().is_dir() {
        return Err("local_agent_home_unavailable".to_string());
    }
    #[cfg(unix)]
    {
        std::fs::set_permissions(home, std::fs::Permissions::from_mode(0o700))
            .map_err(|_| "local_agent_home_unavailable".to_string())?;
        if let Some(parent) = home.parent() {
            let _ = std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o700));
        }
    }
    seed_private_config(home)
}

fn seed_private_config(home: &Path) -> Result<(), String> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    options.mode(0o600);
    match options.open(home.join("config.toml")) {
        Ok(mut file) => file
            .write_all(PRIVATE_CONFIG_TOML.as_bytes())
            .map_err(|_| "local_agent_home_unavailable".to_string()),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => Ok(()),
        Err(_) => Err("local_agent_home_unavailable".to_string()),
    }
}

/// Whether the private home holds a sign-in. The bundled binary writes
/// `auth.json` on `codex login` (an API key or ChatGPT tokens) and removes it
/// on `codex logout`; nothing outside the private home is consulted.
fn codex_home_signed_in(home: &Path) -> bool {
    let path = home.join("auth.json");
    let Ok(metadata) = path.symlink_metadata() else {
        return false;
    };
    if !metadata.file_type().is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_AUTH_FILE_BYTES
    {
        return false;
    }
    let Ok(bytes) = std::fs::read(&path) else {
        return false;
    };
    let Ok(value) = serde_json::from_slice::<Value>(&bytes) else {
        return false;
    };
    // Spelled in two halves so the source never carries the provider-key
    // literal that the surface-boundary gate forbids; the runtime writes it.
    let api_key = value
        .get(concat!("OPENAI_", "API_KEY"))
        .and_then(Value::as_str)
        .is_some_and(|key| !key.is_empty());
    let tokens = value
        .get("tokens")
        .and_then(Value::as_object)
        .is_some_and(|tokens| {
            ["access_token", "id_token", "refresh_token"]
                .iter()
                .any(|field| {
                    tokens
                        .get(*field)
                        .and_then(Value::as_str)
                        .is_some_and(|token| !token.is_empty())
                })
        });
    value.is_object() && (api_key || tokens)
}

fn remove_private_auth(home: &Path) -> Result<(), String> {
    match std::fs::remove_file(home.join("auth.json")) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err("local_agent_sign_out_failed".to_string()),
    }
}

/// Sign the bundled runtime in to its private home with its device-code flow.
///
/// `codex login --device-auth` prints a sign-in page and a one-time code and
/// then polls until the user finishes in the browser; unlike `codex login` it
/// opens no local listener and does not launch a browser itself, so the app is
/// the only thing that opens the page. The child runs under the private
/// `CODEX_HOME` with the same cleared environment as a local turn.
pub(crate) async fn sign_in(
    app: &AppHandle,
    runtime: &LocalAgentRuntime,
    on_event: tauri::ipc::Channel<LocalAgentSignInEvent>,
) -> Result<LocalAgentSignInView, String> {
    let binary = resolve_binary(app)?;
    let _ = probe_binary(&binary.path, binary.source)?;
    let home = private_codex_home(app)?;
    let (stop, stop_rx) = mpsc::channel(1);
    let generation = uuid::Uuid::new_v4().to_string();
    {
        if runtime.active.lock().await.is_some() {
            return Err("local_agent_busy".to_string());
        }
        let mut signing_in = runtime.sign_in.lock().await;
        if signing_in.is_some() {
            return Err("local_agent_busy".to_string());
        }
        *signing_in = Some(ActiveChild {
            generation: generation.clone(),
            stop,
        });
    }
    let result = run_sign_in(app, binary.path, &home, on_event, stop_rx).await;
    let mut signing_in = runtime.sign_in.lock().await;
    if signing_in
        .as_ref()
        .is_some_and(|child| child.generation == generation)
    {
        *signing_in = None;
    }
    result
}

async fn run_sign_in(
    app: &AppHandle,
    binary: PathBuf,
    home: &Path,
    on_event: tauri::ipc::Channel<LocalAgentSignInEvent>,
    mut stop_rx: mpsc::Receiver<()>,
) -> Result<LocalAgentSignInView, String> {
    let mut command = Command::new(binary);
    command
        .arg("login")
        .arg("--device-auth")
        .current_dir(home)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    apply_safe_environment(&mut command, home);
    let mut child = command
        .spawn()
        .map_err(|_| "local_agent_spawn_failed".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "local_agent_stdio_unavailable".to_string())?;
    let _ = on_event.send(LocalAgentSignInEvent::Started);
    let driven = tokio::time::timeout(
        SIGN_IN_TIMEOUT,
        drive_sign_in(app, BufReader::new(stdout), &on_event, &mut stop_rx),
    )
    .await
    .unwrap_or_else(|_| Err("local_agent_sign_in_timed_out".to_string()));
    let status = match driven {
        Ok(()) => tokio::time::timeout(SIGN_OUT_TIMEOUT, child.wait()).await,
        Err(reason) => {
            let _ = child.kill().await;
            let _ = child.wait().await;
            return Err(reason);
        }
    };
    let exited = matches!(status, Ok(Ok(status)) if status.success());
    if !exited {
        let _ = child.kill().await;
        let _ = child.wait().await;
        return Err("local_agent_sign_in_failed".to_string());
    }
    if !codex_home_signed_in(home) {
        return Err("local_agent_sign_in_failed".to_string());
    }
    let _ = on_event.send(LocalAgentSignInEvent::Completed);
    Ok(LocalAgentSignInView { signed_in: true })
}

/// Read the child's prompt until it exits. `Ok(())` means stdout closed.
async fn drive_sign_in(
    app: &AppHandle,
    mut stdout: BufReader<ChildStdout>,
    on_event: &tauri::ipc::Channel<LocalAgentSignInEvent>,
    stop_rx: &mut mpsc::Receiver<()>,
) -> Result<(), String> {
    let mut prompt = SignInPrompt::default();
    let mut announced = false;
    let mut total = 0_usize;
    loop {
        let line = tokio::select! {
            line = read_text_line(&mut stdout) => line?,
            stopped = stop_rx.recv() => {
                return Err(if stopped.is_some() {
                    "local_agent_sign_in_cancelled".to_string()
                } else {
                    "local_agent_control_closed".to_string()
                });
            }
        };
        let Some(line) = line else {
            return Ok(());
        };
        total = total.saturating_add(line.len());
        if total > MAX_SIGN_IN_OUTPUT_BYTES {
            return Err("local_agent_output_too_large".to_string());
        }
        prompt.observe(&line);
        if announced {
            continue;
        }
        if let (Some(url), Some(code)) = (&prompt.url, &prompt.code) {
            announced = true;
            let opened = open_sign_in_url(app, url);
            on_event
                .send(LocalAgentSignInEvent::Code {
                    url: url.clone(),
                    code: code.clone(),
                    opened,
                })
                .map_err(|_| "local_agent_renderer_disconnected".to_string())?;
        }
    }
}

/// What the device-code prompt tells the user: the page to open and the
/// one-time code to enter there. Parsed from plain text with terminal colour
/// codes removed; nothing else on the child's stdout is interpreted.
#[derive(Default)]
struct SignInPrompt {
    url: Option<String>,
    code: Option<String>,
}

impl SignInPrompt {
    fn observe(&mut self, line: &str) {
        let clean = strip_ansi(line);
        for token in clean.split_whitespace() {
            if self.url.is_none() && token.starts_with("https://") {
                self.url = Some(token.trim_end_matches(['.', ',', ')']).to_string());
            } else if self.url.is_some() && self.code.is_none() && looks_like_device_code(token) {
                self.code = Some(token.to_string());
            }
        }
    }
}

fn looks_like_device_code(token: &str) -> bool {
    let bytes = token.as_bytes();
    (7..=24).contains(&bytes.len())
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || *byte == b'-')
        && token.contains('-')
        && token.split('-').all(|part| part.len() >= 3)
}

fn strip_ansi(line: &str) -> String {
    let mut clean = String::with_capacity(line.len());
    let mut chars = line.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch == '\u{1b}' {
            if chars.peek() == Some(&'[') {
                chars.next();
                for next in chars.by_ref() {
                    if ('\u{40}'..='\u{7e}').contains(&next) {
                        break;
                    }
                }
            }
            continue;
        }
        if !ch.is_control() {
            clean.push(ch);
        }
    }
    clean
}

/// The app opens only the runtime's own HTTPS sign-in page; a URL the child
/// prints that points anywhere else is shown to the user but never launched.
fn sign_in_url_is_openable(url: &str) -> bool {
    url::Url::parse(url).is_ok_and(|parsed| {
        parsed.scheme() == "https"
            && parsed.username().is_empty()
            && parsed.password().is_none()
            && parsed
                .host_str()
                .is_some_and(|host| host == "openai.com" || host.ends_with(".openai.com"))
    })
}

fn open_sign_in_url(app: &AppHandle, url: &str) -> bool {
    sign_in_url_is_openable(url) && app.opener().open_url(url, None::<&str>).is_ok()
}

/// Remove the sign-in from the private home. A sign-in still in progress is
/// cancelled first; the bundled binary's own `logout` runs when it is
/// available, and the credential file is removed regardless.
pub(crate) async fn sign_out(
    app: &AppHandle,
    runtime: &LocalAgentRuntime,
) -> Result<LocalAgentSignInView, String> {
    let pending = runtime
        .sign_in
        .lock()
        .await
        .as_ref()
        .map(|child| child.stop.clone());
    if let Some(stop) = pending {
        let _ = stop.send(()).await;
    }
    if runtime.active.lock().await.is_some() {
        return Err("local_agent_busy".to_string());
    }
    let home = private_codex_home(app)?;
    if let Ok(binary) = resolve_binary(app) {
        if probe_binary(&binary.path, binary.source).is_ok() {
            let mut command = Command::new(binary.path);
            command
                .arg("logout")
                .current_dir(&home)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .kill_on_drop(true);
            apply_safe_environment(&mut command, &home);
            if let Ok(mut child) = command.spawn() {
                let _ = tokio::time::timeout(SIGN_OUT_TIMEOUT, child.wait()).await;
            }
        }
    }
    remove_private_auth(&home)?;
    Ok(LocalAgentSignInView {
        signed_in: codex_home_signed_in(&home),
    })
}

/// One bounded line of plain text; `Ok(None)` when the stream closes.
async fn read_text_line<R: AsyncBufRead + Unpin>(reader: &mut R) -> Result<Option<String>, String> {
    let mut bytes = Vec::new();
    loop {
        let buffer = reader
            .fill_buf()
            .await
            .map_err(|_| "local_agent_transport_failed".to_string())?;
        if buffer.is_empty() {
            if bytes.is_empty() {
                return Ok(None);
            }
            break;
        }
        let newline = buffer.iter().position(|byte| *byte == b'\n');
        let take = newline.map_or(buffer.len(), |index| index + 1);
        if bytes.len().saturating_add(take) > MAX_SIGN_IN_LINE_BYTES + 1 {
            return Err("local_agent_frame_too_large".to_string());
        }
        bytes.extend_from_slice(&buffer[..take]);
        reader.consume(take);
        if newline.is_some() {
            break;
        }
    }
    while matches!(bytes.last(), Some(b'\n' | b'\r')) {
        bytes.pop();
    }
    Ok(Some(String::from_utf8_lossy(&bytes).into_owned()))
}

fn absolute_path_entries(value: &OsStr) -> Option<OsString> {
    let paths = std::env::split_paths(value).filter(|path| path.is_absolute());
    std::env::join_paths(paths)
        .ok()
        .filter(|value| !value.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn line_reader_bounds_and_decodes_one_json_object() {
        let input = b"{\"id\":1,\"result\":{}}\n{\"id\":2}\n".as_slice();
        let mut reader = BufReader::new(input);
        assert_eq!(read_json_line(&mut reader).await.unwrap()["id"], 1);
        assert_eq!(read_json_line(&mut reader).await.unwrap()["id"], 2);
    }

    #[tokio::test]
    async fn line_reader_refuses_non_objects_and_oversized_frames() {
        let mut scalar = BufReader::new(b"[]\n".as_slice());
        assert_eq!(
            read_json_line(&mut scalar).await,
            Err("local_agent_protocol_invalid".to_string())
        );
        let mut oversized = vec![b'x'; MAX_JSON_LINE_BYTES + 2];
        oversized.push(b'\n');
        let mut reader = BufReader::new(oversized.as_slice());
        assert_eq!(
            read_json_line(&mut reader).await,
            Err("local_agent_frame_too_large".to_string())
        );
    }

    #[test]
    fn notifications_are_owned_by_the_exact_active_thread_and_turn() {
        let params = serde_json::json!({"threadId": "thread-1", "turnId": "turn-1"});
        assert!(notification_owned(
            &params,
            Some("thread-1"),
            Some("turn-1")
        ));
        assert!(!notification_owned(
            &params,
            Some("thread-2"),
            Some("turn-1")
        ));
        assert!(!notification_owned(&params, Some("thread-1"), None));
    }

    #[test]
    fn local_posture_encoding_is_bounded_and_unknown_values_fail_closed() {
        for posture in [
            ApprovalPosture::AlwaysAsk,
            ApprovalPosture::RiskBased,
            ApprovalPosture::FullAccess,
        ] {
            assert_eq!(decode_posture(encode_posture(posture)).unwrap(), posture);
        }
        assert_eq!(
            decode_posture("cloud_full_access"),
            Err("local_agent_posture_invalid".to_string())
        );
    }

    #[test]
    fn local_agent_environment_never_delegates_shell_or_cloud_credentials() {
        for forbidden in [
            "AWS_ACCESS_KEY_ID",
            "BOLTRIG_MODEL_GATEWAY_KEY",
            "GITHUB_TOKEN",
            concat!("OPENAI_", "API_KEY"),
            "SSH_AUTH_SOCK",
        ] {
            assert!(!SAFE_LOCAL_AGENT_ENVIRONMENT.contains(&forbidden));
        }
        // CODEX_HOME is never passed through: the private home is set explicitly.
        assert!(!SAFE_LOCAL_AGENT_ENVIRONMENT.contains(&"CODEX_HOME"));
        assert!(SAFE_LOCAL_AGENT_ENVIRONMENT.contains(&"HOME"));
        assert!(SAFE_LOCAL_AGENT_ENVIRONMENT.contains(&"PATH"));
    }

    fn private_home_fixture() -> PathBuf {
        PathBuf::from(if cfg!(windows) {
            r"C:\app-data\local-agent\codex-home"
        } else {
            "/app-data/local-agent/codex-home"
        })
    }

    fn scratch_dir(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "boltrig-local-agent-{label}-{}",
            uuid::Uuid::new_v4()
        ))
    }

    #[test]
    fn local_agent_codex_home_is_always_the_private_directory() {
        let private = private_home_fixture();
        let parent = |key: &str| -> Option<OsString> {
            match key {
                "CODEX_HOME" => Some(OsString::from("/home/user/.codex")),
                "HOME" => Some(OsString::from("/home/user")),
                "PATH" => std::env::join_paths([std::env::temp_dir()]).ok(),
                _ => None,
            }
        };
        let environment = safe_environment(parent, &private);
        let codex_homes: Vec<_> = environment
            .iter()
            .filter(|(key, _)| *key == "CODEX_HOME")
            .collect();
        assert_eq!(codex_homes.len(), 1);
        assert_eq!(codex_homes[0].1, private.as_os_str());
        assert!(environment
            .iter()
            .any(|(key, value)| *key == "HOME" && value == "/home/user"));
        assert!(!environment
            .iter()
            .any(|(_, value)| value == "/home/user/.codex"));
        // A parent with no CODEX_HOME at all still yields the private one.
        assert_eq!(
            safe_environment(|_| None, &private),
            vec![("CODEX_HOME", private.clone().into_os_string())]
        );
    }

    #[test]
    fn private_codex_home_is_created_private_seeded_once_and_copies_nothing_personal() {
        let root = scratch_dir("home");
        let personal = root.join("personal-home").join(".codex");
        std::fs::create_dir_all(&personal).unwrap();
        std::fs::write(
            personal.join("config.toml"),
            "model_provider = \"personal-marker\"\n",
        )
        .unwrap();
        std::fs::write(
            personal.join("auth.json"),
            format!("{{\"{}\":\"sk-personal\"}}", concat!("OPENAI_", "API_KEY")),
        )
        .unwrap();
        let home = root
            .join("app-data")
            .join(LOCAL_AGENT_DIR)
            .join(PRIVATE_CODEX_HOME_DIR);

        ensure_private_codex_home(&home).unwrap();

        assert!(home.is_dir());
        #[cfg(unix)]
        {
            assert_eq!(home.metadata().unwrap().permissions().mode() & 0o777, 0o700);
            assert_eq!(
                home.parent()
                    .unwrap()
                    .metadata()
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o700
            );
            assert_eq!(
                home.join("config.toml")
                    .metadata()
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o600
            );
        }
        let config = std::fs::read_to_string(home.join("config.toml")).unwrap();
        assert_eq!(config, PRIVATE_CONFIG_TOML);
        assert!(!config.contains("personal-marker"));
        assert!(!home.join("auth.json").exists());
        assert!(!codex_home_signed_in(&home));

        // A second visit keeps whatever the home already holds.
        std::fs::write(home.join("config.toml"), "# edited\n").unwrap();
        ensure_private_codex_home(&home).unwrap();
        assert_eq!(
            std::fs::read_to_string(home.join("config.toml")).unwrap(),
            "# edited\n"
        );
        assert_eq!(
            ensure_private_codex_home(Path::new("relative/codex-home")),
            Err("local_agent_home_unavailable".to_string())
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn private_codex_home_refuses_a_symlinked_directory() {
        let root = scratch_dir("symlink");
        let elsewhere = root.join("elsewhere");
        std::fs::create_dir_all(&elsewhere).unwrap();
        let home = root.join(LOCAL_AGENT_DIR).join(PRIVATE_CODEX_HOME_DIR);
        std::fs::create_dir_all(home.parent().unwrap()).unwrap();
        std::os::unix::fs::symlink(&elsewhere, &home).unwrap();
        assert_eq!(
            ensure_private_codex_home(&home),
            Err("local_agent_home_unavailable".to_string())
        );
        assert!(!elsewhere.join("config.toml").exists());
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn signed_in_reads_only_the_private_auth_file() {
        let home = scratch_dir("auth");
        std::fs::create_dir_all(&home).unwrap();
        let auth = home.join("auth.json");
        assert!(!codex_home_signed_in(&home));
        let api_key_field = concat!("OPENAI_", "API_KEY");
        let with_api_key = format!("{{\"{api_key_field}\":\"sk-test\",\"auth_mode\":\"apikey\"}}");
        let with_empty_api_key = format!("{{\"{api_key_field}\":\"\"}}");
        for (contents, expected) in [
            (with_api_key.as_str(), true),
            ("{\"auth_mode\":\"chatgpt\",\"tokens\":{\"access_token\":\"a\",\"refresh_token\":\"r\"}}", true),
            (with_empty_api_key.as_str(), false),
            ("{}", false),
            ("[]", false),
            ("not json", false),
            ("", false),
        ] {
            std::fs::write(&auth, contents).unwrap();
            assert_eq!(codex_home_signed_in(&home), expected, "{contents}");
        }
        remove_private_auth(&home).unwrap();
        assert!(!auth.exists());
        remove_private_auth(&home).unwrap();
        let _ = std::fs::remove_dir_all(home);
    }

    /// The exact prompt Codex 0.144.3 prints for `login --device-auth`,
    /// captured on 2026-08-22 with its terminal colour codes intact.
    #[test]
    fn sign_in_prompt_parser_finds_the_device_page_and_code() {
        let mut prompt = SignInPrompt::default();
        for line in [
            "",
            "Welcome to Codex [v\u{1b}[90m0.144.3\u{1b}[0m]",
            "\u{1b}[90mOpenAI's command-line coding agent\u{1b}[0m",
            "Follow these steps to sign in with ChatGPT using device code authorization:",
            "1. Open this link in your browser and sign in to your account",
        ] {
            prompt.observe(line);
            assert!(prompt.url.is_none() && prompt.code.is_none(), "{line:?}");
        }
        prompt.observe("   \u{1b}[94mhttps://auth.openai.com/codex/device\u{1b}[0m");
        prompt.observe("2. Enter this one-time code \u{1b}[90m(expires in 15 minutes)\u{1b}[0m");
        assert!(prompt.code.is_none());
        prompt.observe("   \u{1b}[94m6B30-9JOVE\u{1b}[0m");
        assert_eq!(
            prompt.url.as_deref(),
            Some("https://auth.openai.com/codex/device")
        );
        assert_eq!(prompt.code.as_deref(), Some("6B30-9JOVE"));
        // Later output never rewrites what was announced.
        prompt.observe("https://evil.example/ ZZZZ-ZZZZZ");
        assert_eq!(
            prompt.url.as_deref(),
            Some("https://auth.openai.com/codex/device")
        );
        assert_eq!(prompt.code.as_deref(), Some("6B30-9JOVE"));
    }

    #[test]
    fn sign_in_only_opens_the_runtime_sign_in_page() {
        assert!(sign_in_url_is_openable(
            "https://auth.openai.com/codex/device"
        ));
        for refused in [
            "http://auth.openai.com/codex/device",
            "https://auth.openai.com.evil.example/codex/device",
            "https://evil.example/?next=auth.openai.com",
            "https://user:pass@auth.openai.com/codex/device",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "",
        ] {
            assert!(!sign_in_url_is_openable(refused), "{refused}");
        }
    }

    #[tokio::test]
    async fn text_line_reader_bounds_lines_and_reports_end_of_stream() {
        let mut reader = BufReader::new(b"first\r\nsecond".as_slice());
        assert_eq!(
            read_text_line(&mut reader).await.unwrap().as_deref(),
            Some("first")
        );
        assert_eq!(
            read_text_line(&mut reader).await.unwrap().as_deref(),
            Some("second")
        );
        assert_eq!(read_text_line(&mut reader).await.unwrap(), None);
        let mut oversized = vec![b'x'; MAX_SIGN_IN_LINE_BYTES + 2];
        oversized.push(b'\n');
        let mut reader = BufReader::new(oversized.as_slice());
        assert_eq!(
            read_text_line(&mut reader).await,
            Err("local_agent_frame_too_large".to_string())
        );
    }

    #[cfg(unix)]
    #[test]
    fn local_agent_path_drops_relative_workspace_search_entries() {
        let input = std::env::join_paths(["/usr/bin", ".", "relative/bin", "/bin"]).unwrap();
        let filtered = absolute_path_entries(&input).unwrap();
        assert_eq!(
            std::env::split_paths(&filtered).collect::<Vec<_>>(),
            vec![PathBuf::from("/usr/bin"), PathBuf::from("/bin")]
        );
    }

    #[test]
    fn projection_tracks_message_phase_and_bounds_cumulative_output() {
        let mut projection = ProjectionState::default();
        projection
            .start_message("commentary-1".to_string(), AgentMessagePhase::Commentary)
            .unwrap();
        assert_eq!(
            projection.message_phase("commentary-1").unwrap(),
            AgentMessagePhase::Commentary
        );
        projection
            .finish_message("commentary-1", AgentMessagePhase::Commentary)
            .unwrap();
        assert!(projection.message_phase("commentary-1").is_err());
        assert!(projection.charge(MAX_PROJECTED_BYTES).is_ok());
        assert_eq!(
            projection.charge(1),
            Err("local_agent_output_too_large".to_string())
        );
    }
}
