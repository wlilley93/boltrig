"""Familiar genotype is a pure identity projection, never an authority source."""

import pytest

from boltrig.models.familiar import derive_familiar_genotype


@pytest.mark.invariant("SEC-WRK-10")
def test_agent_capability_name_derives_one_pinned_versioned_genotype():
    genotype = derive_familiar_genotype("local-worker")
    assert genotype.as_view() == {
        "source": "agent_capability.name.v1",
        "seed": 104173362,
        "body": "pioneer",
        "palette": ["#fce7f3", "#ec4899", "#831843"],
        "markings": ["orbit"],
        "accessories": ["signal-pin"],
        "voice_id": None,
    }
    assert derive_familiar_genotype("local-worker") == genotype


@pytest.mark.invariant("SEC-WRK-10")
def test_genotype_projection_contains_no_authority_or_runtime_state():
    view = derive_familiar_genotype("researcher").as_view()
    assert set(view) == {
        "source",
        "seed",
        "body",
        "palette",
        "markings",
        "accessories",
        "voice_id",
    }
    assert not {
        "tenant_id",
        "runtime",
        "skills",
        "grants",
        "model_endpoint",
        "cost_tier",
        "phenotype",
        "mood",
    } & set(view)
