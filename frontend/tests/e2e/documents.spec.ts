import { expect, test, type Page } from "@playwright/test";

import type { DocumentBody, JobBody } from "../../src/client/types.gen.ts";
import { answer, ask, expectAccessible, fakeService, LIBRARY } from "./fakes.ts";

const PDF = {
  name: "faa-manual.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.7"),
};
const CREATED = "2026-09-29T09:00:00Z";

function job(documentId: string, fields: Partial<JobBody>): JobBody {
  return {
    id: "27e7cbe8-7dc9-4866-8f9f-f96bf505a35f",
    document_id: documentId,
    status: "pending",
    stage: null,
    attempt: 1,
    max_attempts: 3,
    pages_done: 0,
    pages_total: 71,
    failure_code: null,
    failure_reason: null,
    summary: null,
    created_at: CREATED,
    started_at: null,
    finished_at: null,
    ...fields,
  };
}

/** A library whose uploaded document moves one step through its job on each poll. */
async function fakeLibrary(page: Page, steps: Array<Partial<JobBody>>, failed = false) {
  const documents: DocumentBody[] = [];
  const id = "998496fb-02ce-4d4a-a178-37f0914ce20b";
  let step = 0;
  await page.route("**/config.json", (route) =>
    route.fulfill({
      json: { answerWaitSeconds: 105, maxFilterDocuments: 20, statusPollSeconds: 0.3 },
    }),
  );
  await page.route(LIBRARY, async (route) => {
    if (route.request().method() === "POST") {
      const already = documents.some((document) => document.id === id);
      if (!already) {
        documents.unshift({
          id,
          file_name: PDF.name,
          size_bytes: 8,
          page_count: 71,
          created_at: CREATED,
          latest_job: job(id, {}),
        });
      }
      return route.fulfill({
        status: already ? 200 : 202,
        json: {
          document_id: id,
          job_id: job(id, {}).id,
          status: already ? "completed" : "pending",
          already_ingested: already,
        },
      });
    }
    return route.fulfill({ json: { items: documents, next_cursor: null } });
  });
  await page.route(`**/api/v1/documents/${id}`, (route) => {
    const document = documents[0]!;
    const fields = steps[Math.min(step, steps.length - 1)]!;
    step += 1;
    document.latest_job = job(id, fields);
    if (failed && step >= steps.length) {
      document.latest_job = job(id, {
        status: "failed",
        failure_reason: "The PDF is damaged and cannot be read.",
      });
    }
    return route.fulfill({ json: document });
  });
}

const PROCESSING: Array<Partial<JobBody>> = [
  { status: "processing", stage: "extracting", pages_done: 12 },
  { status: "processing", stage: "extracting", pages_done: 40 },
  { status: "processing", stage: "embedding", pages_done: 71, attempt: 2 },
  {
    status: "completed",
    stage: "finalizing",
    pages_done: 71,
    summary: {
      pages: 71,
      text_elements: 900,
      tables: 4,
      table_chains: 0,
      images: 23,
      figures_described: 20,
      figures_skipped: 3,
      figures_not_described: 0,
      retrieval_units: 300,
      recognized_pages: 0,
    },
  },
];

test("an upload is followed from pending, through processing, to ready", async ({
  page,
}) => {
  await fakeService(page, []);
  await fakeLibrary(page, PROCESSING);
  await page.goto("/");

  await page.getByLabel("Upload a PDF").setInputFiles(PDF);

  const row = page
    .getByRole("list", { name: "Documents" })
    .getByRole("listitem")
    .first();
  await expect(row).toContainText(PDF.name);
  await expect(row).toContainText("Reading pages, 12 of 71 pages");
  await expect(row.getByRole("progressbar")).toBeVisible();
  await expect(row).toContainText("Retrying (2 of 3)");
  await expect(row).toContainText("Ready");
  await expect(row).toContainText("71 pages, 4 tables, 23 images");
  await expectAccessible(page);
});

test("a reload keeps following a document still processing", async ({ page }) => {
  await fakeService(page, []);
  await fakeLibrary(page, PROCESSING);
  await page.goto("/");
  await page.getByLabel("Upload a PDF").setInputFiles(PDF);
  const row = () =>
    page.getByRole("list", { name: "Documents" }).getByRole("listitem").first();
  await expect(row()).toContainText("Reading pages");

  await page.reload();

  await expect(row()).toContainText("Ready");
});

test("a failed document shows its reason and can be uploaded again", async ({
  page,
}) => {
  await fakeService(page, []);
  await fakeLibrary(
    page,
    [{ status: "processing", stage: "extracting", pages_done: 3 }],
    true,
  );
  await page.goto("/");

  await page.getByLabel("Upload a PDF").setInputFiles(PDF);

  const row = page
    .getByRole("list", { name: "Documents" })
    .getByRole("listitem")
    .first();
  await expect(row).toContainText("Failed");
  await expect(row).toContainText("The PDF is damaged and cannot be read.");
  await expect(row.getByRole("button", { name: "Upload again" })).toBeVisible();
});

test("a file that is not a PDF is refused, and content already ingested is reported", async ({
  page,
}) => {
  await fakeService(page, []);
  await fakeLibrary(page, PROCESSING);
  await page.goto("/");

  await page.getByLabel("Upload a PDF").setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("x"),
  });
  await expect(page.getByText("Only PDF files can be uploaded.")).toBeVisible();

  await page.getByLabel("Upload a PDF").setInputFiles(PDF);
  await expect(
    page.getByRole("list", { name: "Documents" }).getByRole("listitem"),
  ).toHaveCount(1);
  await page.getByLabel("Upload a PDF").setInputFiles(PDF);
  await expect(page.getByText(/Already ingested/)).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Documents" }).getByRole("listitem"),
  ).toHaveCount(1);
});

test("the collapsed panel gives the conversation its width and counts what is processing", async ({
  page,
}) => {
  await fakeService(page, []);
  await fakeLibrary(page, [
    { status: "processing", stage: "extracting", pages_done: 12 },
  ]);
  await page.goto("/");
  await page.getByLabel("Upload a PDF").setInputFiles(PDF);
  const input = page.getByRole("textbox", {
    name: "Ask a question about your manuals",
  });
  const openWidth = (await input.boundingBox())!.width;

  await page.getByRole("button", { name: "Hide documents" }).click();

  await expect(page.getByText("1 processing")).toBeVisible();
  await expect
    .poll(async () => (await input.boundingBox())!.width)
    .toBeGreaterThan(openWidth);
  await expectAccessible(page);
});

test("in a window narrower than the layout, the panel stays and 'Upload a manual' reaches it", async ({
  page,
}) => {
  await fakeService(page, [answer("no-information-no-documents")]);
  await page.setViewportSize({ width: 700, height: 800 });
  await page.goto("/");

  await expect(page.getByRole("button", { name: "Hide documents" })).toBeVisible();
  await page.getByRole("button", { name: "Hide documents" }).click();
  await ask(page, "How is a shunt generator wired?");
  await page.getByRole("button", { name: "Upload a manual" }).click();

  await expect(page.getByRole("button", { name: "Upload a PDF" })).toBeFocused();
  await expect(page.getByRole("button", { name: "Upload a PDF" })).toBeVisible();
});

const READY_ID = "9660318f-9004-4fa9-925c-fb616874f516";
const BUSY_ID = "73c717ef-eac1-41a0-9ac9-7665a72f4f5f";

/**
 * A library with a ready and a processing document, whose deletions answer with
 * `deletion` and, when it is 204, remove the document.
 */
async function fakeFinishedLibrary(page: Page, deletion: 204 | 409 = 204) {
  const documents: DocumentBody[] = [
    {
      id: READY_ID,
      file_name: "faa-manual.pdf",
      size_bytes: 8,
      page_count: 3,
      created_at: CREATED,
      latest_job: job(READY_ID, {
        status: "completed",
        pages_done: 3,
        pages_total: 3,
        summary: PROCESSING.at(-1)!.summary!,
      }),
    },
    {
      id: BUSY_ID,
      file_name: "welding-manual.pdf",
      size_bytes: 8,
      page_count: 65,
      created_at: CREATED,
      latest_job: job(BUSY_ID, { status: "processing", stage: "extracting" }),
    },
  ];
  const deleted: string[] = [];
  await page.route(LIBRARY, (route) =>
    route.fulfill({ json: { items: documents, next_cursor: null } }),
  );
  await page.route(`**/api/v1/documents/${BUSY_ID}`, (route) =>
    route.fulfill({ json: documents.find((document) => document.id === BUSY_ID) }),
  );
  await page.route(`**/api/v1/documents/${READY_ID}`, (route) => {
    if (route.request().method() !== "DELETE") return route.fallback();
    if (deletion === 409) {
      return route.fulfill({
        status: 409,
        contentType: "application/problem+json",
        body: JSON.stringify({
          title: "Conflict",
          status: 409,
          instance: `/api/v1/documents/${READY_ID}`,
          code: "ingestion_in_progress",
          request_id: "e2e",
        }),
      });
    }
    deleted.push(READY_ID);
    documents.splice(0, 1);
    return route.fulfill({ status: 204 });
  });
  return { deleted };
}

function documentRow(page: Page, name: string) {
  return page
    .getByRole("list", { name: "Documents" })
    .getByRole("listitem")
    .filter({ hasText: name });
}

test("a ready document opens on its first page and steps to its last", async ({
  page,
}) => {
  await fakeService(page, []);
  await fakeFinishedLibrary(page);
  await page.goto("/");

  await documentRow(page, "faa-manual.pdf")
    .getByRole("button", { name: "View document" })
    .click();

  // The dialog's name follows the page, so it is found by role alone.
  const dialog = page.getByRole("dialog");
  await expect(dialog).toHaveAccessibleName("faa-manual.pdf, page 1");
  await expect(dialog.getByText("Page 1 of 3")).toBeVisible();
  await dialog.getByRole("button", { name: "Next page" }).click();
  await dialog.getByRole("button", { name: "Next page" }).click();
  await expect(dialog).toHaveAccessibleName("faa-manual.pdf, page 3");
  await expect(dialog.getByRole("img")).toHaveAttribute(
    "src",
    `/api/v1/documents/${READY_ID}/pages/3/image`,
  );
  await expect(dialog.getByRole("button", { name: "Next page" })).toBeDisabled();
});

test("a confirmed deletion removes the document, and one being processed offers none", async ({
  page,
}) => {
  await fakeService(page, []);
  const service = await fakeFinishedLibrary(page);
  await page.goto("/");

  await expect(
    documentRow(page, "welding-manual.pdf").getByRole("button", { name: "Delete" }),
  ).toHaveCount(0);
  await documentRow(page, "faa-manual.pdf")
    .getByRole("button", { name: "Delete" })
    .click();
  const confirmation = page.getByRole("alertdialog", {
    name: "Delete faa-manual.pdf?",
  });
  await expectAccessible(page);
  await confirmation.getByRole("button", { name: "Delete document" }).click();

  await expect(confirmation).toBeHidden();
  await expect(documentRow(page, "faa-manual.pdf")).toHaveCount(0);
  expect(service.deleted).toEqual([READY_ID]);
});

test("a refused deletion explains why and keeps the document", async ({ page }) => {
  await fakeService(page, []);
  await fakeFinishedLibrary(page, 409);
  await page.goto("/");

  await documentRow(page, "faa-manual.pdf")
    .getByRole("button", { name: "Delete" })
    .click();
  const confirmation = page.getByRole("alertdialog");
  await confirmation.getByRole("button", { name: "Delete document" }).click();

  await expect(
    confirmation.getByText(
      "This document is being processed. It can be deleted once processing ends.",
    ),
  ).toBeVisible();
  await expect(confirmation.getByText("Reference:")).toBeVisible();
  await expectAccessible(page);
  await confirmation.getByRole("button", { name: "Cancel" }).click();
  await expect(documentRow(page, "faa-manual.pdf")).toHaveCount(1);
});
