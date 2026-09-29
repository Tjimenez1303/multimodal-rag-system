from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from multimodal_rag.adapters.storage.filesystem import (
    FilesystemBlobStorage,
    InvalidBlobKeyError,
)
from multimodal_rag.ingestion.errors import BlobNotFoundError


async def chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def failing_chunks() -> AsyncIterator[bytes]:
    yield b"partial"
    raise ConnectionResetError("client went away")


@pytest.fixture
def storage(tmp_path: Path) -> FilesystemBlobStorage:
    return FilesystemBlobStorage(tmp_path)


async def test_save_stream_writes_every_chunk_and_reports_the_size(
    storage: FilesystemBlobStorage,
) -> None:
    size = await storage.save_stream("documents/abc.pdf", chunks(b"%PDF-", b"1.7"))

    assert size == 8
    assert await storage.read_bytes("documents/abc.pdf") == b"%PDF-1.7"


async def test_a_failed_stream_leaves_no_file_behind(
    storage: FilesystemBlobStorage, tmp_path: Path
) -> None:
    with pytest.raises(ConnectionResetError):
        await storage.save_stream("staging/upload.pdf", failing_chunks())

    assert not await storage.exists("staging/upload.pdf")
    assert list((tmp_path / "staging").iterdir()) == []


async def test_save_bytes_replaces_existing_content(
    storage: FilesystemBlobStorage,
) -> None:
    await storage.save_bytes("figures/doc/fig.png", b"old")
    await storage.save_bytes("figures/doc/fig.png", b"new")

    assert await storage.read_bytes("figures/doc/fig.png") == b"new"


async def test_move_renames_an_object(storage: FilesystemBlobStorage) -> None:
    await storage.save_bytes("staging/x.pdf", b"%PDF-")

    await storage.move("staging/x.pdf", "documents/x.pdf")

    assert await storage.exists("documents/x.pdf")
    assert not await storage.exists("staging/x.pdf")


async def test_delete_is_idempotent(storage: FilesystemBlobStorage) -> None:
    await storage.save_bytes("figures/a.png", b"png")

    await storage.delete("figures/a.png")
    await storage.delete("figures/a.png")

    assert not await storage.exists("figures/a.png")


async def test_delete_tree_removes_every_object_under_a_prefix_only(
    storage: FilesystemBlobStorage,
) -> None:
    for key in ("pages/a/1.png", "pages/a/2.png", "pages/ab/1.png", "figures/a/x.png"):
        await storage.save_bytes(key, b"png")

    await storage.delete_tree("pages/a")
    await storage.delete_tree("pages/a")
    await storage.delete_tree("pages/never")

    assert not await storage.exists("pages/a/1.png")
    assert not await storage.exists("pages/a/2.png")
    assert await storage.exists("pages/ab/1.png")
    assert await storage.exists("figures/a/x.png")


async def test_delete_tree_rejects_unsafe_prefixes(
    storage: FilesystemBlobStorage,
) -> None:
    with pytest.raises(InvalidBlobKeyError):
        await storage.delete_tree("../outside")


async def test_materialize_yields_the_stored_file(
    storage: FilesystemBlobStorage,
) -> None:
    await storage.save_bytes("documents/y.pdf", b"%PDF-y")

    with storage.materialize("documents/y.pdf") as path:
        assert path.read_bytes() == b"%PDF-y"


async def test_missing_objects_raise_blob_not_found(
    storage: FilesystemBlobStorage,
) -> None:
    with pytest.raises(BlobNotFoundError):
        await storage.read_bytes("documents/missing.pdf")
    with pytest.raises(BlobNotFoundError):
        await storage.move("documents/missing.pdf", "documents/other.pdf")
    with pytest.raises(BlobNotFoundError), storage.materialize("missing.pdf"):
        pass


@pytest.mark.parametrize("key", ["", "/etc/passwd", "../outside.pdf", "a/../../b"])
async def test_unsafe_keys_are_rejected(
    storage: FilesystemBlobStorage, key: str
) -> None:
    with pytest.raises(InvalidBlobKeyError):
        await storage.save_bytes(key, b"x")


async def test_check_writable_leaves_no_probe_behind(
    storage: FilesystemBlobStorage, tmp_path: Path
) -> None:
    await storage.check_writable()

    assert list((tmp_path / ".probes").iterdir()) == []
