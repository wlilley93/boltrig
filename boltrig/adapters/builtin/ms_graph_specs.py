"""Verb specifications for the Microsoft Graph adapter.

Split from :mod:`ms_graph` when the adapter gained its first INVERSE verb
(``calendar.delete_event``): the declarations are pure data, the module was at
the structural floor, and the sibling precedent is ``mcp_verb_specs.py``.
"""

from __future__ import annotations

from boltrig.adapters.base import VerbSpec

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


_READ_RL = {"per": "minute", "max": 1000, "scope": "tenant"}
_WRITE_RL = {"per": "minute", "max": 200, "scope": "tenant"}
_SEND_RL = {"per": "minute", "max": 30, "scope": "tenant"}


def _document_specs() -> list[VerbSpec]:
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
        rate_limit=_READ_RL,
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
        rate_limit=_READ_RL,
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
        rate_limit=_WRITE_RL,
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
        rate_limit=_WRITE_RL,
        consequence="high",
    ),
    ]


def _email_specs() -> list[VerbSpec]:
    return [
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
        rate_limit=_SEND_RL,
    ),
    ]


def _calendar_specs() -> list[VerbSpec]:
    return [
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
        rate_limit=_WRITE_RL,
    ),
    VerbSpec(
        verb_id="calendar.delete_event",
        noun_id="calendar",
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "owner": {"type": "string"},
            },
            "required": ["event_id"],
        },
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
        },
        # Deletes from a customer's calendar: gated exactly like the
        # create it reverses.
        consequence="high",
        description="Delete a calendar event (the inverse of calendar.create_event)",
        rate_limit=_WRITE_RL,
    ),
    ]


def _chat_directory_specs() -> list[VerbSpec]:
    return [
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
        rate_limit=_WRITE_RL,
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
        rate_limit=_READ_RL,
    ),
    ]


def ms_graph_specs() -> list[VerbSpec]:
    return [
        *_document_specs(),
        *_email_specs(),
        *_calendar_specs(),
        *_chat_directory_specs(),
    ]
