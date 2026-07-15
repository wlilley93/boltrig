from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import check_codex_protocol

REPO_ROOT = Path(__file__).resolve().parents[2]
PIN_ROOT = REPO_ROOT / "schemas/codex/0.144.3"


def _copy_pin(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(PIN_ROOT, root / "schemas/codex/0.144.3")
    return root


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _synthetic_bundle(
    tmp_path: Path,
) -> tuple[Path, check_codex_protocol.Verification]:
    verification = check_codex_protocol.check_repository(REPO_ROOT)
    bundle = tmp_path / "reference-bundle"
    bundle.mkdir()
    shutil.copy2(verification.schema_path, bundle / verification.pin.root_file)
    _write_json(
        bundle / "ServerRequest.json",
        {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "properties": {"id": {"type": "string"}, "method": {"type": "string"}},
            "required": ["id", "method"],
            "title": "ServerRequest",
            "type": "object",
        },
    )
    _write_json(
        bundle / "v2/ThreadStartParams.json",
        {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "properties": {"cwd": {"type": "string"}},
            "required": ["cwd"],
            "title": "ThreadStartParams",
            "type": "object",
        },
    )
    bundle_sha256, file_count = check_codex_protocol._canonical_bundle_sha256(bundle)
    synthetic_pin = replace(
        verification.pin,
        generated_file_count=file_count,
        bundle_sha256=bundle_sha256,
    )
    return bundle, replace(verification, pin=synthetic_pin)


def _configure_fake_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bundle: Path,
    verification: check_codex_protocol.Verification,
    *,
    tamper_auxiliary: bool = False,
) -> tuple[Path, list[list[str]]]:
    fake = tmp_path / "codex"
    fake.write_text("pinned binary placeholder", encoding="utf-8")
    fake.chmod(0o755)
    commands: list[list[str]] = []

    monkeypatch.setattr(
        check_codex_protocol,
        "_file_sha256",
        lambda _path: verification.pin.binary_sha256,
    )

    def fake_run(
        command: list[str], *, cwd: Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env
        commands.append(command)
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "codex-cli 0.144.3\n", "")
        output = Path(command[-1])
        shutil.copytree(bundle, output, dirs_exist_ok=True)
        if tamper_auxiliary:
            request_path = output / "ServerRequest.json"
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["properties"]["authority"] = {"type": "string"}
            request_path.write_text(json.dumps(request), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(check_codex_protocol, "_run", fake_run)
    return fake, commands


@pytest.mark.invariant("FR-RUN-19")
def test_checked_in_codex_protocol_pin_is_exact() -> None:
    verification = check_codex_protocol.check_repository(REPO_ROOT)

    assert verification.pin == check_codex_protocol.ProtocolPin(
        version="0.144.3",
        target="x86_64-unknown-linux-musl",
        binary_sha256="37e6f5953f191b04f7b62cb07dae90f51d0947ad89f0355665b421fbde28700b",
        root_file="codex_app_server_protocol.v2.schemas.json",
        schema_sha256="66ab7534f29e1ee7c065eb15c799d5f6e93fdd1d0ba86c262c3842a6a8f3d0c8",
        generated_file_count=267,
        bundle_sha256="0194f4370fd6ec268f81270217b56b2d1133ecc2c2a1560f3870dd6ec16e9810",
    )
    assert verification.schema_path.is_file()


def test_manifest_records_stable_transport_and_bundle_probe() -> None:
    manifest = json.loads((PIN_ROOT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["appServer"] == {
        "experimentalApi": False,
        "transport": {
            "allowed": ["stdio", "private-unix-socket"],
            "remoteWebSocketAllowed": False,
        },
    }
    assert manifest["schema"]["bundleProbe"] == {
        "fileCount": 267,
        "canonicalSha256": "0194f4370fd6ec268f81270217b56b2d1133ecc2c2a1560f3870dd6ec16e9810",
        "verification": "enforced-relative-path-canonical-json-sha256-lines-v1",
    }


def test_semantically_changed_schema_fails_closed(tmp_path: Path) -> None:
    root = _copy_pin(tmp_path)
    schema_path = root / "schemas/codex/0.144.3/codex_app_server_protocol.v2.schemas.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["definitions"]["BoltrigTamper"] = {"type": "null"}
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    with pytest.raises(check_codex_protocol.ProtocolPinError, match="schema digest mismatch"):
        check_codex_protocol.check_repository(root)


@pytest.mark.parametrize(
    ("section", "key", "replacement", "message"),
    [
        ("codex", "version", "0.145.0", "codex.version"),
        ("appServer", "experimentalApi", True, "experimentalApi"),
        (
            "schema",
            "canonicalSha256",
            "0" * 64,
            "schema.canonicalSha256",
        ),
    ],
)
def test_manifest_drift_fails_closed(
    tmp_path: Path,
    section: str,
    key: str,
    replacement: object,
    message: str,
) -> None:
    root = _copy_pin(tmp_path)
    manifest_path = root / "schemas/codex/0.144.3/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[section][key] = replacement
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(check_codex_protocol.ProtocolPinError, match=message):
        check_codex_protocol.check_repository(root)


def test_manifest_unknown_field_fails_closed(tmp_path: Path) -> None:
    root = _copy_pin(tmp_path)
    manifest_path = root / "schemas/codex/0.144.3/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["unreviewedOverride"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(check_codex_protocol.ProtocolPinError, match="keys mismatch"):
        check_codex_protocol.check_repository(root)


def test_schema_must_be_regular_non_symlink_file(tmp_path: Path) -> None:
    root = _copy_pin(tmp_path)
    schema_path = root / "schemas/codex/0.144.3/codex_app_server_protocol.v2.schemas.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(schema_path.read_bytes())
    schema_path.unlink()
    schema_path.symlink_to(outside)

    with pytest.raises(check_codex_protocol.ProtocolPinError, match="non-symlink"):
        check_codex_protocol.check_repository(root)


def test_canonical_digest_ignores_json_format_and_key_order() -> None:
    left = {"z": [3, 2, 1], "a": {"right": True, "left": None}}
    right = {"a": {"left": None, "right": True}, "z": [3, 2, 1]}

    assert check_codex_protocol._canonical_json_sha256(left) == (
        check_codex_protocol._canonical_json_sha256(right)
    )


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"authority":"read","authority":"write"}', encoding="utf-8")

    with pytest.raises(check_codex_protocol.ProtocolPinError, match="duplicate JSON key"):
        check_codex_protocol._read_json(duplicate)


def test_non_finite_json_is_rejected(tmp_path: Path) -> None:
    non_finite = tmp_path / "non-finite.json"
    non_finite.write_text('{"limit": NaN}', encoding="utf-8")

    with pytest.raises(check_codex_protocol.ProtocolPinError, match="non-finite JSON"):
        check_codex_protocol._read_json(non_finite)


def test_bundle_digest_rejects_symlinks_and_non_json_files(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _write_json(bundle / "ServerRequest.json", {"title": "ServerRequest"})
    outside = tmp_path / "outside.json"
    _write_json(outside, {"title": "Outside"})
    (bundle / "linked.json").symlink_to(outside)

    with pytest.raises(check_codex_protocol.ProtocolPinError, match="must not contain symlinks"):
        check_codex_protocol._canonical_bundle_sha256(bundle)

    (bundle / "linked.json").unlink()
    (bundle / "README.txt").write_text("not schema JSON", encoding="utf-8")
    with pytest.raises(check_codex_protocol.ProtocolPinError, match="non-JSON file"):
        check_codex_protocol._canonical_bundle_sha256(bundle)


def test_bundle_digest_is_order_stable_and_path_sensitive(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    moved = tmp_path / "moved"
    for root in (left, right, moved):
        root.mkdir()
    _write_json(left / "A.json", {"title": "A", "type": "object"})
    _write_json(left / "v2/B.json", {"title": "B", "type": "object"})
    _write_json(right / "v2/B.json", {"type": "object", "title": "B"})
    _write_json(right / "A.json", {"type": "object", "title": "A"})
    _write_json(moved / "nested/A.json", {"title": "A", "type": "object"})
    _write_json(moved / "v2/B.json", {"title": "B", "type": "object"})

    left_digest, left_count = check_codex_protocol._canonical_bundle_sha256(left)
    right_digest, right_count = check_codex_protocol._canonical_bundle_sha256(right)
    moved_digest, moved_count = check_codex_protocol._canonical_bundle_sha256(moved)

    assert (left_digest, left_count) == (right_digest, right_count)
    assert moved_count == left_count
    assert moved_digest != left_digest


def test_cli_verification_rejects_wrong_binary_before_execution(tmp_path: Path) -> None:
    verification = check_codex_protocol.check_repository(REPO_ROOT)
    fake = tmp_path / "codex"
    fake.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    fake.chmod(0o755)

    with pytest.raises(check_codex_protocol.ProtocolPinError, match="binary digest mismatch"):
        check_codex_protocol.verify_codex_cli(fake, verification)


@pytest.mark.invariant("FR-RUN-19")
def test_cli_verification_generates_only_stable_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, verification = _synthetic_bundle(tmp_path)
    fake, commands = _configure_fake_cli(tmp_path, monkeypatch, bundle, verification)

    check_codex_protocol.verify_codex_cli(fake, verification)

    generation = commands[1]
    assert generation[1:4] == ["app-server", "generate-json-schema", "--out"]
    assert "--experimental" not in generation


def test_cli_verification_rejects_changed_auxiliary_schema_with_same_count_and_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, verification = _synthetic_bundle(tmp_path)
    fake, _commands = _configure_fake_cli(
        tmp_path,
        monkeypatch,
        bundle,
        verification,
        tamper_auxiliary=True,
    )

    with pytest.raises(check_codex_protocol.ProtocolPinError, match="bundle digest mismatch"):
        check_codex_protocol.verify_codex_cli(fake, verification)
