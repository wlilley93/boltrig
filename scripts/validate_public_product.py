#!/usr/bin/env python3
"""Validate the public product boundary.

The checked-in examples are a product template, not the operator's private
manifest. This gate keeps personal tenant/model/provider values out of that
template and makes the two stock Stage characters an explicit release
contract. Operator-owned ``manifest.yaml`` and secret stores remain free to
provide their own Bifrost catalogue and integrations.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str, *, root: Path) -> str:
    return (root / relative).read_text(encoding="utf-8")


def _require(text: str, needle: str, *, label: str) -> None:
    if needle not in text:
        raise ValueError(f"{label} is missing required public-product contract: {needle}")


def _forbid(text: str, needle: str, *, label: str) -> None:
    if needle.casefold() in text.casefold():
        raise ValueError(f"{label} contains personal or private value: {needle}")


def _typescript_without_comments(text: str) -> str:
    """Return the tiny stock join's executable text, not its documentation."""

    without_blocks = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return "\n".join(
        code
        for line in without_blocks.splitlines()
        if (code := line.split("//", 1)[0].strip())
    )


def validate(root: Path = ROOT) -> None:
    root = root.resolve()
    manifest = _read("manifest.example.yaml", root=root)
    env = _read(".env.example", root=root)
    characters = _read("apps/worker/src/components/characters.ts", root=root)
    character_plugins = _read("apps/worker/src/characterPlugins.ts", root=root)
    main = _read("apps/worker/src/main.tsx", root=root)
    dockerfile = _read("apps/worker/Dockerfile", root=root)
    worker_package_text = _read("apps/worker/package.json", root=root)
    worker_lock = _read("apps/worker/pnpm-lock.yaml", root=root)
    worker_package = json.loads(worker_package_text)
    familiar_manifest_path = root / "apps/worker/src/bundles/familiar/character.json"
    familiar_manifest_text = familiar_manifest_path.read_text(encoding="utf-8")
    familiar_manifest = json.loads(familiar_manifest_text)
    familiar_shader = familiar_manifest_path.parent / "familiar.frag"
    ultron_manifest_path = root / "apps/worker/src/bundles/ultron/character.json"
    ultron_manifest_text = ultron_manifest_path.read_text(encoding="utf-8")
    ultron_manifest = json.loads(ultron_manifest_text)

    # These are known values from the local deployment history. A public
    # template must not make them part of another operator's installation.
    private_markers = (
        "Acme Corp",
        "acme-admins",
        "acme-engineering",
        "acme-staff",
        "deepreinforce-ai",
        "Ornith-1.0-35B",
        "will.lilley93@gmail.com",
        "/Users/williamlilley",
        "/home/jellytot",
        "jellytot-prod",
        # Private dev inference belongs in the operator's Bifrost store and
        # deployment environment, never in the portable product template.
        "100.108.41.109",
        "mac-mini-m1",
        "qwen3vl-abliterated",
    )
    for marker in private_markers:
        _forbid(manifest, marker, label="manifest.example.yaml")
        _forbid(env, marker, label=".env.example")
        _forbid(familiar_manifest_text, marker, label="Familiar stock bundle")
        _forbid(ultron_manifest_text, marker, label="Ultron stock bundle")
    _forbid(
        familiar_manifest_text,
        "wlilley93/beelink-desktop",
        label="Familiar stock bundle",
    )

    standard = re.search(
        r"(?ms)^\s*- id: standard\s*\n\s*kind: ([^\n]+)\s*\n\s*model: ([^\n]+)",
        manifest,
    )
    if not standard or standard.group(1).strip() != "bifrost":
        raise ValueError("public standard route must be a Bifrost endpoint")
    if standard.group(2).strip() != "${BOLTRIG_DEFAULT_MODEL:-}":
        raise ValueError("public standard route must not bundle a model identity")
    _require(
        manifest,
        "BOLTRIG_MODEL_GATEWAY_URL:-http://bifrost:8080/v1",
        label="manifest.example.yaml",
    )
    for line in env.splitlines():
        if re.match(r"^\s*[A-Z0-9_]*(?:API_KEY|ACCESS_TOKEN)\s*=", line):
            value = line.split("=", 1)[1].strip()
            if value:
                raise ValueError(".env.example contains a non-empty provider secret assignment")
    _require(env, "Model provider keys do not belong in this file", label=".env.example")
    for line in env.splitlines():
        if re.match(r"^\s*TEAMS_WEBHOOK\s*=", line):
            value = line.split("=", 1)[1].strip()
            if value:
                raise ValueError(".env.example bundles a webhook value")

    # The production registry is deliberately closed: Familiar, Jarvis and Ultron
    # are first-party. A private distribution can own a separate entrypoint, but
    # the public package graph, lockfile, and stock plugin join must be hermetic.
    # Widening the set is the easy half; the point of a closed list is that each
    # member carries the same guarantee, so Ultron's bundle is checked below the
    # way Familiar's is.
    registrations = re.findall(
        r"(?m)^\s*registerCharacter\(([A-Z][A-Z0-9_]*)\);\s*$", characters
    )
    if registrations != ["FAMILIAR", "JARVIS", "ULTRON"]:
        raise ValueError(
            "character registry must register exactly Familiar, Jarvis then Ultron"
        )
    if familiar_manifest.get("id") != "familiar":
        raise ValueError("stock Familiar bundle must keep the familiar id")
    if familiar_manifest.get("provenance", {}).get("ships") is not True:
        raise ValueError("stock Familiar bundle must declare ships=true")
    fragment = familiar_manifest.get("visual", {}).get("fragment", {})
    if fragment.get("file") != "familiar.frag":
        raise ValueError("stock Familiar bundle must own familiar.frag")
    if familiar_shader.is_symlink() or not familiar_shader.is_file():
        raise ValueError("stock Familiar shader must be a regular in-bundle file")
    shader_digest = hashlib.sha256(familiar_shader.read_bytes()).hexdigest()
    if fragment.get("sha256") != shader_digest:
        raise ValueError("stock Familiar bundle shader digest does not match its file")
    if ultron_manifest.get("id") != "ultron":
        raise ValueError("stock Ultron bundle must keep the ultron id")
    if ultron_manifest.get("provenance", {}).get("ships") is not True:
        raise ValueError("stock Ultron bundle must declare ships=true")
    if ultron_manifest.get("provenance", {}).get("upstream") != "boltrig-stock:ultron":
        raise ValueError("stock Ultron bundle must declare the stock upstream")
    # Deliberately NO shader-digest check, and the absence is the assertion:
    # Ultron carries no .frag because he is a simulation and four passes rather
    # than one shader (his manifest says so). Demanding a fragment here would
    # refuse a body the product ships; pinning nothing at all would let one
    # appear unnoticed. So the manifest must keep saying it has none.
    if ultron_manifest.get("visual", {}).get("fragment") is not None:
        raise ValueError(
            "stock Ultron bundle declares a fragment - pin its digest the way "
            "Familiar's is, or drop it"
        )
    if "import.meta.glob" in characters:
        raise ValueError("character registry uses a bundler glob that ships external companions")
    if _typescript_without_comments(character_plugins) != "export {};":
        raise ValueError("stock characterPlugins.ts must be the literal empty module")
    _require(main, 'import "./characterPlugins";', label="Worker entrypoint")
    worker_source = root / "apps/worker/src"
    if worker_source.is_dir():
        source_files = (
            *worker_source.rglob("*.ts"),
            *worker_source.rglob("*.tsx"),
            *worker_source.rglob("*.js"),
            *worker_source.rglob("*.jsx"),
            *worker_source.rglob("*.mts"),
            *worker_source.rglob("*.mjs"),
        )
        for source in sorted(source_files):
            if source == worker_source / "components/characters.ts":
                continue
            if re.search(r"\bregisterCharacter\s*\(", source.read_text(encoding="utf-8")):
                relative = source.relative_to(root)
                raise ValueError(f"stock Worker registers a character outside core: {relative}")

    dependencies = {
        **worker_package.get("dependencies", {}),
        **worker_package.get("devDependencies", {}),
    }
    for name, specifier in dependencies.items():
        if not isinstance(specifier, str) or not specifier.startswith("file:"):
            continue
        dependency = (root / "apps/worker" / specifier.removeprefix("file:")).resolve()
        if not dependency.is_relative_to(root):
            raise ValueError(
                f"Worker dependency {name} escapes the public repository: {specifier}"
            )
    for label, text in (
        ("Worker package", worker_package_text),
        ("Worker lockfile", worker_lock),
        ("Worker Dockerfile", dockerfile),
    ):
        if "boltrig-companion" in text or "file:../../../" in text:
            raise ValueError(f"{label} includes an operator-owned companion dependency")
    if "VITE_BOLTRIG_ENABLE_EXTERNAL_COMPANIONS" in dockerfile:
        raise ValueError("Worker Dockerfile exposes a dead companion build flag")
    _require(
        dockerfile,
        "Published Worker images always ship the stock companion set",
        label="Worker Dockerfile",
    )


def main() -> int:
    try:
        validate()
    except (OSError, ValueError) as exc:
        print(f"public-product: FAIL: {exc}", file=sys.stderr)
        return 1
    print("public-product: PASS (BYO Bifrost; Familiar + Jarvis only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
