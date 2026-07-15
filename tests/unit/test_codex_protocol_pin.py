from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import check_codex_protocol

REPO_ROOT = Path(__file__).resolve().parents[2]
PIN_ROOT = REPO_ROOT / "schemas/codex/0.144.3"


def _copy_pin(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(PIN_ROOT, root / "schemas/codex/0.144.3")
    return root


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
        "verification": "recorded-evidence",
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
    verification = check_codex_protocol.check_repository(REPO_ROOT)
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
        shutil.copy2(verification.schema_path, output / verification.pin.root_file)
        for index in range(verification.pin.generated_file_count - 1):
            (output / f"schema-{index:03}.json").write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(check_codex_protocol, "_run", fake_run)

    check_codex_protocol.verify_codex_cli(fake, verification)

    generation = commands[1]
    assert generation[1:4] == ["app-server", "generate-json-schema", "--out"]
    assert "--experimental" not in generation
