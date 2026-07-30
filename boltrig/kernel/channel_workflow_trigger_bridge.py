"""Small channel-intake bridge to workflow-trigger delivery."""

from fastapi.responses import JSONResponse

from .workflow_trigger_delivery import deliver_channel_workflow_triggers


async def bound_event_response(
    hitl_reply,
    kernel,
    channel,
    principal,
    external_user_id: str,
    delivery_id: str,
    body: dict,
    reply_route: dict,
    request,
) -> JSONResponse | None:
    hitl_response = await hitl_reply(
        kernel,
        channel,
        principal,
        external_user_id,
        body,
        reply_route,
    )
    if hitl_response is not None:
        return hitl_response
    triggered = await deliver_channel_workflow_triggers(
        kernel,
        channel,
        principal,
        delivery_id,
        body,
        request,
    )
    if not triggered:
        return None
    return JSONResponse(
        {"status": "workflow_trigger", "triggers": triggered},
        status_code=202,
    )
