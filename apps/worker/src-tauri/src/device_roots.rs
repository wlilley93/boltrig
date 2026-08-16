use std::collections::VecDeque;
use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::process::Stdio;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tauri::AppHandle;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tokio::process::Command;

use crate::device_protocol::{DeviceLease, ValidatedAction};
use crate::session::{valid_identifier, KEYRING_SERVICE};

const ROOT_VERSION: u8 = 1;
const MAX_PAYLOAD_BYTES: usize = 100 * 1024 * 1024;
const MAX_BUFFERED_BYTES: usize = 200 * 1024 * 1024;
const MAX_BUFFERED_ITEMS: usize = 4;
const MAX_DIRECTORY_SCAN_ENTRIES: usize = 2_000;
const MAX_DIRECTORY_METADATA_BYTES: usize = 10 * 1024;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct NativeRoot {
    version: u8,
    api_origin: String,
    device_id: String,
    root_id: String,
    path: String,
    scope: String,
    command_enabled: bool,
}

#[derive(Debug, Serialize)]
pub(crate) struct NativeRootView {
    pub(crate) root_id: String,
    pub(crate) scope: String,
    pub(crate) command_enabled: bool,
}

#[derive(Debug)]
pub(crate) struct ExecutionOutcome {
    pub(crate) status: &'static str,
    pub(crate) receipt: Value,
}

#[derive(Debug)]
struct BufferedBytes {
    id: String,
    bytes: Vec<u8>,
}

#[derive(Debug, Default)]
struct ByteQueue {
    entries: VecDeque<BufferedBytes>,
    total_bytes: usize,
}

#[derive(Debug, Default)]
pub(crate) struct DeviceBuffers {
    writes: Mutex<ByteQueue>,
    reads: Mutex<ByteQueue>,
}

impl DeviceBuffers {
    pub(crate) fn clear(&self) -> Result<(), String> {
        for queue in [&self.writes, &self.reads] {
            let mut queue = queue
                .lock()
                .map_err(|_| "device_buffer_unavailable".to_string())?;
            queue.entries.clear();
            queue.total_bytes = 0;
        }
        Ok(())
    }

    pub(crate) fn stage_write(
        &self,
        content_digest: &str,
        bytes: Vec<u8>,
    ) -> Result<NativePayloadView, String> {
        if bytes.len() > MAX_PAYLOAD_BYTES
            || content_digest.len() != 64
            || hex::encode(Sha256::digest(&bytes)) != content_digest
        {
            return Err("write_payload_digest_mismatch".to_string());
        }
        insert_bytes(&self.writes, content_digest.to_string(), bytes)?;
        Ok(NativePayloadView {
            content_digest: content_digest.to_string(),
            byte_size: self.write_size(content_digest)?,
        })
    }

    fn write_size(&self, digest: &str) -> Result<usize, String> {
        let queue = self
            .writes
            .lock()
            .map_err(|_| "device_buffer_unavailable".to_string())?;
        queue
            .entries
            .iter()
            .find(|item| item.id == digest)
            .map(|item| item.bytes.len())
            .ok_or_else(|| "write_payload_unavailable".to_string())
    }

    fn take_write(&self, digest: &str, size: u64) -> Result<Vec<u8>, String> {
        let mut queue = self
            .writes
            .lock()
            .map_err(|_| "device_buffer_unavailable".to_string())?;
        let index = queue
            .entries
            .iter()
            .position(|item| item.id == digest)
            .ok_or_else(|| "write_payload_unavailable".to_string())?;
        if queue.entries[index].bytes.len() as u64 != size {
            return Err("write_payload_size_mismatch".to_string());
        }
        let item = queue
            .entries
            .remove(index)
            .ok_or_else(|| "write_payload_unavailable".to_string())?;
        queue.total_bytes = queue.total_bytes.saturating_sub(item.bytes.len());
        Ok(item.bytes)
    }

    fn remember_read(&self, lease_id: String, bytes: Vec<u8>) -> Result<(), String> {
        insert_bytes(&self.reads, lease_id, bytes)
    }

    pub(crate) fn take_read(&self, lease_id: &str) -> Result<Option<Vec<u8>>, String> {
        if !valid_identifier(lease_id) {
            return Err("invalid_lease_id".to_string());
        }
        let mut queue = self
            .reads
            .lock()
            .map_err(|_| "device_buffer_unavailable".to_string())?;
        let Some(index) = queue.entries.iter().position(|item| item.id == lease_id) else {
            return Ok(None);
        };
        let item = queue
            .entries
            .remove(index)
            .ok_or_else(|| "read_result_unavailable".to_string())?;
        queue.total_bytes = queue.total_bytes.saturating_sub(item.bytes.len());
        Ok(Some(item.bytes))
    }
}

#[derive(Debug, Serialize)]
pub(crate) struct NativePayloadView {
    pub(crate) content_digest: String,
    pub(crate) byte_size: usize,
}

fn insert_bytes(queue: &Mutex<ByteQueue>, id: String, bytes: Vec<u8>) -> Result<(), String> {
    let mut queue = queue
        .lock()
        .map_err(|_| "device_buffer_unavailable".to_string())?;
    if let Some(index) = queue.entries.iter().position(|item| item.id == id) {
        let old = queue
            .entries
            .remove(index)
            .ok_or_else(|| "device_buffer_unavailable".to_string())?;
        queue.total_bytes = queue.total_bytes.saturating_sub(old.bytes.len());
    }
    queue.total_bytes = queue
        .total_bytes
        .checked_add(bytes.len())
        .ok_or_else(|| "device_buffer_full".to_string())?;
    queue.entries.push_back(BufferedBytes { id, bytes });
    while queue.entries.len() > MAX_BUFFERED_ITEMS || queue.total_bytes > MAX_BUFFERED_BYTES {
        let removed = queue
            .entries
            .pop_front()
            .ok_or_else(|| "device_buffer_unavailable".to_string())?;
        queue.total_bytes = queue.total_bytes.saturating_sub(removed.bytes.len());
    }
    Ok(())
}

fn root_account(origin: &str, device_id: &str, root_id: &str) -> String {
    let digest = Sha256::digest(format!("{origin}\0{device_id}\0{root_id}"));
    format!("device-root-{}", hex::encode(digest))
}

fn root_entry(origin: &str, device_id: &str, root_id: &str) -> Result<keyring::Entry, String> {
    keyring::Entry::new(KEYRING_SERVICE, &root_account(origin, device_id, root_id))
        .map_err(|_| "os_keychain_unavailable".to_string())
}

pub(crate) fn store_root(root: &NativeRoot) -> Result<(), String> {
    validate_root(root)?;
    let encoded =
        serde_json::to_string(root).map_err(|_| "device_root_encode_failed".to_string())?;
    root_entry(&root.api_origin, &root.device_id, &root.root_id)?
        .set_password(&encoded)
        .map_err(|_| "os_keychain_write_failed".to_string())
}

pub(crate) fn load_root(
    origin: &str,
    device_id: &str,
    root_id: &str,
) -> Result<Option<NativeRoot>, String> {
    if !valid_identifier(device_id) || !valid_identifier(root_id) {
        return Err("invalid_device_root".to_string());
    }
    match root_entry(origin, device_id, root_id)?.get_password() {
        Ok(encoded) => {
            let root: NativeRoot = serde_json::from_str(&encoded)
                .map_err(|_| "device_root_rebind_required".to_string())?;
            validate_root(&root)?;
            if root.api_origin != origin || root.device_id != device_id || root.root_id != root_id {
                return Err("device_root_binding_mismatch".to_string());
            }
            Ok(Some(root))
        }
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(_) => Err("os_keychain_read_failed".to_string()),
    }
}

/// Resolve the native workspace for the private desktop agent. This is not the
/// remote lease executor: it merely reuses the user's enrolled, opaque root
/// binding as the only lawful way to choose a local App Server cwd.
pub(crate) fn local_agent_workspace(
    origin: &str,
    device_id: &str,
    root_id: &str,
) -> Result<PathBuf, String> {
    let root = load_root(origin, device_id, root_id)?
        .ok_or_else(|| "local_agent_root_unbound".to_string())?;
    if root.scope != "read_write" || !root.command_enabled {
        return Err("local_agent_root_not_enabled".to_string());
    }
    verified_root_path(&root)
}

pub(crate) fn delete_root(origin: &str, device_id: &str, root_id: &str) -> Result<(), String> {
    match root_entry(origin, device_id, root_id)?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(_) => Err("os_keychain_delete_failed".to_string()),
    }
}

pub(crate) fn new_root(
    origin: String,
    device_id: String,
    root_id: String,
    path: PathBuf,
    scope: String,
    command_enabled: bool,
) -> Result<NativeRoot, String> {
    let canonical = path
        .canonicalize()
        .map_err(|_| "device_root_unavailable".to_string())?;
    if !canonical.is_dir() {
        return Err("device_root_not_directory".to_string());
    }
    let path = canonical
        .to_str()
        .ok_or_else(|| "device_root_path_not_unicode".to_string())?
        .to_string();
    let root = NativeRoot {
        version: ROOT_VERSION,
        api_origin: origin,
        device_id,
        root_id,
        path,
        scope,
        command_enabled,
    };
    validate_root(&root)?;
    Ok(root)
}

fn validate_root(root: &NativeRoot) -> Result<(), String> {
    if root.version != ROOT_VERSION
        || !valid_identifier(&root.device_id)
        || !valid_identifier(&root.root_id)
        || !matches!(root.scope.as_str(), "read" | "read_write")
        || root.path.is_empty()
        || root.path.len() > 4096
        || !Path::new(&root.path).is_absolute()
    {
        return Err("invalid_device_root".to_string());
    }
    Ok(())
}

pub(crate) async fn execute(
    app: &AppHandle,
    buffers: &DeviceBuffers,
    root: &NativeRoot,
    lease: &DeviceLease,
    action: ValidatedAction,
) -> ExecutionOutcome {
    let result = match action {
        ValidatedAction::List {
            relative_path,
            max_entries,
        } => execute_list(root, relative_path, max_entries).await,
        ValidatedAction::Read {
            relative_path,
            max_bytes,
        } => execute_read(buffers, root, lease, relative_path, max_bytes).await,
        ValidatedAction::Write {
            relative_path,
            content_digest,
            byte_size,
            overwrite,
        } => {
            execute_write(
                buffers,
                root,
                relative_path,
                content_digest,
                byte_size,
                overwrite,
            )
            .await
        }
        ValidatedAction::Command {
            argv,
            cwd_relative,
            timeout_seconds,
        } => execute_command(app, root, argv, cwd_relative, timeout_seconds).await,
    };
    match result {
        Ok(receipt) => ExecutionOutcome {
            status: "completed",
            receipt,
        },
        Err(code) => ExecutionOutcome {
            status: "failed",
            receipt: json!({"code": code}),
        },
    }
}

async fn execute_list(
    root: &NativeRoot,
    relative_path: Option<String>,
    max_entries: usize,
) -> Result<Value, String> {
    let root_path = verified_root_path(root)?;
    tokio::task::spawn_blocking(move || {
        let directory = match relative_path {
            Some(relative) => resolve_existing(&root_path, &relative, true)?,
            None => root_path.clone(),
        };
        let mut entries = Vec::new();
        let mut scanned = 0_usize;
        let mut truncated = false;
        let reader =
            std::fs::read_dir(directory).map_err(|_| "directory_list_failed".to_string())?;
        for item in reader {
            if scanned >= MAX_DIRECTORY_SCAN_ENTRIES {
                truncated = true;
                break;
            }
            scanned += 1;
            let item = item.map_err(|_| "directory_list_failed".to_string())?;
            let name = match item.file_name().into_string() {
                Ok(name) if safe_leaf_name(&name) => name,
                _ => {
                    truncated = true;
                    continue;
                }
            };
            let item_path = item.path();
            let metadata = std::fs::symlink_metadata(&item_path)
                .map_err(|_| "directory_list_failed".to_string())?;
            let (kind, byte_size) = if metadata.file_type().is_symlink() {
                ("symlink", None)
            } else if metadata.is_dir() {
                ("directory", None)
            } else if metadata.is_file() {
                if metadata.len() > 9_007_199_254_740_991 {
                    truncated = true;
                    continue;
                }
                ("file", Some(metadata.len()))
            } else {
                truncated = true;
                continue;
            };
            let relative = item_path
                .strip_prefix(&root_path)
                .map_err(|_| "root_relative_target_refused".to_string())?
                .to_str()
                .ok_or_else(|| "directory_entry_not_unicode".to_string())?
                .replace(std::path::MAIN_SEPARATOR, "/");
            reject_relative(&relative)?;
            if relative.len() > 1024 {
                truncated = true;
                continue;
            }
            entries.push(json!({
                "name": name,
                "path": relative,
                "kind": kind,
                "byte_size": byte_size,
            }));
        }
        entries.sort_by(|left, right| {
            left.get("name")
                .and_then(Value::as_str)
                .cmp(&right.get("name").and_then(Value::as_str))
        });
        let mut bounded = Vec::new();
        let mut metadata_bytes = 0_usize;
        for entry in entries {
            let name_bytes = entry
                .get("name")
                .and_then(Value::as_str)
                .map(str::len)
                .unwrap_or(0);
            let path_bytes = entry
                .get("path")
                .and_then(Value::as_str)
                .map(str::len)
                .unwrap_or(0);
            let entry_bytes = name_bytes.saturating_add(path_bytes).saturating_add(64);
            if bounded.len() >= max_entries
                || metadata_bytes.saturating_add(entry_bytes) > MAX_DIRECTORY_METADATA_BYTES
            {
                truncated = true;
                break;
            }
            metadata_bytes = metadata_bytes.saturating_add(entry_bytes);
            bounded.push(entry);
        }
        Ok(json!({"entries": bounded, "truncated": truncated}))
    })
    .await
    .map_err(|_| "device_io_task_failed".to_string())?
}

async fn execute_read(
    buffers: &DeviceBuffers,
    root: &NativeRoot,
    lease: &DeviceLease,
    relative_path: String,
    max_bytes: u64,
) -> Result<Value, String> {
    let root_path = verified_root_path(root)?;
    let bytes = tokio::task::spawn_blocking(move || {
        let path = resolve_existing(&root_path, &relative_path, false)?;
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.custom_flags(libc::O_NOFOLLOW);
        }
        let file = options
            .open(path)
            .map_err(|_| "file_read_failed".to_string())?;
        let mut bytes = Vec::new();
        file.take(max_bytes + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| "file_read_failed".to_string())?;
        if bytes.len() as u64 > max_bytes {
            return Err("file_exceeds_approved_limit".to_string());
        }
        Ok(bytes)
    })
    .await
    .map_err(|_| "device_io_task_failed".to_string())??;
    let digest = hex::encode(Sha256::digest(&bytes));
    let byte_size = bytes.len();
    buffers.remember_read(lease.id.clone(), bytes)?;
    Ok(json!({
        "byte_size": byte_size,
        "content_digest": digest,
        "local_result_available": true,
    }))
}

async fn execute_write(
    buffers: &DeviceBuffers,
    root: &NativeRoot,
    relative_path: String,
    content_digest: String,
    byte_size: u64,
    overwrite: bool,
) -> Result<Value, String> {
    if root.scope != "read_write" {
        return Err("root_is_read_only".to_string());
    }
    let bytes = buffers.take_write(&content_digest, byte_size)?;
    if hex::encode(Sha256::digest(&bytes)) != content_digest {
        return Err("write_payload_digest_mismatch".to_string());
    }
    let root_path = verified_root_path(root)?;
    tokio::task::spawn_blocking(move || {
        let path = resolve_write_target(&root_path, &relative_path)?;
        let mut options = OpenOptions::new();
        options.write(true);
        if overwrite {
            options.create(true).truncate(true);
        } else {
            options.create_new(true);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.custom_flags(libc::O_NOFOLLOW);
        }
        let mut file = options
            .open(path)
            .map_err(|_| "file_write_failed".to_string())?;
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| "file_write_failed".to_string())
    })
    .await
    .map_err(|_| "device_io_task_failed".to_string())??;
    Ok(json!({
        "byte_size": byte_size,
        "content_digest": content_digest,
        "overwrite": overwrite,
    }))
}

async fn execute_command(
    app: &AppHandle,
    root: &NativeRoot,
    argv: Vec<String>,
    cwd_relative: Option<String>,
    timeout_seconds: u64,
) -> Result<Value, String> {
    if !root.command_enabled {
        return Err("command_disabled".to_string());
    }
    let root_path = verified_root_path(root)?;
    let cwd = match cwd_relative {
        Some(relative) => resolve_existing(&root_path, &relative, true)?,
        None => root_path,
    };
    let executable = resolve_executable(&argv[0])?;
    let prompt = format!(
        "Run this signed, individually approved command?\n\n{}",
        display_argv(&argv)
    );
    let approved = app
        .dialog()
        .message(prompt)
        .title("Boltrig command approval")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::YesNo)
        .blocking_show();
    if !approved {
        return Err("native_command_declined".to_string());
    }
    let started = Instant::now();
    let mut command = Command::new(executable);
    command
        .args(&argv[1..])
        .current_dir(cwd)
        .env_clear()
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    let mut child = command
        .spawn()
        .map_err(|_| "command_spawn_failed".to_string())?;
    let status =
        match tokio::time::timeout(Duration::from_secs(timeout_seconds), child.wait()).await {
            Ok(result) => result.map_err(|_| "command_wait_failed".to_string())?,
            Err(_) => {
                let _ = child.kill().await;
                let _ = child.wait().await;
                return Err("command_timed_out".to_string());
            }
        };
    let duration_ms = started.elapsed().as_millis().min(u64::MAX as u128) as u64;
    if !status.success() {
        return Err("command_failed".to_string());
    }
    Ok(json!({
        "duration_ms": duration_ms,
        "exit_code": status.code(),
        "output_captured": false,
    }))
}

fn verified_root_path(root: &NativeRoot) -> Result<PathBuf, String> {
    validate_root(root)?;
    let stored = PathBuf::from(&root.path);
    let canonical = stored
        .canonicalize()
        .map_err(|_| "device_root_unavailable".to_string())?;
    if canonical != stored || !canonical.is_dir() {
        return Err("device_root_rebind_required".to_string());
    }
    Ok(canonical)
}

fn resolve_existing(root: &Path, relative: &str, directory: bool) -> Result<PathBuf, String> {
    reject_relative(relative)?;
    let mut current = root.to_path_buf();
    for component in Path::new(relative).components() {
        let Component::Normal(part) = component else {
            return Err("invalid_relative_path".to_string());
        };
        current.push(part);
        let metadata = std::fs::symlink_metadata(&current)
            .map_err(|_| "root_relative_target_unavailable".to_string())?;
        if metadata.file_type().is_symlink() {
            return Err("root_relative_symlink_refused".to_string());
        }
    }
    let canonical = current
        .canonicalize()
        .map_err(|_| "root_relative_target_unavailable".to_string())?;
    if !canonical.starts_with(root)
        || (directory && !canonical.is_dir())
        || (!directory && !canonical.is_file())
    {
        return Err("root_relative_target_refused".to_string());
    }
    Ok(canonical)
}

fn resolve_write_target(root: &Path, relative: &str) -> Result<PathBuf, String> {
    reject_relative(relative)?;
    let path = Path::new(relative);
    let leaf = path
        .file_name()
        .ok_or_else(|| "invalid_relative_path".to_string())?;
    let parent = path.parent().unwrap_or_else(|| Path::new(""));
    let canonical_parent = if parent.as_os_str().is_empty() {
        root.to_path_buf()
    } else {
        resolve_existing(
            root,
            parent
                .to_str()
                .ok_or_else(|| "invalid_relative_path".to_string())?,
            true,
        )?
    };
    let target = canonical_parent.join(leaf);
    if let Ok(metadata) = std::fs::symlink_metadata(&target) {
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err("root_relative_target_refused".to_string());
        }
    }
    if !target.starts_with(root) {
        return Err("root_relative_target_refused".to_string());
    }
    Ok(target)
}

fn reject_relative(value: &str) -> Result<(), String> {
    if value.is_empty()
        || value.contains('\\')
        || value.contains('\0')
        || Path::new(value).is_absolute()
        || value
            .split('/')
            .any(|part| part.is_empty() || matches!(part, "." | ".."))
    {
        return Err("invalid_relative_path".to_string());
    }
    Ok(())
}

fn safe_leaf_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 255
        && !name.contains('/')
        && !name.contains('\\')
        && !name.chars().any(char::is_control)
}

fn resolve_executable(program: &str) -> Result<PathBuf, String> {
    if program.is_empty() || program.contains('\0') {
        return Err("invalid_command_executable".to_string());
    }
    let requested = Path::new(program);
    let resolved = if requested.is_absolute() {
        requested
            .canonicalize()
            .map_err(|_| "command_executable_unavailable".to_string())?
    } else {
        if requested.components().count() != 1 {
            return Err("invalid_command_executable".to_string());
        }
        let path =
            std::env::var_os("PATH").ok_or_else(|| "command_executable_unavailable".to_string())?;
        std::env::split_paths(&path)
            .filter(|directory| directory.is_absolute())
            .map(|directory| directory.join(requested))
            .find(|candidate| candidate.is_file())
            .ok_or_else(|| "command_executable_unavailable".to_string())?
            .canonicalize()
            .map_err(|_| "command_executable_unavailable".to_string())?
    };
    if !resolved.is_file() {
        return Err("command_executable_unavailable".to_string());
    }
    if is_shell_executable(&resolved) {
        return Err("command_shell_refused".to_string());
    }
    Ok(resolved)
}

fn is_shell_executable(path: &Path) -> bool {
    path.file_name()
        .and_then(|name| name.to_str())
        .map(|name| {
            matches!(
                name.to_ascii_lowercase().as_str(),
                "bash"
                    | "cmd"
                    | "cmd.exe"
                    | "command.com"
                    | "dash"
                    | "fish"
                    | "ksh"
                    | "powershell"
                    | "powershell.exe"
                    | "pwsh"
                    | "sh"
                    | "tcsh"
                    | "zsh"
            )
        })
        .unwrap_or(true)
}

fn display_argv(argv: &[String]) -> String {
    let mut display = argv
        .iter()
        .map(|argument| format!("{argument:?}"))
        .collect::<Vec<_>>()
        .join(" ");
    if display.len() > 2000 {
        display.truncate(2000);
        display.push('…');
    }
    display
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    fn temp_root() -> PathBuf {
        let path = std::env::temp_dir().join(format!("boltrig-root-{}", Uuid::new_v4()));
        std::fs::create_dir_all(&path).unwrap();
        path.canonicalize().unwrap()
    }

    fn native_root(path: &Path, scope: &str) -> NativeRoot {
        NativeRoot {
            version: ROOT_VERSION,
            api_origin: "https://kernel.boltrig.io".to_string(),
            device_id: "device_1".to_string(),
            root_id: "root_1".to_string(),
            path: path.to_str().unwrap().to_string(),
            scope: scope.to_string(),
            command_enabled: false,
        }
    }

    #[test]
    fn strict_root_resolution_rejects_traversal_and_symlink_escape() {
        let root = temp_root();
        std::fs::write(root.join("safe.txt"), b"safe").unwrap();
        assert_eq!(
            resolve_existing(&root, "safe.txt", false).unwrap(),
            root.join("safe.txt")
        );
        assert!(resolve_existing(&root, "../outside", false).is_err());
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink("/etc/passwd", root.join("escape")).unwrap();
            assert_eq!(
                resolve_existing(&root, "escape", false).unwrap_err(),
                "root_relative_symlink_refused"
            );
        }
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn write_and_read_buffers_are_digest_bound_bounded_and_single_take() {
        let buffers = DeviceBuffers::default();
        let bytes = b"approved bytes".to_vec();
        let digest = hex::encode(Sha256::digest(&bytes));
        assert!(buffers.stage_write(&"0".repeat(64), bytes.clone()).is_err());
        assert_eq!(
            buffers
                .stage_write(&digest, bytes.clone())
                .unwrap()
                .byte_size,
            bytes.len()
        );
        assert_eq!(
            buffers.take_write(&digest, bytes.len() as u64).unwrap(),
            bytes
        );
        assert!(buffers.take_write(&digest, 14).is_err());
        buffers
            .remember_read("lease_1".to_string(), b"result".to_vec())
            .unwrap();
        assert_eq!(
            buffers.take_read("lease_1").unwrap(),
            Some(b"result".to_vec())
        );
        assert_eq!(buffers.take_read("lease_1").unwrap(), None);
        buffers
            .stage_write(&digest, b"approved bytes".to_vec())
            .unwrap();
        buffers.clear().unwrap();
        assert!(buffers.take_write(&digest, bytes.len() as u64).is_err());
    }

    #[test]
    fn executable_resolution_never_uses_the_working_directory() {
        let root = temp_root();
        std::fs::write(root.join("git"), b"not executable").unwrap();
        let resolved = resolve_executable("git");
        if let Ok(path) = resolved {
            assert!(!path.starts_with(&root));
            assert!(path.is_absolute());
        }
        assert!(resolve_executable("./git").is_err());
        assert!(is_shell_executable(Path::new("/bin/sh")));
        assert!(is_shell_executable(Path::new("cmd.exe")));
        std::fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn directory_metadata_is_bounded_sorted_and_never_follows_symlinks() {
        let path = temp_root();
        std::fs::create_dir(path.join("folder")).unwrap();
        std::fs::write(path.join("alpha.txt"), b"alpha").unwrap();
        std::fs::write(path.join("zeta.txt"), b"zeta").unwrap();
        #[cfg(unix)]
        std::os::unix::fs::symlink("/etc/passwd", path.join("escape")).unwrap();

        let complete = execute_list(&native_root(&path, "read"), None, 100)
            .await
            .unwrap();
        let entries = complete["entries"].as_array().unwrap();
        let names = entries
            .iter()
            .map(|entry| entry["name"].as_str().unwrap())
            .collect::<Vec<_>>();
        assert!(names.windows(2).all(|pair| pair[0] <= pair[1]));
        let alpha = entries
            .iter()
            .find(|entry| entry["name"] == "alpha.txt")
            .unwrap();
        assert_eq!(alpha["kind"], "file");
        assert_eq!(alpha["byte_size"], 5);
        #[cfg(unix)]
        {
            let escape = entries
                .iter()
                .find(|entry| entry["name"] == "escape")
                .unwrap();
            assert_eq!(escape["kind"], "symlink");
            assert!(escape["byte_size"].is_null());
            assert_eq!(
                execute_list(&native_root(&path, "read"), Some("escape".to_string()), 10,)
                    .await
                    .unwrap_err(),
                "root_relative_symlink_refused"
            );
        }

        let bounded = execute_list(&native_root(&path, "read"), None, 1)
            .await
            .unwrap();
        assert_eq!(bounded["entries"].as_array().unwrap().len(), 1);
        assert_eq!(bounded["truncated"], true);
        std::fs::remove_dir_all(path).unwrap();
    }

    #[tokio::test]
    async fn writes_require_a_digest_bound_buffer_and_a_read_write_root() {
        let path = temp_root();
        let buffers = DeviceBuffers::default();
        let bytes = b"exact approved payload".to_vec();
        let digest = hex::encode(Sha256::digest(&bytes));
        buffers.stage_write(&digest, bytes.clone()).unwrap();
        assert_eq!(
            execute_write(
                &buffers,
                &native_root(&path, "read"),
                "output.txt".to_string(),
                digest.clone(),
                bytes.len() as u64,
                false,
            )
            .await
            .unwrap_err(),
            "root_is_read_only"
        );
        assert_eq!(
            buffers.take_write(&digest, bytes.len() as u64).unwrap(),
            bytes
        );
        buffers
            .stage_write(&digest, b"exact approved payload".to_vec())
            .unwrap();
        execute_write(
            &buffers,
            &native_root(&path, "read_write"),
            "output.txt".to_string(),
            digest.clone(),
            22,
            false,
        )
        .await
        .unwrap();
        assert_eq!(
            std::fs::read(path.join("output.txt")).unwrap(),
            b"exact approved payload"
        );
        assert!(buffers.take_write(&digest, 22).is_err());
        std::fs::remove_dir_all(path).unwrap();
    }
}
