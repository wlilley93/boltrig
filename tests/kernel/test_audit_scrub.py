"""K-20: the audit scrubber recurses into list/tuple detail values."""

from boltrig.kernel.audit import _scrub


def test_scrub_redacts_secrets_inside_lists_and_tuples():
    secret = "sk-ant-abcdefghijklmnopqrstuvwxyz"
    out = _scrub(
        {
            "items": [secret, "plain", {"nested": [secret]}],
            "pair": (secret, 42),
        }
    )
    assert out["items"][0]["_scrubbed"] is True
    assert out["items"][0]["size"] == len(secret)
    assert out["items"][1] == "plain"
    assert out["items"][2]["nested"][0]["_scrubbed"] is True
    assert out["pair"][0]["_scrubbed"] is True
    assert out["pair"][1] == 42
    assert secret not in str(out)
