"""Jira ticketing adapter (US-WRK-01).

Exposes the ``ticket`` noun (create / read / update / search / comment) over the
Jira Cloud REST API v3. The site host is per-tenant, so it rides in on the
credential material as ``base_url`` (falling back to the configured default).

Auth: Jira Cloud uses HTTP basic auth with an account email + API token, so the
kernel resolves a ``Credential`` of kind ``basic`` (``username`` = email,
``api_token`` = token). OAuth bearer tokens also work (the base derives a bearer
header from ``access_token``). Material is never logged (SEC-05).

Descriptions and comments use the Atlassian Document Format (ADF); plain text is
wrapped into a minimal ADF document by :func:`_adf`.
"""

from __future__ import annotations

from typing import Any

import httpx

from boltrig.adapters.base import Result, VerbSpec
from boltrig.adapters.http_base import Handler, HttpAdapter, RateLimitConfig
from boltrig.models import InvocationContext

_API = "/rest/api/3"
_DEFAULT_BASE = "https://example.atlassian.net"

_TICKET_OUT = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "key": {"type": "string"},
        "summary": {"type": "string"},
        "status": {"type": "string"},
    },
    "required": ["key"],
}


def _adf(text: str) -> dict[str, Any]:
    """Wrap plain text into a minimal Atlassian Document Format document."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


def _status_of(fields: dict[str, Any]) -> str | None:
    status = fields.get("status")
    return status.get("name") if isinstance(status, dict) else None


_READ_RL = {"per": "minute", "max": 300, "scope": "tenant"}
_WRITE_RL = {"per": "minute", "max": 100, "scope": "tenant"}

# The ``ticket`` verb schemas as a module-level declaration (was the body of
# ``JiraAdapter.describe``). These are immutable capability specs; ``describe``
# returns a fresh list over them so a caller can never mutate the shared table.
_VERBS: list[VerbSpec] = [
    VerbSpec(
        verb_id="ticket.create",
        noun_id="ticket",
        input_schema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "summary": {"type": "string"},
                "issue_type": {"type": "string"},
                "description": {"type": "string"},
                "assignee": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "priority": {"type": "string"},
            },
            "required": ["project", "summary"],
        },
        output_schema=_TICKET_OUT,
        consequence="high",
        description="Create a Jira issue",
        rate_limit=_WRITE_RL,
    ),
    VerbSpec(
        verb_id="ticket.read",
        noun_id="ticket",
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "fields": {"type": ["array", "string"]},
            },
            "required": ["key"],
        },
        output_schema=_TICKET_OUT,
        description="Read a Jira issue by key",
        rate_limit=_READ_RL,
    ),
    VerbSpec(
        verb_id="ticket.update",
        noun_id="ticket",
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "summary": {"type": "string"},
                "description": {"type": "string"},
                "fields": {"type": "object"},
            },
            "required": ["key"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "updated": {"type": "boolean"},
            },
        },
        consequence="high",
        description="Update fields on a Jira issue",
        rate_limit=_WRITE_RL,
    ),
    VerbSpec(
        verb_id="ticket.search",
        noun_id="ticket",
        input_schema={
            "type": "object",
            "properties": {
                "jql": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["jql"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "results": {"type": "array"},
                "count": {"type": "integer"},
            },
        },
        description="Search Jira issues by JQL",
        rate_limit=_READ_RL,
    ),
    VerbSpec(
        verb_id="ticket.comment",
        noun_id="ticket",
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["key", "body"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "created": {"type": "string"},
            },
            "required": ["id"],
        },
        consequence="high",
        description="Add a comment to a Jira issue",
        rate_limit=_WRITE_RL,
    ),
]


class JiraAdapter(HttpAdapter):
    id = "jira"
    version = "1.0.0"
    user_agent = "boltrig-jira/1.0"

    def __init__(self, base_url: str = _DEFAULT_BASE) -> None:
        super().__init__(
            base_url=base_url,
            rate_limit=RateLimitConfig(max=300, per="minute", scope="tenant"),
        )

    def describe(self) -> list[VerbSpec]:
        return list(_VERBS)

    def _handlers(self) -> dict[str, Handler]:
        return {
            "ticket.create": self._ticket_create,
            "ticket.read": self._ticket_read,
            "ticket.update": self._ticket_update,
            "ticket.search": self._ticket_search,
            "ticket.comment": self._ticket_comment,
        }

    # --- handlers ------------------------------------------------------------
    async def _ticket_create(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        fields: dict[str, Any] = {
            "project": {"key": params["project"]},
            "summary": params["summary"],
            "issuetype": {"name": params.get("issue_type", "Task")},
        }
        if params.get("description"):
            fields["description"] = _adf(params["description"])
        if params.get("assignee"):
            fields["assignee"] = {"accountId": params["assignee"]}
        if params.get("labels"):
            fields["labels"] = list(params["labels"])
        if params.get("priority"):
            fields["priority"] = {"name": params["priority"]}
        data = await self.request(
            client, "POST", f"{_API}/issue", json={"fields": fields}, expected=(201,)
        )
        return Result.success(
            {"id": data.get("id"), "key": data.get("key"), "self": data.get("self")}
        )

    async def _ticket_read(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        url = f"{_API}/issue/{params['key']}"
        query: dict[str, Any] = {}
        fields = params.get("fields")
        if fields:
            query["fields"] = (
                ",".join(fields) if isinstance(fields, (list, tuple)) else str(fields)
            )
        data = await self.request(client, "GET", url, params=query or None, expected=(200,))
        issue_fields = data.get("fields") or {}
        return Result.success(
            {
                "id": data.get("id"),
                "key": data.get("key"),
                "summary": issue_fields.get("summary"),
                "status": _status_of(issue_fields),
                "fields": issue_fields,
            }
        )

    async def _ticket_update(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        url = f"{_API}/issue/{params['key']}"
        fields: dict[str, Any] = dict(params.get("fields") or {})
        if params.get("summary"):
            fields["summary"] = params["summary"]
        if params.get("description"):
            fields["description"] = _adf(params["description"])
        await self.request(client, "PUT", url, json={"fields": fields}, expected=(204,))
        return Result.success({"key": params["key"], "updated": True})

    async def _ticket_search(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        limit = int(params.get("limit", 50))
        results: list[dict[str, Any]] = []
        async for issue in self.paginate_offset(
            client,
            f"{_API}/search",
            params={"jql": params["jql"]},
            items_key="issues",
            start_key="startAt",
            max_key="maxResults",
            total_key="total",
            page_size=min(max(limit, 1), 100),
        ):
            issue_fields = issue.get("fields") or {}
            results.append(
                {
                    "id": issue.get("id"),
                    "key": issue.get("key"),
                    "summary": issue_fields.get("summary"),
                    "status": _status_of(issue_fields),
                }
            )
            if len(results) >= limit:
                break
        return Result.success({"results": results, "count": len(results)})

    async def _ticket_comment(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        url = f"{_API}/issue/{params['key']}/comment"
        data = await self.request(
            client, "POST", url, json={"body": _adf(params["body"])}, expected=(201,)
        )
        return Result.success({"id": data.get("id"), "created": data.get("created")})


def build() -> JiraAdapter:
    return JiraAdapter()
