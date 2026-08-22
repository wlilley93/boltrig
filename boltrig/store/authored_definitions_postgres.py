"""PostgreSQL authored-definition persistence and lifecycle semantics."""

from __future__ import annotations

from boltrig.models import Noun, Skill, Verb, VerbBinding

from .rows import _binding, _noun, _skill, _verb


class AuthoredDefinitionStorePG:
    async def get_noun(self, tenant_id, noun_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM nouns
               WHERE tenant_id=$1 AND id=$2 AND is_active=TRUE""",
            tenant_id, noun_id,
        )
        return _noun(row)

    async def get_noun_any(self, tenant_id, noun_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM nouns WHERE tenant_id=$1 AND id=$2", tenant_id, noun_id
        )
        return _noun(row)

    async def list_nouns(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM nouns WHERE tenant_id=$1 AND is_active=TRUE",
            tenant_id,
        )
        return [_noun(row) for row in rows]

    async def list_all_nouns(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM nouns WHERE tenant_id=$1", tenant_id
        )
        return [_noun(row) for row in rows]

    async def get_verb(self, tenant_id, verb_id):
        row = await self._pool.fetchrow(
            """SELECT v.* FROM verbs v
               JOIN nouns n ON n.tenant_id=v.tenant_id AND n.id=v.noun_id
               WHERE v.tenant_id=$1 AND v.id=$2
                 AND v.is_active=TRUE AND n.is_active=TRUE""",
            tenant_id, verb_id,
        )
        return _verb(row)

    async def get_verb_any(self, tenant_id, verb_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM verbs WHERE tenant_id=$1 AND id=$2", tenant_id, verb_id
        )
        return _verb(row)

    async def list_verbs(self, tenant_id, noun_id=None):
        if noun_id is None:
            rows = await self._pool.fetch(
                """SELECT v.* FROM verbs v
                   JOIN nouns n
                     ON n.tenant_id=v.tenant_id AND n.id=v.noun_id
                   WHERE v.tenant_id=$1
                     AND v.is_active=TRUE AND n.is_active=TRUE""",
                tenant_id,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT v.* FROM verbs v
                   JOIN nouns n
                     ON n.tenant_id=v.tenant_id AND n.id=v.noun_id
                   WHERE v.tenant_id=$1 AND v.noun_id=$2
                     AND v.is_active=TRUE AND n.is_active=TRUE""",
                tenant_id, noun_id,
            )
        return [_verb(row) for row in rows]

    async def list_all_verbs(self, tenant_id, noun_id=None):
        if noun_id is None:
            rows = await self._pool.fetch(
                "SELECT * FROM verbs WHERE tenant_id=$1", tenant_id
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM verbs WHERE tenant_id=$1 AND noun_id=$2",
                tenant_id, noun_id,
            )
        return [_verb(row) for row in rows]

    async def get_binding(self, tenant_id, verb_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM verb_bindings WHERE tenant_id=$1 AND verb_id=$2",
            tenant_id, verb_id,
        )
        return _binding(row)

    async def upsert_noun(self, noun: Noun):
        await self._pool.execute(
            """INSERT INTO nouns (id, tenant_id, description, schema, is_active)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 description=EXCLUDED.description, schema=EXCLUDED.schema,
                 updated_at=now()""",
            noun.id, noun.tenant_id, noun.description, noun.schema, noun.is_active,
        )

    async def upsert_verb(self, verb: Verb):
        await self._pool.execute(
            """INSERT INTO verbs (
                 id, tenant_id, noun_id, description, input_schema, output_schema,
                 consequence, identity_mode, degraded_mode, idempotency_mode, is_active
               )
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 noun_id=EXCLUDED.noun_id, description=EXCLUDED.description,
                 input_schema=EXCLUDED.input_schema,
                 output_schema=EXCLUDED.output_schema,
                 consequence=EXCLUDED.consequence,
                 identity_mode=EXCLUDED.identity_mode,
                 degraded_mode=EXCLUDED.degraded_mode,
                 idempotency_mode=EXCLUDED.idempotency_mode, updated_at=now()""",
            verb.id, verb.tenant_id, verb.noun_id, verb.description,
            verb.input_schema, verb.output_schema, verb.consequence.value,
            verb.identity_mode, verb.degraded_mode, verb.idempotency_mode.value,
            verb.is_active,
        )

    async def set_noun_active(self, tenant_id, noun_id, active):
        result = await self._pool.execute(
            """UPDATE nouns SET is_active=$3, updated_at=now()
               WHERE tenant_id=$1 AND id=$2""",
            tenant_id, noun_id, active,
        )
        return (
            await self.get_noun_any(tenant_id, noun_id)
            if result == "UPDATE 1"
            else None
        )

    async def set_verb_active(self, tenant_id, verb_id, active):
        result = await self._pool.execute(
            """UPDATE verbs SET is_active=$3, updated_at=now()
               WHERE tenant_id=$1 AND id=$2""",
            tenant_id, verb_id, active,
        )
        return (
            await self.get_verb_any(tenant_id, verb_id)
            if result == "UPDATE 1"
            else None
        )

    async def upsert_binding(self, binding: VerbBinding):
        rate_limit = (
            {
                "per": binding.rate_limit.per,
                "max": binding.rate_limit.max,
                "scope": binding.rate_limit.scope,
            }
            if binding.rate_limit
            else None
        )
        await self._pool.execute(
            """INSERT INTO verb_bindings (
                 verb_id, tenant_id, target_type, target_ref, rate_limit,
                 internal_source_operation_id, canonical_capability_id,
                 model_display_name, connection_label
               )
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (verb_id, tenant_id) DO UPDATE SET
                 target_type=EXCLUDED.target_type,
                 target_ref=EXCLUDED.target_ref,
                 rate_limit=EXCLUDED.rate_limit,
                 internal_source_operation_id=EXCLUDED.internal_source_operation_id,
                 canonical_capability_id=EXCLUDED.canonical_capability_id,
                 model_display_name=EXCLUDED.model_display_name,
                 connection_label=EXCLUDED.connection_label,
                 updated_at=now()""",
            binding.verb_id, binding.tenant_id, binding.target_type.value,
            binding.target_ref, rate_limit,
            binding.internal_source_operation_id,
            binding.canonical_capability_id,
            binding.model_display_name,
            binding.connection_label,
        )

    async def delete_noun(self, tenant_id, noun_id):
        await self._pool.execute(
            "DELETE FROM nouns WHERE tenant_id=$1 AND id=$2", tenant_id, noun_id
        )

    async def delete_verb(self, tenant_id, verb_id):
        await self._pool.execute(
            "DELETE FROM verbs WHERE tenant_id=$1 AND id=$2", tenant_id, verb_id
        )

    async def delete_binding(self, tenant_id, verb_id):
        await self._pool.execute(
            "DELETE FROM verb_bindings WHERE tenant_id=$1 AND verb_id=$2",
            tenant_id, verb_id,
        )

    async def upsert_skill(self, skill: Skill):
        await self._pool.execute(
            """INSERT INTO skills (
                 id, tenant_id, version, prompt_fragment, tool_grants,
                 context_requirements, extends, locale, description, is_active
               )
               VALUES (
                 $1,$2,$3,$4,$5,$6,$7,$8,$9,
                 COALESCE(
                   (SELECT is_active FROM skills
                    WHERE tenant_id=$2 AND id=$1
                    ORDER BY version DESC LIMIT 1),
                   $10
                 )
               )
               ON CONFLICT (tenant_id, id, version) DO UPDATE SET
                 prompt_fragment=EXCLUDED.prompt_fragment,
                 tool_grants=EXCLUDED.tool_grants,
                 context_requirements=EXCLUDED.context_requirements,
                 extends=EXCLUDED.extends, locale=EXCLUDED.locale,
                 description=EXCLUDED.description, updated_at=now()""",
            skill.id, skill.tenant_id, skill.version, skill.prompt_fragment,
            skill.tool_grants, skill.context_requirements, skill.extends,
            skill.locale, skill.description, skill.is_active,
        )

    async def get_skill(self, tenant_id, skill_id):
        skill = await self.get_skill_any(tenant_id, skill_id)
        return skill if skill is not None and skill.is_active else None

    async def get_skill_any(self, tenant_id, skill_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM skills
               WHERE tenant_id=$1 AND id=$2
               ORDER BY version DESC LIMIT 1""",
            tenant_id, skill_id,
        )
        return _skill(row)

    async def list_skills(self, tenant_id):
        return [
            skill
            for skill in await self.list_all_skills(tenant_id)
            if skill.is_active
        ]

    async def list_all_skills(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT DISTINCT ON (id) * FROM skills WHERE tenant_id=$1
               ORDER BY id, version DESC""",
            tenant_id,
        )
        return [_skill(row) for row in rows]

    async def set_skill_active(self, tenant_id, skill_id, active):
        result = await self._pool.execute(
            """UPDATE skills SET is_active=$3, updated_at=now()
               WHERE tenant_id=$1 AND id=$2""",
            tenant_id, skill_id, active,
        )
        return (
            await self.get_skill_any(tenant_id, skill_id)
            if result != "UPDATE 0"
            else None
        )
