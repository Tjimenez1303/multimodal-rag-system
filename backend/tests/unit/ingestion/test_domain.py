import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from multimodal_rag.ingestion.domain import (
    BoundingBox,
    DescriptionStatus,
    Document,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    FailureCode,
    IngestionJob,
    JobStage,
    JobStatus,
    JobSummary,
    RelationshipKind,
    TextOrigin,
    element_id_for,
    unit_id_for,
)
from multimodal_rag.ingestion.errors import (
    ElementWithoutPositionError,
    InvalidBoundingBoxError,
    InvalidDocumentError,
    InvalidElementError,
    InvalidJobTransitionError,
)
from multimodal_rag.shared.errors import ConcurrencyError, DataInconsistencyError

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
SHA = "a" * 64
BOX = BoundingBox(left=10, top=20, right=110, bottom=70)


def new_job(max_attempts: int = 3) -> IngestionJob:
    return IngestionJob.create(
        job_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        max_attempts=max_attempts,
        correlation_id="req-1",
        now=NOW,
    )


def claim(job: IngestionJob) -> IngestionJob:
    return job.claim(
        lease_token=uuid.uuid4(),
        lease_expires_at=NOW + timedelta(seconds=90),
        worker_id="worker-1",
        now=NOW,
    )


def element(**overrides: Any) -> ExtractedElement:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "kind": ElementKind.PARAGRAPH,
        "page": 1,
        "bbox": BOX,
        "reading_order": 0,
        "text": "Magneto timing",
    }
    return ExtractedElement(**(values | overrides))


class TestBoundingBox:
    def test_accepts_a_regular_box_and_exposes_its_size(self) -> None:
        assert BOX.width == 100
        assert BOX.height == 50
        assert BOX.area == 5000
        assert BOX.origin == "top_left"

    @pytest.mark.parametrize(
        ("left", "top", "right", "bottom"),
        [(50, 20, 40, 70), (10, 70, 110, 20), (10, 20, 10, 70), (-1, 20, 110, 70)],
    )
    def test_rejects_inverted_empty_or_negative_boxes(
        self, left: float, top: float, right: float, bottom: float
    ) -> None:
        with pytest.raises(InvalidBoundingBoxError):
            BoundingBox(left=left, top=top, right=right, bottom=bottom)

    def test_rejects_non_finite_coordinates(self) -> None:
        with pytest.raises(InvalidBoundingBoxError):
            BoundingBox(left=0, top=0, right=float("inf"), bottom=10)

    def test_on_page_clamps_small_overshoots(self) -> None:
        box = BoundingBox.on_page(
            left=-0.4, top=0, right=612.6, bottom=100, page_width=612, page_height=792
        )

        assert (box.left, box.right) == (0.0, 612)

    def test_on_page_rejects_boxes_outside_the_page(self) -> None:
        with pytest.raises(InvalidBoundingBoxError):
            BoundingBox.on_page(
                left=0, top=0, right=700, bottom=100, page_width=612, page_height=792
            )

    def test_a_box_starting_beyond_the_page_edge_is_rejected(self) -> None:
        with pytest.raises(InvalidBoundingBoxError):
            BoundingBox.on_page(
                left=612.5,
                top=10,
                right=612.9,
                bottom=20,
                page_width=612,
                page_height=792,
            )


class TestDocument:
    def document(self, **overrides: Any) -> Document:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "sha256": SHA,
            "file_name": "manual.pdf",
            "size_bytes": 1024,
            "page_count": 12,
            "blob_key": Document.blob_key_for(SHA),
            "created_at": NOW,
        }
        return Document(**(values | overrides))

    def test_uses_a_content_addressed_blob_key(self) -> None:
        assert self.document().blob_key == f"documents/{SHA}.pdf"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"sha256": "A" * 64},
            {"sha256": "a" * 63},
            {"file_name": ""},
            {"file_name": "x" * 256},
            {"size_bytes": 0},
            {"page_count": 0},
        ],
    )
    def test_rejects_records_that_break_identity_rules(
        self, overrides: dict[str, Any]
    ) -> None:
        with pytest.raises(InvalidDocumentError):
            self.document(**overrides)

    def test_accepts_the_maximum_file_name_and_an_unknown_page_count(self) -> None:
        document = self.document(file_name="x" * 255, page_count=None)

        assert document.page_count is None


class TestIngestionJob:
    def test_is_created_pending(self) -> None:
        job = new_job()

        assert job.status is JobStatus.PENDING
        assert job.attempt == 0
        assert not job.is_terminal

    def test_claim_starts_processing_and_counts_the_attempt(self) -> None:
        job = claim(new_job())

        assert job.status is JobStatus.PROCESSING
        assert job.attempt == 1
        assert job.started_at == NOW
        assert job.lease_token is not None

    def test_reclaim_stays_processing_with_a_new_token(self) -> None:
        first = claim(new_job())
        second = claim(first)

        assert second.status is JobStatus.PROCESSING
        assert second.attempt == 2
        assert second.lease_token != first.lease_token
        assert second.started_at == first.started_at

    def test_claim_is_refused_once_attempts_are_exhausted(self) -> None:
        job = claim(claim(new_job(max_attempts=2)))

        assert job.attempts_exhausted
        with pytest.raises(InvalidJobTransitionError):
            claim(job)

    def test_advance_records_stage_and_progress(self) -> None:
        job = claim(new_job()).advance(
            stage=JobStage.EXTRACTING, pages_done=4, pages_total=71, now=NOW
        )

        assert (job.stage, job.pages_done, job.pages_total) == (
            JobStage.EXTRACTING,
            4,
            71,
        )

    def test_advance_rejects_more_pages_than_the_total(self) -> None:
        with pytest.raises(InvalidJobTransitionError):
            claim(new_job()).advance(
                stage=JobStage.EXTRACTING, pages_done=72, pages_total=71, now=NOW
            )

    def test_advance_requires_processing(self) -> None:
        with pytest.raises(InvalidJobTransitionError):
            new_job().advance(
                stage=JobStage.EXTRACTING, pages_done=0, pages_total=None, now=NOW
            )

    def test_complete_releases_the_lease_and_keeps_the_summary(self) -> None:
        summary = JobSummary(pages=71, retrieval_units=120)

        job = claim(new_job()).complete(summary=summary, now=NOW)

        assert job.status is JobStatus.COMPLETED
        assert job.summary == summary
        assert job.lease_token is None
        assert job.finished_at == NOW

    def test_fail_keeps_code_and_reason(self) -> None:
        job = claim(new_job()).fail(
            code=FailureCode.ENCRYPTED_DOCUMENT, reason="PDF is encrypted", now=NOW
        )

        assert job.status is JobStatus.FAILED
        assert job.failure_code is FailureCode.ENCRYPTED_DOCUMENT
        assert job.failure_reason == "PDF is encrypted"

    def test_a_job_interrupted_on_every_attempt_fails_with_a_fixed_reason(
        self,
    ) -> None:
        job = claim(new_job(max_attempts=1))

        failed = job.fail_interrupted(now=NOW)

        assert failed.failure_code is FailureCode.INTERRUPTED_REPEATEDLY
        assert failed.failure_reason == (
            "Processing was interrupted repeatedly. Attempts used: 1 of 1."
        )

    def test_fail_requires_a_reason(self) -> None:
        with pytest.raises(InvalidJobTransitionError):
            claim(new_job()).fail(code=FailureCode.INTERNAL_ERROR, reason=" ", now=NOW)

    def test_completed_job_cannot_return_to_processing(self) -> None:
        completed = claim(new_job()).complete(summary=JobSummary(), now=NOW)

        with pytest.raises(ConcurrencyError):
            claim(completed)

    @pytest.mark.parametrize("action", ["complete", "fail"])
    def test_terminal_jobs_reject_further_transitions(self, action: str) -> None:
        failed = claim(new_job()).fail(
            code=FailureCode.CORRUPT_DOCUMENT, reason="damaged", now=NOW
        )

        with pytest.raises(InvalidJobTransitionError):
            if action == "complete":
                failed.complete(summary=JobSummary(), now=NOW)
            else:
                failed.fail(code=FailureCode.INTERNAL_ERROR, reason="again", now=NOW)

    def test_pending_job_cannot_complete(self) -> None:
        with pytest.raises(InvalidJobTransitionError):
            new_job().complete(summary=JobSummary(), now=NOW)


class TestExtractedElement:
    def test_a_missing_page_is_a_data_inconsistency(self) -> None:
        with pytest.raises(DataInconsistencyError):
            element(page=0)

    def test_a_missing_box_is_a_data_inconsistency(self) -> None:
        with pytest.raises(ElementWithoutPositionError):
            element(bbox=None)

    def test_recognized_text_carries_a_confidence(self) -> None:
        recognized = element(origin=TextOrigin.RECOGNIZED, confidence=0.93)

        assert recognized.confidence == 0.93

    @pytest.mark.parametrize(
        "overrides",
        [
            {"confidence": 0.9},
            {"origin": TextOrigin.RECOGNIZED, "confidence": 1.5},
            {"heading_level": 2},
            {"kind": ElementKind.HEADING},
            {"table": (("a",),)},
            {"labels": ("V-12",)},
            {"image_key": "figures/x.png"},
            {"is_decorative": True},
        ],
    )
    def test_rejects_fields_that_do_not_match_the_kind(
        self, overrides: dict[str, Any]
    ) -> None:
        with pytest.raises(InvalidElementError):
            element(**overrides)

    def test_image_can_record_its_description(self) -> None:
        image = element(
            kind=ElementKind.IMAGE, text=None, labels=("V-12",), image_key="k.png"
        )

        described = image.with_description(
            status=DescriptionStatus.DESCRIBED,
            description="Hydraulic circuit with valve V-12",
            unverified_identifiers=("P-9",),
        )

        assert described.description_status is DescriptionStatus.DESCRIBED
        assert described.unverified_identifiers == ("P-9",)

    def test_described_status_requires_text(self) -> None:
        image = element(kind=ElementKind.IMAGE, text=None)

        with pytest.raises(InvalidElementError):
            image.with_description(status=DescriptionStatus.DESCRIBED)

    def test_only_images_can_be_described(self) -> None:
        with pytest.raises(InvalidElementError):
            element().with_description(status=DescriptionStatus.SKIPPED)

    def test_image_references_its_crop_by_a_key_derived_from_its_ids(self) -> None:
        image = element(kind=ElementKind.IMAGE, text=None)
        key = ExtractedElement.image_key_for(
            document_id=image.document_id, element_id=image.id
        )

        assert image.with_image_key(key).image_key == (
            f"figures/{image.document_id}/{image.id}.png"
        )

    def test_only_images_reference_a_crop(self) -> None:
        with pytest.raises(InvalidElementError):
            element().with_image_key("figures/x/y.png")


def test_relationships_cannot_link_an_element_to_itself() -> None:
    element_id = uuid.uuid4()

    with pytest.raises(InvalidElementError):
        ElementRelationship(
            source_id=element_id, target_id=element_id, kind=RelationshipKind.NEAR
        )


def test_ids_are_deterministic_and_distinct_per_kind() -> None:
    assert element_id_for(document_sha256=SHA, element_key="p1-0") == element_id_for(
        document_sha256=SHA, element_key="p1-0"
    )
    assert element_id_for(document_sha256=SHA, element_key="k") != unit_id_for(
        document_sha256=SHA, unit_key="k"
    )


def test_ids_never_change_across_releases() -> None:
    # Stored element and unit ids derive from these values, so a change orphans data.
    assert str(element_id_for(document_sha256=SHA, element_key="p1-0")) == (
        "5f26abc8-4e6d-5f52-8359-33ba2eaf642c"
    )
    assert str(unit_id_for(document_sha256=SHA, unit_key="text-0")) == (
        "310f8f1e-3f37-5ecf-8442-614840002df1"
    )
