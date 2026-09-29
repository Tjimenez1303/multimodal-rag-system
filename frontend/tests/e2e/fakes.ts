import { readFileSync } from "node:fs";

import { AxeBuilder } from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

import type { AnswerBody } from "../../src/client/types.gen.ts";

const ANSWERS = new URL("../fixtures/answers/", import.meta.url);

/** The library route, with or without its query string. */
export const LIBRARY = /\/api\/v1\/documents(\?.*)?$/;

// A 1 × 1 PNG, served for every figure and page image.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

/**
 * Read a response of the reference answer set.
 *
 * @param name - File name without `.json`.
 * @returns The response as the service returned it.
 */
export function answer(name: string): AnswerBody {
  return JSON.parse(
    readFileSync(new URL(`${name}.json`, ANSWERS), "utf8"),
  ) as AnswerBody;
}

/**
 * Fake the service on the page: configuration, images and, in order, one response per
 * question asked.
 *
 * @param page - The page under test.
 * @param responses - Bodies answered to successive questions. The last one repeats.
 */
export async function fakeService(page: Page, responses: AnswerBody[]): Promise<void> {
  let asked = 0;
  // Registered first, so every more specific fake wins, and no request can reach a
  // real API behind the preview server's proxy.
  await page.route("**/api/**", (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/problem+json",
      body: JSON.stringify({
        title: "Not Found",
        status: 404,
        instance: new URL(route.request().url()).pathname,
        code: "not_found",
        request_id: "e2e",
      }),
    }),
  );
  await page.route("**/config.json", (route) =>
    route.fulfill({
      json: { answerWaitSeconds: 105, maxFilterDocuments: 20, statusPollSeconds: 2 },
    }),
  );
  await page.route(LIBRARY, (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route("**/api/v1/questions", (route) => {
    const body = responses[Math.min(asked, responses.length - 1)]!;
    asked += 1;
    return route.fulfill({ json: body, headers: { "X-Request-ID": "e2e" } });
  });
  await page.route(
    /\/api\/v1\/documents\/[^/]+\/(images\/[^/]+|pages\/\d+\/image)$/,
    (route) => route.fulfill({ body: PNG, contentType: "image/png" }),
  );
}

/**
 * Type a question and send it with Enter.
 *
 * @param page - The page under test.
 * @param question - The question.
 */
export async function ask(page: Page, question: string): Promise<void> {
  const input = page.getByRole("textbox", {
    name: "Ask a question about your manuals",
  });
  await input.fill(question);
  await input.press("Enter");
}

/**
 * Fail on any WCAG 2.1 A or AA violation in the page's current state (FR-044).
 *
 * @param page - The page under test.
 */
export async function expectAccessible(page: Page): Promise<void> {
  // Colors are checked once transitions end, not halfway through a fade.
  await page.waitForFunction(() =>
    document.getAnimations().every((animation) => animation.playState !== "running"),
  );
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations).toEqual([]);
}
