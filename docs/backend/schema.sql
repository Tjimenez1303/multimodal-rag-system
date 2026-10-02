-- Generated offline by Alembic (upgrade head --sql), migrations 0001 to 0004.
-- Alembic bookkeeping (alembic_version) and BEGIN/COMMIT removed.

-- Running upgrade  -> 0001

CREATE TABLE documents (
    id UUID NOT NULL,
    sha256 CHAR(64) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    size_bytes BIGINT NOT NULL,
    page_count INTEGER,
    blob_key TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_documents PRIMARY KEY (id),
    CONSTRAINT ck_documents_positive_pages CHECK (page_count IS NULL OR page_count > 0),
    CONSTRAINT ck_documents_positive_size CHECK (size_bytes > 0),
    CONSTRAINT uq_documents_sha256 UNIQUE (sha256)
);

CREATE INDEX ix_documents_created_at_id ON documents (created_at, id);

CREATE TABLE extracted_elements (
    id UUID NOT NULL,
    document_id UUID NOT NULL,
    kind VARCHAR(16) NOT NULL,
    page INTEGER NOT NULL,
    bbox_left FLOAT NOT NULL,
    bbox_top FLOAT NOT NULL,
    bbox_right FLOAT NOT NULL,
    bbox_bottom FLOAT NOT NULL,
    reading_order INTEGER NOT NULL,
    origin VARCHAR(16) NOT NULL,
    heading_level INTEGER,
    text TEXT,
    table_rows JSONB,
    confidence FLOAT,
    image_key TEXT,
    image_class TEXT,
    labels JSONB DEFAULT '[]' NOT NULL,
    description TEXT,
    description_status VARCHAR(16),
    unverified_identifiers JSONB DEFAULT '[]' NOT NULL,
    is_decorative BOOLEAN DEFAULT 'false' NOT NULL,
    CONSTRAINT pk_extracted_elements PRIMARY KEY (id),
    CONSTRAINT ck_extracted_elements_valid_description_status CHECK (description_status IS NULL OR description_status IN ('described', 'skipped', 'not_described')),
    CONSTRAINT ck_extracted_elements_valid_kind CHECK (kind IN ('heading', 'paragraph', 'list_item', 'caption', 'table', 'image', 'page_furniture')),
    CONSTRAINT ck_extracted_elements_valid_origin CHECK (origin IN ('text_layer', 'recognized')),
    CONSTRAINT ck_extracted_elements_ordered_box CHECK (bbox_left < bbox_right AND bbox_top < bbox_bottom),
    CONSTRAINT ck_extracted_elements_confidence_in_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT ck_extracted_elements_positive_page CHECK (page >= 1),
    CONSTRAINT fk_extracted_elements_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE INDEX ix_extracted_elements_document_id_page ON extracted_elements (document_id, page);

CREATE INDEX ix_extracted_elements_document_id_reading_order ON extracted_elements (document_id, reading_order);

CREATE TABLE ingestion_jobs (
    id UUID NOT NULL,
    document_id UUID NOT NULL,
    status VARCHAR(16) NOT NULL,
    stage VARCHAR(32),
    pages_total INTEGER,
    pages_done INTEGER DEFAULT '0' NOT NULL,
    attempt INTEGER DEFAULT '0' NOT NULL,
    max_attempts INTEGER NOT NULL,
    lease_token UUID,
    lease_expires_at TIMESTAMP WITH TIME ZONE,
    worker_id TEXT,
    correlation_id TEXT NOT NULL,
    failure_code VARCHAR(32),
    failure_reason TEXT,
    summary JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_ingestion_jobs PRIMARY KEY (id),
    CONSTRAINT ck_ingestion_jobs_failure_iff_failed CHECK ((status = 'failed') = (failure_code IS NOT NULL)),
    CONSTRAINT ck_ingestion_jobs_valid_failure_code CHECK (failure_code IS NULL OR failure_code IN ('encrypted_document', 'corrupt_document', 'no_extractable_text', 'provider_unavailable', 'interrupted_repeatedly', 'internal_error')),
    CONSTRAINT ck_ingestion_jobs_valid_stage CHECK (stage IS NULL OR stage IN ('extracting', 'describing_figures', 'building_units', 'embedding', 'indexing', 'finalizing')),
    CONSTRAINT ck_ingestion_jobs_valid_status CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    CONSTRAINT ck_ingestion_jobs_attempt_in_range CHECK (attempt >= 0 AND attempt <= max_attempts),
    CONSTRAINT ck_ingestion_jobs_progress_in_range CHECK (pages_done >= 0 AND (pages_total IS NULL OR pages_done <= pages_total)),
    CONSTRAINT fk_ingestion_jobs_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE INDEX ix_ingestion_jobs_document_id_created_at ON ingestion_jobs (document_id, created_at);

CREATE INDEX ix_ingestion_jobs_status_lease_expires_at ON ingestion_jobs (status, lease_expires_at);

CREATE TABLE element_relationships (
    document_id UUID NOT NULL,
    source_id UUID NOT NULL,
    target_id UUID NOT NULL,
    kind VARCHAR(16) NOT NULL,
    score FLOAT,
    CONSTRAINT pk_element_relationships PRIMARY KEY (source_id, target_id, kind),
    CONSTRAINT ck_element_relationships_valid_kind CHECK (kind IN ('caption_of', 'title_of', 'describes', 'near', 'continues')),
    CONSTRAINT ck_element_relationships_no_self_link CHECK (source_id <> target_id),
    CONSTRAINT fk_element_relationships_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE,
    CONSTRAINT fk_element_relationships_source_id_extracted_elements FOREIGN KEY(source_id) REFERENCES extracted_elements (id) ON DELETE CASCADE,
    CONSTRAINT fk_element_relationships_target_id_extracted_elements FOREIGN KEY(target_id) REFERENCES extracted_elements (id) ON DELETE CASCADE
);

CREATE INDEX ix_element_relationships_document_id ON element_relationships (document_id);

CREATE FUNCTION notify_ingestion_job() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('ingestion_jobs', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ingestion_jobs_notify
AFTER INSERT ON ingestion_jobs
FOR EACH ROW EXECUTE FUNCTION notify_ingestion_job();

-- Running upgrade 0001 -> 0002

CREATE UNIQUE INDEX uq_ingestion_jobs_document_id_active ON ingestion_jobs (document_id) WHERE status <> 'failed';

-- Running upgrade 0002 -> 0003

DROP INDEX ix_extracted_elements_document_id_reading_order;

ALTER TABLE extracted_elements ADD CONSTRAINT uq_extracted_elements_document_id_reading_order UNIQUE (document_id, reading_order);

CREATE INDEX ix_ingestion_jobs_pending_created_at ON ingestion_jobs (created_at, id) WHERE status = 'pending';

-- Running upgrade 0003 -> 0004

CREATE INDEX ix_element_relationships_target_id ON element_relationships (target_id);
