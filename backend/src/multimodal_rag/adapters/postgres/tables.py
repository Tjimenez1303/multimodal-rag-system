"""Schema of the PostgreSQL database, shared by the repositories and Alembic."""

from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from multimodal_rag.ingestion.domain import (
    DescriptionStatus,
    ElementKind,
    FailureCode,
    JobStage,
    JobStatus,
    RelationshipKind,
    TextOrigin,
)

metadata = sa.MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


# Literal SQL, because a bound parameter in an ON CONFLICT predicate stops PostgreSQL
# from matching the partial index once it switches to a generic plan.
ACTIVE_JOB_PREDICATE = "status <> 'failed'"


def _one_of(column: str, values: type[StrEnum]) -> str:
    allowed = ", ".join(f"'{member}'" for member in values)
    return f"{column} IN ({allowed})"


def _timestamp(name: str, *, nullable: bool) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


documents = sa.Table(
    "documents",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("sha256", sa.CHAR(64), nullable=False, unique=True),
    sa.Column("file_name", sa.String(255), nullable=False),
    sa.Column("size_bytes", sa.BigInteger(), nullable=False),
    sa.Column("page_count", sa.Integer(), nullable=True),
    sa.Column("blob_key", sa.Text(), nullable=False),
    _timestamp("created_at", nullable=False),
    sa.CheckConstraint("size_bytes > 0", name="positive_size"),
    sa.CheckConstraint("page_count IS NULL OR page_count > 0", name="positive_pages"),
    sa.Index(None, "created_at", "id"),
)

ingestion_jobs = sa.Table(
    "ingestion_jobs",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column(
        "document_id",
        sa.Uuid(),
        sa.ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("stage", sa.String(32), nullable=True),
    sa.Column("pages_total", sa.Integer(), nullable=True),
    sa.Column("pages_done", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("max_attempts", sa.Integer(), nullable=False),
    sa.Column("lease_token", sa.Uuid(), nullable=True),
    _timestamp("lease_expires_at", nullable=True),
    sa.Column("worker_id", sa.Text(), nullable=True),
    sa.Column("correlation_id", sa.Text(), nullable=False),
    sa.Column("failure_code", sa.String(32), nullable=True),
    sa.Column("failure_reason", sa.Text(), nullable=True),
    sa.Column("summary", postgresql.JSONB(), nullable=True),
    _timestamp("created_at", nullable=False),
    _timestamp("started_at", nullable=True),
    _timestamp("finished_at", nullable=True),
    _timestamp("updated_at", nullable=False),
    sa.CheckConstraint(_one_of("status", JobStatus), name="valid_status"),
    sa.CheckConstraint(
        f"stage IS NULL OR {_one_of('stage', JobStage)}", name="valid_stage"
    ),
    sa.CheckConstraint(
        f"failure_code IS NULL OR {_one_of('failure_code', FailureCode)}",
        name="valid_failure_code",
    ),
    sa.CheckConstraint(
        "attempt >= 0 AND attempt <= max_attempts", name="attempt_in_range"
    ),
    sa.CheckConstraint(
        "pages_done >= 0 AND (pages_total IS NULL OR pages_done <= pages_total)",
        name="progress_in_range",
    ),
    sa.CheckConstraint(
        "(status = 'failed') = (failure_code IS NOT NULL)", name="failure_iff_failed"
    ),
    sa.Index(None, "status", "lease_expires_at"),
    sa.Index(None, "document_id", "created_at"),
    # Serves the claim, which takes the oldest pending job first.
    sa.Index(
        "ix_ingestion_jobs_pending_created_at",
        "created_at",
        "id",
        postgresql_where=sa.text("status = 'pending'"),
    ),
    # At most one job that has not failed per document, so concurrent uploads of
    # identical content share one job.
    sa.Index(
        "uq_ingestion_jobs_document_id_active",
        "document_id",
        unique=True,
        postgresql_where=sa.text(ACTIVE_JOB_PREDICATE),
    ),
)

extracted_elements = sa.Table(
    "extracted_elements",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column(
        "document_id",
        sa.Uuid(),
        sa.ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("page", sa.Integer(), nullable=False),
    sa.Column("bbox_left", sa.Float(), nullable=False),
    sa.Column("bbox_top", sa.Float(), nullable=False),
    sa.Column("bbox_right", sa.Float(), nullable=False),
    sa.Column("bbox_bottom", sa.Float(), nullable=False),
    sa.Column("reading_order", sa.Integer(), nullable=False),
    sa.Column("origin", sa.String(16), nullable=False),
    sa.Column("heading_level", sa.Integer(), nullable=True),
    sa.Column("text", sa.Text(), nullable=True),
    sa.Column("table_rows", postgresql.JSONB(), nullable=True),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column("image_key", sa.Text(), nullable=True),
    sa.Column("image_class", sa.Text(), nullable=True),
    sa.Column("labels", postgresql.JSONB(), nullable=False, server_default="[]"),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("description_status", sa.String(16), nullable=True),
    sa.Column(
        "unverified_identifiers",
        postgresql.JSONB(),
        nullable=False,
        server_default="[]",
    ),
    sa.Column("is_decorative", sa.Boolean(), nullable=False, server_default="false"),
    sa.CheckConstraint(_one_of("kind", ElementKind), name="valid_kind"),
    sa.CheckConstraint(_one_of("origin", TextOrigin), name="valid_origin"),
    sa.CheckConstraint(
        "description_status IS NULL OR "
        + _one_of("description_status", DescriptionStatus),
        name="valid_description_status",
    ),
    sa.CheckConstraint("page >= 1", name="positive_page"),
    sa.CheckConstraint(
        "bbox_left < bbox_right AND bbox_top < bbox_bottom", name="ordered_box"
    ),
    sa.CheckConstraint(
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
        name="confidence_in_range",
    ),
    # Keyset pagination of elements relies on one element per reading position.
    sa.UniqueConstraint("document_id", "reading_order"),
    sa.Index(None, "document_id", "page"),
)

element_relationships = sa.Table(
    "element_relationships",
    metadata,
    sa.Column(
        "document_id",
        sa.Uuid(),
        sa.ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "source_id",
        sa.Uuid(),
        sa.ForeignKey("extracted_elements.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column(
        "target_id",
        sa.Uuid(),
        sa.ForeignKey("extracted_elements.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("kind", sa.String(16), primary_key=True),
    sa.Column("score", sa.Float(), nullable=True),
    sa.CheckConstraint(_one_of("kind", RelationshipKind), name="valid_kind"),
    sa.CheckConstraint("source_id <> target_id", name="no_self_link"),
    sa.Index(None, "document_id"),
    # The primary key serves lookups by source, this index serves lookups by target.
    sa.Index(None, "target_id"),
)
