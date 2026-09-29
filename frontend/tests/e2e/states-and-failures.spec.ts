import { expect, test, type Page } from "@playwright/test";

import { answer, ask, expectAccessible, fakeService } from "./fakes.ts";

const plain = answer("series-generator-on-airplanes");
const bicycle = answer("no-information-bicycle");

function problem(status: number, code: string, headers: Record<string, string> = {}) {
  return {
    status,
    contentType: "application/problem+json",
    headers,
    body: JSON.stringify({
      type: "about:blank",
      title: "Problem",
      status,
      detail: code,
      instance: "/api/v1/questions",
      code,
      request_id: "service-id",
    }),
  };
}

/** Holds every question until the test releases it. */
async function holdQuestions(page: Page) {
  const pending: Array<() => Promise<void>> = [];
  await page.route("**/api/v1/questions", async (route) => {
    const { question } = route.request().postDataJSON() as { question: string };
    await new Promise<void>((release) =>
      pending.push(async () => {
        release();
        await route
          .fulfill({ json: { ...plain, answer: `Answer to ${question}` } })
          .catch(() => {});
      }),
    );
  });
  return {
    releaseNext: async () => {
      await expect.poll(() => pending.length).toBeGreaterThan(0);
      await pending.shift()!();
    },
  };
}

function input(page: Page) {
  return page.getByRole("textbox", { name: "Ask a question about your manuals" });
}

test("the working indicator appears within half a second of sending (SC-006)", async ({
  page,
}) => {
  await fakeService(page, [plain]);
  await holdQuestions(page);
  await page.goto("/");

  await input(page).fill("How is a shunt generator wired?");
  const sent = Date.now();
  await input(page).press("Enter");
  await expect(
    page.getByRole("status").filter({ hasText: "Preparing the answer…" }),
  ).toBeVisible();

  expect(Date.now() - sent).toBeLessThan(500);
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
});

test("a reply without information is shown in its own state", async ({ page }) => {
  await fakeService(page, [bicycle]);
  await page.goto("/");

  await ask(page, "What is the recommended tire pressure for a bicycle?");

  const state = page.getByRole("region", { name: "No information found" });
  await expect(state).toBeVisible();
  await expect(state).toContainText(/rephras/i);
  await expect(page.getByRole("list", { name: "Sources" })).toHaveCount(0);
  await expectAccessible(page);
});

test("an answer model failure shows its message, reference and a retry that replaces it", async ({
  page,
}) => {
  await fakeService(page, [plain]);
  let failures = 1;
  await page.route("**/api/v1/questions", (route) =>
    failures-- > 0
      ? route.fulfill(problem(503, "answer_model_unavailable"))
      : route.fallback(),
  );
  await page.goto("/");

  await ask(page, "Why is a series wound generator never used on airplanes?");
  const turn = page.getByRole("article");
  await expect(turn).toContainText("The answer model is not responding.");
  await expect(turn).toContainText(/Reference: [0-9a-f-]{36}/);
  await expectAccessible(page);

  await turn.getByRole("button", { name: "Retry" }).click();
  await expect(turn.getByRole("region", { name: "Answer" })).toBeVisible();
  await expect(turn).not.toContainText("The answer model is not responding.");
  await expect(page.getByRole("article")).toHaveCount(1);
});

test("the busy message says when to retry", async ({ page }) => {
  await fakeService(page, [plain]);
  await page.route("**/api/v1/questions", (route) =>
    route.fulfill(problem(503, "answering_busy", { "Retry-After": "7" })),
  );
  await page.goto("/");

  await ask(page, "question");

  await expect(page.getByRole("article")).toContainText(
    "The system is busy answering other questions. You can retry in 7 seconds.",
  );
});

test("stop cancels the request, held questions follow, and a retry answers", async ({
  page,
}) => {
  await fakeService(page, [plain]);
  const questions = await holdQuestions(page);
  const cancelled: string[] = [];
  page.on("requestfailed", (request) => {
    if (request.url().endsWith("/api/v1/questions"))
      cancelled.push(request.failure()?.errorText ?? "");
  });
  await page.goto("/");

  await ask(page, "slow question");
  await ask(page, "held question");
  await expect(page.getByRole("article").nth(1)).toContainText("Waiting to be sent");
  await page.getByRole("button", { name: "Stop" }).click();

  await expect.poll(() => cancelled.length).toBe(1);
  const stopped = page.getByRole("article").first();
  await expect(stopped).toContainText("Stopped");
  await questions.releaseNext();
  await questions.releaseNext();
  await expect(page.getByRole("article").nth(1)).toContainText(
    "Answer to held question",
  );

  await stopped.getByRole("button", { name: "Retry" }).click();
  await questions.releaseNext();
  await expect(stopped).toContainText("Answer to slow question");
});

test("a reload keeps every turn, and a new tab starts empty (SC-008)", async ({
  page,
  browser,
}) => {
  await fakeService(page, [plain, bicycle]);
  await page.goto("/");
  await ask(page, "first question");
  await expect(page.getByRole("region", { name: "Answer" })).toBeVisible();
  await ask(page, "second question");
  await expect(
    page.getByRole("region", { name: "No information found" }),
  ).toBeVisible();

  await page.reload();

  const turns = page.getByRole("article");
  await expect(turns).toHaveCount(2);
  await expect(turns.nth(0)).toContainText("first question");
  await expect(turns.nth(1)).toContainText("second question");

  const other = await browser.newPage();
  await fakeService(other, [plain]);
  await other.goto("/");
  await expect(other.getByRole("article")).toHaveCount(0);
  await other.close();
});

test("the connection notice appears while the service is unreachable and clears after", async ({
  page,
}) => {
  await fakeService(page, [plain]);
  let unreachable = true;
  await page.route("**/api/v1/questions", (route) =>
    unreachable ? route.abort("connectionrefused") : route.fallback(),
  );
  await page.goto("/");

  await ask(page, "question");
  await expect(page.getByText("Can't reach the service. Retrying…")).toBeVisible();
  await expect(page.getByRole("article")).toContainText(
    "The service could not be reached.",
  );

  unreachable = false;
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("region", { name: "Answer" })).toBeVisible();
  await expect(page.getByText("Can't reach the service. Retrying…")).toBeHidden();
});
