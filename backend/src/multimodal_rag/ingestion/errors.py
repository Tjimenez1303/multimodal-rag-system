"""Errors specific to document ingestion, one per root cause."""

from multimodal_rag.shared.errors import (
    ConcurrencyError,
    DataInconsistencyError,
    ExtractionError,
    NotFoundError,
    ProviderError,
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


class InvalidFileNameError(ValidationError):
    """The uploaded file name is empty or longer than the documented limit."""

    code = "invalid_file_name"


class InvalidCursorError(ValidationError):
    """A pagination cursor was not issued by the system or is damaged."""

    code = "invalid_cursor"


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


class ServiceFailedError(ProviderError):
    """An external service used by processing failed after its retries.

    Args:
        service: Name of the service shown to clients, such as ``embedding model``.
        transient: Whether the service was unavailable, as opposed to rejecting a
            request.
    """

    code = "service_failed"

    def __init__(self, service: str, *, transient: bool) -> None:
        super().__init__(f"The {service} failed")
        self.service = service
        self.transient = transient


class ImageNotFoundError(NotFoundError):
    """The requested element has no stored image."""

    code = "image_not_found"


class PageNotFoundError(NotFoundError):
    """The requested page number is outside the document."""

    code = "page_not_found"


class InvalidJobTransitionError(ConcurrencyError):
    """A job was asked to move to a state its current state does not allow."""

    code = "invalid_job_transition"


class LeaseLostError(ConcurrencyError):
    """The worker no longer holds the lease of the job it is writing to."""

    code = "lease_lost"


class IngestionNotCompletedError(ConcurrencyError):
    """The document has no completed ingestion yet."""

    code = "ingestion_not_completed"


class IngestionInProgressError(ConcurrencyError):
    """The document has a job that is pending or processing."""

    code = "ingestion_in_progress"


class JobNotLeasedError(DataInconsistencyError):
    """A job was handed to processing without the lease of a claim."""

    code = "job_not_leased"


class InvalidBoundingBoxError(DataInconsistencyError):
    """A bounding box has inverted edges or lies outside its page."""

    code = "invalid_bounding_box"


class InvalidPageSizeError(DataInconsistencyError):
    """A page size is not a positive, finite number of points."""

    code = "invalid_page_size"


class UnknownPageSizeError(DataInconsistencyError):
    """An element lies on a page whose size the extractor did not report."""

    code = "unknown_page_size"


class ElementWithoutPositionError(DataInconsistencyError):
    """An extracted element lacks its page number or bounding box."""

    code = "element_without_position"


class InvalidDocumentError(DataInconsistencyError):
    """A document record breaks its identity rules."""

    code = "invalid_document"


class InvalidElementError(DataInconsistencyError):
    """An extracted element carries fields that do not match its kind."""

    code = "invalid_element"
