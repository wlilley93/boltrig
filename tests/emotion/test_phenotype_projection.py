"""EMO-7: the Worker phenotype projection is bounded, content-free, and fails
toward resting - never toward an error the client could mistake for a fault."""

from __future__ import annotations

import json
import os
import time

import pytest

from boltrig.kernel.familiar_phenotype_routes import (
    PHENOTYPE_SCALARS,
    read_phenotype_projection,
)

RESTING = {"v": 1, "fresh": False, "phenotype": None}


def _write(path, document, mtime=None):
    path.write_text(json.dumps(document))
    if mtime is not None:
        os.utime(path, (mtime, mtime))


@pytest.mark.invariant("EMO-7")
def test_missing_stale_or_malformed_files_all_answer_resting(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    now = time.time()
    # no file at all
    assert read_phenotype_projection(now) == RESTING
    # no runtime dir
    monkeypatch.setenv("XDG_RUNTIME_DIR", "")
    assert read_phenotype_projection(now) == RESTING
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = tmp_path / "boltrig-phenotype.json"
    # malformed JSON
    path.write_text("{not json")
    assert read_phenotype_projection(now) == RESTING
    # stale file
    _write(path, {"v": 1, "phenotype": {"valence": 0.7}}, mtime=now - 60)
    assert read_phenotype_projection(now) == RESTING
    # oversized file
    path.write_text("0" * 8192)
    assert read_phenotype_projection(now) == RESTING
    # wrong shape
    _write(path, {"v": 1, "phenotype": "cheerful"}, mtime=now)
    assert read_phenotype_projection(now) == RESTING


@pytest.mark.invariant("EMO-7")
def test_projection_is_whitelisted_clamped_and_content_free(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    now = time.time()
    sentinel = "the user said something private"
    document = {
        "v": 1,
        "ts": now,
        "phenotype": {
            "valence": 0.66,
            "arousal": 7.0,            # clamps to 1
            "tension": -3.0,           # clamps to 0
            "fatigue": float("nan"),   # dropped
            "attachment": 0.4,         # tenth scalar (decision 0024)
            "note": sentinel,          # never passes the whitelist
            "transcript": [sentinel],
        },
    }
    _write(tmp_path / "boltrig-phenotype.json", document, mtime=now)
    projection = read_phenotype_projection(now)
    assert projection["fresh"] is True
    scalars = projection["phenotype"]
    assert scalars["valence"] == 0.66
    assert scalars["arousal"] == 1.0
    assert scalars["tension"] == 0.0
    assert "fatigue" not in scalars
    assert scalars["attachment"] == 0.4
    assert set(scalars) <= set(PHENOTYPE_SCALARS)
    assert sentinel not in json.dumps(projection)


@pytest.mark.invariant("EMO-7")
def test_projection_module_never_imports_the_emotion_package():
    import ast
    import importlib

    module = importlib.import_module("boltrig.kernel.familiar_phenotype_routes")
    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [a.name for a in node.names if a.name.startswith("boltrig.emotion")]
        elif isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if name.startswith("boltrig.emotion") or (node.level and "emotion" in name):
                offenders.append(name)
    assert offenders == []
