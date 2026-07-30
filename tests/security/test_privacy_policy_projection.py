"""Privacy policy projection preserves the exact partial enforcement boundary."""

from fastapi.testclient import TestClient

from boltrig.config.manifest import PrivacyConfig
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.store import InMemoryStore


def test_privacy_projection_labels_parsed_only_rules_inactive() -> None:
    client = TestClient(
        create_app(
            Kernel(InMemoryStore()),
            platform={
                "privacy_policy": PrivacyConfig(
                    pii_redaction=True,
                    data_residency="gb",
                    retention_days=30,
                    redact_fields=("email", "phone"),
                )
            },
        )
    )
    headers = {
        "x-boltrig-tenant": "acme",
        "x-boltrig-subject": "alice",
        "x-boltrig-role": "member",
    }

    response = client.get("/v1/privacy/policy", headers=headers)
    assert response.status_code == 200
    policy = response.json()["policy"]
    assert policy["state"] == "partial"
    assert policy["retention"] == {
        "days": 30,
        "serving_state": "closed_conversations_only",
        "coverage": ["closed_conversation_messages"],
    }
    assert policy["redaction"] == {
        "configured": True,
        "fields": ["email", "phone"],
        "serving_state": "inactive_no_consumer",
    }
    assert policy["residency"] == {
        "region": "gb",
        "serving_state": "inactive_no_consumer",
    }
    assert policy["compliance_export"] == "account_summary_only"
    assert len(policy["generation"]) == 64
