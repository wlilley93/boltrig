"""Merge the capability-doctrine and scoped-integration chains.

Two branches left 0076_typed_memory_ledger at the same time and each grew its
own line:

    0076 -> 0077_trajectory -> 0078_scoped_integration_connections
    0076 -> 0077_audit_outbox -> 0078_capability_presentation_fields
                              -> 0079_capability_routing_shard
                              -> 0080_probe_tool_count_bound

so the merged tree had two heads and `alembic upgrade head` refuses to guess
between them.

THIS IS A MERGE REVISION, NOT A RE-PARENT, and that is the whole point. The
obvious alternative was to re-parent 0077_audit_outbox onto
0078_scoped_integration_connections and renumber its four files. Both chains are
already on origin and both have been pulled, so renumbering rewrites published
history: anyone holding the old ids gets a revision that no longer exists, and a
database already stamped with one of them can never be upgraded again. A merge
revision names both heads, yields exactly one, and rewrites nothing.

It has no schema of its own. Everything it joins was already applied by the
revisions above it, so upgrade and downgrade are deliberately empty rather than
forgotten: there is nothing for them to do, and inventing work here would make
the join itself a thing that can fail.

Downgrade splits the DAG back into the two heads it came from. That is the
correct inverse and it is also why it is not a route back to 0076 - crossing
either chain still needs that chain's own downgrades, and 0022_schema_parity
remains irreversible regardless.
"""

from __future__ import annotations

revision = "0081_merge_capability_and_integration_scope"
down_revision = (
    "0078_scoped_integration_connections",
    "0080_probe_tool_count_bound",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nothing to apply. The join is the migration."""


def downgrade() -> None:
    """Nothing to undo. Downgrading past this restores the two separate heads."""
