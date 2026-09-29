import { render, screen, within } from "@testing-library/react";

import { AnswerMarkdown } from "@/answer/markdown/AnswerMarkdown";

const FORMATTED = [
  "# Heading one",
  "",
  "## Heading two",
  "",
  "Some **bold** and *italic* text with `inline code`.",
  "",
  "1. First step",
  "2. Second step",
  "   - nested item",
  "",
  "- Unordered item",
  "",
  "| Part | Code |",
  "|------|------|",
  "| Pump | A-1  |",
  "",
  "```",
  "SET GAP 0.016",
  "```",
].join("\n");

function renderAnswer(answer: string, citations: number[] = []) {
  return render(<AnswerMarkdown answer={answer} citationNumbers={citations} />);
}

test("every Markdown element renders with its formatting and no formatting characters", () => {
  const { container } = renderAnswer(FORMATTED);

  expect(
    screen.getByRole("heading", { level: 1, name: "Heading one" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { level: 2, name: "Heading two" }),
  ).toBeInTheDocument();
  expect(container.querySelector("strong")).toHaveTextContent("bold");
  expect(container.querySelector("em")).toHaveTextContent("italic");
  expect(container.querySelector("ol")).toBeInTheDocument();
  expect(container.querySelector("ol ul li")).toHaveTextContent("nested item");
  expect(container.querySelectorAll("ul").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("inline code").tagName).toBe("CODE");
  expect(container.querySelector("pre code")).toHaveTextContent("SET GAP 0.016");
  const table = screen.getByRole("table");
  expect(within(table).getByRole("cell", { name: "A-1" })).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/[#*|]/);
});

test("a marker whose citation exists becomes a citation link", () => {
  renderAnswer("Check the leads [1].", [1]);

  expect(screen.getByRole("link", { name: "Citation 1" })).toBeInTheDocument();
  expect(screen.queryByText("[1]")).not.toBeInTheDocument();
});

test("a marker without a citation stays text", () => {
  renderAnswer("See step [7].", [1]);

  expect(screen.queryByRole("link", { name: "Citation 7" })).not.toBeInTheDocument();
  expect(screen.getByText(/See step \[7\]\./)).toBeInTheDocument();
});

test("markers inside code stay literal", () => {
  const { container } = renderAnswer("Type `[1]` then:\n\n```\narray[1]\n```", [1]);

  expect(screen.queryByRole("link", { name: "Citation 1" })).not.toBeInTheDocument();
  expect(container.querySelector("p code")).toHaveTextContent("[1]");
  expect(container.querySelector("pre code")).toHaveTextContent("array[1]");
});

test("raw markup is shown as text and never becomes elements", () => {
  const { container } = renderAnswer(
    'Before <script>alert(1)</script> and\n\n<img src=x onerror="alert(2)">\n\nafter <b>bold</b>.',
  );

  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("b")).toBeNull();
  expect(container).toHaveTextContent("<script>alert(1)</script>");
  expect(container).toHaveTextContent('<img src=x onerror="alert(2)">');
  expect(container).toHaveTextContent("<b>bold</b>");
});

test("Markdown images show their alt text and load nothing", () => {
  const { container } = renderAnswer("![Wiring diagram](http://example.com/a.png)");

  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector('link[rel="preload"]')).toBeNull();
  expect(container).toHaveTextContent("Wiring diagram");
});

test("a javascript: link is not rendered as a link", () => {
  renderAnswer("[click me](javascript:alert(1))");

  expect(screen.queryByRole("link", { name: /click me/ })).not.toBeInTheDocument();
});

test("links open in a new tab without referrer", () => {
  renderAnswer("See [the FAA site](https://www.faa.gov/).");

  const link = screen.getByRole("link", { name: "the FAA site" });
  expect(link).toHaveAttribute("href", "https://www.faa.gov/");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener noreferrer");
});

test("a wide table scrolls sideways inside a focusable region", () => {
  renderAnswer("| a | b |\n|---|---|\n| 1 | 2 |");

  const region = screen.getByRole("region", { name: "Table" });
  expect(region).toHaveAttribute("tabindex", "0");
  expect(region).toContainElement(screen.getByRole("table"));
});
