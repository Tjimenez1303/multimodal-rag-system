import logging

import pytest

from multimodal_rag.answering.domain import (
    Answer,
    AnswerStatus,
    GeneratedAnswer,
    NotEnoughReason,
)
from multimodal_rag.answering.messages import not_enough_message
from multimodal_rag.ingestion.domain import Document, RetrievalUnit
from multimodal_rag.shared.errors import DataInconsistencyError
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
        library.index.default_similarity = 0.59
        await add_text(library, faa, SERIES, 12)

        answer = await library.ask(min_similarity=0.60)(QUESTION)

        assert_not_enough(answer, NotEnoughReason.NO_RELEVANT_CONTENT)
        assert answer.text == not_enough_message(
            NotEnoughReason.NO_RELEVANT_CONTENT, language="en"
        )
        assert library.generator.prompts == []

    async def test_the_fixed_message_is_in_the_language_of_the_question(
        self, library: Library, faa: Document
    ) -> None:
        library.index.default_similarity = 0.27
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


async def test_the_search_asks_for_twice_the_units_and_drops_identical_ones(
    library: Library, faa: Document
) -> None:
    copy = document("faa-powerplant-copy.pdf")
    original = await add_text(library, faa, SERIES, 12)
    await add_text(library, copy, SERIES, 12)
    await add_text(library, faa, TABLE, 3, 4)

    answer = await library.ask(top_k=8)(QUESTION)

    assert library.index.searches[0]["limit"] == 16
    assert [s.unit_id for s in answer.sources][0] == original.id
    assert len(answer.sources) == 2
