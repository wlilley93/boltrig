//! Native, read-only camera inventory and hotplug status.
//!
//! macOS discovery uses AVFoundation to enumerate video devices without
//! requesting permission and without opening a capture session.  The bridge
//! intentionally does not claim UVC PTZ, privacy, HID, or snapshot proof.
//! Those capabilities require separate evidence and stay unproven here.

use std::collections::BTreeMap;
use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter, Manager};
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;

use crate::camera_protocol::{verify_lease, CameraLease, ValidatedCameraAction};
use crate::session::LeaseVerifier;

#[cfg(target_os = "macos")]
unsafe extern "C" {
    fn boltrig_camera_inventory_json() -> *mut c_char;
    fn boltrig_camera_inventory_free(value: *mut c_char);
    fn boltrig_uvc_inventory_json() -> *mut c_char;
    fn boltrig_uvc_ptz_json(
        descriptor_fingerprint: *const c_char,
        operation: *const c_char,
        pan: i64,
        tilt: i64,
    ) -> *mut c_char;
    fn boltrig_uvc_capture_json(descriptor_fingerprint: *const c_char) -> *mut c_char;
    fn boltrig_uvc_json_free(value: *mut c_char);
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeInventory {
    schema_version: u8,
    runtime: String,
    state: String,
    reason: Option<String>,
    cameras: Vec<NativeCamera>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeCamera {
    native_key: String,
    #[serde(default)]
    descriptor_fingerprint: Option<String>,
    label: String,
    model: String,
    #[serde(default)]
    manufacturer: Option<String>,
    permission: String,
    format_count: u32,
    #[serde(default)]
    transport: Option<String>,
    #[serde(default)]
    controls: Value,
    #[serde(default)]
    vid: u16,
    #[serde(default)]
    pid: u16,
    #[serde(default)]
    uvc_interface: u8,
    #[serde(default)]
    terminal_id: u8,
    #[serde(default)]
    uvc_version: String,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub(crate) struct CameraCapability {
    pub(crate) state: String,
    pub(crate) source: String,
    pub(crate) evidence: Vec<String>,
    pub(crate) reason: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub(crate) struct CameraView {
    pub(crate) camera_id: String,
    pub(crate) descriptor_fingerprint: String,
    pub(crate) label: String,
    pub(crate) manufacturer: Option<String>,
    pub(crate) product: String,
    pub(crate) transport: String,
    pub(crate) connection_state: String,
    pub(crate) permission: String,
    pub(crate) format_count: u32,
    pub(crate) capabilities: BTreeMap<String, CameraCapability>,
    pub(crate) interfaces: Vec<String>,
    pub(crate) warnings: Vec<String>,
    pub(crate) allowed_verbs: Vec<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub(crate) struct CameraDiscoveryStatus {
    pub(crate) schema_version: u8,
    pub(crate) state: String,
    pub(crate) runtime: String,
    pub(crate) cameras: Vec<CameraView>,
    pub(crate) refreshed_at: String,
    pub(crate) reason: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub(crate) struct CameraVerification {
    pub(crate) camera_id: String,
    pub(crate) kind: String,
    pub(crate) state: String,
    pub(crate) control_mechanism: String,
    pub(crate) capture_attempted: bool,
    pub(crate) writes_attempted: bool,
    pub(crate) hid_reports_sent: bool,
    pub(crate) evidence: Vec<String>,
    pub(crate) errors: Vec<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub(crate) struct CameraLeaseValidation {
    pub(crate) camera_id: String,
    pub(crate) verb: String,
    pub(crate) state: String,
    pub(crate) action_digest: String,
    pub(crate) writes_allowed: bool,
    pub(crate) reason: String,
}

const MAX_NATIVE_RESULT_BYTES: usize = 64 * 1024;
const UVC_MILLIDEGREES_PER_UNIT: i64 = 10;
const MAX_UVC_ANGLE: i64 = i32::MAX as i64;

pub(crate) struct CameraRuntime {
    current: Mutex<Option<CameraDiscoveryStatus>>,
    proven_ptz: Mutex<BTreeMap<String, bool>>,
}

impl CameraRuntime {
    pub(crate) fn new() -> Self {
        Self {
            current: Mutex::new(None),
            proven_ptz: Mutex::new(BTreeMap::new()),
        }
    }

    pub(crate) fn refresh(&self) -> Result<CameraDiscoveryStatus, String> {
        let raw = native_inventory_json()?;
        let inventory: NativeInventory = serde_json::from_str(&raw)
            .map_err(|_| "invalid_native_camera_inventory".to_string())?;
        let status = project_inventory(inventory)?;
        let proven = self
            .proven_ptz
            .lock()
            .map_err(|_| "camera_runtime_poisoned".to_string())?
            .clone();
        let mut status = status;
        for camera in &mut status.cameras {
            if proven.get(&camera.camera_id).copied().unwrap_or(false) {
                for axis in ["pan", "tilt"] {
                    if let Some(capability) = camera.capabilities.get_mut(axis) {
                        capability.state = "proven".to_string();
                        if !capability.evidence.iter().any(|item| {
                            item == "bounded_uvc_set_readback_frame_change_and_exact_restoration"
                        }) {
                            capability.evidence.push(
                                "bounded_uvc_set_readback_frame_change_and_exact_restoration"
                                    .to_string(),
                            );
                        }
                        capability.reason = Some(
                            "bounded_uvc_set_readback_frame_change_and_exact_restoration"
                                .to_string(),
                        );
                    }
                }
                if !camera
                    .allowed_verbs
                    .iter()
                    .any(|verb| verb == "camera.ptz.set")
                {
                    camera.allowed_verbs.push("camera.ptz.set".to_string());
                }
            }
        }
        *self
            .current
            .lock()
            .map_err(|_| "camera_runtime_poisoned".to_string())? = Some(status.clone());
        Ok(status)
    }

    pub(crate) fn status(&self) -> Result<CameraDiscoveryStatus, String> {
        if let Some(status) = self
            .current
            .lock()
            .map_err(|_| "camera_runtime_poisoned".to_string())?
            .clone()
        {
            return Ok(status);
        }
        self.refresh()
    }

    pub(crate) fn verify_snapshot(&self, camera_id: &str) -> Result<CameraVerification, String> {
        let status = self.status()?;
        let camera = find_camera(&status.cameras, camera_id)?;
        if camera.permission != "authorized" {
            return Ok(CameraVerification {
                camera_id: camera_id.to_string(),
                kind: "snapshot".to_string(),
                state: "permission_required".to_string(),
                control_mechanism: "none".to_string(),
                capture_attempted: false,
                writes_attempted: false,
                hid_reports_sent: false,
                evidence: vec!["avfoundation_device_enumerated".to_string()],
                errors: vec!["camera_permission_not_authorized".to_string()],
            });
        }
        let result = self.capture(camera_id)?;
        if result.get("ok") != Some(&Value::Bool(true)) {
            return Ok(CameraVerification {
                camera_id: camera_id.to_string(),
                kind: "snapshot".to_string(),
                state: "unproven".to_string(),
                control_mechanism: "avfoundation_bounded_one_frame".to_string(),
                capture_attempted: result
                    .get("capture_attempted")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
                writes_attempted: false,
                hid_reports_sent: false,
                evidence: vec!["avfoundation_device_enumerated".to_string()],
                errors: vec!["bounded_one_frame_capture_failed".to_string()],
            });
        }
        Ok(CameraVerification {
            camera_id: camera_id.to_string(),
            kind: "snapshot".to_string(),
            state: "proven".to_string(),
            control_mechanism: "avfoundation_bounded_one_frame".to_string(),
            capture_attempted: true,
            writes_attempted: false,
            hid_reports_sent: false,
            evidence: vec![
                "avfoundation_device_enumerated".to_string(),
                "bounded_one_frame_captured_and_discarded".to_string(),
                "frame_digest_recorded_without_frame_persistence".to_string(),
            ],
            errors: Vec::new(),
        })
    }

    pub(crate) fn verify_ptz(&self, camera_id: &str) -> Result<CameraVerification, String> {
        let result = self.ptz_get(camera_id)?;
        if result.get("ok") != Some(&Value::Bool(true)) {
            let errors = result
                .get("errors")
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|item| item.get("error").and_then(Value::as_str))
                        .map(str::to_string)
                        .collect::<Vec<_>>()
                })
                .filter(|items| !items.is_empty())
                .unwrap_or_else(|| vec!["standard_uvc_ptz_read_failed".to_string()]);
            return Ok(CameraVerification {
                camera_id: camera_id.to_string(),
                kind: "ptz".to_string(),
                state: "unproven".to_string(),
                control_mechanism: "standard_uvc_camera_terminal_pan_tilt_absolute".to_string(),
                capture_attempted: false,
                writes_attempted: false,
                hid_reports_sent: false,
                evidence: vec!["standard_uvc_camera_terminal_identified".to_string()],
                errors,
            });
        }
        let advertised = result
            .get("advertised_millidegrees")
            .and_then(Value::as_object)
            .ok_or_else(|| "standard_uvc_ptz_readback_incomplete".to_string())?;
        let original = advertised
            .get("current")
            .and_then(pair_from_value)
            .ok_or_else(|| "standard_uvc_ptz_current_missing".to_string())?;
        let minimum = advertised
            .get("min")
            .and_then(pair_from_value)
            .ok_or_else(|| "standard_uvc_ptz_minimum_missing".to_string())?;
        let maximum = advertised
            .get("max")
            .and_then(pair_from_value)
            .ok_or_else(|| "standard_uvc_ptz_maximum_missing".to_string())?;
        let step = advertised
            .get("step")
            .and_then(pair_from_value)
            .ok_or_else(|| "standard_uvc_ptz_step_missing".to_string())?;
        let pan_target = safe_step_target(original[0], minimum[0], maximum[0], step[0])
            .ok_or_else(|| "no_safe_pan_step_available".to_string())?;
        let tilt_target = safe_step_target(original[1], minimum[1], maximum[1], step[1])
            .ok_or_else(|| "no_safe_tilt_step_available".to_string())?;
        let mut evidence = vec![
            "standard_uvc_camera_terminal_identified".to_string(),
            "standard_uvc_ptz_get_current_succeeded".to_string(),
        ];
        let before_frame = self.capture(camera_id)?;
        let Some(before_digest) = before_frame.get("frame_digest").and_then(Value::as_str) else {
            return Ok(CameraVerification {
                camera_id: camera_id.to_string(),
                kind: "ptz".to_string(),
                state: "unproven".to_string(),
                control_mechanism: "standard_uvc_camera_terminal_pan_tilt_absolute".to_string(),
                capture_attempted: true,
                writes_attempted: false,
                hid_reports_sent: false,
                evidence: vec!["standard_uvc_ptz_readback_succeeded".to_string()],
                errors: vec!["bounded_frame_capture_required_for_physical_proof".to_string()],
            });
        };
        let mut errors = Vec::new();
        let mut writes_attempted = false;
        let (pan_ok, pan_physical) = self.run_guarded_axis_test(
            camera_id,
            original,
            [pan_target, original[1]],
            before_digest,
            &mut writes_attempted,
            &mut errors,
            "pan",
        );
        if pan_ok {
            evidence.push("standard_uvc_pan_set_readback_succeeded".to_string());
            evidence.push("standard_uvc_pan_exact_restoration_succeeded".to_string());
        }
        let (tilt_ok, tilt_physical) = self.run_guarded_axis_test(
            camera_id,
            original,
            [original[0], tilt_target],
            before_digest,
            &mut writes_attempted,
            &mut errors,
            "tilt",
        );
        if tilt_ok {
            evidence.push("standard_uvc_tilt_set_readback_succeeded".to_string());
            evidence.push("standard_uvc_tilt_exact_restoration_succeeded".to_string());
        }
        if pan_ok && tilt_ok && pan_physical && tilt_physical {
            self.proven_ptz
                .lock()
                .map_err(|_| "camera_runtime_poisoned".to_string())?
                .insert(camera_id.to_string(), true);
            let _ = self.refresh();
        } else {
            errors.push("physical_motion_not_proven_for_each_axis".to_string());
        }
        Ok(CameraVerification {
            camera_id: camera_id.to_string(),
            kind: "ptz".to_string(),
            state: if pan_ok && tilt_ok && pan_physical && tilt_physical {
                "proven"
            } else if pan_ok && tilt_ok {
                "readback_proven"
            } else {
                "unproven"
            }
            .to_string(),
            control_mechanism: "standard_uvc_camera_terminal_pan_tilt_absolute".to_string(),
            capture_attempted: false,
            writes_attempted,
            hid_reports_sent: false,
            evidence,
            errors,
        })
    }

    fn run_guarded_axis_test(
        &self,
        camera_id: &str,
        original: [i64; 2],
        target: [i64; 2],
        before_digest: &str,
        writes_attempted: &mut bool,
        errors: &mut Vec<String>,
        axis: &str,
    ) -> (bool, bool) {
        *writes_attempted = true;
        let moved = self.ptz_set(camera_id, target[0], target[1]);
        let moved_ok = moved.as_ref().ok().and_then(|report| report.get("ok"))
            == Some(&Value::Bool(true))
            && moved
                .as_ref()
                .ok()
                .and_then(|report| report.get("observed_readback_millidegrees"))
                .and_then(pair_from_value)
                == Some(target);
        let after_frame = self.capture(camera_id).ok();
        let physical_changed = after_frame
            .as_ref()
            .and_then(|report| report.get("frame_digest"))
            .and_then(Value::as_str)
            .map(|digest| digest != before_digest)
            .unwrap_or(false);
        if !moved_ok {
            errors.push(format!("{axis}_set_or_readback_failed"));
        } else if !physical_changed {
            errors.push(format!("{axis}_frame_did_not_change"));
        }
        let restored = self.ptz_set(camera_id, original[0], original[1]);
        let restored_ok = restored.as_ref().ok().and_then(|report| report.get("ok"))
            == Some(&Value::Bool(true))
            && restored
                .as_ref()
                .ok()
                .and_then(|report| report.get("observed_readback_millidegrees"))
                .and_then(pair_from_value)
                == Some(original);
        if !restored_ok {
            errors.push(format!("{axis}_exact_restoration_failed"));
        }
        (moved_ok && restored_ok, physical_changed)
    }

    fn capture(&self, camera_id: &str) -> Result<Value, String> {
        let status = self.status()?;
        let camera = find_camera(&status.cameras, camera_id)?;
        native_uvc_capture_json(&camera.descriptor_fingerprint)
    }

    pub(crate) fn ptz_get(&self, camera_id: &str) -> Result<Value, String> {
        let status = self.status()?;
        let camera = find_camera(&status.cameras, camera_id)?;
        let raw = native_uvc_ptz_json(&camera.descriptor_fingerprint, "get", 0, 0)?;
        decorate_ptz_result(raw, camera_id, &camera.descriptor_fingerprint)
    }

    pub(crate) fn ptz_set(
        &self,
        camera_id: &str,
        pan_millidegrees: i64,
        tilt_millidegrees: i64,
    ) -> Result<Value, String> {
        let status = self.status()?;
        let camera = find_camera(&status.cameras, camera_id)?;
        let pan = millidegrees_to_uvc(pan_millidegrees)?;
        let tilt = millidegrees_to_uvc(tilt_millidegrees)?;
        let raw = native_uvc_ptz_json(&camera.descriptor_fingerprint, "set", pan, tilt)?;
        decorate_ptz_result(raw, camera_id, &camera.descriptor_fingerprint)
    }

    pub(crate) fn execute_camera_lease(
        &self,
        lease: &CameraLease,
        expected_device_id: &str,
        verifier: &LeaseVerifier,
    ) -> Result<Value, String> {
        let action = verify_lease(lease, expected_device_id, verifier)?;
        let status = self.status()?;
        let camera = find_camera(&status.cameras, &lease.camera_id)?;
        let descriptor = match &action {
            ValidatedCameraAction::PtzGet {
                descriptor_fingerprint,
            }
            | ValidatedCameraAction::PtzSet {
                descriptor_fingerprint,
                ..
            } => descriptor_fingerprint,
        };
        if descriptor != &camera.descriptor_fingerprint {
            return Err("camera_descriptor_changed".to_string());
        }
        let report = match action {
            ValidatedCameraAction::PtzGet { .. } => self.ptz_get(&lease.camera_id)?,
            ValidatedCameraAction::PtzSet {
                pan_millidegrees,
                tilt_millidegrees,
                ..
            } => self.ptz_set(&lease.camera_id, pan_millidegrees, tilt_millidegrees)?,
        };
        if report.get("ok") != Some(&Value::Bool(true)) {
            return Err("camera_uvc_operation_failed".to_string());
        }
        let mut receipt = serde_json::Map::new();
        receipt.insert("code".to_string(), json!("camera_uvc_completed"));
        receipt.insert("camera_id".to_string(), json!(lease.camera_id));
        receipt.insert("verb".to_string(), json!(lease.verb));
        receipt.insert(
            "control_mechanism".to_string(),
            json!("standard_uvc_camera_terminal_pan_tilt_absolute"),
        );
        receipt.insert("hid_reports_sent".to_string(), json!(false));
        receipt.insert("zoom_or_focus_writes".to_string(), json!(false));
        for key in [
            "starting_millidegrees",
            "requested_millidegrees",
            "observed_readback_millidegrees",
            "readback_match",
            "handles_closed",
        ] {
            if let Some(value) = report.get(key) {
                receipt.insert(key.to_string(), value.clone());
            }
        }
        Ok(Value::Object(receipt))
    }

    pub(crate) fn validate_lease(
        &self,
        lease: CameraLease,
        expected_device_id: &str,
        verifier: &LeaseVerifier,
    ) -> Result<CameraLeaseValidation, String> {
        let action = verify_lease(&lease, expected_device_id, verifier)?;
        let status = self.status()?;
        let camera = find_camera(&status.cameras, &lease.camera_id)?;
        let descriptor_fingerprint = match &action {
            ValidatedCameraAction::PtzGet {
                descriptor_fingerprint,
            }
            | ValidatedCameraAction::PtzSet {
                descriptor_fingerprint,
                ..
            } => descriptor_fingerprint,
        };
        if descriptor_fingerprint != &camera.descriptor_fingerprint {
            return Err("camera_descriptor_changed".to_string());
        }
        let write_capability = camera
            .capabilities
            .get("pan")
            .map(|capability| capability.state == "writable")
            .unwrap_or(false)
            && camera
                .capabilities
                .get("tilt")
                .map(|capability| capability.state == "writable")
                .unwrap_or(false);
        let reason = match action {
            ValidatedCameraAction::PtzGet { .. } => "signed_ptz_read_validated".to_string(),
            ValidatedCameraAction::PtzSet { .. } if write_capability => {
                "signed_ptz_write_validated_native_uvc_recheck".to_string()
            }
            ValidatedCameraAction::PtzSet { .. } => {
                "local_uvc_ptz_write_not_advertised".to_string()
            }
        };
        let verb = lease.verb.clone();
        Ok(CameraLeaseValidation {
            camera_id: lease.camera_id,
            verb,
            state: if write_capability || !lease.verb.ends_with(".set") {
                "validated".to_string()
            } else {
                "unproven".to_string()
            },
            action_digest: lease.action_digest,
            writes_allowed: write_capability && lease.verb == "camera.ptz.set",
            reason,
        })
    }

    fn refresh_and_emit(&self, app: &AppHandle) -> Result<(), String> {
        let before = self.status().ok();
        let after = self.refresh()?;
        let changed = match before.as_ref() {
            None => true,
            Some(previous) => {
                previous.state != after.state
                    || previous.runtime != after.runtime
                    || previous.reason != after.reason
                    || previous.cameras != after.cameras
            }
        };
        if changed {
            let _ = app.emit("boltrig://camera-discovery-changed", &after);
        }
        Ok(())
    }
}

pub(crate) async fn run_loop(app: AppHandle) {
    loop {
        if let Some(runtime) = app.try_state::<CameraRuntime>() {
            let _ = runtime.refresh_and_emit(&app);
        }
        tokio::time::sleep(Duration::from_secs(3)).await;
    }
}

fn find_camera<'a>(cameras: &'a [CameraView], camera_id: &str) -> Result<&'a CameraView, String> {
    cameras
        .iter()
        .find(|camera| camera.camera_id == camera_id)
        .ok_or_else(|| "camera_not_found".to_string())
}

fn project_inventory(inventory: NativeInventory) -> Result<CameraDiscoveryStatus, String> {
    if inventory.schema_version != 1
        || inventory.runtime.is_empty()
        || inventory.state.is_empty()
        || inventory.cameras.len() > 64
    {
        return Err("invalid_native_camera_inventory".to_string());
    }
    let cameras = inventory
        .cameras
        .into_iter()
        .map(project_camera)
        .collect::<Result<Vec<_>, _>>()?;
    let state = if inventory.state == "unavailable" {
        "unavailable".to_string()
    } else if cameras
        .iter()
        .any(|camera| camera.permission != "authorized")
    {
        "permission_required".to_string()
    } else if cameras.is_empty() {
        "unavailable".to_string()
    } else {
        "advertised".to_string()
    };
    Ok(CameraDiscoveryStatus {
        schema_version: 1,
        state,
        runtime: inventory.runtime,
        cameras,
        refreshed_at: OffsetDateTime::now_utc()
            .format(&Rfc3339)
            .map_err(|_| "camera_time_unavailable".to_string())?,
        reason: inventory.reason,
    })
}

fn project_camera(camera: NativeCamera) -> Result<CameraView, String> {
    let _native_usb_metadata = (
        camera.vid,
        camera.pid,
        camera.uvc_interface,
        camera.terminal_id,
        camera.uvc_version.as_str(),
    );
    if camera.native_key.is_empty()
        || camera.native_key.len() > 512
        || camera.label.is_empty()
        || camera.label.len() > 256
        || camera.model.len() > 256
        || camera.permission.len() > 32
    {
        return Err("invalid_native_camera_record".to_string());
    }
    let computed_digest = hex::encode(Sha256::digest(camera.native_key.as_bytes()));
    let descriptor_fingerprint = match camera.descriptor_fingerprint {
        Some(value) if value == computed_digest => value,
        Some(_) => return Err("native_camera_descriptor_fingerprint_mismatch".to_string()),
        None => computed_digest,
    };
    let camera_id = format!("camera_{}", &descriptor_fingerprint[..32]);
    let mut capabilities = BTreeMap::new();
    let transport = camera
        .transport
        .clone()
        .unwrap_or_else(|| "avfoundation".to_string());
    let source = transport.clone();
    capabilities.insert(
        "snapshot".to_string(),
        CameraCapability {
            state: "advertised".to_string(),
            source: source.clone(),
            evidence: vec!["video_device_enumerated".to_string()],
            reason: Some("one_frame_capture_required_for_proven".to_string()),
        },
    );
    let ptz = camera.controls.get("pan_tilt_absolute");
    let ptz_state = control_state(ptz, true);
    let ptz_reason = if ptz_state == "writable" {
        Some("native_uvc_readback_and_write_advertised_physical_proof_still_required".to_string())
    } else if ptz_state == "readable" {
        Some("native_uvc_readback_advertised_physical_proof_still_required".to_string())
    } else {
        Some("standard_uvc_ptz_control_not_readable".to_string())
    };
    for name in ["pan", "tilt"] {
        capabilities.insert(
            name.to_string(),
            CameraCapability {
                state: ptz_state.to_string(),
                source: source.clone(),
                evidence: if ptz_state == "unknown" {
                    Vec::new()
                } else {
                    vec!["standard_uvc_camera_terminal_control_descriptor".to_string()]
                },
                reason: ptz_reason.clone(),
            },
        );
    }
    let privacy = camera.controls.get("privacy");
    let privacy_state = control_state(privacy, false);
    capabilities.insert(
        "privacy".to_string(),
        CameraCapability {
            state: privacy_state.to_string(),
            source: source.clone(),
            evidence: if privacy_state == "unknown" {
                Vec::new()
            } else {
                vec!["standard_uvc_camera_terminal_privacy_descriptor".to_string()]
            },
            reason: Some(
                "privacy_semantics_require_separate_guarded_physical_verification".to_string(),
            ),
        },
    );
    for name in ["tracking", "hid"] {
        capabilities.insert(
            name.to_string(),
            CameraCapability {
                state: "unknown".to_string(),
                source: source.to_string(),
                evidence: Vec::new(),
                reason: Some("not_exposed_by_native_uvc_bridge".to_string()),
            },
        );
    }
    let mut warnings = vec![
        "native_inventory_does_not_prove_physical_ptz_motion".to_string(),
        "native_inventory_does_not_send_hid_reports".to_string(),
    ];
    if camera.permission != "authorized" {
        warnings.push("camera_capture_permission_required".to_string());
    }
    Ok(CameraView {
        camera_id,
        descriptor_fingerprint,
        label: camera.label,
        manufacturer: camera.manufacturer,
        product: camera.model,
        transport,
        connection_state: if matches!(camera.permission.as_str(), "authorized" | "not_enumerated") {
            "connected".to_string()
        } else {
            "permission_required".to_string()
        },
        permission: camera.permission,
        format_count: camera.format_count,
        capabilities,
        interfaces: if source == "uvc_libusb" {
            vec!["video.avfoundation".to_string(), "control.uvc".to_string()]
        } else {
            vec!["video.avfoundation".to_string()]
        },
        warnings,
        allowed_verbs: {
            let mut verbs = vec![
                "camera.device.list".to_string(),
                "camera.device.status".to_string(),
                "camera.device.capabilities".to_string(),
            ];
            if ptz_state == "readable" || ptz_state == "writable" {
                verbs.push("camera.ptz.get".to_string());
            }
            verbs
        },
    })
}

fn control_state(control: Option<&Value>, require_pair: bool) -> &'static str {
    let Some(control) = control.and_then(Value::as_object) else {
        return "unknown";
    };
    let readable = control
        .get("readable")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let writable = control
        .get("writable")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if require_pair
        && ["min", "max", "step", "current"]
            .iter()
            .any(|key| !valid_pair(control.get(*key)))
    {
        return "unknown";
    }
    if !require_pair {
        let Some(current) = control.get("current") else {
            return "unknown";
        };
        let Some(number) = current.as_i64() else {
            return "invalid_descriptor";
        };
        if number != 0 && number != 1 {
            return "invalid_descriptor";
        }
    }
    if writable {
        "writable"
    } else if readable {
        "readable"
    } else {
        "unknown"
    }
}

fn valid_pair(value: Option<&Value>) -> bool {
    value
        .and_then(Value::as_array)
        .is_some_and(|items| items.len() == 2 && items.iter().all(|item| item.as_i64().is_some()))
}

fn native_inventory_json() -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        let uvc_ptr = unsafe { boltrig_uvc_inventory_json() };
        if !uvc_ptr.is_null() {
            let uvc_value = unsafe { CStr::from_ptr(uvc_ptr) }
                .to_str()
                .map(str::to_owned)
                .map_err(|_| "invalid_native_camera_inventory_encoding".to_string());
            unsafe { boltrig_uvc_json_free(uvc_ptr) };
            if let Ok(value) = uvc_value {
                if let Ok(inventory) = serde_json::from_str::<NativeInventory>(&value) {
                    if !inventory.cameras.is_empty() {
                        return Ok(value);
                    }
                }
            }
        }
        // The Objective-C bridge returns an owned UTF-8 JSON buffer.  It never
        // contains the native key in the projected value returned to the UI.
        let ptr = unsafe { boltrig_camera_inventory_json() };
        if ptr.is_null() {
            return Err("native_camera_inventory_unavailable".to_string());
        }
        let value = unsafe { CStr::from_ptr(ptr) }
            .to_str()
            .map(str::to_owned)
            .map_err(|_| "invalid_native_camera_inventory_encoding".to_string());
        unsafe { boltrig_camera_inventory_free(ptr) };
        return value;
    }
    #[cfg(not(target_os = "macos"))]
    {
        Ok(
            r#"{"schema_version":1,"runtime":"unavailable","state":"unavailable","reason":"macos_avfoundation_required","cameras":[]}"#
                .to_string(),
        )
    }
}

fn millidegrees_to_uvc(value: i64) -> Result<i64, String> {
    if value % UVC_MILLIDEGREES_PER_UNIT != 0 {
        return Err("camera_ptz_angle_must_match_uvc_precision".to_string());
    }
    let raw = value / UVC_MILLIDEGREES_PER_UNIT;
    if !(-MAX_UVC_ANGLE..=MAX_UVC_ANGLE).contains(&raw) {
        return Err("camera_ptz_angle_out_of_range".to_string());
    }
    Ok(raw)
}

fn native_uvc_ptz_json(
    descriptor_fingerprint: &str,
    operation: &str,
    pan: i64,
    tilt: i64,
) -> Result<Value, String> {
    #[cfg(target_os = "macos")]
    {
        let fingerprint = CString::new(descriptor_fingerprint)
            .map_err(|_| "invalid_camera_descriptor_fingerprint".to_string())?;
        let operation =
            CString::new(operation).map_err(|_| "invalid_camera_ptz_operation".to_string())?;
        let ptr =
            unsafe { boltrig_uvc_ptz_json(fingerprint.as_ptr(), operation.as_ptr(), pan, tilt) };
        if ptr.is_null() {
            return Err("native_uvc_ptz_backend_unavailable".to_string());
        }
        let raw = unsafe { CStr::from_ptr(ptr) }
            .to_str()
            .map(str::to_owned)
            .map_err(|_| "invalid_native_uvc_result_encoding".to_string());
        unsafe { boltrig_uvc_json_free(ptr) };
        let raw = raw?;
        if raw.len() > MAX_NATIVE_RESULT_BYTES {
            return Err("native_uvc_result_too_large".to_string());
        }
        serde_json::from_str(&raw).map_err(|_| "invalid_native_uvc_result".to_string())
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (descriptor_fingerprint, operation, pan, tilt);
        Err("native_uvc_backend_requires_macos".to_string())
    }
}

fn native_uvc_capture_json(descriptor_fingerprint: &str) -> Result<Value, String> {
    #[cfg(target_os = "macos")]
    {
        let fingerprint = CString::new(descriptor_fingerprint)
            .map_err(|_| "invalid_camera_descriptor_fingerprint".to_string())?;
        let ptr = unsafe { boltrig_uvc_capture_json(fingerprint.as_ptr()) };
        if ptr.is_null() {
            return Err("native_camera_capture_backend_unavailable".to_string());
        }
        let raw = unsafe { CStr::from_ptr(ptr) }
            .to_str()
            .map(str::to_owned)
            .map_err(|_| "invalid_native_camera_capture_encoding".to_string());
        unsafe { boltrig_uvc_json_free(ptr) };
        let raw = raw?;
        if raw.len() > MAX_NATIVE_RESULT_BYTES {
            return Err("native_camera_capture_result_too_large".to_string());
        }
        serde_json::from_str(&raw).map_err(|_| "invalid_native_camera_capture_result".to_string())
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = descriptor_fingerprint;
        Err("native_camera_capture_requires_macos".to_string())
    }
}

fn decorate_ptz_result(
    raw: Value,
    camera_id: &str,
    descriptor_fingerprint: &str,
) -> Result<Value, String> {
    let mut object = raw
        .as_object()
        .cloned()
        .ok_or_else(|| "invalid_native_uvc_result".to_string())?;
    if object.get("descriptor_fingerprint").and_then(Value::as_str) != Some(descriptor_fingerprint)
    {
        return Err("native_uvc_descriptor_mismatch".to_string());
    }
    object.insert("camera_id".to_string(), json!(camera_id));
    object.insert(
        "semantic_unit".to_string(),
        json!("millidegrees; native UVC values are 0.01 degrees"),
    );
    if let Some(advertised) = object.get("advertised").cloned() {
        object.insert(
            "advertised_millidegrees".to_string(),
            convert_control_pairs(&advertised),
        );
    }
    for (raw_key, semantic_key) in [
        ("starting", "starting_millidegrees"),
        ("requested", "requested_millidegrees"),
        ("observed_readback", "observed_readback_millidegrees"),
    ] {
        if let Some(value) = object.get(raw_key).and_then(pair_from_value) {
            object.insert(semantic_key.to_string(), json!(value));
        }
    }
    Ok(Value::Object(object))
}

fn convert_control_pairs(value: &Value) -> Value {
    let Some(object) = value.as_object() else {
        return Value::Null;
    };
    let mut result = serde_json::Map::new();
    for key in ["min", "max", "step", "default", "current"] {
        if let Some(pair) = object.get(key).and_then(pair_from_value) {
            result.insert(
                key.to_string(),
                json!(pair.map(|item| item * UVC_MILLIDEGREES_PER_UNIT)),
            );
        }
    }
    Value::Object(result)
}

fn pair_from_value(value: &Value) -> Option<[i64; 2]> {
    let values = value.as_array()?;
    if values.len() != 2 {
        return None;
    }
    Some([values[0].as_i64()?, values[1].as_i64()?])
}

fn safe_step_target(current: i64, minimum: i64, maximum: i64, step: i64) -> Option<i64> {
    let magnitude = step.abs();
    if magnitude == 0 {
        return None;
    }
    for target in [
        current.saturating_add(magnitude),
        current.saturating_sub(magnitude),
    ] {
        if target > minimum.saturating_add(magnitude)
            && target < maximum.saturating_sub(magnitude)
            && (target - minimum) % magnitude == 0
        {
            return Some(target);
        }
    }
    None
}
