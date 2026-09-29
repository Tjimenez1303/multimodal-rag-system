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

  // An image opens at full size within 300 ms: from the click to the first frame
  // painted with the dialog, measured in the page so the test driver's own latency is
  // left out.
  const opener = page.getByRole("button", { name: "View full size" }).last();
  await opener.scrollIntoViewIfNeeded();
  await opener.evaluate((element) => {
    const timing = { clicked: 0, painted: 0 };
    Object.assign(window, { dialogTiming: timing });
    element.addEventListener("click", () => (timing.clicked = performance.now()), {
      once: true,
    });
    const observer = new MutationObserver(() => {
      if (document.querySelector('[role="dialog"]') === null) return;
      observer.disconnect();
      requestAnimationFrame(() => (timing.painted = performance.now()));
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
  await opener.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const opening = await page.evaluate(() => {
    const { clicked, painted } = (
      window as unknown as { dialogTiming: { clicked: number; painted: number } }
    ).dialogTiming;
    return painted - clicked;
  });
  expect(opening).toBeGreaterThan(0);
  expect(opening).toBeLessThan(300);
  await page.keyboard.press("Escape");

  // Scrolling back to the first turn with the wheel completes. A user's scroll releases
  // the conversation from following the newest turn.
  const first = page.getByRole("article").first();
  const conversation = page.getByRole("log");
  await conversation.hover();
  await expect(async () => {
    await page.mouse.wheel(0, -20_000);
    await expect(first).toBeInViewport();
  }).toPass();
});
