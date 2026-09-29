"""``DocumentExtractor`` adapter backed by Docling.

One converter is built per worker process and reused for every document, because
loading the layout, table and OCR models dominates start-up time. Documents are
converted in page ranges, as in docling-serve's split processing example, so the job
reports progress per batch and memory stays bounded by the batch size. Each range has
the conversion timeout Docling recommends for production.
"""

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
        options = PdfPipelineOptions(
            artifacts_path=artifacts_path,
            document_timeout=batch_timeout_seconds,
            do_ocr=True,
            ocr_options=RapidOcrOptions(),
            do_table_structure=True,
            do_picture_classification=True,
            generate_picture_images=True,
            images_scale=IMAGES_SCALE,
            accelerator_options=AcceleratorOptions(
                num_threads=threads, device=AcceleratorDevice.CPU
            ),
        )
        # The parser takes its threads from its own options, not from the pipeline.
        backend_options = ThreadedDoclingParseBackendOptions(parser_threads=threads)
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
        layout = read_layout(path)
        context = DocumentContext(
            document_id=document_id,
            sha256=document_sha256,
            pages_without_text=layout.pages_without_text,
            headings=HeadingLevels(layout.outline),
        )
        next_order = 0
        for first in range(1, layout.page_count + 1, batch_size):
            last = min(first + batch_size - 1, layout.page_count)
            result = self._convert(path, first, last)
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
            yield ExtractionBatch(
                first_page=first,
                last_page=last,
                pages_total=layout.page_count,
                elements=mapped.elements,
                images=mapped.images,
                recognized_pages=tuple(
                    page
                    for page in range(first, last + 1)
                    if page in layout.pages_without_text
                ),
            )

    def _convert(self, path: Path, first: int, last: int) -> ConversionResult:
        try:
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
