"""Error hierarchy shared by every layer.

Every error raised on purpose derives from ``MultimodalRagError`` and belongs to one
failure family. Each family and each concrete error carries a stable ``code`` that
clients and logs can rely on, and adapters map families to transport concerns such as
HTTP status codes in a single place.
"""

from typing import ClassVar


class MultimodalRagError(Exception):
    """Root of every error raised on purpose by the system."""

    code: ClassVar[str] = "internal_error"


class ConfigurationError(MultimodalRagError):
    """A required setting is missing or invalid, detected at startup."""

    code = "configuration_error"


class ValidationError(MultimodalRagError):
    """Input supplied by a caller breaks a documented rule."""

    code = "invalid_request"


class NotFoundError(MultimodalRagError):
    """A resource referenced by a caller does not exist."""

    code = "not_found"


class ExtractionError(MultimodalRagError):
    """A document cannot be read or yields no usable content."""

    code = "extraction_error"


class ProviderError(MultimodalRagError):
    """An external service such as a model or the vector index failed."""

    code = "provider_error"


class ProviderUnavailableError(ProviderError):
    """An external service is unreachable or answered with a transient error."""

    code = "provider_unavailable"


class ProviderTimeoutError(ProviderError):
    """An external service did not answer within its configured timeout."""

    code = "provider_timeout"


class ProviderResponseError(ProviderError):
    """An external service rejected the request or returned an unusable answer."""

    code = "provider_response_error"


class StorageError(MultimodalRagError):
    """Stored data or files cannot be read or written."""

    code = "storage_error"


class StorageUnavailableError(StorageError):
    """A storage service is unreachable or dropped its connection."""

    code = "storage_unavailable"


class StorageTimeoutError(StorageError):
    """A storage service did not answer within its configured timeout."""

    code = "storage_timeout"


class ConcurrencyError(MultimodalRagError):
    """An operation conflicts with the current state of a resource."""

    code = "conflict"


class DataInconsistencyError(MultimodalRagError):
    """Data breaks an invariant the system relies on. Always an internal error."""

    code = "data_inconsistency"
