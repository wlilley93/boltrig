"""Opt-in live adapter reads (P2-1). Skipped unless BOLTRIG_LIVE_SMOKE=1 and the
per-adapter credential env is present; never runs in the offline suite / CI.

These exercise one real read verb per builtin adapter through the secret-ref path
(credentials are passed as resolved material, never inlined in code)."""

import json
import os

import pytest

from boltrig.adapters.base import Credential
from boltrig.models import GrantSet, InvocationContext

pytestmark = pytest.mark.skipif(
    os.environ.get("BOLTRIG_LIVE_SMOKE") not in {"1", "true", "yes"},
    reason="set BOLTRIG_LIVE_SMOKE=1 (and per-adapter creds) to run live adapter reads",
)

_TARGETS = [
    ("boltrig.adapters.builtin.jira", "ticket.search",
     {"jql": "order by created DESC", "max_results": 1}, "JIRA_OAUTH", "oauth"),
    ("boltrig.adapters.builtin.ms_graph", "directory.get_user",
     {"id": "me"}, "GRAPH_APP", "oauth"),
    ("boltrig.adapters.builtin.crm_sql", "contact.search",
     {"query": ""}, "CRM_DB_RO", "basic"),
]


def _ctx(verb):
    noun = verb.split(".")[0]
    return InvocationContext(tenant_id="acme", grants=GrantSet.of([f"{noun}.read"]), actor="smoke")


@pytest.mark.parametrize("module_path,verb,params,cred_env,kind", _TARGETS)
async def test_live_adapter_read(module_path, verb, params, cred_env, kind):
    import importlib

    raw = os.environ.get(cred_env)
    if not raw:
        pytest.skip(f"{cred_env} not set")
    adapter = importlib.import_module(module_path).build()
    material = json.loads(raw) if raw.strip().startswith("{") else {"value": raw}
    cred = Credential(id=module_path, kind=kind, material=material)
    result = await adapter.execute(verb, params, cred, _ctx(verb))
    assert result.ok, None if result.ok else f"{result.error.error_class}: {result.error.message}"
