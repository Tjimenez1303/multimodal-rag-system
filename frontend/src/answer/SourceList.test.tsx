import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CitationProvider } from "@/answer/citations";
import { AnswerMarkdown } from "@/answer/markdown/AnswerMarkdown";
import { SourceList } from "@/answer/SourceList";

import { answerWithFigures } from "../../tests/fixtures/answers/sample";
import { scrolledIntoView } from "../../tests/setup";

function renderSources() {
  return render(
    <CitationProvider turnId="turn-1" response={answerWithFigures}>
      <AnswerMarkdown
        answer={answerWithFigures.answer}
        citationNumbers={[1, 2, 3, 4]}
      />
      <SourceList response={answerWithFigures} />
    </CitationProvider>,
  );
}

function sourceLine(number: number): HTMLElement {
  return screen.getByRole("listitem", { name: new RegExp(`^Source ${number}\\b`) });
}

test("each citation renders one numbered source line with its label", () => {
  renderSources();

  const lines = within(screen.getByRole("list", { name: "Sources" })).getAllByRole(
    "listitem",
  );
  expect(lines).toHaveLength(4);
  expect(sourceLine(1)).toHaveTextContent(
    "Source: faa-powerplant-ch4-ignition-electrical.pdf, page 12",
  );
  expect(sourceLine(2)).toHaveTextContent("pages 12–13");
  expect(sourceLine(4)).toHaveTextContent(
    "Source: tm-5-3431-201-10-welding-machine-scanned.pdf, pages 3–4, 9",
  );
});

test("expanding a line shows its section, excerpt and table rows", async () => {
  const user = userEvent.setup();
  renderSources();

  await user.click(within(sourceLine(3)).getByRole("button", { name: "Show details" }));

  const line = sourceLine(3);
  expect(line).toHaveTextContent("Generators › Terminal markings");
  const table = within(line).getByRole("table");
  expect(
    within(table).getByRole("cell", { name: "Field positive" }),
  ).toBeInTheDocument();
  await user.click(within(sourceLine(1)).getByRole("button", { name: "Show details" }));
  expect(sourceLine(1)).toHaveTextContent(
    "In a shunt generator the field coil is connected in parallel with the armature.",
  );
});

test("a low-confidence source is marked with an explanation", () => {
  renderSources();

  const line = sourceLine(4);
  expect(within(line).getByText("Low-confidence OCR")).toBeInTheDocument();
  expect(line).toHaveTextContent(/recognized from a scan with low confidence/i);
  expect(line).toHaveTextContent(/check it against the page/i);
});

test("a generated description is marked and lists its unverified identifiers", () => {
  renderSources();

  const line = sourceLine(4);
  expect(within(line).getByText("Described automatically")).toBeInTheDocument();
  expect(line).toHaveTextContent("Unverified identifiers: S-12, R-4");
  expect(
    within(sourceLine(1)).queryByText("Low-confidence OCR"),
  ).not.toBeInTheDocument();
});

test("uncited passages are available on demand under their own disclosure", async () => {
  const user = userEvent.setup();
  renderSources();

  expect(
    screen.queryByText("Magneto timing is checked with a timing light."),
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: /Other retrieved passages \(1\)/ }),
  );

  expect(
    screen.getByText("Magneto timing is checked with a timing light."),
  ).toBeInTheDocument();
});

test("activating a marker highlights the matching line and moves focus to it", async () => {
  const user = userEvent.setup();
  renderSources();

  await user.click(screen.getByRole("link", { name: "Citation 2" }));

  expect(sourceLine(2)).toHaveAttribute("data-highlighted", "true");
  expect(sourceLine(2)).toHaveFocus();
  expect(scrolledIntoView).toContain(sourceLine(2));
  expect(sourceLine(1)).not.toHaveAttribute("data-highlighted", "true");
});

test("every source line can open its page", () => {
  renderSources();

  for (const number of [1, 2, 3, 4]) {
    expect(
      within(sourceLine(number)).getByRole("button", { name: "Open page" }),
    ).toBeEnabled();
  }
});
