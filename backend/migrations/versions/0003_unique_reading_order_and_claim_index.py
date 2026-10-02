"""Unique reading order per document and an index for claiming pending jobs.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28 23:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    # Make the reading order unique per document, replacing the plain index
    op.drop_index(
        "ix_extracted_elements_document_id_reading_order",
        table_name="extracted_elements",
    )
    op.create_unique_constraint(
        "uq_extracted_elements_document_id_reading_order",
        "extracted_elements",
        ["document_id", "reading_order"],
    )

    # Partial index of pending jobs, in the order the worker claims them
    op.create_index(
        "ix_ingestion_jobs_pending_created_at",
        "ingestion_jobs",
        ["created_at", "id"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    """Revert this revision."""
    # Restore the plain reading order index and drop the claim index
    op.drop_index("ix_ingestion_jobs_pending_created_at", table_name="ingestion_jobs")
    op.drop_constraint(
        "uq_extracted_elements_document_id_reading_order",
        "extracted_elements",
        type_="unique",
    )
    op.create_index(
        "ix_extracted_elements_document_id_reading_order",
        "extracted_elements",
        ["document_id", "reading_order"],
    )
