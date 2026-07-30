"""Add durable automatic budget-window usage buckets.

Revision ID: 0061_budget_windows
Revises: 0060_memory_projection_delivery
"""

from __future__ import annotations

from alembic import op

revision = "0061_budget_windows"
down_revision = "0060_memory_projection_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS budget_usage (
            tenant_id          TEXT NOT NULL,
            scope_id           TEXT NOT NULL,
            window_key         TEXT NOT NULL,
            window_started_at  TIMESTAMPTZ NOT NULL,
            window_ends_at     TIMESTAMPTZ,
            reset_generation   BIGINT NOT NULL DEFAULT 0
                               CHECK (reset_generation >= 0),
            spent_tokens       BIGINT NOT NULL DEFAULT 0
                               CHECK (spent_tokens >= 0),
            spent_micros       BIGINT NOT NULL DEFAULT 0
                               CHECK (spent_micros >= 0),
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, scope_id, window_key),
            FOREIGN KEY (tenant_id, scope_id)
                REFERENCES budgets(tenant_id, id) ON DELETE CASCADE,
            CHECK (
                window_ends_at IS NULL
                OR window_ends_at > window_started_at
            )
        );
        CREATE INDEX IF NOT EXISTS budget_usage_current_idx
          ON budget_usage (
            tenant_id,scope_id,window_started_at DESC
          );

        INSERT INTO budget_usage (
            tenant_id, scope_id, window_key, window_started_at,
            window_ends_at, spent_tokens, spent_micros
        )
        SELECT
            tenant_id,
            id,
            CASE "window"
              WHEN 'daily' THEN
                'day:' || to_char(
                  date_trunc('day', now() AT TIME ZONE 'UTC'),
                  'YYYY-MM-DD'
                )
              WHEN 'monthly' THEN
                'month:' || to_char(
                  date_trunc('month', now() AT TIME ZONE 'UTC'),
                  'YYYY-MM'
                )
              ELSE 'legacy:pre-window'
            END,
            CASE "window"
              WHEN 'daily' THEN
                date_trunc('day', now() AT TIME ZONE 'UTC')
                AT TIME ZONE 'UTC'
              WHEN 'monthly' THEN
                date_trunc('month', now() AT TIME ZONE 'UTC')
                AT TIME ZONE 'UTC'
              ELSE COALESCE(updated_at, created_at, now())
            END,
            CASE "window"
              WHEN 'daily' THEN (
                date_trunc('day', now() AT TIME ZONE 'UTC')
                AT TIME ZONE 'UTC'
              ) + interval '1 day'
              WHEN 'monthly' THEN (
                date_trunc('month', now() AT TIME ZONE 'UTC')
                AT TIME ZONE 'UTC'
              ) + interval '1 month'
              ELSE NULL
            END,
            spent_tokens,
            spent_micros
        FROM budgets
        WHERE spent_tokens <> 0 OR spent_micros <> 0
        ON CONFLICT (tenant_id, scope_id, window_key) DO NOTHING;

        UPDATE budgets SET spent_tokens=0, spent_micros=0
        WHERE spent_tokens <> 0 OR spent_micros <> 0;

        ALTER TABLE budget_usage ENABLE ROW LEVEL SECURITY;
        ALTER TABLE budget_usage FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON budget_usage;
        CREATE POLICY tenant_isolation ON budget_usage
          USING (tenant_id = current_setting('app.tenant_id', true))
          WITH CHECK (
            tenant_id = current_setting('app.tenant_id', true)
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE budgets AS b
        SET spent_tokens=u.spent_tokens,
            spent_micros=u.spent_micros,
            updated_at=now()
        FROM (
            SELECT tenant_id, scope_id,
                   SUM(spent_tokens) AS spent_tokens,
                   SUM(spent_micros) AS spent_micros
            FROM budget_usage
            GROUP BY tenant_id, scope_id
        ) AS u
        WHERE b.tenant_id=u.tenant_id AND b.id=u.scope_id;

        DROP TABLE IF EXISTS budget_usage;
        """
    )
