"""In-memory authored-definition persistence and lifecycle semantics."""

from __future__ import annotations

from dataclasses import replace

from boltrig.models import AdapterRecord, Noun, Skill, Verb, VerbBinding


class AuthoredDefinitionStoreMem:
    def _init_authored_definition_state(self) -> None:
        self._nouns: dict[tuple[str, str], Noun] = {}
        self._verbs: dict[tuple[str, str], Verb] = {}
        self._bindings: dict[tuple[str, str], VerbBinding] = {}
        self._adapters: dict[tuple[str, str], AdapterRecord] = {}
        self._skills: dict[tuple[str, str, str], Skill] = {}

    async def get_noun(self, tenant_id, noun_id):
        noun = await self.get_noun_any(tenant_id, noun_id)
        return noun if noun is not None and noun.is_active else None

    async def get_noun_any(self, tenant_id, noun_id):
        return self._nouns.get((tenant_id, noun_id))

    async def list_nouns(self, tenant_id):
        return [
            noun
            for noun in await self.list_all_nouns(tenant_id)
            if noun.is_active
        ]

    async def list_all_nouns(self, tenant_id):
        return [
            noun for (tenant, _), noun in self._nouns.items()
            if tenant == tenant_id
        ]

    async def get_verb(self, tenant_id, verb_id):
        verb = await self.get_verb_any(tenant_id, verb_id)
        if verb is None or not verb.is_active:
            return None
        return verb if await self.get_noun(tenant_id, verb.noun_id) is not None else None

    async def get_verb_any(self, tenant_id, verb_id):
        return self._verbs.get((tenant_id, verb_id))

    async def list_verbs(self, tenant_id, noun_id=None):
        out = await self.list_all_verbs(tenant_id, noun_id)
        active_nouns = {
            noun.id
            for (tenant, _), noun in self._nouns.items()
            if tenant == tenant_id and noun.is_active
        }
        return [verb for verb in out if verb.is_active and verb.noun_id in active_nouns]

    async def list_all_verbs(self, tenant_id, noun_id=None):
        out = [verb for (tenant, _), verb in self._verbs.items() if tenant == tenant_id]
        return (
            [verb for verb in out if verb.noun_id == noun_id]
            if noun_id is not None
            else out
        )

    async def get_binding(self, tenant_id, verb_id):
        return self._bindings.get((tenant_id, verb_id))

    async def upsert_noun(self, noun):
        key = (noun.tenant_id, noun.id)
        existing = self._nouns.get(key)
        self._nouns[key] = replace(
            noun,
            is_active=existing.is_active if existing is not None else noun.is_active,
        )

    async def upsert_verb(self, verb):
        key = (verb.tenant_id, verb.id)
        existing = self._verbs.get(key)
        self._verbs[key] = replace(
            verb,
            is_active=existing.is_active if existing is not None else verb.is_active,
        )

    async def set_noun_active(self, tenant_id, noun_id, active):
        key = (tenant_id, noun_id)
        noun = self._nouns.get(key)
        if noun is None:
            return None
        updated = replace(noun, is_active=active)
        self._nouns[key] = updated
        return updated

    async def set_verb_active(self, tenant_id, verb_id, active):
        key = (tenant_id, verb_id)
        verb = self._verbs.get(key)
        if verb is None:
            return None
        updated = replace(verb, is_active=active)
        self._verbs[key] = updated
        return updated

    async def upsert_binding(self, binding):
        self._bindings[(binding.tenant_id, binding.verb_id)] = binding

    async def delete_noun(self, tenant_id, noun_id):
        self._nouns.pop((tenant_id, noun_id), None)

    async def delete_verb(self, tenant_id, verb_id):
        self._verbs.pop((tenant_id, verb_id), None)

    async def delete_binding(self, tenant_id, verb_id):
        self._bindings.pop((tenant_id, verb_id), None)

    async def upsert_skill(self, skill):
        existing = await self.get_skill_any(skill.tenant_id, skill.id)
        self._skills[(skill.tenant_id, skill.id, skill.version)] = replace(
            skill,
            is_active=existing.is_active if existing is not None else skill.is_active,
        )

    async def get_skill(self, tenant_id, skill_id):
        skill = await self.get_skill_any(tenant_id, skill_id)
        return skill if skill is not None and skill.is_active else None

    async def get_skill_any(self, tenant_id, skill_id):
        versions = [
            skill
            for (tenant, current_id, _), skill in self._skills.items()
            if tenant == tenant_id and current_id == skill_id
        ]
        return max(versions, key=lambda skill: skill.version, default=None)

    async def list_skills(self, tenant_id):
        return [
            skill
            for skill in await self.list_all_skills(tenant_id)
            if skill.is_active
        ]

    async def list_all_skills(self, tenant_id):
        latest: dict[str, Skill] = {}
        for (tenant, skill_id, _), skill in self._skills.items():
            if (
                tenant == tenant_id
                and (
                    skill_id not in latest
                    or skill.version > latest[skill_id].version
                )
            ):
                latest[skill_id] = skill
        return list(latest.values())

    async def set_skill_active(self, tenant_id, skill_id, active):
        found = False
        for key, skill in tuple(self._skills.items()):
            if key[0] == tenant_id and key[1] == skill_id:
                self._skills[key] = replace(skill, is_active=active)
                found = True
        return await self.get_skill_any(tenant_id, skill_id) if found else None
