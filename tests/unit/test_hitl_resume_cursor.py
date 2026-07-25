import pytest

from boltrig.kernel.events import EventRelay
from boltrig.models import HITLType
from boltrig.kernel import hitl_http
from boltrig.kernel.hitl_http import respond_to_hitl


class _Req:
    def __init__(self, run_id):
        self.id = "req-1"
        self.run_id = run_id
        self.type = HITLType.APPROVAL
        self.verb = "row.update"


class _Resp:
    id = "resp-1"


class _Hitl:
    def __init__(self, req, relay, run_id):
        self._req, self._relay, self._run = req, relay, run_id
    async def get(self, tenant, request_id):
        return self._req
    async def answer(self, tenant, request_id, decision, subject, notes=""):
        # the resume lane publishes AFTER the decision is recorded
        self._relay.publish(tenant, self._run, {"type": "tool_result", "call_id": "c1"})
        self._relay.publish(tenant, self._run, {"type": "message_end"})
        return _Resp()


class _Kernel:
    def __init__(self, relay, hitl):
        self.events, self.hitl = relay, hitl


class _P:
    tenant_id = "t1"
    subject = "u1"
    actor_tier = "human"
    on_behalf_of = None


def _async(v):
    async def _f(*a, **k):
        return v
    return _f


@pytest.mark.asyncio
async def test_respond_returns_pre_resume_cursor(monkeypatch):
    relay = EventRelay()
    run = "run-1"
    relay.publish("t1", run, {"type": "text_delta", "delta": "hi"})      # seq 1
    relay.publish("t1", run, {"type": "tool_call", "call_id": "c1"})       # seq 2
    relay.publish("t1", run, {"type": "hitl", "hitl_request_id": "req-1"}) # seq 3 (marker)
    kernel = _Kernel(relay, _Hitl(_Req(run), relay, run))
    monkeypatch.setattr(hitl_http, "authorize_hitl_response", _async(False))
    result = await respond_to_hitl(kernel, _P(), "req-1", "approve", "")
    assert result["resume_since"] == 3          # captured before the 2 resume frames
    assert result["run_id"] == run
    assert relay.max_seq("t1", run) == 5         # resume advanced to seq 5
    # the continuation is exactly what a ?since=<resume_since> replay would yield
    cont = [e["type"] for e in relay.snapshot("t1", run, since=result["resume_since"])]
    assert cont == ["tool_result", "message_end"]


@pytest.mark.asyncio
async def test_respond_without_relay_omits_resume_since(monkeypatch):
    class _NoEvents:
        def __init__(self, hitl):
            self.hitl = hitl  # no .events attribute
    kernel = _NoEvents(_Hitl(_Req("run-x"), EventRelay(), "run-x"))
    monkeypatch.setattr(hitl_http, "authorize_hitl_response", _async(False))
    result = await respond_to_hitl(kernel, _P(), "req-1", "approve", "")
    assert "resume_since" not in result       # fail-safe -> caller falls back
