"""Notification + personal-agent store domains (arc-1 structural partials),
extracted verbatim from ``store/postgres.py`` + ``store/memory.py``. PG host:
``self._pool``; Mem host: ``self._notif`` / ``self._personal``. Two tiny
per-user domains, one file each side to keep the partial count honest.
Public surface unchanged.
"""

from __future__ import annotations

from boltrig.models import NotificationPref, PersonalAgent

from .rows import _notif, _personal


class NotificationsStorePG:
    """Notification-preference methods for ``PostgresStore``."""

    async def upsert_notification_pref(self, p: NotificationPref):
        await self._pool.execute(
            """INSERT INTO notification_prefs (id, tenant_id, scope_kind, scope_ref, event_type, channel, target, enabled)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 scope_kind=EXCLUDED.scope_kind, scope_ref=EXCLUDED.scope_ref,
                 event_type=EXCLUDED.event_type, channel=EXCLUDED.channel,
                 target=EXCLUDED.target, enabled=EXCLUDED.enabled""",
            p.id, p.tenant_id, p.scope_kind, p.scope_ref, p.event_type, p.channel,
            p.target, p.enabled,
        )

    async def list_notification_prefs(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM notification_prefs WHERE tenant_id=$1", tenant_id
        )
        return [_notif(r) for r in rows]


class NotificationsStoreMem:
    """Notification-preference methods for ``InMemoryStore``."""

    async def upsert_notification_pref(self, pref):
        self._notif[(pref.tenant_id, pref.id)] = pref

    async def list_notification_prefs(self, tenant_id):
        return [p for (t, _), p in self._notif.items() if t == tenant_id]


class PersonalAgentsStorePG:
    """Personal-agent methods for ``PostgresStore``."""

    async def upsert_personal_agent(self, a: PersonalAgent):
        await self._pool.execute(
            """INSERT INTO personal_agents (id, tenant_id, user_id, runtime, skills, enabled)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 user_id=EXCLUDED.user_id, runtime=EXCLUDED.runtime,
                 skills=EXCLUDED.skills, enabled=EXCLUDED.enabled""",
            a.id, a.tenant_id, a.user_id, a.runtime, a.skills, a.enabled,
        )

    async def get_personal_agent(self, tenant_id, user_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM personal_agents WHERE tenant_id=$1 AND user_id=$2
               ORDER BY created_at DESC LIMIT 1""",
            tenant_id, user_id,
        )
        return _personal(row)

    async def delete_personal_agent(self, tenant_id, user_id):
        result = await self._pool.execute(
            "DELETE FROM personal_agents WHERE tenant_id=$1 AND user_id=$2",
            tenant_id, user_id,
        )
        return result != "DELETE 0"


class PersonalAgentsStoreMem:
    """Personal-agent methods for ``InMemoryStore``."""

    async def upsert_personal_agent(self, agent):
        self._personal[(agent.tenant_id, agent.user_id)] = agent

    async def get_personal_agent(self, tenant_id, user_id):
        return self._personal.get((tenant_id, user_id))

    async def delete_personal_agent(self, tenant_id, user_id):
        return self._personal.pop((tenant_id, user_id), None) is not None
