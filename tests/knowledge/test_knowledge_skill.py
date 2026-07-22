from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from boltrig.skills.schema import parse_skill


@pytest.mark.invariant("KNO-01")
def test_codex_knowledge_skill_is_read_only_and_requires_citations() -> None:
    path = Path("libraries/skills/knowledge/retrieval.yaml")
    skill = parse_skill(yaml.safe_load(path.read_text(encoding="utf-8")), "test")

    assert skill.tool_grants == [
        "knowledge.asset.list",
        "knowledge.asset.get",
        "knowledge.asset.original",
        "knowledge.search",
        "knowledge.context.build",
    ]
    assert "citation" in skill.prompt_fragment.lower()
    assert "untrusted source content" in skill.prompt_fragment.lower()
    assert not any(grant.endswith(("upload.begin", "commit", "erase")) for grant in skill.tool_grants)
