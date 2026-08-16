"""The trajectory stream: verbatim turn records, short-lived and opt-in.

Decision TRJ-01. Separate from ``audit_events`` on purpose. The audit chain is
bounded and scrubbed -- digest plus a 256-character preview -- which is right
for a tamper-evident record somebody may keep for years and wrong for answering
"why did it say that". This table holds the whole prompt, the whole tool
payload and the whole result, so it gets the opposite posture: opt-in, expiring,
purgeable, and NOT part of the hash chain.

No foreign key to a runs table: a trajectory may outlive the work item it
describes, and it must be deletable on its own without a cascade reaching into
the compliance record.

Revision ID: 0077_trajectory
Revises: 0076_typed_memory_ledger
"""

from __future__ import annotations

from alembic import op

revision = "0077_trajectory"
down_revision = "0076_typed_memory_ledger"
branch_labels = None
depends_on = None

_UP = """
CREATE TABLE IF NOT EXISTS trajectory_events (
    tenant_id      TEXT        NOT NULL,
    run_id         TEXT        NOT NULL,
    seq            INTEGER     NOT NULL,
    kind           TEXT        NOT NULL,
    payload        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    actor          TEXT        NOT NULL DEFAULT 'unknown',
    parent_run_id  TEXT,
    depth          INTEGER     NOT NULL DEFAULT 0,
    at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, run_id, seq),
    CONSTRAINT trajectory_events_kind_check CHECK (kind IN (
        'prompt', 'context', 'reasoning', 'message',
        'tool_call', 'tool_result', 'error'
    ))
);

-- Reading a run is always (tenant, run) ordered by seq, which the primary key
-- already serves. These two cover the other two accesses: listing recent runs,
-- and the expiry sweep.
CREATE INDEX IF NOT EXISTS trajectory_events_recent
    ON trajectory_events (tenant_id, at DESC);

CREATE INDEX IF NOT EXISTS trajectory_events_expiry
    ON trajectory_events (expires_at)
    WHERE expires_at IS NOT NULL;
"""

_DOWN = """
DROP INDEX IF EXISTS trajectory_events_expiry;
DROP INDEX IF EXISTS trajectory_events_recent;
DROP TABLE IF EXISTS trajectory_events;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
