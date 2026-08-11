#!/usr/bin/env python3
"""Produce deterministic image-diff evidence for the seven console states."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw


ROOT = Path(__file__).resolve().parent
TARGETS = {
    "new-chat": "new-chat__13-2.png",
    "chat-run": "chat-run__5-2.png",
    "agents": "agents__15-2.png",
    "plugins": "plugins__14-2.png",
    "command-palette": "command-palette__16-2.png",
    "call": "call__17-2.png",
    "settings-you": "settings-you__22-2.png",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare(slug: str, target_path: Path, shipped_path: Path) -> dict[str, object]:
    target = Image.open(target_path).convert("RGB")
    shipped = Image.open(shipped_path).convert("RGB")
    if target.size != shipped.size:
        raise ValueError(f"{slug}: target {target.size} != shipped {shipped.size}")

    target_pixels = np.asarray(target, dtype=np.int16)
    shipped_pixels = np.asarray(shipped, dtype=np.int16)
    channel_delta = np.abs(target_pixels - shipped_pixels)
    pixel_delta = np.max(channel_delta, axis=2)
    mse = float(np.mean(np.square(channel_delta.astype(np.float64))))
    psnr = None if mse == 0 else 20 * math.log10(255.0 / math.sqrt(mse))

    diff_gray = ImageChops.difference(target, shipped).convert("L")
    amplified = diff_gray.point(lambda value: min(255, value * 4))
    diff_image = Image.merge(
        "RGB",
        (amplified, Image.new("L", target.size, 0), amplified),
    )
    diff_path = ROOT / "diff" / f"{slug}.png"
    diff_image.save(diff_path, optimize=True)

    sheet = Image.new("RGB", (target.width * 3, target.height + 34), "#111111")
    sheet.paste(target, (0, 34))
    sheet.paste(shipped, (target.width, 34))
    sheet.paste(diff_image, (target.width * 2, 34))
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), "Figma target", fill="#f4f4f4")
    draw.text((target.width + 12, 10), "Shipped fixture", fill="#f4f4f4")
    draw.text((target.width * 2 + 12, 10), "4x absolute delta", fill="#f4f4f4")
    sheet_path = ROOT / "diff" / f"{slug}__triptych.png"
    sheet.save(sheet_path, optimize=True)

    total_pixels = target.width * target.height
    return {
        "state": slug,
        "viewport": {"width": target.width, "height": target.height},
        "target_path": str(target_path.relative_to(ROOT.parent.parent.parent.parent)),
        "target_sha256": sha256(target_path),
        "shipped_path": str(shipped_path.relative_to(ROOT.parent.parent.parent.parent)),
        "shipped_sha256": sha256(shipped_path),
        "diff_path": str(diff_path.relative_to(ROOT.parent.parent.parent.parent)),
        "diff_sha256": sha256(diff_path),
        "exact_changed_pixel_ratio": float(np.count_nonzero(pixel_delta) / total_pixels),
        "changed_pixel_ratio_gt_8": float(np.count_nonzero(pixel_delta > 8) / total_pixels),
        "changed_pixel_ratio_gt_16": float(np.count_nonzero(pixel_delta > 16) / total_pixels),
        "changed_pixel_ratio_gt_32": float(np.count_nonzero(pixel_delta > 32) / total_pixels),
        "mean_absolute_channel_delta": float(np.mean(channel_delta)),
        "root_mean_square_channel_delta": math.sqrt(mse),
        "psnr_db": psnr,
    }


def main() -> None:
    (ROOT / "diff").mkdir(exist_ok=True)
    rows = []
    missing = []
    for slug, target_name in TARGETS.items():
        target_path = ROOT / "figma" / target_name
        shipped_path = ROOT / "shipped" / f"{slug}.png"
        if not target_path.exists() or not shipped_path.exists():
            missing.append(slug)
            continue
        rows.append(compare(slug, target_path, shipped_path))

    report = {
        "schema": "boltrig-console-visual-diff.v1",
        "viewport": "1440x900",
        "states_expected": list(TARGETS),
        "states_compared": [row["state"] for row in rows],
        "states_missing": missing,
        "metrics": rows,
    }
    (ROOT / "metrics.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if missing:
        raise SystemExit(f"missing shipped captures: {', '.join(missing)}")


if __name__ == "__main__":
    main()
