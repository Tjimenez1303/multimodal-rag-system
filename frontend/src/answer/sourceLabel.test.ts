import { formatPages, sourceLabel } from "@/answer/sourceLabel";

test.each([
  [[12], "Source: X.pdf, page 12"],
  [[12, 13], "Source: X.pdf, pages 12–13"],
  [[3, 4, 9], "Source: X.pdf, pages 3–4, 9"],
  [[9, 3, 4], "Source: X.pdf, pages 3–4, 9"],
  [[12, 12, 13], "Source: X.pdf, pages 12–13"],
  [[5, 5], "Source: X.pdf, page 5"],
  [[1, 2, 3, 7, 9, 10], "Source: X.pdf, pages 1–3, 7, 9–10"],
])("pages %j give %s", (pages, label) => {
  expect(sourceLabel("X.pdf", pages)).toBe(label);
});

test("the pages alone are formatted without the document", () => {
  expect(formatPages([13, 12])).toBe("pages 12–13");
});
