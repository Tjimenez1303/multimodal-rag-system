import logging

import pytest

from multimodal_rag.answering.domain import AnswerStatus, GeneratedAnswer
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
