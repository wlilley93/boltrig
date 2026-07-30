use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::Mutex;

use uuid::Uuid;

const MAX_MATERIALIZED_HANDLES: usize = 64;

#[derive(Debug)]
struct MaterializedArtifact {
    handle: String,
    path: PathBuf,
}

/// Paths selected by the user never cross into the webview. The webview gets
/// an opaque, process-local handle that can only reopen or reveal a file saved
/// during this app process.
#[derive(Debug, Default)]
pub(crate) struct MaterializedArtifacts {
    entries: Mutex<VecDeque<MaterializedArtifact>>,
}

impl MaterializedArtifacts {
    pub(crate) fn remember(&self, path: PathBuf) -> Result<String, String> {
        self.remember_as(Uuid::new_v4().to_string(), path)
    }

    fn remember_as(&self, handle: String, path: PathBuf) -> Result<String, String> {
        let mut entries = self
            .entries
            .lock()
            .map_err(|_| "artifact_registry_unavailable".to_string())?;
        entries.push_back(MaterializedArtifact {
            handle: handle.clone(),
            path,
        });
        while entries.len() > MAX_MATERIALIZED_HANDLES {
            entries.pop_front();
        }
        Ok(handle)
    }

    pub(crate) fn resolve(&self, handle: &str) -> Result<PathBuf, String> {
        if handle.len() != 36
            || !handle
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() || byte == b'-')
        {
            return Err("invalid_artifact_handle".to_string());
        }
        let entries = self
            .entries
            .lock()
            .map_err(|_| "artifact_registry_unavailable".to_string())?;
        let path = entries
            .iter()
            .find(|entry| entry.handle == handle)
            .map(|entry| entry.path.clone())
            .ok_or_else(|| "artifact_handle_not_found".to_string())?;
        if !path.is_file() {
            return Err("artifact_file_unavailable".to_string());
        }
        Ok(path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn handle(index: usize) -> String {
        format!("00000000-0000-4000-8000-{index:012x}")
    }

    #[test]
    fn registry_is_bounded_and_does_not_accept_a_path_as_a_handle() {
        let registry = MaterializedArtifacts::default();
        for index in 0..=MAX_MATERIALIZED_HANDLES {
            registry
                .remember_as(handle(index), PathBuf::from(format!("/tmp/{index}")))
                .unwrap();
        }
        assert_eq!(
            registry.resolve("/tmp/64").unwrap_err(),
            "invalid_artifact_handle"
        );
        assert_eq!(
            registry.resolve(&handle(0)).unwrap_err(),
            "artifact_handle_not_found"
        );
    }

    #[test]
    fn absent_and_malformed_handles_fail_closed() {
        let registry = MaterializedArtifacts::default();
        assert_eq!(
            registry.resolve("not-a-handle").unwrap_err(),
            "invalid_artifact_handle"
        );
        assert_eq!(
            registry.resolve(&handle(1)).unwrap_err(),
            "artifact_handle_not_found"
        );
    }

    #[test]
    fn a_handle_resolves_only_while_its_materialized_file_exists() {
        let path = std::env::temp_dir().join(format!("boltrig-artifact-{}", Uuid::new_v4()));
        std::fs::write(&path, b"authorized artifact").unwrap();
        let registry = MaterializedArtifacts::default();
        let artifact_handle = registry.remember(path.clone()).unwrap();
        assert_eq!(registry.resolve(&artifact_handle).unwrap(), path);
        std::fs::remove_file(&path).unwrap();
        assert_eq!(
            registry.resolve(&artifact_handle).unwrap_err(),
            "artifact_file_unavailable"
        );
    }
}
