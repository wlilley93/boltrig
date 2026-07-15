#!/usr/bin/env python3
"""Verify Boltrig's exact Codex App Server protocol and binary pin."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, cast

ROOT = Path(__file__).resolve().parent.parent
PIN_DIRECTORY = Path("schemas/codex/0.144.3")
MANIFEST_FILE = "manifest.json"

PIN_VERSION = "0.144.3"
PIN_TARGET = "x86_64-unknown-linux-musl"
PIN_BINARY_SHA256 = "37e6f5953f191b04f7b62cb07dae90f51d0947ad89f0355665b421fbde28700b"
PIN_SCHEMA_FILE = "codex_app_server_protocol.v2.schemas.json"
PIN_SCHEMA_SHA256 = "66ab7534f29e1ee7c065eb15c799d5f6e93fdd1d0ba86c262c3842a6a8f3d0c8"
PIN_BUNDLE_FILE_COUNT = 267
PIN_BUNDLE_SHA256 = "0194f4370fd6ec268f81270217b56b2d1133ecc2c2a1560f3870dd6ec16e9810"
PIN_TRANSPORTS = ("stdio", "private-unix-socket")


class ProtocolPinError(RuntimeError):
    """The checked-in or installed Codex protocol does not match the pin."""


@dataclass(frozen=True)
class ProtocolPin:
    version: str
    target: str
    binary_sha256: str
    root_file: str
    schema_sha256: str
    generated_file_count: int


@dataclass(frozen=True)
class Verification:
    pin: ProtocolPin
    schema_path: Path


def _reject_non_finite(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    try:
        source = path.read_text(encoding="utf-8")
        return cast(
            object,
            json.loads(
                source,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_non_finite,
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProtocolPinError(f"cannot read strict JSON from {path}: {exc}") from exc


def _as_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProtocolPinError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _exact_keys(value: dict[str, object], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ProtocolPinError(f"{label} keys mismatch; missing={missing}, extra={extra}")


def _exact(value: object, expected: object, label: str) -> None:
    if type(value) is not type(expected) or value != expected:
        raise ProtocolPinError(f"{label} must be {expected!r}; got {value!r}")


def _load_manifest(path: Path) -> ProtocolPin:
    manifest = _as_object(_read_json(path), "protocol manifest")
    _exact_keys(manifest, {"manifestVersion", "codex", "appServer", "schema"}, "manifest")
    _exact(manifest["manifestVersion"], 1, "manifestVersion")

    codex = _as_object(manifest["codex"], "codex")
    _exact_keys(codex, {"version", "target", "binarySha256"}, "codex")
    _exact(codex["version"], PIN_VERSION, "codex.version")
    _exact(codex["target"], PIN_TARGET, "codex.target")
    _exact(codex["binarySha256"], PIN_BINARY_SHA256, "codex.binarySha256")

    app_server = _as_object(manifest["appServer"], "appServer")
    _exact_keys(app_server, {"experimentalApi", "transport"}, "appServer")
    _exact(app_server["experimentalApi"], False, "appServer.experimentalApi")
    transport = _as_object(app_server["transport"], "appServer.transport")
    _exact_keys(transport, {"allowed", "remoteWebSocketAllowed"}, "appServer.transport")
    _exact(transport["allowed"], list(PIN_TRANSPORTS), "appServer.transport.allowed")
    _exact(transport["remoteWebSocketAllowed"], False, "remote WebSocket policy")

    schema = _as_object(manifest["schema"], "schema")
    _exact_keys(
        schema,
        {"generator", "rootFile", "canonicalization", "canonicalSha256", "bundleProbe"},
        "schema",
    )
    _exact(
        schema["generator"],
        ["app-server", "generate-json-schema", "--out", "<dir>"],
        "schema.generator",
    )
    _exact(schema["rootFile"], PIN_SCHEMA_FILE, "schema.rootFile")
    _exact(schema["canonicalization"], "json-sort-keys-compact-lf-v1", "canonicalization")
    _exact(schema["canonicalSha256"], PIN_SCHEMA_SHA256, "schema.canonicalSha256")
    bundle = _as_object(schema["bundleProbe"], "schema.bundleProbe")
    _exact_keys(bundle, {"fileCount", "canonicalSha256", "verification"}, "bundleProbe")
    _exact(bundle["fileCount"], PIN_BUNDLE_FILE_COUNT, "bundleProbe.fileCount")
    _exact(bundle["canonicalSha256"], PIN_BUNDLE_SHA256, "bundleProbe.canonicalSha256")
    _exact(bundle["verification"], "recorded-evidence", "bundleProbe.verification")
    return ProtocolPin(
        version=PIN_VERSION,
        target=PIN_TARGET,
        binary_sha256=PIN_BINARY_SHA256,
        root_file=PIN_SCHEMA_FILE,
        schema_sha256=PIN_SCHEMA_SHA256,
        generated_file_count=PIN_BUNDLE_FILE_COUNT,
    )


def _canonical_json_sha256(value: object) -> str:
    try:
        payload = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise ProtocolPinError(f"cannot canonicalize JSON: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise ProtocolPinError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _validate_root_schema(path: Path, expected_sha256: str) -> None:
    schema = _as_object(_read_json(path), "Codex stable-v2 root schema")
    _exact(schema.get("title"), "CodexAppServerProtocolV2", "root schema title")
    _exact(schema.get("$schema"), "http://json-schema.org/draft-07/schema#", "schema dialect")
    definitions = _as_object(schema.get("definitions"), "root schema definitions")
    if not definitions:
        raise ProtocolPinError("Codex stable-v2 root schema has no definitions")
    actual_sha256 = _canonical_json_sha256(schema)
    if actual_sha256 != expected_sha256:
        raise ProtocolPinError(
            f"stable-v2 schema digest mismatch; expected {expected_sha256}, got {actual_sha256}"
        )


def check_repository(root: Path = ROOT) -> Verification:
    pin_root = root / PIN_DIRECTORY
    pin = _load_manifest(pin_root / MANIFEST_FILE)
    relative_schema = Path(pin.root_file)
    if relative_schema.is_absolute() or len(relative_schema.parts) != 1:
        raise ProtocolPinError("schema.rootFile must be a single relative file name")
    schema_path = pin_root / relative_schema
    if schema_path.is_symlink() or not schema_path.is_file():
        raise ProtocolPinError(f"pinned root schema must be a regular non-symlink file: {schema_path}")
    _validate_root_schema(schema_path, pin.schema_sha256)
    return Verification(pin=pin, schema_path=schema_path)


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProtocolPinError(f"Codex verification command failed: {exc}") from exc


def verify_codex_cli(codex: Path, verification: Verification) -> None:
    if codex.is_symlink() or not codex.is_file() or not os.access(codex, os.X_OK):
        raise ProtocolPinError(f"Codex CLI must be an executable regular non-symlink file: {codex}")
    binary_sha256 = _file_sha256(codex)
    if binary_sha256 != verification.pin.binary_sha256:
        raise ProtocolPinError(
            "Codex binary digest mismatch; "
            f"expected {verification.pin.binary_sha256}, got {binary_sha256}"
        )
    with tempfile.TemporaryDirectory(prefix="boltrig-codex-pin-") as temporary:
        temp_root = Path(temporary)
        home = temp_root / "home"
        codex_home = home / ".codex"
        output = temp_root / "schema"
        codex_home.mkdir(parents=True)
        output.mkdir()
        env = {
            "CODEX_HOME": str(codex_home),
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": os.defpath,
        }
        version = _run([str(codex), "--version"], cwd=temp_root, env=env)
        expected_version = f"codex-cli {verification.pin.version}"
        if version.returncode != 0 or version.stdout.strip() != expected_version:
            raise ProtocolPinError(
                f"Codex version mismatch; expected {expected_version!r}, "
                f"got stdout={version.stdout.strip()!r}, stderr={version.stderr.strip()!r}"
            )
        generated = _run(
            [str(codex), "app-server", "generate-json-schema", "--out", str(output)],
            cwd=temp_root,
            env=env,
        )
        if generated.returncode != 0:
            raise ProtocolPinError(
                f"stable schema generation failed: {generated.stderr.strip() or generated.stdout.strip()}"
            )
        files = tuple(path for path in output.rglob("*") if path.is_file())
        if len(files) != verification.pin.generated_file_count:
            raise ProtocolPinError(
                "stable schema bundle file count mismatch; "
                f"expected {verification.pin.generated_file_count}, got {len(files)}"
            )
        _validate_root_schema(output / verification.pin.root_file, verification.pin.schema_sha256)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument(
        "--codex",
        type=Path,
        help="also verify this exact installed Codex binary and its generated stable schema",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verification = check_repository(args.root)
        if args.codex is not None:
            verify_codex_cli(args.codex, verification)
    except ProtocolPinError as exc:
        print(f"Codex protocol pin check failed: {exc}", file=sys.stderr)
        return 1
    scope = "repository and installed CLI" if args.codex is not None else "repository"
    print(
        f"Codex protocol pin clean ({scope}): "
        f"version={verification.pin.version}, target={verification.pin.target}, "
        f"stable-v2={verification.pin.schema_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
