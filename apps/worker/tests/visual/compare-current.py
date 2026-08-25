#!/usr/bin/env python3
"""Compare source-bound current Worker captures to their Figma exports.

This writes only beneath the manifest's ``current_capture_root`` and deliberately
does not issue an authority or VDS verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[4]
STATES_PATH = SCRIPT.with_name("states.json")
SOURCE_SCOPE = ("apps/worker/src", "apps/worker/tests/visual")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_tree_digest() -> str:
    digest = hashlib.sha256()
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *SOURCE_SCOPE],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    for relative_path in sorted(path for path in listed.split(b"\0") if path):
        decoded = os.fsdecode(relative_path)
        path = REPO_ROOT / decoded
        if not path.exists() and not path.is_symlink():
            continue  # staged deletion: indexed, but absent from the candidate tree
        digest.update(relative_path)
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.fsencode(os.readlink(path)))
            digest.update(b"\0")
        else:
            digest.update(b"file\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def load_plan() -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    manifest = json.loads(STATES_PATH.read_text(encoding="utf-8"))
    governed_ids = manifest["governed_state_ids"]
    # NOT A FIXED SEVEN ANY MORE. The count was a proxy; UNIQUENESS is the
    # invariant it was standing in for, because a repeated id would compare one
    # state twice and report the second pass as coverage. agents, plugins and
    # call were retired when the routes a cell can serve were narrowed, so a
    # hard 7 now refuses a manifest that is correct - see `retired_state_ids`
    # in states.json for which went and why.
    if not governed_ids or len(set(governed_ids)) != len(governed_ids):
        raise ValueError("states.json must declare a non-empty set of unique governed states")
    by_id = {state["id"]: state for state in manifest["states"]}
    states = []
    for state_id in governed_ids:
        state = by_id.get(state_id)
        if state is None:
            raise ValueError(f"governed state {state_id!r} is missing")
        for field in ("figma_node_id", "target_output", "current_output"):
            if not state.get(field):
                raise ValueError(f"{state_id}: missing {field}")
        target = (REPO_ROOT / state["target_output"]).resolve()
        current = (REPO_ROOT / state["current_output"]).resolve()
        expected_target_root = (
            REPO_ROOT / "docs/design/evidence/2026-08-11-console-parity/figma"
        ).resolve()
        current_root = (REPO_ROOT / manifest["current_capture_root"]).resolve()
        if target.parent != expected_target_root:
            raise ValueError(f"{state_id}: target escapes the declared Figma export root")
        if current.parent != current_root / "shipped":
            raise ValueError(f"{state_id}: current output escapes current/shipped")
        states.append(state)
    return manifest, states, (REPO_ROOT / manifest["current_capture_root"]).resolve()


def validate_capture(
    states: list[dict[str, Any]], current_root: Path
) -> tuple[dict[str, Any], str]:
    capture_path = current_root / "capture-manifest.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    if capture.get("schema") != "boltrig-console-current-capture-manifest.v1":
        raise ValueError("current capture manifest has the wrong schema")
    if capture.get("status") != "captured_unreviewed":
        raise ValueError("current capture is not captured_unreviewed")
    if capture.get("visualVerdict") != "not_assessed":
        raise ValueError("current capture already claims a visual verdict")
    if capture.get("vdsReviewsUpdated") is not False:
        raise ValueError("current capture does not preserve the VDS review boundary")
    viewport = capture.get("viewport", {})
    if (viewport.get("width"), viewport.get("height"), viewport.get("deviceScaleFactor")) != (
        1440,
        900,
        1,
    ):
        raise ValueError("current capture viewport is not 1440x900 at scale 1")

    source_binding = capture.get("sourceBinding", {})
    before = source_binding.get("digestBeforeCapture")
    after = source_binding.get("digestAfterCapture")
    current = source_tree_digest()
    if before != after or source_binding.get("sourceUnchangedDuringCapture") is not True:
        raise ValueError("capture manifest says source changed during capture")
    if current != after:
        raise ValueError(
            f"current source digest {current} does not match capture digest {after}; recapture first"
        )

    capture_states = capture.get("states", [])
    if [row.get("state") for row in capture_states] != [state["id"] for state in states]:
        raise ValueError("capture states do not exactly match the governed-state order")
    for state, row in zip(states, capture_states, strict=True):
        if row.get("figmaNodeId") != state["figma_node_id"]:
            raise ValueError(f"{state['id']}: capture has the wrong Figma node")
        if row.get("target") != state["target_output"]:
            raise ValueError(f"{state['id']}: capture has the wrong target path")
        if row.get("output") != state["current_output"]:
            raise ValueError(f"{state['id']}: capture has the wrong current output path")
        if (row.get("width"), row.get("height")) != (1440, 900):
            raise ValueError(f"{state['id']}: capture receipt dimensions are not 1440x900")
        current_path = REPO_ROOT / state["current_output"]
        if sha256(current_path) != row.get("sha256"):
            raise ValueError(f"{state['id']}: current PNG digest does not match its receipt")
    return capture, sha256(capture_path)


def compare_state(
    state: dict[str, Any], current_root: Path, diff_root: Path
) -> dict[str, Any]:
    try:
        import numpy as np
        from PIL import Image, ImageChops, ImageDraw
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "current comparison requires Pillow and NumPy; use the bundled workspace Python"
        ) from error
    target_path = REPO_ROOT / state["target_output"]
    current_path = REPO_ROOT / state["current_output"]
    with Image.open(target_path) as opened_target:
        target = opened_target.convert("RGB")
    with Image.open(current_path) as opened_current:
        current = opened_current.convert("RGB")
    if target.size != (1440, 900) or current.size != (1440, 900):
        raise ValueError(
            f"{state['id']}: target {target.size} and current {current.size} must both be 1440x900"
        )

    target_pixels = np.asarray(target, dtype=np.int16)
    current_pixels = np.asarray(current, dtype=np.int16)
    channel_delta = np.abs(target_pixels - current_pixels)
    pixel_delta = np.max(channel_delta, axis=2)
    squared = np.square(channel_delta.astype(np.float64))
    mse = float(np.mean(squared))
    psnr = None if mse == 0 else 20 * math.log10(255.0 / math.sqrt(mse))

    diff_gray = ImageChops.difference(target, current).convert("L")
    amplified = diff_gray.point(lambda value: min(255, value * 4))
    diff_image = Image.merge(
        "RGB",
        (amplified, Image.new("L", target.size, 0), amplified),
    )
    diff_path = diff_root / f"{state['id']}.png"
    diff_image.save(diff_path, optimize=True)

    triptych = Image.new("RGB", (target.width * 3, target.height + 34), "#111111")
    triptych.paste(target, (0, 34))
    triptych.paste(current, (target.width, 34))
    triptych.paste(diff_image, (target.width * 2, 34))
    labels = ImageDraw.Draw(triptych)
    labels.text((12, 10), "Figma target", fill="#f4f4f4")
    labels.text((target.width + 12, 10), "Current source capture", fill="#f4f4f4")
    labels.text((target.width * 2 + 12, 10), "4x absolute delta", fill="#f4f4f4")
    triptych_path = diff_root / f"{state['id']}__triptych.png"
    triptych.save(triptych_path, optimize=True)

    total_pixels = target.width * target.height
    return {
        "state": state["id"],
        "figmaNodeId": state["figma_node_id"],
        "viewport": {"width": target.width, "height": target.height},
        "targetPath": state["target_output"],
        "targetSha256": sha256(target_path),
        "currentPath": state["current_output"],
        "currentSha256": sha256(current_path),
        "diffPath": f"{current_root.relative_to(REPO_ROOT).as_posix()}/diff/{state['id']}.png",
        "diffSha256": sha256(diff_path),
        "triptychPath": (
            f"{current_root.relative_to(REPO_ROOT).as_posix()}/diff/"
            f"{state['id']}__triptych.png"
        ),
        "triptychSha256": sha256(triptych_path),
        "exactChangedPixelRatio": float(np.count_nonzero(pixel_delta) / total_pixels),
        "changedPixelRatioGt8": float(np.count_nonzero(pixel_delta > 8) / total_pixels),
        "changedPixelRatioGt16": float(np.count_nonzero(pixel_delta > 16) / total_pixels),
        "changedPixelRatioGt32": float(np.count_nonzero(pixel_delta > 32) / total_pixels),
        "meanAbsoluteChannelDelta": float(np.mean(channel_delta)),
        "rootMeanSquareChannelDelta": math.sqrt(mse),
        "psnrDb": psnr,
    }


def promote_comparison(stage: Path, current_root: Path) -> None:
    destination_diff = current_root / "diff"
    destination_metrics = current_root / "metrics.json"
    backup_suffix = f".previous-{uuid.uuid4()}"
    backup_diff = current_root / f"diff{backup_suffix}"
    backup_metrics = current_root / f"metrics.json{backup_suffix}"
    had_diff = destination_diff.exists()
    had_metrics = destination_metrics.exists()
    if had_diff:
        destination_diff.rename(backup_diff)
    if had_metrics:
        destination_metrics.rename(backup_metrics)
    try:
        (stage / "diff").rename(destination_diff)
        (stage / "metrics.json").rename(destination_metrics)
    except Exception:
        if destination_diff.exists():
            shutil.rmtree(destination_diff)
        if destination_metrics.exists():
            destination_metrics.unlink()
        if had_diff:
            backup_diff.rename(destination_diff)
        if had_metrics:
            backup_metrics.rename(destination_metrics)
        raise
    else:
        if had_diff:
            shutil.rmtree(backup_diff)
        if had_metrics:
            backup_metrics.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check-plan",
        action="store_true",
        help="validate the target/current mappings without requiring captures",
    )
    args = parser.parse_args()
    manifest, states, current_root = load_plan()
    if args.check_plan:
        print(
            json.dumps(
                {
                    "status": "plan_valid",
                    "currentCaptureRoot": manifest["current_capture_root"],
                    "states": [
                        {
                            "state": state["id"],
                            "figmaNodeId": state["figma_node_id"],
                            "target": state["target_output"],
                            "current": state["current_output"],
                        }
                        for state in states
                    ],
                },
                indent=2,
            )
        )
        return

    capture, capture_digest = validate_capture(states, current_root)
    stage = Path(tempfile.mkdtemp(prefix=".comparison-staging-", dir=current_root))
    try:
        diff_root = stage / "diff"
        diff_root.mkdir()
        rows = [compare_state(state, current_root, diff_root) for state in states]
        if source_tree_digest() != capture["sourceBinding"]["digestAfterCapture"]:
            raise ValueError("source changed while comparison artifacts were generated")
        report = {
            "schema": "boltrig-console-current-visual-diff.v1",
            "status": "measured_unreviewed",
            "visualVerdict": "not_assessed",
            "vdsReviewsUpdated": False,
            "viewport": "1440x900@1x",
            "captureManifestPath": (
                f"{current_root.relative_to(REPO_ROOT).as_posix()}/capture-manifest.json"
            ),
            "captureManifestSha256": capture_digest,
            "captureSourceBinding": capture["sourceBinding"],
            "statesExpected": [state["id"] for state in states],
            "statesCompared": [row["state"] for row in rows],
            "statesMissing": [],
            "metrics": rows,
            "reviewPolicy": {
                "pixelsClaimed": False,
                "instruction": (
                    "These are deterministic measurements, not an authority verdict. "
                    "Update VDS only through a separate signed review."
                ),
            },
        }
        (stage / "metrics.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        promote_comparison(stage, current_root)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "visualVerdict": report["visualVerdict"],
                    "output": report["captureManifestPath"].replace(
                        "capture-manifest.json", "metrics.json"
                    ),
                    "statesCompared": report["statesCompared"],
                },
                indent=2,
            )
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    main()
