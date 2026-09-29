import pytest

from multimodal_rag.shared import errors

FAMILIES = [
    errors.ConfigurationError,
    errors.ValidationError,
    errors.NotFoundError,
    errors.ExtractionError,
    errors.ProviderError,
    errors.StorageError,
    errors.ConcurrencyError,
    errors.DataInconsistencyError,
]


@pytest.mark.parametrize("family", FAMILIES)
def test_every_family_derives_from_the_root_error(
    family: type[errors.MultimodalRagError],
) -> None:
    assert issubclass(family, errors.MultimodalRagError)


def test_codes_are_unique_across_the_hierarchy() -> None:
    classes = [errors.MultimodalRagError, *FAMILIES]
    classes += [
        errors.ProviderUnavailableError,
        errors.ProviderTimeoutError,
        errors.ProviderResponseError,
        errors.StorageUnavailableError,
        errors.StorageTimeoutError,
    ]
    codes = [cls.code for cls in classes]

    assert len(codes) == len(set(codes))


@pytest.mark.parametrize(
    "error",
    [
        errors.ProviderUnavailableError,
        errors.ProviderTimeoutError,
        errors.ProviderResponseError,
    ],
)
def test_provider_errors_belong_to_the_provider_family(
    error: type[errors.MultimodalRagError],
) -> None:
    assert issubclass(error, errors.ProviderError)


@pytest.mark.parametrize(
    "error", [errors.StorageUnavailableError, errors.StorageTimeoutError]
)
def test_transient_storage_errors_belong_to_the_storage_family(
    error: type[errors.MultimodalRagError],
) -> None:
    assert issubclass(error, errors.StorageError)


def test_an_error_keeps_its_message() -> None:
    error = errors.NotFoundError("job 42 does not exist")

    assert str(error) == "job 42 does not exist"
    assert error.code == "not_found"
