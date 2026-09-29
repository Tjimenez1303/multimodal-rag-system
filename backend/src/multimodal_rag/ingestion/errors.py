"""Errors specific to document ingestion, one per root cause."""

from multimodal_rag.shared.errors import (
    ConcurrencyError,
    DataInconsistencyError,
    ExtractionError,
    NotFoundError,
    StorageError,
    ValidationError,
)


class UnsupportedMediaTypeError(ValidationError):
    """The uploaded file is not a PDF, judged by its content."""

    code = "unsupported_media_type"


class FileTooLargeError(ValidationError):
    """The uploaded file exceeds the configured size limit."""

    code = "file_too_large"


class PageLimitExceededError(ValidationError):
    """The uploaded PDF has more pages than the configured limit."""

    code = "page_limit_exceeded"


class DocumentNotFoundError(NotFoundError):
    """No document exists with the requested id."""

    code = "document_not_found"


class JobNotFoundError(NotFoundError):
    """No ingestion job exists with the requested id."""

    code = "job_not_found"


class ElementNotFoundError(NotFoundError):
    """No extracted element exists with the requested id in the document."""

    code = "element_not_found"


class BlobNotFoundError(StorageError):
    """A stored file referenced by the system is missing."""

    code = "blob_not_found"


class EncryptedDocumentError(ExtractionError):
    """The PDF is password protected or encrypted."""

    code = "encrypted_document"


class CorruptDocumentError(ExtractionError):
    """The PDF cannot be parsed."""

    code = "corrupt_document"


class NoExtractableTextError(ExtractionError):
    """No page yields text from its text layer or from recognition."""

    code = "no_extractable_text"


class InvalidJobTransitionError(ConcurrencyError):
    """A job was asked to move to a state its current state does not allow."""

    code = "invalid_job_transition"


class LeaseLostError(ConcurrencyError):
    """The worker no longer holds the lease of the job it is writing to."""

    code = "lease_lost"


class IngestionNotCompletedError(ConcurrencyError):
    """The document has no completed ingestion yet."""

    code = "ingestion_not_completed"


class InvalidBoundingBoxError(DataInconsistencyError):
    """A bounding box has inverted edges or lies outside its page."""

    code = "invalid_bounding_box"


class ElementWithoutPositionError(DataInconsistencyError):
    """An extracted element lacks its page number or bounding box."""

    code = "element_without_position"


class InvalidDocumentError(DataInconsistencyError):
    """A document record breaks its identity rules."""

    code = "invalid_document"


class InvalidElementError(DataInconsistencyError):
    """An extracted element carries fields that do not match its kind."""

    code = "invalid_element"
