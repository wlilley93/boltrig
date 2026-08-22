"""The probe receipt's tool_count CHECK still says 500 while the cap says 5000.

``MCP_MAX_TOOL_SNAPSHOT`` was raised 500 -> 5000 because Opbox publishes 633
verbs (``boltrig/models/mcp_lifecycle.py`` records the measurement). Every
Python bound moved with it - the snapshot validator, the ``McpProbeReceipt``
invariant - but the column's CHECK did not:

    tool_count INTEGER NOT NULL CHECK (tool_count BETWEEN 0 AND 500)

So a probe of any server publishing 501-5000 tools passes discovery, passes
``validate_mcp_tool_snapshot``, passes the receipt's own ``__post_init__``, and
then dies inside ``insert_probe`` on a constraint nothing in Python knows about.
The failure lands at the write, after the network round trip, on the exact
server the merge depends on: probing Opbox's MCP door records a receipt the
database refuses.

This aligns the constraint with the Python bound, which is the one that was
deliberately chosen. Naming it explicitly (rather than leaving the inline
auto-name) so a future change to the same bound has something to grep for.

The downgrade narrows the bound back to 500 and will therefore FAIL if any
receipt above 500 has been written in between - correct behaviour for a
narrowing constraint, and stated here rather than discovered.

Revision ID: 0080_probe_tool_count_bound
Revises: 0079_capability_routing_shard
"""

from __future__ import annotations

from alembic import op

revision = "0080_probe_tool_count_bound"
down_revision = "0079_capability_routing_shard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE mcp_probe_receipts
          DROP CONSTRAINT IF EXISTS mcp_probe_receipts_tool_count_check;
        ALTER TABLE mcp_probe_receipts
          ADD CONSTRAINT mcp_probe_receipts_tool_count_check
          CHECK (tool_count BETWEEN 0 AND 5000);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE mcp_probe_receipts
          DROP CONSTRAINT IF EXISTS mcp_probe_receipts_tool_count_check;
        ALTER TABLE mcp_probe_receipts
          ADD CONSTRAINT mcp_probe_receipts_tool_count_check
          CHECK (tool_count BETWEEN 0 AND 500);
        """
    )
