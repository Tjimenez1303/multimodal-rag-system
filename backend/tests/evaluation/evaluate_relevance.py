"""Measure the reranked relevance gate against a labeled question set.

Run it by hand against a running system with the sample manuals and
``tests/fixtures/labeled_total.pdf`` ingested. It is not part of CI, because it needs
the models::

    uv run --directory backend python -m tests.evaluation.evaluate_relevance \\
        --base-url http://127.0.0.1:8000

It asks every question of ``relevance_questions.yaml`` once, after one warm-up question
so that no model load is counted, and reports the success criteria of
``specs/004-reranked-relevance-gate/spec.md``:

- SC-001: answerable questions that reach the answer model.
- SC-002: answerable questions of one to three words that reach it.
- SC-003: unanswerable questions stopped by the gate, and ending as not enough
  information overall.
- SC-004: 95th percentile of the request time of the questions the gate stopped, which
  pay only search and judging, so it bounds the judging time from above.
- SC-007: identifier questions with a supplied source from their expected document on
  one of their expected pages.

A question the gate stopped returns no sources, so its best judgement is only in the
API log. With ``--api-log``, a file saved with ``docker compose logs api
--no-log-prefix``, the report also prints the best judgement of every question by
label, which is the evidence for a change of ``MIN_RELEVANCE``. The run exits with
status 1 when a criterion misses its target.
"""

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from tests.load.upload_backlog import summarize

logger = logging.getLogger(__name__)

QUESTIONS_PATH = "/api/v1/questions"
DEFAULT_SET = Path(__file__).with_name("relevance_questions.yaml")
WARM_UP = "What does the manual cover?"
# Reasons that mean the answer model was never asked.
STOPPED_BEFORE_MODEL = frozenset({"no_relevant_content", "no_searchable_documents"})
# Failures that end a question before the answer model is asked.
STOPPED_BY_FAILURE = frozenset(
    {
        "search_unavailable",
        "search_timeout",
        "reranker_unavailable",
        "reranker_timeout",
        "reranker_invalid_response",
    }
)
SHORT_QUESTION_WORDS = 3
_WORD = re.compile(r"\w+")
_TOP_RELEVANCE = re.compile(r"top_relevance (\d+(?:\.\d+)?)")


@dataclass(frozen=True, slots=True)
class LabeledQuestion:
    """One question of the set with what it is expected to do.

    Attributes:
        id: Unique name of the question.
        question: Text sent to the API.
        label: ``answerable``, ``hard_negative`` or ``unrelated``.
        expected_document: File name of the document the question is about.
        expected_pages: Pages that hold the answer, for answerable questions.
        identifier: The identifier the question asks about, if any.
    """

    id: str
    question: str
    label: str
    expected_document: str | None = None
    expected_pages: tuple[int, ...] = ()
    identifier: str | None = None

    @property
    def answerable(self) -> bool:
        """Whether the documents answer the question."""
        return self.label == "answerable"

    @property
    def short(self) -> bool:
        """Whether the question has one to three words."""
        return len(_WORD.findall(self.question)) <= SHORT_QUESTION_WORDS


@dataclass(frozen=True, slots=True)
class Outcome:
    """What the API did with one question.

    Attributes:
        question: The labeled question.
        status: ``answered``, ``not_enough_information`` or ``error``.
        reason: Why there is no answer, the problem code of an error, or ``None``.
        seconds: Request time.
        sources: Document name, pages and relevance of each supplied source.
        request_id: The ``X-Request-ID`` of the response, to find its log line.
    """

    question: LabeledQuestion
    status: str
    reason: str | None
    seconds: float
    sources: tuple[Mapping[str, Any], ...]
    request_id: str

    @property
    def reached_model(self) -> bool:
        """Whether the gate let the question through to the answer model."""
        return self.reason not in STOPPED_BEFORE_MODEL | STOPPED_BY_FAILURE


@dataclass(frozen=True, slots=True)
class Criterion:
    """One success criterion measured on the run.

    Attributes:
        name: Criterion id and what it counts.
        passed: Questions that satisfy it.
        total: Questions it applies to.
        target: Smallest share that meets it, or the time in seconds that a time
            criterion must stay under.
        value: Measured share, or seconds for a time criterion.
        met: Whether the criterion is met.
    """

    name: str
    passed: int
    total: int
    target: float
    value: float
    met: bool


def load_questions(path: Path) -> list[LabeledQuestion]:
    """Read a labeled question file.

    Args:
        path: YAML file with a ``questions`` list.

    Returns:
        The questions in file order.
    """
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]
    return [
        LabeledQuestion(
            id=entry["id"],
            question=entry["question"],
            label=entry["label"],
            expected_document=entry.get("expected_document"),
            expected_pages=tuple(entry.get("expected_pages") or ()),
            identifier=entry.get("identifier"),
        )
        for entry in entries
    ]


def supplies_expected_page(outcome: Outcome) -> bool:
    """Return whether a supplied source comes from the expected document and page.

    Args:
        outcome: The API's handling of a question with an expected document.

    Returns:
        ``True`` when a source has that document and one of the expected pages.
    """
    expected = outcome.question
    return any(
        source["document_name"] == expected.expected_document
        and set(source["pages"]) & set(expected.expected_pages)
        for source in outcome.sources
    )


def evaluate(outcomes: Sequence[Outcome]) -> list[Criterion]:
    """Compute the success criteria of the reranked relevance gate.

    Args:
        outcomes: One outcome per question of the set.

    Returns:
        SC-001, SC-002, SC-003 (both parts), SC-004 and SC-007, in that order.
    """
    answerable = [o for o in outcomes if o.question.answerable]
    short = [o for o in answerable if o.question.short]
    unanswerable = [o for o in outcomes if not o.question.answerable]
    identifiers = [o for o in answerable if o.question.identifier]
    stopped = [o for o in outcomes if not o.reached_model]
    criteria = [
        _share("SC-001 answerable reach the model", answerable, 0.90, _reached),
        _share("SC-002 short answerable reach the model", short, 0.75, _reached),
        _share("SC-003 unanswerable stopped by the gate", unanswerable, 0.70, _stopped),
        _share(
            "SC-003 unanswerable end as not enough information",
            unanswerable,
            0.90,
            lambda o: o.status == "not_enough_information",
        ),
    ]
    p95 = summarize([o.seconds for o in stopped]).p95 if stopped else 0.0
    criteria.append(
        Criterion(
            name="SC-004 p95 seconds of questions stopped by the gate",
            passed=len(stopped),
            total=len(stopped),
            target=2.5,
            value=p95,
            met=p95 < 2.5,
        )
    )
    criteria.append(
        _share(
            "SC-007 identifier units supplied",
            identifiers,
            0.95,
            supplies_expected_page,
        )
    )
    return criteria


def top_relevances_from_log(lines: Iterable[str]) -> dict[str, float]:
    """Read the best judgement of every question from the API's JSON log.

    Args:
        lines: Lines of ``docker compose logs api --no-log-prefix``.

    Returns:
        The ``top_relevance`` of each question's log record, by request id.
    """
    found: dict[str, float] = {}
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        match = _TOP_RELEVANCE.search(str(record.get("message", "")))
        if match and "request_id" in record:
            found[str(record["request_id"])] = float(match.group(1))
    return found


def _reached(outcome: Outcome) -> bool:
    return outcome.reached_model


def _stopped(outcome: Outcome) -> bool:
    return not outcome.reached_model


def _share(
    name: str,
    outcomes: Sequence[Outcome],
    target: float,
    passes: Callable[[Outcome], bool],
) -> Criterion:
    passed = sum(1 for outcome in outcomes if passes(outcome))
    value = passed / len(outcomes) if outcomes else 1.0
    return Criterion(
        name=name,
        passed=passed,
        total=len(outcomes),
        target=target,
        value=value,
        met=value >= target,
    )


async def _ask(client: httpx.AsyncClient, question: LabeledQuestion) -> Outcome:
    started = time.perf_counter()
    response = await client.post(QUESTIONS_PATH, json={"question": question.question})
    seconds = time.perf_counter() - started
    body = response.json()
    if response.is_error:
        # A failed question is part of the measurement, such as an answer cut by the
        # answer model's token limit after the gate let the question through.
        return Outcome(
            question=question,
            status="error",
            reason=body.get("code", str(response.status_code)),
            seconds=seconds,
            sources=(),
            request_id=response.headers.get("x-request-id", ""),
        )
    return Outcome(
        question=question,
        status=body["status"],
        reason=body["reason"],
        seconds=seconds,
        sources=tuple(body["sources"]),
        request_id=response.headers.get("x-request-id", ""),
    )


async def _run(args: argparse.Namespace) -> list[Outcome]:
    questions = load_questions(args.questions)
    outcomes = []
    async with httpx.AsyncClient(
        base_url=args.base_url, timeout=args.timeout
    ) as client:
        await client.post(QUESTIONS_PATH, json={"question": WARM_UP})
        for question in questions:
            outcome = await _ask(client, question)
            logger.info(
                "%s: %s %s in %.2f s",
                question.id,
                outcome.status,
                outcome.reason or "",
                outcome.seconds,
            )
            outcomes.append(outcome)
    return outcomes


def _report(outcomes: Sequence[Outcome], log: Path | None) -> bool:
    criteria = evaluate(outcomes)
    lines = [f"{'criterion':<52}{'passed':>8}{'value':>9}{'target':>9}  met"]
    failed = [o for o in outcomes if o.status == "error"]
    for outcome in failed:
        lines.append(f"error {outcome.reason}: {outcome.question.id}")
    for criterion in criteria:
        lines.append(
            f"{criterion.name:<52}{criterion.passed:>4}/{criterion.total:<3}"
            f"{criterion.value:>9.3f}{criterion.target:>9.2f}  "
            f"{'yes' if criterion.met else 'no'}"
        )
    if log is not None:
        best = top_relevances_from_log(log.read_text(encoding="utf-8").splitlines())
        lines.append("")
        lines.append(f"{'label':<14}{'question':<44}{'top relevance':>14}  reached")
        for outcome in sorted(outcomes, key=lambda o: o.question.label):
            relevance = best.get(outcome.request_id)
            shown = "-" if relevance is None else f"{relevance:.3f}"
            lines.append(
                f"{outcome.question.label:<14}{outcome.question.question[:42]:<44}"
                f"{shown:>14}  {'yes' if outcome.reached_model else 'no'}"
            )
    sys.stdout.write("\n".join(lines) + "\n")
    return all(criterion.met for criterion in criteria)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tests.evaluation.evaluate_relevance",
        description="Measure the relevance gate against labeled questions.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--questions", type=Path, default=DEFAULT_SET)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--api-log", type=Path, help="saved `docker compose logs api --no-log-prefix`"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Ask every labeled question and write the report to standard output.

    Args:
        argv: Command-line arguments without the program name. Defaults to
            ``sys.argv[1:]``.

    Raises:
        SystemExit: With status 1 when a success criterion misses its target.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    # httpx logs every request at INFO, which would bury the progress lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = _arguments(argv)
    outcomes = asyncio.run(_run(args))
    if not _report(outcomes, args.api_log):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
