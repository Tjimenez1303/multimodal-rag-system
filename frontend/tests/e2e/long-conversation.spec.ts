import { expect, test } from "@playwright/test";

import { answer, fakeService } from "./fakes.ts";

const withImage = answer("shunt-generator-wiring");
const TURNS = 50;

test("a conversation of 50 turns with images stays responsive (SC-010)", async ({
  page,
}) => {
  await fakeService(page, [withImage]);
  const turns = Array.from({ length: TURNS }, (_, index) => ({
    id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    question: `Question ${index + 1}: how is a shunt generator wired?`,
    restriction: [],
    state: "answered",
    requestId: `req-${index}`,
    response: withImage,
    failure: null,
    stopReason: null,
  }));
  await page.addInitScript(
    (stored) => {
      sessionStorage.setItem("multimodal-rag.conversation.v1", stored);
    },
    JSON.stringify({ version: 1, turns }),
  );
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(TURNS);

  // A typed character shows in the input within 100 ms: from the key press to the
  // first frame painted after the input changed.
  const input = page.getByRole("textbox", {
    name: "Ask a question about your manuals",
  });
  await input.focus();
  await input.evaluate((element) => {
    const timing = { down: 0, painted: 0 };
    Object.assign(window, { typingTiming: timing });
    element.addEventListener("keydown", () => (timing.down = performance.now()), {
      once: true,
    });
    element.addEventListener(
      "input",
      () => requestAnimationFrame(() => (timing.painted = performance.now())),
      { once: true },
    );
  });
  await page.keyboard.press("x");
  await expect(input).toHaveValue("x");
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as unknown as { typingTiming: { painted: number } }).typingTiming
            .painted,
      ),
    )
    .toBeGreaterThan(0);
  const typing = await page.evaluate(() => {
    const { down, painted } = (
      window as unknown as { typingTiming: { down: number; painted: number } }
    ).typingTiming;
    return painted - down;
  });
  expect(typing).toBeLessThan(100);

  // An image opens at full size within 300 ms.
  const opener = page.getByRole("button", { name: "View full size" }).last();
  await opener.scrollIntoViewIfNeeded();
  const opened = Date.now();
  await opener.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(Date.now() - opened).toBeLessThan(300);
  await page.keyboard.press("Escape");

  // Scrolling back to the first turn completes.
  const first = page.getByRole("article").first();
  await first.scrollIntoViewIfNeeded();
  await expect(first).toBeInViewport();
});
