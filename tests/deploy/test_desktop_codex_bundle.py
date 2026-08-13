from __future__ import annotations

import io
from pathlib import Path
import sys
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import stage_desktop_codex as stage  # noqa: E402


@pytest.mark.invariant("SEC-198")
def test_release_stages_one_exact_platform_codex_tree_and_runtime_rechecks_it() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    native = (
        ROOT / "apps/worker/src-tauri/src/local_agent.rs"
    ).read_text(encoding="utf-8")

    assert set(stage.PLATFORMS) == {
        "darwin-aarch64",
        "linux-x86_64",
        "windows-x86_64",
    }
    for platform, spec in stage.PLATFORMS.items():
        assert len(spec["archive_sha256"]) == 64, platform
        assert len(spec["binary_sha256"]) == 64, platform
        assert spec["binary_sha256"] in native
        assert spec["triple"] in native
    assert "python scripts/stage_desktop_codex.py" in workflow
    assert 'resources/codex")]: "codex"' in workflow
    assert "desktop-codex-receipt.json" in workflow
    assert "bundled_binary_sha256(path)?" in native
    assert "local_agent_binary_digest_mismatch" in native


@pytest.mark.invariant("SEC-198")
def test_desktop_codex_extractor_refuses_links_and_parent_paths(tmp_path: Path) -> None:
    for name, kind in (("package/link", "link"), ("package/../escape", "file")):
        archive = tmp_path / f"{kind}.tgz"
        with tarfile.open(archive, "w:gz") as bundle:
            member = tarfile.TarInfo(name)
            if kind == "link":
                member.type = tarfile.SYMTYPE
                member.linkname = "/tmp/escape"
                bundle.addfile(member)
            else:
                payload = b"escape"
                member.size = len(payload)
                bundle.addfile(member, io.BytesIO(payload))
        with pytest.raises(stage.StageError):
            stage._extract(archive, tmp_path / f"out-{kind}")
