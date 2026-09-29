import pytest

from multimodal_rag.answering.citations import has_markers, resolve_citations
from multimodal_rag.answering.domain import Citation
from multimodal_rag.ingestion.domain import Document, RetrievalUnit
from tests.library import document, element, unit

FAA = document("faa-powerplant.pdf")
TM = document("tm-5-3431.pdf")
NAMES = {FAA.id: FAA.file_name, TM.id: TM.file_name}


def on(owner: Document, *pages: int) -> RetrievalUnit:
    members = [element(owner, page=page) for page in pages]
    return unit(owner, f"text on {pages}", members=members)


def test_markers_of_supplied_sources_are_kept_and_adjacent_ones_count_apart() -> None:
    units = [on(FAA, 12), on(FAA, 13), on(TM, 5)]

    cited = resolve_citations(
        "Poor regulation [1][3]. It is never used [1].", units, document_names=NAMES
    )

    assert cited.text == "Poor regulation [1][2]. It is never used [1]."
    assert cited.citations == (
        Citation(
            number=1,
            document_id=FAA.id,
            document_name="faa-powerplant.pdf",
            pages=(12,),
            unit_ids=(units[0].id,),
        ),
        Citation(
            number=2,
            document_id=TM.id,
            document_name="tm-5-3431.pdf",
            pages=(5,),
            unit_ids=(units[2].id,),
        ),
    )
    assert cited.numbers == {units[0].id: 1, units[2].id: 2}


def test_out_of_range_markers_and_zero_are_removed_from_the_text() -> None:
    units = [on(FAA, 12), on(FAA, 13)]

    cited = resolve_citations(
        "First [0]. Second [9]. Third [2][7].", units, document_names=NAMES
    )

    assert cited.text == "First. Second. Third [1]."
    assert [c.unit_ids for c in cited.citations] == [(units[1].id,)]


def test_units_sharing_document_and_pages_merge_into_one_citation() -> None:
    units = [on(FAA, 3, 4), on(TM, 3, 4), on(FAA, 3, 4)]

    cited = resolve_citations(
        "The table continues [1]. Torque is 35 Nm [3][1]. Other [2].",
        units,
        document_names=NAMES,
    )

    assert cited.text == "The table continues [1]. Torque is 35 Nm [1]. Other [2]."
    first, second = cited.citations
    assert (first.pages, first.unit_ids) == ((3, 4), (units[0].id, units[2].id))
    assert (second.document_id, second.unit_ids) == (TM.id, (units[1].id,))
    assert cited.numbers == {units[0].id: 1, units[2].id: 1, units[1].id: 2}


def test_citations_are_renumbered_in_order_of_first_appearance() -> None:
    units = [on(FAA, 1), on(FAA, 2), on(FAA, 3)]

    cited = resolve_citations(
        "Alpha [3]. Beta [1]. Gamma [3] and [2].", units, document_names=NAMES
    )

    assert cited.text == "Alpha [1]. Beta [2]. Gamma [1] and [3]."
    assert [c.pages for c in cited.citations] == [(3,), (1,), (2,)]
    assert [c.number for c in cited.citations] == [1, 2, 3]


def test_every_citation_is_referenced_in_the_text() -> None:
    units = [on(FAA, 1), on(FAA, 2), on(TM, 7)]

    cited = resolve_citations(
        "Only the last source [3] is cited, twice [3].", units, document_names=NAMES
    )

    assert [c.number for c in cited.citations] == [1]
    assert all(f"[{c.number}]" in cited.text for c in cited.citations)


def test_a_text_without_valid_markers_yields_no_citations() -> None:
    units = [on(FAA, 1)]

    cited = resolve_citations("Nothing [4] supports this.", units, document_names=NAMES)

    assert cited.text == "Nothing supports this."
    assert cited.citations == ()
    assert cited.numbers == {}


@pytest.mark.parametrize(
    ("written", "rewritten"),
    [
        ("Both apply [1, 3].", "Both apply [1][2]."),
        ("Both apply [1,3].", "Both apply [1][2]."),
        ("A range [1-3].", "A range [1][2][3]."),
        ("Doubled [[3]].", "Doubled [1]."),
        ("Wide brackets 【3】.", "Wide brackets [1]."),
        ("Invalid inside [3, 9].", "Invalid inside [1]."),
    ],
)
def test_marker_variants_become_separate_markers(written: str, rewritten: str) -> None:
    units = [on(FAA, 1), on(FAA, 2), on(TM, 3)]

    cited = resolve_citations(written, units, document_names=NAMES)

    assert cited.text == rewritten


def test_a_range_expands_only_up_to_the_supplied_sources() -> None:
    units = [on(FAA, 1), on(FAA, 2)]

    cited = resolve_citations("Everything [1-99999999].", units, document_names=NAMES)

    assert cited.text == "Everything [1][2]."
    assert [c.number for c in cited.citations] == [1, 2]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Cited [1].", True),
        ("Cited [1, 2].", True),
        ("Cited 【2】.", True),
        ("Cited [[2]].", True),
        ("Not cited at all.", False),
        ("A footnote-like [a] is not a marker.", False),
    ],
)
def test_markers_are_detected_in_every_accepted_form(text: str, expected: bool) -> None:
    assert has_markers(text) is expected
