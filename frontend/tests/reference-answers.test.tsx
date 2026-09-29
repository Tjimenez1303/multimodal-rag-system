import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { formatPages } from "@/answer/sourceLabel";
import type { AnswerBody } from "@/client";
import type { Turn } from "@/conversation/state";
import { ConversationView } from "@/conversation/ConversationView";
import { TurnView } from "@/conversation/TurnView";

import { answeredReferences, referenceAnswers } from "./fixtures/answers";
import { questionFailures } from "./fixtures/failures/questions";
import { server } from "./msw/server";
import { renderWithProviders } from "./render";

// Markdown syntax that must never survive rendering (SC-002).
const MARKDOWN_SYNTAX = /\*\*|__|^#{1,6}\s|```|`|^\s*\|?\s*-{3,}\s*\|/m;

function answeredTurn(question: string, response: AnswerBody): Turn {
  return {
    id: "turn-1",
    question,
    restriction: [],
    state: "answered",
    requestId: "req-1",
    response,
    failure: null,
    stopReason: null,
  };
}

test("the reference set holds at least 12 answered responses", () => {
  expect(answeredReferences.length).toBeGreaterThanOrEqual(12);
  expect(referenceAnswers.length).toBeGreaterThan(answeredReferences.length);
});

describe.each(
  answeredReferences.map(({ name, response }) => [name, response] as const),
)("reference answer %s", (name, response) => {
  beforeEach(() => {
    render(<TurnView turn={answeredTurn(name, response)} />);
  });

  test("every citation has its source line with the document name and pages (SC-001)", () => {
    const lines = within(screen.getByRole("list", { name: "Sources" })).getAllByRole(
      "listitem",
    );
    expect(lines).toHaveLength(response.citations.length);
    response.citations.forEach((citation, index) => {
      expect(lines[index]).toHaveTextContent(
        `Source: ${citation.document_name}, ${formatPages(citation.pages)}`,
      );
    });
  });

  test("the primary image is beside the answer with its caption and page (SC-001)", () => {
    const image = response.primary_image;
    const figures = screen.queryByRole("complementary", { name: "Figures" });
    if (image === null) {
      // Without a primary image, the column exists only for related images.
      expect(figures !== null).toBe(response.related_images.length > 0);
      return;
    }
    const figure = within(figures!).getAllByRole("figure")[0]!;
    expect(figure).toHaveTextContent(image.caption ?? "No caption");
    expect(figure).toHaveTextContent(`${image.document_name}, page ${image.page}`);
    expect(within(figure).getByRole("img")).toHaveAttribute("src", image.url);
  });

  test("no Markdown syntax remains in the rendered answer (SC-002)", () => {
    const answer = screen.getByRole("region", { name: "Answer" });
    const text =
      answer.querySelector("[data-streamdown], .space-y-4")?.textContent ?? "";
    expect(text).not.toMatch(MARKDOWN_SYNTAX);
  });

  test("every flagged source carries its mark (SC-003)", () => {
    const lines = within(screen.getByRole("list", { name: "Sources" })).getAllByRole(
      "listitem",
    );
    response.citations.forEach((citation, index) => {
      const sources = response.sources.filter((source) =>
        citation.unit_ids.includes(source.unit_id),
      );
      const line = within(lines[index]!);
      if (sources.some((source) => source.low_confidence_text)) {
        expect(line.getByText("Low-confidence OCR")).toBeInTheDocument();
      }
      if (sources.some((source) => source.generated_description)) {
        expect(line.getByText("Described automatically")).toBeInTheDocument();
      }
    });
  });
});

test("an answer in Spanish is shown as returned, with the interface in English", () => {
  const spanish = answeredReferences.find(({ name }) => name === "cinco-reglas-de-oro");
  render(
    <TurnView
      turn={answeredTurn("¿Cuáles son las cinco reglas de oro?", spanish!.response)}
    />,
  );

  const answer = screen.getByRole("region", { name: "Answer" });
  const firstWords = spanish!.response.answer.split(/\s+/).slice(0, 4).join(" ");
  expect(answer).toHaveTextContent(firstWords.replace(/[*#`]/g, ""));
  expect(screen.getByText("Sources")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Open page" }).length).toBeGreaterThan(
    0,
  );
});

describe.each(
  referenceAnswers
    .filter(({ response }) => response.status === "not_enough_information")
    .map(({ name, response }) => [name, response] as const),
)("no-information reference %s", (name, response) => {
  test("is shown as no information found, without sources or images", () => {
    const turn = answeredTurn(name, response);
    render(<TurnView turn={{ ...turn, state: "no_information" }} />);

    expect(
      screen.getByRole("region", { name: "No information found" }),
    ).toHaveTextContent(response.answer);
    expect(screen.queryByRole("list", { name: "Sources" })).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

test("the reference set holds at least 20 responses with the failures", () => {
  expect(referenceAnswers.length + questionFailures.length).toBeGreaterThanOrEqual(20);
  const reasons = new Set(referenceAnswers.map(({ response }) => response.reason));
  expect(reasons).toEqual(
    new Set([
      null,
      "no_searchable_documents",
      "no_relevant_content",
      "not_answered_by_sources",
      "no_valid_citations",
    ]),
  );
});

describe.each(questionFailures.map((fixture) => [fixture.name, fixture] as const))(
  "failure reference %s",
  (_name, fixture) => {
    test("shows its plain-English message, its reference and a retry where retryable (SC-007)", async () => {
      server.use(
        http.post("/api/v1/questions", () =>
          HttpResponse.json(fixture.body, {
            status: fixture.status,
            headers: {
              "Content-Type": "application/problem+json",
              ...(fixture.retryAfter ? { "Retry-After": fixture.retryAfter } : {}),
            },
          }),
        ),
      );
      const user = userEvent.setup();
      renderWithProviders(<ConversationView />);

      await user.type(
        screen.getByRole("textbox", { name: "Ask a question about your manuals" }),
        "question{Enter}",
      );

      const turn = screen.getByRole("article", { name: "Question: question" });
      expect(await within(turn).findByText(fixture.message)).toBeVisible();
      expect(turn).toHaveTextContent(/Reference: [0-9a-f-]{36}/);
      expect(turn).not.toHaveTextContent(fixture.body.code);
      expect(within(turn).queryByRole("button", { name: "Retry" }) !== null).toBe(
        fixture.retryable,
      );
    });
  },
);
