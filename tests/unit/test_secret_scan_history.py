from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import check_secret_scan_history as gate


def completed(*, returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        ["git", "rev-list"], returncode, stdout=stdout, stderr=stderr
    )


def test_complete_history_passes(monkeypatch, capsys):
    monkeypatch.setattr(gate, "revision_walk", lambda: completed(stdout="abc path\ndef other\n"))

    assert gate.main() == 0
    assert "complete Git object graph available" in capsys.readouterr().out


def test_promised_objects_refuse_instead_of_scanning_a_subset(monkeypatch, capsys):
    monkeypatch.setattr(
        gate,
        "revision_walk",
        lambda: completed(stdout="abc path\n?missing-one\n?missing-two\n"),
    )

    assert gate.main() == 1
    assert "2 promised object(s) missing" in capsys.readouterr().err


def test_failed_revision_walk_refuses(monkeypatch, capsys):
    monkeypatch.setattr(
        gate,
        "revision_walk",
        lambda: completed(returncode=128, stderr="fatal: corrupt object graph\n"),
    )

    assert gate.main() == 1
    assert "fatal: corrupt object graph" in capsys.readouterr().err


def test_make_target_preflights_history_before_gitleaks():
    makefile = (Path(__file__).parents[2] / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("secret-scan:", 1)[1].split("\n\n", 1)[0]

    assert target.index("check_secret_scan_history.py") < target.index("gitleaks")
