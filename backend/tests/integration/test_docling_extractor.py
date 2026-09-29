"""Docling extraction and pypdfium2 inspection on the generated fixtures.

The extraction models load once per session. Without ``DOCLING_ARTIFACTS_PATH`` they
are downloaded to the default cache on first use.
"""

import os
import threading
import uuid
from pathlib import Path

import pytest
from docling.utils.locks import pypdfium2_lock
from pypdf import PdfWriter

from multimodal_rag.adapters.docling.extractor import DoclingExtractor
from multimodal_rag.adapters.docling.headings import OutlineEntry
from multimodal_rag.adapters.docling.pdfium import PdfiumInspector, read_layout
from multimodal_rag.ingestion.domain import (
    ElementKind,
    ExtractedElement,
    PageSize,
    TextOrigin,
)
from multimodal_rag.ingestion.errors import (
    CorruptDocumentError,
    EncryptedDocumentError,
    UnsupportedMediaTypeError,
)
from multimodal_rag.ingestion.ports import ExtractionBatch

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SHA = "e" * 64
# The page tree announces two pages, but the second kid is not a page object.
BROKEN_PAGE_PDF = b"""%PDF-1.7
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj
4 0 obj << /Type /Font >> endobj
trailer << /Root 1 0 R >>
%%EOF
"""


def artifacts_path() -> Path | None:
    # CI prefetches the models there, locally they come from the default caches.
    artifacts = os.environ.get("DOCLING_ARTIFACTS_PATH")
    return Path(artifacts) if artifacts else None


@pytest.fixture(scope="session")
def extractor() -> DoclingExtractor:
    extractor = DoclingExtractor(
        artifacts_path=artifacts_path(), threads=4, batch_timeout_seconds=120
    )
    extractor.warm_up()
    return extractor


def extract(
    extractor: DoclingExtractor, name: str, *, batch_size: int = 4
) -> list[ExtractionBatch]:
    return list(
        extractor.extract(
            path=FIXTURES / name,
            document_id=uuid.uuid4(),
            document_sha256=SHA,
            batch_size=batch_size,
        )
    )


def elements_of(batches: list[ExtractionBatch]) -> list[ExtractedElement]:
    return [element for batch in batches for element in batch.elements]


class TestInspector:
    def test_reports_the_page_count_of_a_digital_pdf(self) -> None:
        info = PdfiumInspector().inspect(FIXTURES / "split_table.pdf")

        assert (info.page_count, info.encrypted) == (2, False)

    def test_flags_encrypted_files_without_a_page_count(self) -> None:
        info = PdfiumInspector().inspect(FIXTURES / "encrypted.pdf")

        assert (info.page_count, info.encrypted) == (None, True)

    def test_rejects_a_text_file_renamed_to_pdf(self) -> None:
        with pytest.raises(UnsupportedMediaTypeError):
            PdfiumInspector().inspect(FIXTURES / "not_a_pdf.pdf")

    def test_waits_while_another_thread_uses_pdfium(self) -> None:
        # PDFium is not thread-safe, so every caller shares Docling's lock.
        finished = threading.Event()

        def inspect() -> None:
            PdfiumInspector().inspect(FIXTURES / "split_table.pdf")
            finished.set()

        with pypdfium2_lock:
            worker = threading.Thread(target=inspect)
            worker.start()
            assert not finished.wait(timeout=0.3)
        worker.join(timeout=5)

        assert finished.is_set()

    def test_a_page_that_cannot_be_loaded_makes_the_document_corrupt(
        self, tmp_path: Path
    ) -> None:
        broken = tmp_path / "broken_page.pdf"
        broken.write_bytes(BROKEN_PAGE_PDF)

        with pytest.raises(CorruptDocumentError):
            read_layout(broken)

    def test_reads_the_outline_with_the_page_of_each_bookmark(
        self, tmp_path: Path
    ) -> None:
        writer = PdfWriter(clone_from=FIXTURES / "split_table.pdf")
        chapter = writer.add_outline_item("Torque", 0)
        writer.add_outline_item("Continued table", 1, parent=chapter)
        writer.add_outline_item("   ", 1)
        outlined = tmp_path / "outlined.pdf"
        writer.write(outlined)

        layout = read_layout(outlined)

        assert layout.outline == (
            OutlineEntry(depth=0, title="Torque", page=1),
            OutlineEntry(depth=1, title="Continued table", page=2),
        )

    def test_rejects_a_pdf_header_followed_by_garbage(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.pdf"
        broken.write_bytes(b"%PDF-1.7\n" + b"\x00garbage" * 50)

        with pytest.raises(UnsupportedMediaTypeError):
            PdfiumInspector().inspect(broken)


@pytest.mark.slow
class TestExtractor:
    def test_digital_pdf_yields_typed_elements_with_page_and_box(
        self, extractor: DoclingExtractor
    ) -> None:
        batches = extract(extractor, "digital.pdf")

        elements = elements_of(batches)
        kinds = {element.kind for element in elements}
        assert {ElementKind.HEADING, ElementKind.PARAGRAPH} <= kinds
        assert {ElementKind.TABLE, ElementKind.IMAGE, ElementKind.CAPTION} <= kinds
        assert all(e.page == 1 and e.bbox.area > 0 for e in elements)
        assert all(e.bbox.bottom <= 842 and e.bbox.right <= 612 for e in elements)
        assert [e.reading_order for e in elements] == list(range(len(elements)))
        assert all(e.origin is TextOrigin.TEXT_LAYER for e in elements)

    def test_tables_keep_their_rows_and_columns(
        self, extractor: DoclingExtractor
    ) -> None:
        [table] = [
            e
            for e in elements_of(extract(extractor, "digital.pdf"))
            if e.kind is ElementKind.TABLE
        ]

        assert table.table is not None
        assert len(table.table) == 5
        assert all(len(row) == 4 for row in table.table)
        assert table.text

    def test_figures_carry_their_crop_class_and_printed_labels(
        self, extractor: DoclingExtractor
    ) -> None:
        batches = extract(extractor, "digital.pdf")

        [figure] = [e for e in elements_of(batches) if e.kind is ElementKind.IMAGE]
        assert batches[0].images[figure.id].startswith(b"\x89PNG")
        assert figure.image_class == "engineering_drawing"
        assert {"V-12", "P-1"} <= set(figure.labels)
        paragraphs = [e.text for e in elements_of(batches) if e.text]
        assert "V-12" not in paragraphs

    def test_every_page_reports_its_size(self, extractor: DoclingExtractor) -> None:
        # Which captions Docling assigns depends on its layout model, whose labels on
        # these synthetic pages differ between macOS and Linux, so the mapping of its
        # caption references is covered by the unit tests instead.
        batches = extract(extractor, "split_table.pdf", batch_size=1)

        assert [b.page_sizes for b in batches] == [
            {1: PageSize(width=612, height=792)},
            {2: PageSize(width=612, height=792)},
        ]

    def test_numbered_headings_get_their_depth(
        self, extractor: DoclingExtractor
    ) -> None:
        headings = [
            (e.text, e.heading_level)
            for e in elements_of(extract(extractor, "digital.pdf"))
            if e.kind is ElementKind.HEADING
        ]

        assert ("1. Magneto inspection", 1) in headings

    def test_scanned_pages_yield_recognized_text_with_confidence(
        self, extractor: DoclingExtractor
    ) -> None:
        batches = extract(extractor, "scanned.pdf")

        texts = [e for e in elements_of(batches) if e.text]
        assert texts
        assert all(e.origin is TextOrigin.RECOGNIZED for e in texts)
        assert all(e.confidence is not None and 0 < e.confidence <= 1 for e in texts)
        assert sorted(p for b in batches for p in b.recognized_pages) == [1, 2]

    def test_page_batches_report_progress_and_keep_one_reading_order(
        self, extractor: DoclingExtractor
    ) -> None:
        single = extract(extractor, "split_table.pdf", batch_size=1)
        whole = extract(extractor, "split_table.pdf", batch_size=3)

        assert [(b.first_page, b.last_page, b.pages_total) for b in single] == [
            (1, 1, 2),
            (2, 2, 2),
        ]
        assert [(b.first_page, b.last_page) for b in whole] == [(1, 2)]

        def outline(batches: list[ExtractionBatch]) -> list[tuple[object, ...]]:
            return [
                (e.id, e.kind, e.page, e.reading_order, e.heading_level)
                for e in elements_of(batches)
            ]

        assert outline(single) == outline(whole)

    def test_encrypted_pdf_raises_encrypted_document(
        self, extractor: DoclingExtractor
    ) -> None:
        with pytest.raises(EncryptedDocumentError):
            extract(extractor, "encrypted.pdf")

    def test_unreadable_pdf_raises_corrupt_document(
        self, extractor: DoclingExtractor, tmp_path: Path
    ) -> None:
        broken = tmp_path / "broken.pdf"
        broken.write_bytes(b"%PDF-1.7\n" + b"\x00garbage" * 50)

        with pytest.raises(CorruptDocumentError):
            list(
                extractor.extract(
                    path=broken,
                    document_id=uuid.uuid4(),
                    document_sha256=SHA,
                    batch_size=4,
                )
            )

    def test_a_batch_that_times_out_is_not_reported_as_extracted(self) -> None:
        # Docling returns the pages it could not finish as a partial success.
        impatient = DoclingExtractor(
            artifacts_path=artifacts_path(), threads=1, batch_timeout_seconds=0.001
        )

        with pytest.raises(CorruptDocumentError, match="partially"):
            list(
                impatient.extract(
                    path=FIXTURES / "split_table.pdf",
                    document_id=uuid.uuid4(),
                    document_sha256=SHA,
                    batch_size=2,
                )
            )
