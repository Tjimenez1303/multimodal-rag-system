"""Initial schema: documents, ingestion jobs, extracted elements and relationships.

Revision ID: 0001
Revises:
Create Date: 2026-09-28 16:42:48.124066

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Wakes idle workers as soon as a job is enqueued, so they do not wait for a poll.
NOTIFY_FUNCTION = """
CREATE FUNCTION notify_ingestion_job() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('ingestion_jobs', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
NOTIFY_TRIGGER = """
CREATE TRIGGER ingestion_jobs_notify
AFTER INSERT ON ingestion_jobs
FOR EACH ROW EXECUTE FUNCTION notify_ingestion_job()
"""

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("blob_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name=op.f("ck_documents_positive_pages"),
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_documents_positive_size")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("sha256", name=op.f("uq_documents_sha256")),
    )
    op.create_index(
        op.f("ix_documents_created_at_id"),
        "documents",
        ["created_at", "id"],
        unique=False,
    )
    op.create_table(
        "extracted_elements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("bbox_left", sa.Float(), nullable=False),
        sa.Column("bbox_top", sa.Float(), nullable=False),
        sa.Column("bbox_right", sa.Float(), nullable=False),
        sa.Column("bbox_bottom", sa.Float(), nullable=False),
        sa.Column("reading_order", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("heading_level", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("table_rows", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("image_key", sa.Text(), nullable=True),
        sa.Column("image_class", sa.Text(), nullable=True),
        sa.Column(
            "labels",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("description_status", sa.String(length=16), nullable=True),
        sa.Column(
            "unverified_identifiers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "is_decorative", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.CheckConstraint(
            "description_status IS NULL OR description_status IN ('described', 'skipped', 'not_described')",
            name=op.f("ck_extracted_elements_valid_description_status"),
        ),
        sa.CheckConstraint(
            "kind IN ('heading', 'paragraph', 'list_item', 'caption', 'table', 'image', 'page_furniture')",
            name=op.f("ck_extracted_elements_valid_kind"),
        ),
        sa.CheckConstraint(
            "origin IN ('text_layer', 'recognized')",
            name=op.f("ck_extracted_elements_valid_origin"),
        ),
        sa.CheckConstraint(
            "bbox_left < bbox_right AND bbox_top < bbox_bottom",
            name=op.f("ck_extracted_elements_ordered_box"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_extracted_elements_confidence_in_range"),
        ),
        sa.CheckConstraint(
            "page >= 1", name=op.f("ck_extracted_elements_positive_page")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_extracted_elements_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extracted_elements")),
    )
    op.create_index(
        op.f("ix_extracted_elements_document_id_page"),
        "extracted_elements",
        ["document_id", "page"],
        unique=False,
    )
    op.create_index(
        op.f("ix_extracted_elements_document_id_reading_order"),
        "extracted_elements",
        ["document_id", "reading_order"],
        unique=False,
    )
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=True),
        sa.Column("pages_total", sa.Integer(), nullable=True),
        sa.Column("pages_done", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("failure_code", sa.String(length=32), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL)",
            name=op.f("ck_ingestion_jobs_failure_iff_failed"),
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ('encrypted_document', 'corrupt_document', 'no_extractable_text', 'provider_unavailable', 'interrupted_repeatedly', 'internal_error')",
            name=op.f("ck_ingestion_jobs_valid_failure_code"),
        ),
        sa.CheckConstraint(
            "stage IS NULL OR stage IN ('extracting', 'describing_figures', 'building_units', 'embedding', 'indexing', 'finalizing')",
            name=op.f("ck_ingestion_jobs_valid_stage"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name=op.f("ck_ingestion_jobs_valid_status"),
        ),
        sa.CheckConstraint(
            "attempt >= 0 AND attempt <= max_attempts",
            name=op.f("ck_ingestion_jobs_attempt_in_range"),
        ),
        sa.CheckConstraint(
            "pages_done >= 0 AND (pages_total IS NULL OR pages_done <= pages_total)",
            name=op.f("ck_ingestion_jobs_progress_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_ingestion_jobs_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_jobs")),
    )
    op.create_index(
        op.f("ix_ingestion_jobs_document_id_created_at"),
        "ingestion_jobs",
        ["document_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingestion_jobs_status_lease_expires_at"),
        "ingestion_jobs",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_table(
        "element_relationships",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('caption_of', 'title_of', 'describes', 'near', 'continues')",
            name=op.f("ck_element_relationships_valid_kind"),
        ),
        sa.CheckConstraint(
            "source_id <> target_id", name=op.f("ck_element_relationships_no_self_link")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_element_relationships_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["extracted_elements.id"],
            name=op.f("fk_element_relationships_source_id_extracted_elements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["extracted_elements.id"],
            name=op.f("fk_element_relationships_target_id_extracted_elements"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "source_id", "target_id", "kind", name=op.f("pk_element_relationships")
        ),
    )
    op.create_index(
        op.f("ix_element_relationships_document_id"),
        "element_relationships",
        ["document_id"],
        unique=False,
    )
    op.execute(NOTIFY_FUNCTION)
    op.execute(NOTIFY_TRIGGER)


def downgrade() -> None:
    """Revert this revision."""
    op.execute("DROP TRIGGER ingestion_jobs_notify ON ingestion_jobs")
    op.execute("DROP FUNCTION notify_ingestion_job()")
    op.drop_index(
        op.f("ix_element_relationships_document_id"), table_name="element_relationships"
    )
    op.drop_table("element_relationships")
    op.drop_index(
        op.f("ix_ingestion_jobs_status_lease_expires_at"), table_name="ingestion_jobs"
    )
    op.drop_index(
        op.f("ix_ingestion_jobs_document_id_created_at"), table_name="ingestion_jobs"
    )
    op.drop_table("ingestion_jobs")
    op.drop_index(
        op.f("ix_extracted_elements_document_id_reading_order"),
        table_name="extracted_elements",
    )
    op.drop_index(
        op.f("ix_extracted_elements_document_id_page"), table_name="extracted_elements"
    )
    op.drop_table("extracted_elements")
    op.drop_index(op.f("ix_documents_created_at_id"), table_name="documents")
    op.drop_table("documents")
