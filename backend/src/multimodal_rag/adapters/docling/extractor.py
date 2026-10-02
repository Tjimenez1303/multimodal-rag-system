"""``DocumentExtractor`` adapter backed by Docling.

One converter is built per worker process and reused for every document, because
loading the layout, table and OCR models dominates start-up time. Documents are
converted in page ranges, so the job reports progress per batch and memory stays
bounded by the batch size. Each range has its own conversion timeout.
"""

import io
import logging
import uuid
from collections.abc import Iterator
from pathlib import Path

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.backend_options import ThreadedDoclingParseBackendOptions
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.exceptions import ConversionError

from multimodal_rag.adapters.docling.headings import HeadingLevels
from multimodal_rag.adapters.docling.mapping import DocumentContext, map_document
from multimodal_rag.adapters.docling.pdfium import read_layout
from multimodal_rag.ingestion.errors import CorruptDocumentError
from multimodal_rag.ingestion.ports import ExtractionBatch

logger = logging.getLogger(__name__)

# Crops are rendered at twice the PDF resolution, 144 dpi, for the vision model.
IMAGES_SCALE = 2.0


class DoclingExtractor:
    """Extracts typed elements with page and position from PDFs.

    Args:
        artifacts_path: Directory with pre-downloaded models, or ``None`` to download
            them on first use.
        threads: CPU threads for the models and for the PDF parser.
        batch_timeout_seconds: Longest conversion of one page batch.
    """

    def __init__(
        self,
        *,
        artifacts_path: Path | None,
        threads: int,
        batch_timeout_seconds: float,
    ) -> None:
        # OCR, table structure, figure classification and images, all on CPU
        options = PdfPipelineOptions(
            artifacts_path=artifacts_path,
            document_timeout=batch_timeout_seconds,
            do_ocr=True,
            ocr_options=RapidOcrOptions(),
            do_table_structure=True,
            do_picture_classification=True,
            generate_picture_images=True,
            # Pages are rendered for the figure crops anyway, so keeping the page
            # images only adds their PNG encoding.
            generate_page_images=True,
            images_scale=IMAGES_SCALE,
            accelerator_options=AcceleratorOptions(
                num_threads=threads, device=AcceleratorDevice.CPU
            ),
        )
        # The parser takes its threads from its own options, not from the pipeline.
        backend_options = ThreadedDoclingParseBackendOptions(parser_threads=threads)

        # One converter for PDFs, reused by every job of this process
        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=options, backend_options=backend_options
                )
            }
        )

    def warm_up(self) -> None:
        """Load every model now, so the first job does not pay for it.

        Raises:
            FileNotFoundError: If ``artifacts_path`` lacks a required model.
        """
        self._converter.initialize_pipeline(InputFormat.PDF)

    def extract(
        self,
        *,
        path: Path,
        document_id: uuid.UUID,
        document_sha256: str,
        batch_size: int,
    ) -> Iterator[ExtractionBatch]:
        """Extract elements page batch by page batch.

        Blocking: the caller runs it in a worker thread.

        Args:
            path: PDF to extract.
            document_id: Document the elements belong to.
            document_sha256: Fingerprint used to derive stable element ids.
            batch_size: Pages converted per batch.

        Yields:
            One batch per page range, in page order.

        Raises:
            EncryptedDocumentError: If the PDF is encrypted.
            CorruptDocumentError: If the PDF or one of its pages cannot be parsed.
        """
        # Read document-wide facts first: page count, scanned pages and outline
        layout = read_layout(path)
        context = DocumentContext(
            document_id=document_id,
            sha256=document_sha256,
            pages_without_text=layout.pages_without_text,
            headings=HeadingLevels(layout.outline),
        )

        # Reading order continues across batches
        next_order = 0

        # Convert the PDF batch_size pages at a time
        for first in range(1, layout.page_count + 1, batch_size):
            last = min(first + batch_size - 1, layout.page_count)
            result = self._convert(path, first, last)

            # Map Docling's output to domain elements, crops and caption links
            mapped = map_document(
                result.document,
                context=context,
                first_order=next_order,
                ocr_scores={
                    page: scores.ocr_score
                    for page, scores in result.confidence.pages.items()
                },
            )
            next_order += len(mapped.elements)
            logger.debug("extracted pages %s to %s", first, last)

            # Hand the batch to the caller, with its page images and recognized pages
            yield ExtractionBatch(
                first_page=first,
                last_page=last,
                pages_total=layout.page_count,
                elements=mapped.elements,
                images=mapped.images,
                page_sizes=mapped.page_sizes,
                relationships=mapped.relationships,
                page_images=_page_images(result, first, last),
                recognized_pages=tuple(
                    page
                    for page in range(first, last + 1)
                    if page in layout.pages_without_text
                ),
            )

    def _convert(self, path: Path, first: int, last: int) -> ConversionResult:
        try:
            # Convert only the pages of this batch
            result = self._converter.convert(path, page_range=(first, last))
        except ConversionError as error:
            raise CorruptDocumentError(
                f"Pages {first} to {last} cannot be converted"
            ) from error
        # Docling returns failed or timed-out pages as a partial success.
        if result.status is not ConversionStatus.SUCCESS:
            raise CorruptDocumentError(
                f"Pages {first} to {last} were converted only partially"
            )
        return result


def _page_images(result: ConversionResult, first: int, last: int) -> dict[int, bytes]:
    """Encode the rendered image of every page of a batch as PNG.

    Raises:
        CorruptDocumentError: If Docling rendered no image for one of the pages.
    """
    images: dict[int, bytes] = {}

    # Encode the rendered image of each page of the batch as PNG
    for page_number in range(first, last + 1):
        page = result.document.pages.get(page_number)
        image = page.image.pil_image if page and page.image else None
        if image is None:
            raise CorruptDocumentError(f"Page {page_number} could not be rendered")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        images[page_number] = buffer.getvalue()
    return images
