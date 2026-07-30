"""Worker approval-policy evidence names active and inactive fields exactly."""

from fastapi.testclient import TestClient

from boltrig.config.manifest import HitlConfig
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.store import InMemoryStore


def test_hitl_policy_projection_does_not_claim_routing_consumers() -> None:
    policy = HitlConfig(
        primary_channel="slack",
        notify_via=("slack", "email"),
        approval_timeout_seconds=900,
        escalation_chain=("team-lead", "owner"),
        blocking_verbs=("finance.transfer", "device.write"),
    )
    client = TestClient(
        create_app(
            Kernel(InMemoryStore()),
            platform={"hitl_policy": policy},
        )
    )
    author = {
        "x-boltrig-tenant": "acme",
        "x-boltrig-subject": "author",
        "x-boltrig-role": "org-admin",
    }

    response = client.get("/v1/hitl/policy", headers=author)
    assert response.status_code == 200
    projected = response.json()["policy"]
    assert projected["blocking_verbs"] == ["device.write", "finance.transfer"]
    assert projected["approval_timeout_seconds"] == 900
    assert projected["routing"] == {
        "primary_channel": "slack",
        "notify_via": ["slack", "email"],
        "escalation_chain": ["team-lead", "owner"],
        "serving_state": "inactive_no_consumer",
    }
    assert projected["changes_apply_at"] == "process_restart"
    assert len(projected["generation"]) == 64
    assert client.get(
        "/v1/hitl/policy",
        headers={**author, "x-boltrig-role": "member"},
    ).status_code == 403
