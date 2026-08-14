use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

pub(crate) const MAX_JSON_LINE_BYTES: usize = 1024 * 1024;
const MAX_PROMPT_BYTES: usize = 128 * 1024;
const MAX_IDENTIFIER_BYTES: usize = 180;
const MAX_NOTICE_BYTES: usize = 2_000;
const MAX_DELTA_BYTES: usize = 256 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ApprovalPosture {
    AlwaysAsk,
    RiskBased,
    FullAccess,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LocalTurnRequest {
    pub(crate) root_id: String,
    pub(crate) thread_id: Option<String>,
    pub(crate) message: String,
}

#[derive(Clone, Debug, Serialize)]
pub(crate) struct LocalTurnOutcome {
    pub(crate) thread_id: String,
    pub(crate) turn_id: String,
    pub(crate) status: String,
    pub(crate) model: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub(crate) enum LocalAgentEvent {
    MessageStart {
        thread_id: String,
        turn_id: String,
        model: String,
    },
    TextDelta {
        delta: String,
    },
    ReasoningDelta {
        delta: String,
    },
    ToolStarted {
        item_id: String,
        tool: String,
    },
    ToolCompleted {
        item_id: String,
        tool: String,
        status: String,
    },
    ApprovalResolved {
        item_id: String,
        decision: String,
    },
    MessageEnd {
        thread_id: String,
        turn_id: String,
        status: String,
    },
    Cancelled {
        thread_id: Option<String>,
        turn_id: Option<String>,
    },
}

pub(crate) struct LocalPolicy {
    pub(crate) approval: &'static str,
    pub(crate) sandbox: &'static str,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum AgentMessagePhase {
    Commentary,
    FinalAnswer,
    Unknown,
}

impl ApprovalPosture {
    pub(crate) fn policy(self) -> LocalPolicy {
        match self {
            Self::AlwaysAsk => LocalPolicy {
                approval: "untrusted",
                sandbox: "workspace-write",
            },
            Self::RiskBased => LocalPolicy {
                approval: "on-request",
                sandbox: "workspace-write",
            },
            Self::FullAccess => LocalPolicy {
                approval: "never",
                sandbox: "danger-full-access",
            },
        }
    }
}

impl LocalTurnRequest {
    pub(crate) fn validate(&self) -> Result<(), String> {
        validate_identifier("root", &self.root_id)?;
        if let Some(thread_id) = &self.thread_id {
            validate_identifier("thread", thread_id)?;
        }
        if self.message.trim().is_empty() || self.message.len() > MAX_PROMPT_BYTES {
            return Err("invalid_local_agent_message".to_string());
        }
        Ok(())
    }
}

pub(crate) fn initialize_request(version: &str) -> Value {
    json!({
        "id": 1,
        "method": "initialize",
        "params": {
            "clientInfo": {
                "name": "boltrig-worker",
                "title": "Boltrig Worker",
                "version": version,
            },
            "capabilities": {"experimentalApi": false},
        },
    })
}

pub(crate) fn initialized_notification() -> Value {
    json!({"method": "initialized"})
}

pub(crate) fn thread_request(
    request: &LocalTurnRequest,
    posture: ApprovalPosture,
    cwd: &str,
) -> Result<Value, String> {
    if cwd.is_empty() || !std::path::Path::new(cwd).is_absolute() {
        return Err("invalid_local_agent_workspace".to_string());
    }
    let policy = posture.policy();
    Ok(match &request.thread_id {
        Some(thread_id) => json!({
            "id": 2,
            "method": "thread/resume",
            "params": {
                "threadId": thread_id,
                "cwd": cwd,
                "approvalPolicy": policy.approval,
                "sandbox": policy.sandbox,
            },
        }),
        None => json!({
            "id": 2,
            "method": "thread/start",
            "params": {
                "cwd": cwd,
                "approvalPolicy": policy.approval,
                "sandbox": policy.sandbox,
                "ephemeral": false,
                "serviceName": "Boltrig Worker",
            },
        }),
    })
}

pub(crate) fn turn_request(thread_id: &str, message: &str) -> Value {
    json!({
        "id": 3,
        "method": "turn/start",
        "params": {
            "threadId": thread_id,
            "clientUserMessageId": format!("boltrig-{}", uuid::Uuid::new_v4()),
            "input": [{"type": "text", "text": message}],
        },
    })
}

pub(crate) fn interrupt_request(thread_id: &str, turn_id: &str) -> Value {
    json!({
        "id": 4,
        "method": "turn/interrupt",
        "params": {"threadId": thread_id, "turnId": turn_id},
    })
}

pub(crate) fn approval_response(request_id: &Value, accepted: bool) -> Value {
    json!({
        "id": request_id,
        "result": {"decision": if accepted { "accept" } else { "decline" }},
    })
}

pub(crate) fn refusal_response(request_id: &Value) -> Value {
    json!({
        "id": request_id,
        "error": {"code": -32601, "message": "unsupported local agent request"},
    })
}

pub(crate) fn response_result<'a>(message: &'a Value, expected_id: i64) -> Option<&'a Value> {
    if message.get("id").and_then(Value::as_i64) != Some(expected_id) {
        return None;
    }
    message.get("result")
}

pub(crate) fn response_failed(message: &Value, expected_id: i64) -> bool {
    message.get("id").and_then(Value::as_i64) == Some(expected_id) && message.get("error").is_some()
}

pub(crate) fn bounded_text(value: Option<&Value>) -> String {
    bounded_string(
        value.and_then(Value::as_str).unwrap_or(""),
        MAX_NOTICE_BYTES,
    )
}

pub(crate) fn bounded_delta(value: Option<&Value>) -> String {
    bounded_string(value.and_then(Value::as_str).unwrap_or(""), MAX_DELTA_BYTES)
}

pub(crate) fn item_identity(params: &Value) -> Option<(String, String, String)> {
    let item = params.get("item")?;
    let id = item.get("id")?.as_str()?;
    if validate_identifier("item", id).is_err() {
        return None;
    }
    let item_type = item.get("type")?.as_str()?;
    let tool = match item_type {
        "commandExecution" => "Local shell",
        "fileChange" => "Local file change",
        "mcpToolCall" => "Tool call",
        "webSearch" => "Web search",
        _ => return None,
    };
    let status = bounded_string(
        item.get("status")
            .and_then(Value::as_str)
            .unwrap_or("running"),
        64,
    );
    Some((id.to_string(), tool.to_string(), status))
}

pub(crate) fn agent_message_identity(params: &Value) -> Option<(String, AgentMessagePhase)> {
    let item = params.get("item")?;
    if item.get("type")?.as_str()? != "agentMessage" {
        return None;
    }
    let id = item.get("id")?.as_str()?;
    if validate_identifier("item", id).is_err() {
        return None;
    }
    let phase = match item.get("phase") {
        None | Some(Value::Null) => AgentMessagePhase::Unknown,
        Some(Value::String(value)) if value == "commentary" => AgentMessagePhase::Commentary,
        Some(Value::String(value)) if value == "final_answer" => AgentMessagePhase::FinalAnswer,
        _ => return None,
    };
    Some((id.to_string(), phase))
}

pub(crate) fn delta_item_id(params: &Value) -> Option<String> {
    let id = params.get("itemId")?.as_str()?;
    validate_identifier("item", id).ok()?;
    Some(id.to_string())
}

fn validate_identifier(label: &str, value: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > MAX_IDENTIFIER_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_graphic() && !byte.is_ascii_whitespace())
    {
        return Err(format!("invalid_local_agent_{label}_id"));
    }
    Ok(())
}

fn bounded_string(value: &str, max_bytes: usize) -> String {
    if value.len() <= max_bytes {
        return value.to_string();
    }
    let mut boundary = max_bytes;
    while boundary > 0 && !value.is_char_boundary(boundary) {
        boundary -= 1;
    }
    let mut result = value[..boundary].to_string();
    result.push('…');
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    /// An absolute workspace path for the platform the test is compiled for.
    ///
    /// `Path::new("/workspace").is_absolute()` is true on Unix and FALSE on
    /// Windows, where an absolute path needs a prefix such as `C:\`. The bare
    /// "/workspace" literal therefore passed on linux-x86_64 and macos-arm64
    /// and failed only on windows-x86_64, where thread_request correctly
    /// returned "invalid_local_agent_workspace". The product code is right;
    /// the fixture was not portable.
    #[cfg(windows)]
    const ABSOLUTE_WORKSPACE: &str = r"C:\workspace";
    #[cfg(not(windows))]
    const ABSOLUTE_WORKSPACE: &str = "/workspace";

    fn request() -> LocalTurnRequest {
        LocalTurnRequest {
            root_id: "root_1".to_string(),
            thread_id: None,
            message: "Inspect the workspace".to_string(),
        }
    }

    #[test]
    fn posture_mapping_never_turns_a_sandboxed_posture_into_full_access() {
        assert_eq!(ApprovalPosture::AlwaysAsk.policy().approval, "untrusted");
        assert_eq!(ApprovalPosture::RiskBased.policy().approval, "on-request");
        for posture in [ApprovalPosture::AlwaysAsk, ApprovalPosture::RiskBased] {
            assert_eq!(posture.policy().sandbox, "workspace-write");
        }
        let full = ApprovalPosture::FullAccess.policy();
        assert_eq!(
            (full.approval, full.sandbox),
            ("never", "danger-full-access")
        );
    }

    #[test]
    fn thread_request_is_local_persistent_and_policy_bound() {
        let value =
            thread_request(&request(), ApprovalPosture::RiskBased, ABSOLUTE_WORKSPACE).unwrap();
        assert_eq!(value["method"], "thread/start");
        assert_eq!(value["params"]["ephemeral"], false);
        assert_eq!(value["params"]["cwd"], ABSOLUTE_WORKSPACE);
        assert_eq!(value["params"]["approvalPolicy"], "on-request");
        assert_eq!(value["params"]["sandbox"], "workspace-write");
    }

    /// The guard the fixture above depends on, which nothing asserted.
    ///
    /// Worth having for its own sake - refusing a relative cwd is what stops a
    /// local agent being pointed at whatever directory the app happens to be
    /// running from - but also because it pins ABSOLUTE_WORKSPACE. Without this,
    /// a constant that drifted to a non-absolute value would surface as a
    /// confusing failure about missing JSON fields rather than about the
    /// workspace. Relative paths are non-absolute on every platform, so unlike
    /// the positive fixture this needs no cfg.
    #[test]
    fn thread_request_refuses_a_workspace_that_is_not_absolute() {
        assert!(std::path::Path::new(ABSOLUTE_WORKSPACE).is_absolute());
        for cwd in ["", "workspace", "./workspace", "../workspace"] {
            assert_eq!(
                thread_request(&request(), ApprovalPosture::RiskBased, cwd),
                Err("invalid_local_agent_workspace".to_string()),
                "cwd {cwd:?} must be refused",
            );
        }
    }

    #[test]
    fn malformed_inputs_and_unknown_server_requests_fail_closed() {
        let mut bad = request();
        bad.root_id = "root id".to_string();
        assert_eq!(
            bad.validate(),
            Err("invalid_local_agent_root_id".to_string())
        );
        let refused = refusal_response(&json!("approval-1"));
        assert_eq!(refused["id"], "approval-1");
        assert_eq!(refused["error"]["code"], -32601);
    }

    #[test]
    fn agent_message_items_carry_their_exact_phase_and_delta_owner() {
        let started = json!({
            "item": {
                "id": "message-1",
                "type": "agentMessage",
                "text": "",
                "phase": "commentary"
            }
        });
        assert_eq!(
            agent_message_identity(&started),
            Some(("message-1".to_string(), AgentMessagePhase::Commentary))
        );
        assert_eq!(
            delta_item_id(&json!({"itemId": "message-1"})),
            Some("message-1".to_string())
        );
        assert!(agent_message_identity(&json!({
            "item": {"id": "message-1", "type": "agentMessage", "phase": "invented"}
        }))
        .is_none());
    }
}
