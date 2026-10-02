"""One job that has not failed per document.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28 19:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    # At most one job that has not failed per document
    op.create_index(
        "uq_ingestion_jobs_document_id_active",
        "ingestion_jobs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'failed'"),
    )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_index("uq_ingestion_jobs_document_id_active", table_name="ingestion_jobs")
