import { expect, test, type Page } from "@playwright/test";

import { answer, ask, expectAccessible, fakeService } from "./fakes.ts";

const withImages = answer("magneto-timing-steps");
const bicycle = answer("no-information-bicycle");

async function openWith(page: Page, responses = [withImages]) {
  await fakeService(page, responses);
  await page.goto("/");
}

test("the empty conversation", async ({ page }) => {
  await openWith(page);
  await expect(page.getByText("Ask about your manuals")).toBeVisible();
  await expectAccessible(page);
});

test("an answer with images, and each of its dialogs", async ({ page }) => {
  await openWith(page);
  await ask(page, "What are the steps to time a magneto?");
  await expect(page.getByRole("region", { name: "Answer" })).toBeVisible();
  await expectAccessible(page);

  await page.getByRole("button", { name: "View full size" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expectAccessible(page);
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Open page" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expectAccessible(page);
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "New conversation" }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await expectAccessible(page);
});

test("no information, and a failure", async ({ page }) => {
  await openWith(page, [bicycle]);
  await ask(page, "What is the recommended tire pressure for a bicycle?");
  await expect(
    page.getByRole("region", { name: "No information found" }),
  ).toBeVisible();
  await page.route("**/api/v1/questions", (route) => route.abort("connectionrefused"));
  await ask(page, "Another question");
  await expect(page.getByText("The service could not be reached.")).toBeVisible();
  await expectAccessible(page);
});

test("the collapsed document panel", async ({ page }) => {
  await openWith(page);
  await page.getByRole("button", { name: "Hide documents" }).click();
  await expect(page.getByRole("button", { name: "Show documents" })).toBeVisible();
  await expectAccessible(page);
});

test("a question can be asked and its page opened with the keyboard only", async ({
  page,
  browserName,
}) => {
  // Safari's default Tab reaches only form controls. Alt+Tab reaches every control.
  const backward = browserName === "webkit" ? "Alt+Shift+Tab" : "Shift+Tab";
  await openWith(page);
  const input = page.getByRole("textbox", {
    name: "Ask a question about your manuals",
  });

  // Tab from the top of the page to the question box.
  for (let presses = 0; presses < 20; presses += 1) {
    if (await input.evaluate((element) => element === document.activeElement)) break;
    await page.keyboard.press("Tab");
  }
  await expect(input).toBeFocused();
  await page.keyboard.type("What are the steps to time a magneto?");
  await page.keyboard.press("Enter");
  const firstLine = page
    .getByRole("list", { name: "Sources" })
    .getByRole("listitem")
    .first();
  await expect(firstLine).toBeVisible();

  // Reach the first source line's "Open page" and open it with Enter.
  const openPage = firstLine.getByRole("button", { name: "Open page" });
  for (let presses = 0; presses < 60; presses += 1) {
    if (await openPage.evaluate((element) => element === document.activeElement)) break;
    await page.keyboard.press(backward);
  }
  await expect(openPage).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toContainText(
    withImages.citations[0]!.document_name,
  );

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(openPage).toBeFocused();
});
