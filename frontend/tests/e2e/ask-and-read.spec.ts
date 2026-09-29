import { expect, test } from "@playwright/test";

import { answer, ask, expectAccessible, fakeService } from "./fakes.ts";

const magneto = answer("magneto-timing-steps");
const markdown = answer("written-markdown-elements");
const lowConfidence = answer("written-low-confidence-scan");
const partial = answer("bonding-jumper-inspection");

test("a question is answered with its sources and its figure beside it", async ({
  page,
}) => {
  await fakeService(page, [magneto]);
  await page.goto("/");

  await ask(page, "What are the steps to time a magneto to the engine?");

  // Scenario 1: the question, then its answer.
  const turn = page.getByRole("article").first();
  await expect(turn).toContainText("What are the steps to time a magneto");
  const answerRegion = turn.getByRole("region", { name: "Answer" });
  await expect(answerRegion).toBeVisible();

  // Scenario 3: a numbered source line per citation.
  const lines = answerRegion
    .getByRole("list", { name: "Sources" })
    .getByRole("listitem");
  await expect(lines).toHaveCount(magneto.citations.length);
  await expect(lines.first()).toContainText(
    `Source: ${magneto.citations[0]!.document_name}`,
  );

  // Scenario 5: the primary figure in a column to the right of the text.
  const figures = answerRegion.getByRole("complementary", { name: "Figures" });
  const textBox = await answerRegion
    .getByRole("list", { name: "Sources" })
    .boundingBox();
  const figureBox = await figures.boundingBox();
  expect(figureBox!.x).toBeGreaterThan(textBox!.x + textBox!.width);
  const primary = figures.getByRole("figure").first();
  await expect(primary).toContainText(`page ${magneto.primary_image!.page}`);

  // Scenario 7: related images as a secondary group under it.
  await expect(
    figures.getByRole("group", { name: "Related images" }).getByRole("figure"),
  ).toHaveCount(magneto.related_images.length);

  await expectAccessible(page);
});

test("a citation marker brings its source line into view and highlights it", async ({
  page,
}) => {
  await fakeService(page, [magneto]);
  await page.goto("/");
  await ask(page, "What are the steps to time a magneto to the engine?");

  const number = magneto.citations.at(-1)!.number;
  await page
    .getByRole("link", { name: `Citation ${number}` })
    .first()
    .click();

  const line = page.getByRole("listitem", { name: new RegExp(`^Source ${number}\\b`) });
  await expect(line).toHaveAttribute("data-highlighted", "true");
  await expect(line).toBeFocused();
  await expect(line).toBeInViewport();
});

test("the answer's Markdown renders with its formatting", async ({ page }) => {
  await fakeService(page, [markdown]);
  await page.goto("/");
  await ask(page, "How do I inspect the ignition leads?");

  const region = page.getByRole("region", { name: "Answer" });
  await expect(
    region.getByRole("heading", { name: "Inspecting ignition leads" }),
  ).toBeVisible();
  await expect(region.locator("strong")).toHaveText("chafing");
  await expect(region.locator("em")).toHaveText("burned");
  await expect(region.getByRole("table")).toBeVisible();
  await expect(region.locator("pre code")).toContainText("LEAD 1: 1.2 kOhm");
  await expect(region).not.toContainText("**");
});

test("a figure opens at full size and closes back to the conversation", async ({
  page,
}) => {
  await fakeService(page, [magneto]);
  await page.goto("/");
  await ask(page, "What are the steps to time a magneto to the engine?");

  const opener = page.getByRole("button", { name: "View full size" }).first();
  await opener.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(`page ${magneto.primary_image!.page}`);
  await expectAccessible(page);

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(opener).toBeFocused();
});

test("a source line opens its page, and a multi-page source steps between its pages", async ({
  page,
}) => {
  await fakeService(page, [magneto]);
  await page.goto("/");
  await ask(page, "What are the steps to time a magneto to the engine?");

  const multiPage = magneto.citations.find((citation) => citation.pages.length > 1)!;
  const pages = [...new Set(multiPage.pages)].sort((a, b) => a - b);
  const line = page.getByRole("listitem", {
    name: new RegExp(`^Source ${multiPage.number}\\b`),
  });
  await line.getByRole("button", { name: "Open page" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(`${multiPage.document_name}, page ${pages[0]}`);
  await expect(dialog.getByRole("img")).toHaveAttribute(
    "src",
    `/api/v1/documents/${multiPage.document_id}/pages/${pages[0]}/image`,
  );
  await dialog.getByRole("button", { name: "Next page" }).click();
  await expect(dialog).toContainText(`${multiPage.document_name}, page ${pages[1]}`);
  await expectAccessible(page);
});

test("flagged sources, partial answers and uncited passages are shown", async ({
  page,
}) => {
  await fakeService(page, [lowConfidence, partial]);
  await page.goto("/");

  await ask(page, "What are the controls on the welding machine control panel?");
  const first = page.getByRole("article").first();
  await expect(first.getByText("Low-confidence OCR")).toBeVisible();
  await expect(first).toContainText("Check it against the page");

  await ask(page, "What does a bonding jumper do and how is it inspected?");
  const second = page.getByRole("article").nth(1);
  await expect(second.getByRole("note")).toContainText("Not covered by the documents");
  await second.getByRole("button", { name: /Other retrieved passages/ }).click();
  const uncited = partial.sources.find((source) => !source.cited)!;
  await expect(second).toContainText(uncited.excerpt.split("\n")[0]!.slice(0, 40));
});

test("a new answer is brought into view and earlier turns stay in order", async ({
  page,
}) => {
  await fakeService(page, [magneto, partial]);
  await page.goto("/");

  await ask(page, "First question");
  await expect(page.getByRole("region", { name: "Answer" })).toHaveCount(1);
  await ask(page, "Second question");
  await expect(page.getByRole("region", { name: "Answer" })).toHaveCount(2);

  const turns = page.getByRole("article");
  await expect(turns.nth(0)).toContainText("First question");
  await expect(turns.nth(1)).toContainText("Second question");
  await expect(turns.nth(1).getByRole("region", { name: "Answer" })).toBeInViewport();
});
