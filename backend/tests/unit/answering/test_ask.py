import asyncio
import logging
from collections.abc import Sequence
from typing import Any

import pytest

from multimodal_rag.answering.domain import (
    Answer,
    AnswerStatus,
    GeneratedAnswer,
    NotEnoughReason,
)
from multimodal_rag.answering.errors import (
    AnswerDeadlineExceededError,
    AnsweringBusyError,
    AnswerModelResponseError,
    AnswerModelTimeoutError,
    AnswerModelUnavailableError,
    InvalidQuestionError,
    RerankerResponseError,
    RerankerTimeoutError,
    RerankerUnavailableError,
    SearchTimeoutError,
    SearchUnavailableError,
)
from multimodal_rag.answering.messages import not_enough_message
from multimodal_rag.ingestion.domain import (
    BoundingBox,
    Document,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    RelationshipKind,
    RetrievalUnit,
)
from multimodal_rag.shared.errors import (
    DataInconsistencyError,
    MultimodalRagError,
    ProviderError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from tests.fakes import FakeAnswerSlots
from tests.library import Library, document, element, unit

QUESTION = "Why is a series wound generator never used on airplanes?"
SERIES = (
    "A series wound generator has poor voltage regulation, so it is never used on "
    "airplanes."
)
TABLE = "Generator ratings table, continued on the next page."
LOGGER = "multimodal_rag.answering.use_cases.ask"


@pytest.fixture
def library() -> Library:
    return Library()


@pytest.fixture
def faa() -> Document:
    return document("faa-powerplant-ch4.pdf")


async def add_text(
    library: Library, owner: Document, text: str, *pages: int
) -> RetrievalUnit:
    members = [element(owner, page=page) for page in pages]
    added = unit(owner, text, members=members)
    await library.add(owner, members, [added])
    return added


async def test_a_supported_question_is_answered_with_its_sources_in_rank_order(
    library: Library, faa: Document
) -> None:
    for number in range(10):
        await add_text(library, faa, f"Generator note {number}.", 20 + number)
    series = await add_text(library, faa, SERIES, 12)

    answer = await library.ask(top_k=8)(QUESTION)

    assert answer.status is AnswerStatus.ANSWERED
    assert answer.reason is None
    assert len(answer.sources) == 8
    assert [source.rank for source in answer.sources] == list(range(1, 9))
    assert answer.sources[0].unit_id == series.id
    assert answer.sources[0].citation_number == 1


async def test_citations_name_the_document_and_every_page_of_the_unit(
    library: Library, faa: Document
) -> None:
    series = await add_text(library, faa, SERIES, 12)
    table = await add_text(library, faa, TABLE, 3, 4)
    library.answer(
        GeneratedAnswer(
            text="Its regulation is poor [1]. Ratings span two pages [2].",
            not_covered="",
        )
    )

    answer = await library.ask()(QUESTION)

    assert answer.text == "Its regulation is poor [1]. Ratings span two pages [2]."
    assert answer.not_covered is None
    [first, second] = answer.citations
    assert (first.document_name, first.pages, first.unit_ids) == (
        "faa-powerplant-ch4.pdf",
        (12,),
        (series.id,),
    )
    assert (second.document_name, second.pages, second.unit_ids) == (
        "faa-powerplant-ch4.pdf",
        (3, 4),
        (table.id,),
    )


async def test_the_model_receives_the_sources_in_rank_order(
    library: Library, faa: Document
) -> None:
    await add_text(library, faa, TABLE, 3, 4)
    await add_text(library, faa, SERIES, 12)

    await library.ask()(QUESTION)

    [prompt] = library.generator.prompts
    assert prompt.user.index(SERIES) < prompt.user.index(TABLE)
    assert QUESTION in prompt.user


async def test_the_model_receives_the_sources_in_judged_order(
    library: Library, faa: Document
) -> None:
    series = await add_text(library, faa, SERIES, 12)
    table = await add_text(library, faa, TABLE, 3, 4)
    library.judge.relevance = {"ratings table": 0.95, "series wound": 0.60}

    answer = await library.ask()(QUESTION)

    [prompt] = library.generator.prompts
    assert prompt.user.index(TABLE) < prompt.user.index(SERIES)
    assert [(s.unit_id, s.rank) for s in answer.sources] == [
        (table.id, 1),
        (series.id, 2),
    ]


async def test_one_log_record_reports_outcome_units_and_timings_without_content(
    library: Library, faa: Document, caplog: pytest.LogCaptureFixture
) -> None:
    await add_text(library, faa, SERIES, 12)
    await add_text(library, faa, TABLE, 3, 4)
    library.answer(GeneratedAnswer(text="Poor regulation [1].", not_covered=""))

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await library.ask()(QUESTION)

    [record] = [r for r in caplog.records if r.name == LOGGER]
    message = record.getMessage()
    assert "outcome answered" in message
    assert "units 2" in message
    assert "cited 1" in message
    assert "search_ms" in message
    assert "ranking_ms" in message
    assert "top_relevance 1.000" in message
    assert "generation_ms" in message
    for content in (QUESTION, "Poor regulation", SERIES, TABLE):
        assert content not in message


async def test_a_hit_whose_document_is_missing_is_an_inconsistency(
    library: Library, faa: Document
) -> None:
    members = [element(faa, page=12)]
    await library.add(
        faa, members, [unit(faa, SERIES, members=members)], registered=False
    )

    with pytest.raises(DataInconsistencyError):
        await library.ask()(QUESTION)

    assert library.generator.prompts == []


async def test_each_question_is_answered_independently(
    library: Library, faa: Document
) -> None:
    await add_text(library, faa, SERIES, 12)
    shunt = "A shunt wound generator has its field across the armature."
    await add_text(library, faa, shunt, 14)
    ask = library.ask()

    await ask(QUESTION)
    await ask("Where does the shunt field connect?")

    first, second = library.generator.prompts
    assert first.system == second.system
    assert QUESTION not in second.user
    assert SERIES in first.user
    assert SERIES not in second.user


def assert_not_enough(answer: Answer, reason: NotEnoughReason) -> None:
    assert answer.status is AnswerStatus.NOT_ENOUGH_INFORMATION
    assert answer.reason is reason
    assert answer.citations == ()
    assert answer.sources == ()
    assert answer.primary_image is None
    assert answer.related_images == ()


class TestNotEnoughInformation:
    async def test_without_searchable_documents_the_model_is_not_asked(
        self, library: Library
    ) -> None:
        answer = await library.ask()(QUESTION)

        assert_not_enough(answer, NotEnoughReason.NO_SEARCHABLE_DOCUMENTS)
        assert answer.text == not_enough_message(
            NotEnoughReason.NO_SEARCHABLE_DOCUMENTS, language="en"
        )
        assert library.generator.prompts == []

    async def test_below_the_relevance_gate_the_model_is_not_asked(
        self, library: Library, faa: Document
    ) -> None:
        library.judge.default = 0.29
        await add_text(library, faa, SERIES, 12)

        answer = await library.ask(min_relevance=0.30)(QUESTION)

        assert_not_enough(answer, NotEnoughReason.NO_RELEVANT_CONTENT)
        assert answer.text == not_enough_message(
            NotEnoughReason.NO_RELEVANT_CONTENT, language="en"
        )
        assert library.generator.prompts == []

    async def test_a_similar_unit_that_does_not_answer_is_not_supplied(
        self, library: Library, faa: Document
    ) -> None:
        profile = await add_text(library, faa, "The company sells generators.", 1)
        library.index.similarities[profile.id] = 0.69
        library.judge.relevance = {"sells generators": 0.08}

        answer = await library.ask(min_relevance=0.30)(
            "How many employees sell generators?"
        )

        assert_not_enough(answer, NotEnoughReason.NO_RELEVANT_CONTENT)
        assert library.generator.prompts == []

    async def test_an_unrelated_question_is_stopped_before_the_model(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        await add_text(library, faa, TABLE, 3, 4)
        library.judge.default = 0.001

        answer = await library.ask()("What is the generator of paella flavor?")

        assert_not_enough(answer, NotEnoughReason.NO_RELEVANT_CONTENT)
        assert library.generator.prompts == []

    async def test_a_stopped_question_logs_its_best_judgement_without_content(
        self, library: Library, faa: Document, caplog: pytest.LogCaptureFixture
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        await add_text(library, faa, TABLE, 3, 4)
        library.judge.default = 0.05
        library.judge.relevance = {"ratings table": 0.12}

        with caplog.at_level(logging.INFO, logger=LOGGER):
            await library.ask()(QUESTION)

        [record] = [r for r in caplog.records if r.name == LOGGER]
        message = record.getMessage()
        assert "reason no_relevant_content" in message
        assert "top_relevance 0.120" in message
        for content in (QUESTION, SERIES, TABLE):
            assert content not in message

    async def test_the_fixed_message_is_in_the_language_of_the_question(
        self, library: Library, faa: Document
    ) -> None:
        library.judge.default = 0.01
        library.languages.keywords = {"receta": "es"}
        await add_text(library, faa, "Receta de un generador.", 12)

        answer = await library.ask()("¿Cuál es la mejor receta de paella?")

        assert_not_enough(answer, NotEnoughReason.NO_RELEVANT_CONTENT)
        assert answer.text == not_enough_message(
            NotEnoughReason.NO_RELEVANT_CONTENT, language="es"
        )
        assert library.generator.prompts == []

    async def test_an_empty_model_answer_reports_what_is_not_covered(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.answer(
            GeneratedAnswer(
                text="  ", not_covered="The sources do not give the APU torque."
            )
        )

        answer = await library.ask()(QUESTION)

        assert_not_enough(answer, NotEnoughReason.NOT_ANSWERED_BY_SOURCES)
        assert answer.text == "The sources do not give the APU torque."

    async def test_an_empty_model_answer_without_explanation_gets_the_message(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.answer(GeneratedAnswer(text="", not_covered=""))

        answer = await library.ask()(QUESTION)

        assert_not_enough(answer, NotEnoughReason.NOT_ANSWERED_BY_SOURCES)
        assert answer.text == not_enough_message(
            NotEnoughReason.NOT_ANSWERED_BY_SOURCES, language="en"
        )

    async def test_an_answer_citing_only_unsupplied_sources_is_not_shown(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.answer(
            GeneratedAnswer(text="Invented from page 99 [7] and [0].", not_covered="")
        )

        answer = await library.ask()(QUESTION)

        assert_not_enough(answer, NotEnoughReason.NO_VALID_CITATIONS)
        assert answer.text == not_enough_message(
            NotEnoughReason.NO_VALID_CITATIONS, language="en"
        )
        assert "Invented" not in answer.text

    async def test_an_answer_without_markers_matching_no_source_is_not_shown(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.answer(
            GeneratedAnswer(text="An uncited claim.", not_covered="The weight.")
        )

        answer = await library.ask()(QUESTION)

        assert_not_enough(answer, NotEnoughReason.NO_VALID_CITATIONS)
        assert answer.text == "The weight."

    async def test_a_partial_answer_stays_answered_and_says_what_is_missing(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.answer(
            GeneratedAnswer(
                text="Regula mal la tensión [1].",
                not_covered="Los documentos no indican cuánto pesa.",
            )
        )

        answer = await library.ask()(QUESTION)

        assert answer.status is AnswerStatus.ANSWERED
        assert answer.reason is None
        assert answer.not_covered == "Los documentos no indican cuánto pesa."
        assert [citation.number for citation in answer.citations] == [1]

    async def test_the_outcome_reason_is_logged(
        self, library: Library, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger=LOGGER):
            await library.ask()(QUESTION)

        [record] = [r for r in caplog.records if r.name == LOGGER]
        message = record.getMessage()
        assert "outcome not_enough_information" in message
        assert "reason no_searchable_documents" in message
        assert "units 0" in message


class TestAttribution:
    async def test_an_answer_without_markers_is_attributed_to_its_sources(
        self, library: Library, faa: Document
    ) -> None:
        series = await add_text(library, faa, SERIES, 12)
        table = await add_text(library, faa, TABLE, 3, 4)
        library.answer(
            GeneratedAnswer(
                text=(
                    "A series wound generator has poor voltage regulation.\n"
                    "- Generator ratings table continues on the next page"
                ),
                not_covered="",
            )
        )

        answer = await library.ask()(QUESTION)

        assert answer.status is AnswerStatus.ANSWERED
        assert answer.text == (
            "A series wound generator has poor voltage regulation [1].\n"
            "- Generator ratings table continues on the next page [2]"
        )
        assert [c.unit_ids for c in answer.citations] == [(series.id,), (table.id,)]

    async def test_statements_and_units_are_embedded_as_passages_in_one_request(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.answer(
            GeneratedAnswer(
                text="A series wound generator has poor voltage regulation.",
                not_covered="",
            )
        )

        await library.ask()(QUESTION)

        [request] = library.embedder.calls
        assert request == [
            "A series wound generator has poor voltage regulation.",
            f"Generators\n{SERIES}",
        ]

    async def test_an_answer_with_markers_is_not_attributed_again(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.answer(GeneratedAnswer(text="Poor regulation [1].", not_covered=""))

        await library.ask()(QUESTION)

        assert library.embedder.calls == []

    async def test_an_answer_too_short_to_attribute_embeds_nothing(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.answer(GeneratedAnswer(text="Yes.", not_covered=""))

        answer = await library.ask()(QUESTION)

        assert_not_enough(answer, NotEnoughReason.NO_VALID_CITATIONS)
        assert library.embedder.calls == []

    async def test_attribution_logs_how_many_statements_it_cited(
        self, library: Library, faa: Document, caplog: pytest.LogCaptureFixture
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.answer(
            GeneratedAnswer(
                text="A series wound generator has poor voltage regulation.",
                not_covered="",
            )
        )

        with caplog.at_level(logging.INFO, logger=LOGGER):
            await library.ask()(QUESTION)

        assert "attributed 1 of 1 statements" in caplog.text


async def test_the_search_asks_for_twice_the_candidates_and_drops_identical_ones(
    library: Library, faa: Document
) -> None:
    copy = document("faa-powerplant-copy.pdf")
    original = await add_text(library, faa, SERIES, 12)
    await add_text(library, copy, SERIES, 12)
    await add_text(library, faa, TABLE, 3, 4)

    answer = await library.ask(top_k=8, rerank_candidates=16)(QUESTION)

    assert library.index.searches[0]["limit"] == 32
    [(_, passages)] = library.judge.calls
    assert len(passages) == 2
    assert [s.unit_id for s in answer.sources][0] == original.id
    assert len(answer.sources) == 2


async def test_an_identifier_question_below_the_gate_reaches_the_model(
    library: Library,
) -> None:
    tm = document("tm-5-3431-201-10.pdf")
    library.judge.default = 0.05
    code = await add_text(library, tm, "Code SPL-480 means low oil pressure.", 13)
    library.answer(
        GeneratedAnswer(text="SPL-480 means low oil pressure [1].", not_covered="")
    )

    answer = await library.ask(min_relevance=0.30)("What is code SPL-480?")

    assert len(library.generator.prompts) == 1
    assert answer.status is AnswerStatus.ANSWERED
    [citation] = answer.citations
    assert (citation.unit_ids, citation.pages) == ((code.id,), (13,))


class TestReranking:
    TOTAL = "Terminos y Condiciones\nTotal Neto:\n$880,900.0"

    @pytest.mark.parametrize("question", ["Total Neto", "Cual es mi total Neto"])
    async def test_a_short_question_answered_by_a_unit_reaches_the_model(
        self, library: Library, question: str
    ) -> None:
        quote = document("labeled_total.pdf")
        total = await add_text(library, quote, self.TOTAL, 2)
        library.index.similarities[total.id] = 0.43
        library.judge.relevance = {"Total Neto": 0.99}
        library.answer(
            GeneratedAnswer(text="El total neto es $880,900.0 [1].", not_covered="")
        )

        answer = await library.ask(min_relevance=0.30)(question)

        assert answer.status is AnswerStatus.ANSWERED
        [citation] = answer.citations
        assert (citation.unit_ids, citation.pages) == ((total.id,), (2,))

    async def test_the_judge_reads_the_question_and_each_candidate_with_headings(
        self, library: Library, faa: Document
    ) -> None:
        for number in range(20):
            await add_text(library, faa, f"Generator note {number}.", 20 + number)

        await library.ask(top_k=8, rerank_candidates=16)("generator note")

        [(question, passages)] = library.judge.calls
        assert question == "generator note"
        assert len(passages) == 16
        assert all(
            passage.startswith("Generators\nGenerator note") for passage in passages
        )

    async def test_the_highest_judged_candidates_are_supplied(
        self, library: Library, faa: Document
    ) -> None:
        notes = [
            await add_text(library, faa, f"Generator note {number}.", 20 + number)
            for number in range(16)
        ]
        library.judge.default = 0.1
        library.judge.relevance = {
            f"note {number}.": 0.2 + number / 100 for number in range(8, 16)
        }

        answer = await library.ask(top_k=8, rerank_candidates=16)("generator note")

        supplied = [source.unit_id for source in answer.sources]
        assert supplied == [notes[number].id for number in range(15, 7, -1)]

    async def test_a_low_judged_identifier_unit_is_still_supplied(
        self, library: Library
    ) -> None:
        tm = document("tm-5-3431-201-10.pdf")
        for number in range(15):
            await add_text(
                library, tm, f"What code {number} means is listed.", number + 1
            )
        code = await add_text(library, tm, "Code SPL-480 means low oil pressure.", 40)
        library.judge.default = 0.9
        library.judge.relevance = {"SPL-480": 0.05}
        # The identifier's unit is judged lowest, so it is the eighth source.
        library.answer(
            GeneratedAnswer(text="SPL-480 means low oil pressure [8].", not_covered="")
        )

        answer = await library.ask(top_k=8, rerank_candidates=16)(
            "What is code SPL-480?"
        )

        assert len(answer.sources) == 8
        assert answer.sources[-1].unit_id == code.id
        [citation] = answer.citations
        assert citation.unit_ids == (code.id,)

    async def test_a_restricted_question_judges_only_its_documents(
        self, library: Library, faa: Document
    ) -> None:
        other = document("other-manual.pdf")
        await add_text(library, faa, SERIES, 12)
        await add_text(library, other, "A series wound generator in another manual.", 3)

        await library.ask()(QUESTION, document_ids=[faa.id])

        [(_, passages)] = library.judge.calls
        assert passages == (f"Generators\n{SERIES}",)


class TestImages:
    @staticmethod
    def figure(owner: Document, *, top: float, **values: Any) -> ExtractedElement:
        fields: dict[str, Any] = {
            "kind": ElementKind.IMAGE,
            "page": 12,
            "bbox": BoundingBox(left=72, top=top, right=540, bottom=top + 100),
            "image_key": f"figures/{owner.id}/{top}.png",
        }
        return element(owner, **(fields | values))

    async def add_figure_text(
        self,
        library: Library,
        owner: Document,
        figures: Sequence[ExtractedElement],
        text: str = SERIES,
        **options: Any,
    ) -> RetrievalUnit:
        paragraph = element(owner, page=12)
        cited = unit(
            owner, text, members=[paragraph], figure_ids=tuple(f.id for f in figures)
        )
        await library.add(owner, [paragraph, *figures], [cited], **options)
        return cited

    async def test_an_answer_returns_the_figure_next_to_its_cited_text(
        self, library: Library, faa: Document
    ) -> None:
        near, far = self.figure(faa, top=170), self.figure(faa, top=600)
        caption = element(faa, kind=ElementKind.CAPTION, text="Figure 4-21. Series")
        link = ElementRelationship(
            source_id=caption.id, target_id=near.id, kind=RelationshipKind.CAPTION_OF
        )
        await library.add(faa, [caption], [], relationships=[link])
        cited = await self.add_figure_text(library, faa, [far, near])

        answer = await library.ask()(QUESTION)

        assert answer.primary_image is not None
        assert answer.primary_image.element_id == near.id
        assert answer.primary_image.caption == "Figure 4-21. Series"
        assert answer.primary_image.unit_id == cited.id
        assert [image.element_id for image in answer.related_images] == [far.id]

    async def test_a_returned_figure_without_its_crop_is_an_inconsistency(
        self, library: Library, faa: Document
    ) -> None:
        await self.add_figure_text(
            library, faa, [self.figure(faa, top=170)], crops=False
        )

        with pytest.raises(DataInconsistencyError):
            await library.ask()(QUESTION)

    async def test_only_returned_figures_need_a_crop(
        self, library: Library, faa: Document
    ) -> None:
        logo = self.figure(faa, top=170, is_decorative=True)
        await self.add_figure_text(library, faa, [logo], crops=False)
        other = document("tm-5-3431.pdf")
        uncited = await self.add_figure_text(
            library, other, [self.figure(other, top=170)], text=TABLE, crops=False
        )
        library.answer(GeneratedAnswer(text="Poor regulation [1].", not_covered=""))

        answer = await library.ask()(QUESTION)

        assert answer.primary_image is None
        assert uncited.id in {source.unit_id for source in answer.sources}
        assert uncited.id not in {c.unit_ids[0] for c in answer.citations}

    async def test_a_not_enough_answer_returns_no_images(
        self, library: Library, faa: Document
    ) -> None:
        await self.add_figure_text(library, faa, [self.figure(faa, top=170)])
        library.answer(GeneratedAnswer(text="", not_covered=""))

        answer = await library.ask()(QUESTION)

        assert (answer.primary_image, answer.related_images) == (None, ())


class TestFailures:
    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            (ProviderUnavailableError("embedder down"), SearchUnavailableError),
            (ProviderTimeoutError("embedder slow"), SearchTimeoutError),
        ],
    )
    async def test_embedding_failures_are_reported_as_search_failures(
        self,
        library: Library,
        failure: ProviderError,
        expected: type[MultimodalRagError],
    ) -> None:
        library.embedder.error = failure

        with pytest.raises(expected) as raised:
            await library.ask()(QUESTION)

        assert raised.value.__cause__ is failure

    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            (ProviderUnavailableError("qdrant down"), SearchUnavailableError),
            (ProviderTimeoutError("qdrant slow"), SearchTimeoutError),
        ],
    )
    async def test_index_failures_are_reported_as_search_failures(
        self,
        library: Library,
        failure: ProviderError,
        expected: type[MultimodalRagError],
    ) -> None:
        library.index.failures["search_hybrid"] = failure

        with pytest.raises(expected) as raised:
            await library.ask()(QUESTION)

        assert raised.value.__cause__ is failure

    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            (ProviderUnavailableError("model down"), AnswerModelUnavailableError),
            (ProviderTimeoutError("model slow"), AnswerModelTimeoutError),
            (ProviderResponseError("model rejected"), AnswerModelResponseError),
        ],
    )
    async def test_generation_failures_name_the_answer_model(
        self,
        library: Library,
        faa: Document,
        failure: ProviderError,
        expected: type[MultimodalRagError],
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.answer(failure)

        with pytest.raises(expected) as raised:
            await library.ask()(QUESTION)

        assert raised.value.__cause__ is failure

    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            (ProviderUnavailableError("reranker down"), RerankerUnavailableError),
            (ProviderTimeoutError("reranker slow"), RerankerTimeoutError),
            (ProviderResponseError("no judgement"), RerankerResponseError),
        ],
    )
    async def test_judging_failures_name_the_reranker_without_a_fallback(
        self,
        library: Library,
        faa: Document,
        failure: ProviderError,
        expected: type[MultimodalRagError],
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.judge.errors = [failure]

        with pytest.raises(expected) as raised:
            await library.ask()(QUESTION)

        assert raised.value.__cause__ is failure
        assert library.generator.prompts == []

    async def test_judging_slower_than_the_deadline_is_cancelled(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.judge.delay_seconds = 1.0

        with pytest.raises(AnswerDeadlineExceededError):
            await library.ask(deadline_seconds=0.05)(QUESTION)

        assert library.judge.cancelled == 1

    async def test_a_cancelled_question_stops_judging_and_frees_its_place(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.slots = FakeAnswerSlots(capacity=1, queue_limit=0)
        library.judge.delay_seconds = 1.0
        running = asyncio.create_task(library.ask()(QUESTION))
        await asyncio.sleep(0.01)

        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

        assert library.judge.cancelled == 1
        library.judge.delay_seconds = 0
        answer = await library.ask()(QUESTION)
        assert answer.status is AnswerStatus.ANSWERED

    async def test_an_answer_model_error_is_raised_as_it_is(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        invalid = AnswerModelResponseError()
        library.answer(invalid)

        with pytest.raises(AnswerModelResponseError) as raised:
            await library.ask()(QUESTION)

        assert raised.value is invalid

    async def test_a_generation_slower_than_the_deadline_is_cancelled(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.generator.delay_seconds = 1.0

        with pytest.raises(AnswerDeadlineExceededError):
            await library.ask(deadline_seconds=0.05)(QUESTION)

        assert library.generator.cancelled == 1

    async def test_a_timeout_that_is_not_the_deadline_is_not_reported_as_one(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.answer(TimeoutError("raised by a component"))

        with pytest.raises(TimeoutError) as raised:
            await library.ask()(QUESTION)

        assert not isinstance(raised.value, AnswerDeadlineExceededError)

    async def test_waiting_for_a_place_counts_toward_the_deadline(
        self, library: Library, faa: Document
    ) -> None:
        await add_text(library, faa, SERIES, 12)
        library.slots = FakeAnswerSlots(capacity=1, queue_limit=5)
        library.generator.delay_seconds = 0.3
        first = asyncio.create_task(library.ask(deadline_seconds=5)(QUESTION))
        await asyncio.sleep(0.01)

        with pytest.raises(AnswerDeadlineExceededError):
            await library.ask(deadline_seconds=0.05)(QUESTION)

        await first
        assert len(library.generator.prompts) == 1

    async def test_a_full_line_rejects_the_question_before_any_search(
        self, library: Library, caplog: pytest.LogCaptureFixture
    ) -> None:
        library.slots = FakeAnswerSlots(capacity=0, queue_limit=0)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            with pytest.raises(AnsweringBusyError):
                await library.ask()(QUESTION)

        assert library.embedder.queries == []
        assert "busy" in caplog.text

    @pytest.mark.parametrize("text", ["   ", "a" * 2001], ids=["blank", "too_long"])
    async def test_an_invalid_question_is_rejected_before_any_port_is_called(
        self, library: Library, text: str
    ) -> None:
        with pytest.raises(InvalidQuestionError):
            await library.ask()(text)

        assert library.embedder.queries == []
        assert library.slots.admitted == 0
