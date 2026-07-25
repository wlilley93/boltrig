"""Microsoft Graph adapter (US-ADP-02).

ONE authenticated connection (an OAuth bearer token resolved by the kernel)
exposes document / email / calendar / chat / directory verbs spanning
SharePoint, OneDrive, Exchange, Teams and Entra (Azure AD) directory, all
through the single Graph endpoint. This is the canonical "one connection, many
surfaces" adapter.

Real Graph URLs and request shapes are used (https://graph.microsoft.com/v1.0).
Actual network calls are implemented; without a valid credential or network they
fail gracefully: the call is attempted and a transport failure / 401 is mapped
to UNAVAILABLE / UNAUTHORISED by :class:`HttpAdapter`, never an exception.

Auth: ``Credential`` with bearer material (``access_token`` or ``token``). The
material is turned into an ``Authorization: Bearer`` header by the base and is
never logged (SEC-05, K-20).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from boltrig.adapters.base import Result, VerbSpec
from boltrig.adapters.http_base import Handler, HttpAdapter, RateLimitConfig
from boltrig.models import InvocationContext

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_DRIVE_ITEM_OUT = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "webUrl": {"type": "string"},
        "size": {"type": "integer"},
    },
    "required": ["id"],
}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


class MsGraphAdapter(HttpAdapter):
    id = "ms-graph"
    version = "1.0.0"
    user_agent = "boltrig-msgraph/1.0"

    def __init__(self, base_url: str = _GRAPH_BASE) -> None:
        super().__init__(
            base_url=base_url,
            rate_limit=RateLimitConfig(max=1000, per="minute", scope="tenant"),
        )

    # --- verbs ---------------------------------------------------------------
    def describe(self) -> list[VerbSpec]:
        read_rl = {"per": "minute", "max": 1000, "scope": "tenant"}
        write_rl = {"per": "minute", "max": 200, "scope": "tenant"}
        send_rl = {"per": "minute", "max": 30, "scope": "tenant"}
        return [
            VerbSpec(
                verb_id="document.search",
                noun_id="document",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "size": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                    "required": ["query"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "results": {"type": "array"},
                        "count": {"type": "integer"},
                    },
                },
                description="Search documents across SharePoint / OneDrive (Graph search API)",
                rate_limit=read_rl,
                degraded_mode={"strategy": "empty", "output": {"results": [], "count": 0}},
            ),
            VerbSpec(
                verb_id="document.read",
                noun_id="document",
                input_schema={
                    "type": "object",
                    "properties": {
                        "drive_id": {"type": "string"},
                        "item_id": {"type": "string"},
                    },
                    "required": ["drive_id", "item_id"],
                },
                output_schema=_DRIVE_ITEM_OUT,
                description="Read a drive item's metadata",
                rate_limit=read_rl,
            ),
            VerbSpec(
                verb_id="document.create",
                noun_id="document",
                input_schema={
                    "type": "object",
                    "properties": {
                        "drive_id": {"type": "string"},
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "content_type": {"type": "string"},
                    },
                    "required": ["drive_id", "path", "content"],
                },
                output_schema=_DRIVE_ITEM_OUT,
                description="Upload a small file to a drive path",
                rate_limit=write_rl,
                # Writes into the customer's drive (see the guard in
                # tests/security/test_builtin_write_verbs_are_gated.py).
                consequence="high",
            ),
            VerbSpec(
                verb_id="document.update",
                noun_id="document",
                input_schema={
                    "type": "object",
                    "properties": {
                        "drive_id": {"type": "string"},
                        "item_id": {"type": "string"},
                        "name": {"type": "string"},
                        "fields": {"type": "object"},
                    },
                    "required": ["drive_id", "item_id"],
                },
                output_schema=_DRIVE_ITEM_OUT,
                description="Update a drive item's metadata",
                rate_limit=write_rl,
                consequence="high",
            ),
            VerbSpec(
                verb_id="email.send",
                noun_id="email",
                input_schema={
                    "type": "object",
                    "properties": {
                        "to": {"type": ["array", "string"]},
                        "cc": {"type": ["array", "string"]},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                        "body_type": {"type": "string", "enum": ["Text", "HTML"]},
                        "from_user": {"type": "string"},
                        "save_to_sent": {"type": "boolean"},
                    },
                    "required": ["to", "subject", "body"],
                },
                output_schema={
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                },
                consequence="high",
                description="Send an email via Exchange Online (sendMail)",
                rate_limit=send_rl,
            ),
            VerbSpec(
                verb_id="calendar.create_event",
                noun_id="calendar",
                input_schema={
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "timezone": {"type": "string"},
                        "attendees": {"type": ["array", "string"]},
                        "location": {"type": "string"},
                        "body": {"type": "string"},
                        "owner": {"type": "string"},
                    },
                    "required": ["subject", "start", "end"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "webLink": {"type": "string"},
                    },
                    "required": ["id"],
                },
                consequence="high",
                description="Create a calendar event (Exchange / Outlook)",
                rate_limit=write_rl,
            ),
            VerbSpec(
                verb_id="chat.post_message",
                noun_id="chat",
                input_schema={
                    "type": "object",
                    "properties": {
                        "chat_id": {"type": "string"},
                        "content": {"type": "string"},
                        "content_type": {"type": "string", "enum": ["text", "html"]},
                    },
                    "required": ["chat_id", "content"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "createdDateTime": {"type": "string"},
                    },
                    "required": ["id"],
                },
                consequence="high",
                description="Post a message to a Teams chat",
                rate_limit=write_rl,
            ),
            VerbSpec(
                verb_id="directory.get_user",
                noun_id="directory",
                input_schema={
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "select": {"type": ["array", "string"]},
                    },
                    "required": ["user_id"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "displayName": {"type": "string"},
                        "mail": {"type": "string"},
                        "userPrincipalName": {"type": "string"},
                    },
                    "required": ["id"],
                },
                description="Read a directory user from Entra ID",
                rate_limit=read_rl,
            ),
        ]

    def _handlers(self) -> dict[str, Handler]:
        return {
            "document.search": self._document_search,
            "document.read": self._document_read,
            "document.create": self._document_create,
            "document.update": self._document_update,
            "email.send": self._email_send,
            "calendar.create_event": self._calendar_create_event,
            "chat.post_message": self._chat_post_message,
            "directory.get_user": self._directory_get_user,
        }

    # --- handlers ------------------------------------------------------------
    async def _document_search(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        body = {
            "requests": [
                {
                    "entityTypes": ["driveItem"],
                    "query": {"queryString": params["query"]},
                    "from": int(params.get("offset", 0)),
                    "size": int(params.get("size", 25)),
                }
            ]
        }
        data = await self.request(client, "POST", "/search/query", json=body, expected=(200,))
        results: list[dict[str, Any]] = []
        for response in data.get("value") or []:
            for container in response.get("hitsContainers") or []:
                for hit in container.get("hits") or []:
                    resource = hit.get("resource") or {}
                    results.append(
                        {
                            "id": resource.get("id"),
                            "name": resource.get("name"),
                            "webUrl": resource.get("webUrl"),
                            "summary": hit.get("summary"),
                        }
                    )
        return Result.success({"results": results, "count": len(results)})

    async def _document_read(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        url = f"/drives/{quote(str(params['drive_id']), safe='')}/items/{quote(str(params['item_id']), safe='')}"
        data = await self.request(client, "GET", url, expected=(200,))
        return Result.success(data)

    async def _document_create(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        path = str(params["path"]).lstrip("/")
        url = f"/drives/{quote(str(params['drive_id']), safe='')}/items/root:/{quote(path, safe='/')}:/content"
        content = params["content"]
        raw = content.encode("utf-8") if isinstance(content, str) else content
        headers = {"Content-Type": params.get("content_type", "text/plain")}
        data = await self.request(
            client, "PUT", url, content=raw, headers=headers, expected=(200, 201)
        )
        return Result.success(data)

    async def _document_update(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        url = f"/drives/{quote(str(params['drive_id']), safe='')}/items/{quote(str(params['item_id']), safe='')}"
        patch: dict[str, Any] = dict(params.get("fields") or {})
        if "name" in params:
            patch["name"] = params["name"]
        data = await self.request(client, "PATCH", url, json=patch, expected=(200,))
        return Result.success(data)

    async def _email_send(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        message: dict[str, Any] = {
            "subject": params["subject"],
            "body": {
                "contentType": params.get("body_type", "Text"),
                "content": params["body"],
            },
            "toRecipients": [
                {"emailAddress": {"address": addr}} for addr in _as_list(params["to"])
            ],
        }
        if params.get("cc"):
            message["ccRecipients"] = [
                {"emailAddress": {"address": addr}} for addr in _as_list(params["cc"])
            ]
        body = {
            "message": message,
            "saveToSentItems": bool(params.get("save_to_sent", True)),
        }
        sender = params.get("from_user")
        url = f"/users/{quote(str(sender), safe='')}/sendMail" if sender else "/me/sendMail"
        await self.request(client, "POST", url, json=body, expected=(202,))
        return Result.success({"status": "sent"})

    async def _calendar_create_event(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        timezone = params.get("timezone", "UTC")
        event: dict[str, Any] = {
            "subject": params["subject"],
            "start": {"dateTime": params["start"], "timeZone": timezone},
            "end": {"dateTime": params["end"], "timeZone": timezone},
        }
        if params.get("attendees"):
            event["attendees"] = [
                {"emailAddress": {"address": addr}, "type": "required"}
                for addr in _as_list(params["attendees"])
            ]
        if params.get("location"):
            event["location"] = {"displayName": params["location"]}
        if params.get("body"):
            event["body"] = {"contentType": "HTML", "content": params["body"]}
        owner = params.get("owner")
        url = f"/users/{quote(str(owner), safe='')}/events" if owner else "/me/events"
        data = await self.request(client, "POST", url, json=event, expected=(201,))
        return Result.success({"id": data.get("id"), "webLink": data.get("webLink")})

    async def _chat_post_message(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        url = f"/chats/{quote(str(params['chat_id']), safe='')}/messages"
        body = {
            "body": {
                "contentType": params.get("content_type", "text"),
                "content": params["content"],
            }
        }
        data = await self.request(client, "POST", url, json=body, expected=(201,))
        return Result.success(
            {"id": data.get("id"), "createdDateTime": data.get("createdDateTime")}
        )

    async def _directory_get_user(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        url = f"/users/{quote(str(params['user_id']), safe='')}"
        query: dict[str, Any] = {}
        select = params.get("select")
        if select:
            query["$select"] = ",".join(_as_list(select))
        data = await self.request(client, "GET", url, params=query or None, expected=(200,))
        return Result.success(data)


def build() -> MsGraphAdapter:
    return MsGraphAdapter()
