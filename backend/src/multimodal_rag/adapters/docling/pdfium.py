"""PDF reads with pypdfium2 that need no rendering: validation, page count and layout.

PDFium is not thread-safe, not even across documents, so every PDFium call holds
Docling's ``pypdfium2_lock``, as Docling does around its own calls. Concurrent uploads
and the worker's extraction thread then never call PDFium at the same time.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from docling.utils.locks import pypdfium2_lock
from docling.utils.pdf_outline import extract_outline_from_pdfium

from multimodal_rag.adapters.docling.headings import OutlineEntry
from multimodal_rag.ingestion.errors import (
    CorruptDocumentError,
    EncryptedDocumentError,
    UnsupportedMediaTypeError,
)
from multimodal_rag.ingestion.ports import PdfInfo

_ENCRYPTION_ERRORS = frozenset(
    {pdfium_raw.FPDF_ERR_PASSWORD, pdfium_raw.FPDF_ERR_SECURITY}
)


@dataclass(frozen=True, slots=True)
class PdfLayout:
    """Document-wide facts the extractor needs before converting pages.

    Attributes:
        page_count: Number of pages.
        pages_without_text: 1-based pages whose text layer has no characters.
        outline: Bookmarks of the document, in document order.
    """

    page_count: int
    pages_without_text: frozenset[int]
    outline: tuple[OutlineEntry, ...]


class PdfiumInspector:
    """``PdfInspector`` that validates an upload by content and counts its pages."""

    def inspect(self, path: Path) -> PdfInfo:
        """Read the page count and encryption flag of a PDF.

        PDFium itself decides whether the bytes are a PDF, so no separate header
        check is needed. Encrypted files are accepted with no page count, so their
        job fails later with a reason instead of the upload being rejected.

        Args:
            path: Uploaded file.

        Returns:
            The page count, or ``None`` with the encrypted flag for encrypted files.

        Raises:
            UnsupportedMediaTypeError: If PDFium cannot load the file as a PDF.
        """
        try:
            with open_pdf(path) as document, pypdfium2_lock:
                return PdfInfo(page_count=len(document), encrypted=False)
        except EncryptedDocumentError:
            return PdfInfo(page_count=None, encrypted=True)
        except CorruptDocumentError as error:
            raise UnsupportedMediaTypeError("The file is not a readable PDF") from error


@contextmanager
def open_pdf(path: Path) -> Iterator[pdfium.PdfDocument]:
    """Open a PDF and close it when the block ends.

    Opening and closing hold the PDFium lock. Callers hold it around their own
    PDFium calls inside the block.

    Args:
        path: PDF to open.

    Yields:
        The open document, usable only inside the block.

    Raises:
        EncryptedDocumentError: If the PDF needs a password or uses an unsupported
            security handler.
        CorruptDocumentError: If PDFium cannot load the file.
    """
    with pypdfium2_lock:
        try:
            document = pdfium.PdfDocument(path)
        except pdfium.PdfiumError as error:
            if error.err_code in _ENCRYPTION_ERRORS:
                raise EncryptedDocumentError("The PDF is encrypted") from error
            raise CorruptDocumentError("PDFium cannot load the PDF") from error
    try:
        yield document
    finally:
        with pypdfium2_lock:
            document.close()


def read_layout(path: Path) -> PdfLayout:
    """Read the page count, the pages without a text layer and the outline.

    The outline comes from Docling's ``extract_outline_from_pdfium``, which takes the
    PDFium lock itself and skips bookmarks without a title.

    Args:
        path: PDF to read.

    Returns:
        The document-wide layout facts.

    Raises:
        EncryptedDocumentError: If the PDF is encrypted.
        CorruptDocumentError: If the PDF or one of its pages cannot be loaded.
    """
    with open_pdf(path) as document:
        with pypdfium2_lock:
            try:
                page_count = len(document)
                pages_without_text = frozenset(
                    number
                    for number in range(1, page_count + 1)
                    if _character_count(document, number - 1) == 0
                )
            except pdfium.PdfiumError as error:
                raise CorruptDocumentError("PDFium cannot load a page") from error
        outline = tuple(
            OutlineEntry(depth=item.level, title=item.title, page=item.page_no)
            for item in extract_outline_from_pdfium(document)
        )
    return PdfLayout(
        page_count=page_count, pages_without_text=pages_without_text, outline=outline
    )


def _character_count(document: pdfium.PdfDocument, index: int) -> int:
    page = document[index]
    try:
        text_page = page.get_textpage()
        try:
            return int(text_page.count_chars())
        finally:
            text_page.close()
    finally:
        page.close()
