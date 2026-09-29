import hashlib
from datetime import timedelta
from pathlib import Path

import pytest

from multimodal_rag.adapters.docling.pdfium import PdfiumInspector
from tests.load.upload_backlog import distinct_copy, makespan, summarize

DIGITAL = Path(__file__).resolve().parents[1] / "fixtures" / "digital.pdf"


def test_copies_are_distinct_documents_with_the_same_pages(tmp_path: Path) -> None:
    original = DIGITAL.read_bytes()
    copies = [distinct_copy(original, run_id="run-a", number=n) for n in range(3)]
    copies.append(distinct_copy(original, run_id="run-b", number=0))

    fingerprints = {hashlib.sha256(copy).hexdigest() for copy in [original, *copies]}
    assert len(fingerprints) == 5
    path = tmp_path / "copy.pdf"
    path.write_bytes(copies[0])
    assert PdfiumInspector().inspect(path).page_count == 1


def test_summary_interpolates_percentiles_between_samples() -> None:
    summary = summarize([float(n) for n in range(100, 0, -1)])

    assert summary.count == 100
    assert summary.p50 == pytest.approx(50.5)
    assert summary.p95 == pytest.approx(95.05)
    assert summary.maximum == 100.0


def test_summary_of_one_sample_is_that_sample() -> None:
    summary = summarize([0.3])

    assert (summary.count, summary.p50, summary.p95, summary.maximum) == (
        1,
        0.3,
        0.3,
        0.3,
    )


def test_makespan_runs_from_the_first_job_created_to_the_last_finished() -> None:
    jobs = [
        {
            "created_at": "2026-09-29T10:00:00Z",
            "finished_at": "2026-09-29T10:03:00Z",
        },
        {
            "created_at": "2026-09-29T10:00:05Z",
            "finished_at": "2026-09-29T10:07:30Z",
        },
    ]

    assert makespan(jobs) == timedelta(minutes=7, seconds=30)
