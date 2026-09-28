import multimodal_rag


def test_package_exposes_its_installed_version() -> None:
    assert multimodal_rag.__version__ == "0.1.0"
