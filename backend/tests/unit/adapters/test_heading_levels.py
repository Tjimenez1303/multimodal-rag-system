import pytest

from multimodal_rag.adapters.docling.headings import HeadingLevels, OutlineEntry


def test_levels_follow_the_outline_depth_of_a_matching_entry() -> None:
    levels = HeadingLevels(
        [
            OutlineEntry(depth=0, title="I. INTRODUCCIÓN", page=3),
            OutlineEntry(depth=0, title="II. Desarrollo", page=5),
            OutlineEntry(depth=1, title="Artículo 1.  Objeto", page=5),
        ]
    )

    assert levels.level_of("I. Introducción", page=3) == 1
    assert levels.level_of("Artículo 1. Objeto", page=5) == 2


def test_a_single_wrapping_root_entry_does_not_count_as_a_level() -> None:
    levels = HeadingLevels(
        [
            OutlineEntry(depth=0, title="Structure Bookmarks", page=1),
            OutlineEntry(depth=1, title="Reciprocating Engine Ignition", page=1),
            OutlineEntry(depth=2, title="Reciprocating Engine Ignition", page=1),
            OutlineEntry(depth=2, title="Magneto Operation", page=4),
        ]
    )

    assert levels.level_of("Reciprocating Engine Ignition", page=1) == 1
    assert levels.level_of("Magneto Operation", page=4) == 2


def test_an_entry_on_another_page_matches_when_its_title_is_unique() -> None:
    levels = HeadingLevels(
        [
            OutlineEntry(depth=0, title="Chapter 4", page=1),
            OutlineEntry(depth=0, title="Chapter 5", page=20),
            OutlineEntry(depth=1, title="Spark Plugs", page=9),
        ]
    )

    assert levels.level_of("Spark plugs", page=10) == 2


@pytest.mark.parametrize(
    ("heading", "level"),
    [
        ("4 Magnetos", 1),
        ("4.2 Magneto timing", 2),
        ("4.2.1. Internal timing", 3),
        ("1.2.3.4.5.6.7 Deep", 6),
        ("Magneto timing", 1),
        ("2026 revisions", 1),
    ],
)
def test_without_outline_the_section_number_gives_the_level(
    heading: str, level: int
) -> None:
    assert HeadingLevels([]).level_of(heading, page=1) == level


def test_outline_levels_are_capped() -> None:
    entries = [OutlineEntry(depth=d, title=f"h{d}", page=1) for d in range(9)]

    assert HeadingLevels(entries).level_of("h8", page=1) == 6


def test_nested_bookmarks_repeating_their_parent_title_add_no_level() -> None:
    # Tagged PDFs such as the FAA handbook nest each section several times under
    # the same title before listing its headings and paragraphs as flat siblings.
    chapter = "Reciprocating Engine Ignition Systems"
    levels = HeadingLevels(
        [
            OutlineEntry(depth=0, title="Structure Bookmarks", page=None),
            OutlineEntry(depth=1, title=chapter, page=1),
            OutlineEntry(depth=2, title=chapter, page=1),
            OutlineEntry(depth=3, title=chapter, page=1),
            OutlineEntry(depth=4, title="Magneto-Ignition Principles", page=1),
            OutlineEntry(depth=4, title="Magnetic Circuit", page=2),
        ]
    )

    assert levels.level_of(chapter, page=1) == 1
    assert levels.level_of("Magnetic Circuit", page=2) == 2
