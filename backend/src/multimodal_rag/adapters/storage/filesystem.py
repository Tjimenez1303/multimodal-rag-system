"""Blob storage on a local directory, such as a Docker volume shared by processes."""

import asyncio
import contextlib
import logging
import os
import shutil
import uuid
from collections.abc import AsyncIterable, Generator
from pathlib import Path, PurePosixPath

from multimodal_rag.ingestion.errors import BlobNotFoundError
from multimodal_rag.shared.errors import StorageError

logger = logging.getLogger(__name__)


class InvalidBlobKeyError(StorageError):
    """A blob key is absolute, empty or escapes the storage root."""

    code = "invalid_blob_key"


class FilesystemBlobStorage:
    """Stores objects as files under a root directory.

    Every write goes to a temporary file in the destination directory and is then
    renamed over the final path, so readers never observe a partial file.

    Args:
        root: Directory that holds every stored object.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def save_stream(self, key: str, chunks: AsyncIterable[bytes]) -> int:
        """Write a stream atomically under a key.

        Args:
            key: Destination key.
            chunks: Content to write, in order.

        Returns:
            The number of bytes written.

        Raises:
            InvalidBlobKeyError: If the key is not a safe relative path.
        """
        # Write to a temporary file next to the destination
        final_path = self._path(key)
        temp_path = self._temporary_path(final_path)
        size = 0
        try:
            # Copy the stream chunk by chunk, off the event loop
            handle = await asyncio.to_thread(temp_path.open, "wb")
            try:
                async for chunk in chunks:
                    await asyncio.to_thread(handle.write, chunk)
                    size += len(chunk)
            finally:
                await asyncio.to_thread(handle.close)

            # Swap the finished file into place in one atomic rename
            await asyncio.to_thread(os.replace, temp_path, final_path)
        except BaseException:
            # Never leave a half-written temporary file behind
            temp_path.unlink(missing_ok=True)
            raise
        return size

    async def save_bytes(self, key: str, data: bytes) -> None:
        """Write a small payload atomically under a key.

        Args:
            key: Destination key.
            data: Content to write.

        Raises:
            InvalidBlobKeyError: If the key is not a safe relative path.
        """
        # Write to a temporary file, then rename it into place
        final_path = self._path(key)
        temp_path = self._temporary_path(final_path)
        try:
            await asyncio.to_thread(temp_path.write_bytes, data)
            await asyncio.to_thread(os.replace, temp_path, final_path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

    async def read_bytes(self, key: str) -> bytes:
        """Return the content stored under a key.

        Args:
            key: Key of the object.

        Returns:
            The stored bytes.

        Raises:
            BlobNotFoundError: If nothing is stored under the key.
        """
        path = self._existing_path(key)
        return await asyncio.to_thread(path.read_bytes)

    async def move(self, source: str, destination: str) -> None:
        """Rename a stored object, replacing any object at the destination.

        Args:
            source: Key of the object to rename.
            destination: New key of the object.

        Raises:
            BlobNotFoundError: If nothing is stored under the source key.
        """
        source_path = self._existing_path(source)
        destination_path = self._path(destination)
        await asyncio.to_thread(os.replace, source_path, destination_path)

    async def delete(self, key: str) -> None:
        """Remove a stored object if it exists.

        Args:
            key: Key of the object.
        """
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)

    async def delete_tree(self, prefix: str) -> None:
        """Remove every object stored under a key prefix, if any.

        Args:
            prefix: Leading path segments of the keys, such as ``pages/{id}``.

        Raises:
            InvalidBlobKeyError: If the prefix is not a safe relative path.
        """
        path = self._path(prefix)

        # Remove the whole folder of the prefix, if it exists
        if await asyncio.to_thread(path.is_dir):
            await asyncio.to_thread(shutil.rmtree, path)

    async def exists(self, key: str) -> bool:
        """Return whether an object is stored under a key.

        Args:
            key: Key to look up.

        Returns:
            Whether the object exists.
        """
        return await asyncio.to_thread(self._path(key).is_file)

    async def check_writable(self) -> None:
        """Write and remove a probe file to prove the storage accepts writes.

        Raises:
            OSError: If the root directory cannot be written.
        """
        # Write and delete a throwaway file under a private prefix
        probe = f".probes/{uuid.uuid4().hex}"
        await self.save_bytes(probe, b"ok")
        await self.delete(probe)

    @contextlib.contextmanager
    def materialize(self, key: str) -> Generator[Path]:
        """Yield the local path of a stored object.

        Args:
            key: Key of the object.

        Yields:
            The path of the file, valid for the duration of the block.

        Raises:
            BlobNotFoundError: If nothing is stored under the key.
        """
        yield self._existing_path(key)

    def _path(self, key: str) -> Path:
        # Refuse keys that are empty, absolute or climb out of the root
        relative = PurePosixPath(key)
        if not key or relative.is_absolute() or ".." in relative.parts:
            raise InvalidBlobKeyError(f"Blob key {key!r} is not a safe relative path")

        # Map the key to a path under the root, creating its folders
        path = self._root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _existing_path(self, key: str) -> Path:
        path = self._path(key)
        if not path.is_file():
            raise BlobNotFoundError(f"No blob stored under {key}")
        return path

    @staticmethod
    def _temporary_path(final_path: Path) -> Path:
        # Same directory as the destination so the final rename stays atomic.
        return final_path.with_name(f".{final_path.name}.{uuid.uuid4().hex}.tmp")
