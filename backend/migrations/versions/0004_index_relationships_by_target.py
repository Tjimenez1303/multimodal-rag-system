"""Index relationships by target, so an element finds the links pointing at it.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29 00:21:49.873257

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.create_index(
        op.f("ix_element_relationships_target_id"),
        "element_relationships",
        ["target_id"],
        unique=False,
    )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_index(
        op.f("ix_element_relationships_target_id"),
        table_name="element_relationships",
    )
