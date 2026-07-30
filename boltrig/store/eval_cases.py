"""Evaluation fixture/run persistence shared by both store implementations."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from boltrig.models import EvalCase, EvalRun

from .rows import _eval_case, _eval_run


class EvalCaseStoreContract(Protocol):
    async def upsert_eval_case(self, case: EvalCase) -> None: ...
    async def get_eval_case(
        self, tenant_id: str, case_id: str
    ) -> EvalCase | None: ...
    async def list_eval_cases(self, tenant_id: str) -> list[EvalCase]: ...
    async def set_eval_case_active(
        self, tenant_id: str, case_id: str, is_active: bool
    ) -> bool: ...
    async def add_eval_run(self, run: EvalRun) -> None: ...
    async def list_eval_runs(
        self, tenant_id: str, case_id: str | None = None
    ) -> list[EvalRun]: ...


class EvalCaseStoreMem:
    async def upsert_eval_case(self, case):
        key = (case.tenant_id, case.id)
        existing = self._eval_cases.get(key)
        self._eval_cases[key] = replace(
            case,
            is_active=(
                existing.is_active if existing is not None else case.is_active
            ),
        )

    async def get_eval_case(self, tenant_id, case_id):
        return self._eval_cases.get((tenant_id, case_id))

    async def list_eval_cases(self, tenant_id):
        return [
            case
            for (tenant, _), case in self._eval_cases.items()
            if tenant == tenant_id
        ]

    async def set_eval_case_active(self, tenant_id, case_id, is_active):
        key = (tenant_id, case_id)
        case = self._eval_cases.get(key)
        if case is None:
            return False
        self._eval_cases[key] = replace(case, is_active=is_active)
        return True

    async def add_eval_run(self, run):
        self._eval_runs.append(run)

    async def list_eval_runs(self, tenant_id, case_id=None):
        out = [
            run
            for run in self._eval_runs
            if run.tenant_id == tenant_id
            and (case_id is None or run.case_id == case_id)
        ]
        return sorted(out, key=lambda run: run.created_at, reverse=True)


class EvalCaseStorePG:
    async def upsert_eval_case(self, case: EvalCase):
        await self._pool.execute(
            """INSERT INTO eval_cases (
                 id, tenant_id, target_kind, target_ref, input, assertions,
                 labels, is_active
               )
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 target_kind=EXCLUDED.target_kind,
                 target_ref=EXCLUDED.target_ref, input=EXCLUDED.input,
                 assertions=EXCLUDED.assertions, labels=EXCLUDED.labels""",
            case.id, case.tenant_id, case.target_kind, case.target_ref,
            case.input, case.assertions, case.labels, case.is_active,
        )

    async def get_eval_case(self, tenant_id, case_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM eval_cases WHERE tenant_id=$1 AND id=$2",
            tenant_id, case_id,
        )
        return _eval_case(row)

    async def list_eval_cases(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM eval_cases WHERE tenant_id=$1", tenant_id
        )
        return [_eval_case(row) for row in rows]

    async def set_eval_case_active(self, tenant_id, case_id, is_active):
        result = await self._pool.execute(
            """UPDATE eval_cases SET is_active=$3
               WHERE tenant_id=$1 AND id=$2""",
            tenant_id, case_id, is_active,
        )
        return result == "UPDATE 1"

    async def add_eval_run(self, run: EvalRun):
        await self._pool.execute(
            """INSERT INTO eval_runs (
                 id, tenant_id, case_id, passed, score, run_id, detail
               )
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            run.id, run.tenant_id, run.case_id, run.passed, run.score,
            run.run_id, run.detail,
        )

    async def list_eval_runs(self, tenant_id, case_id=None):
        if case_id is None:
            rows = await self._pool.fetch(
                """SELECT * FROM eval_runs
                   WHERE tenant_id=$1 ORDER BY created_at DESC""",
                tenant_id,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM eval_runs
                   WHERE tenant_id=$1 AND case_id=$2
                   ORDER BY created_at DESC""",
                tenant_id, case_id,
            )
        return [_eval_run(row) for row in rows]
