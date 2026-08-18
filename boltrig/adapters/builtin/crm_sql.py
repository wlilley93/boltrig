"""Reference SQL adapter: a CRM over a relational database (US-ADP-03, SEC-09).

It is also the capability doctrine's first canonical domain: both verbs declare
``implements`` (``crm.contact.read`` / ``crm.contact.search``), so registering
this adapter creates a provider connection, its source operations and approved
capability bindings. A second CRM declaring the same capability is then a second
binding, not a replacement - which is the whole point of the shard.

Exposes the ``contact`` noun (read / search) against a ``contacts`` table. It is
READ-SCOPED by default (``write_allowed=False``): the base refuses any write for
this binding before a statement reaches the driver, which is how read/write scope
is enforced per binding (SEC-09).

Every statement is parameterised: caller values (the id, the search term, the
page window) are passed as bound parameters, never interpolated into the SQL
text. The DSN is supplied by the kernel via the credential material (or the
adapter default); if the driver is missing or the database is unreachable the
call degrades to UNAVAILABLE rather than crashing (US-ADP-06).
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import AdapterError, ErrorClass, Result, VerbSpec
from boltrig.adapters.sql_base import SqlAdapter, SqlHandler, _Db
from boltrig.models import InvocationContext

_CONTACT_OUT = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
        "email": {"type": "string"},
        "company": {"type": "string"},
    },
    "required": ["id"],
}


class CrmSqlAdapter(SqlAdapter):
    id = "crm-sql"
    version = "1.0.0"

    def __init__(self, dsn: str | None = None) -> None:
        # read-scoped by default; a write-enabled binding would pass write_allowed=True.
        super().__init__(dsn=dsn, write_allowed=False, dialect="postgresql")

    def describe(self) -> list[VerbSpec]:
        read_rl = {"per": "minute", "max": 600, "scope": "tenant"}
        return [
            VerbSpec(
                verb_id="contact.read",
                noun_id="contact",
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
                output_schema=_CONTACT_OUT,
                description="Read a CRM contact by id",
                rate_limit=read_rl,
                implements="crm.contact.read",
            ),
            VerbSpec(
                verb_id="contact.search",
                noun_id="contact",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
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
                description="Search CRM contacts by name or email",
                rate_limit=read_rl,
                implements="crm.contact.search",
            ),
        ]

    def _handlers(self) -> dict[str, SqlHandler]:
        return {
            "contact.read": self._contact_read,
            "contact.search": self._contact_search,
        }

    async def _contact_read(
        self, params: dict[str, Any], db: _Db, context: InvocationContext
    ) -> Result:
        result = await db.query(
            "SELECT id, first_name, last_name, email, phone, company "
            "FROM contacts WHERE id = :id",
            {"id": params["id"]},
        )
        rows = result["rows"]
        if not rows:
            return Result.failure(AdapterError(ErrorClass.NOT_FOUND, "no such contact"))
        return Result.success(rows[0])

    async def _contact_search(
        self, params: dict[str, Any], db: _Db, context: InvocationContext
    ) -> Result:
        # The wildcards live in the bound VALUE, not in the SQL text (SEC-09).
        term = f"%{params['query']}%"
        limit = int(params.get("limit", 25))
        offset = int(params.get("offset", 0))
        result = await db.query(
            "SELECT id, first_name, last_name, email, company FROM contacts "
            "WHERE email ILIKE :term OR first_name ILIKE :term OR last_name ILIKE :term "
            "ORDER BY last_name, first_name LIMIT :limit OFFSET :offset",
            {"term": term, "limit": limit, "offset": offset},
        )
        return Result.success({"results": result["rows"], "count": result["count"]})


def build() -> CrmSqlAdapter:
    return CrmSqlAdapter()
