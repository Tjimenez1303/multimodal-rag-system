import { expect, test, type Page } from "@playwright/test";

import type { DocumentBody, JobBody } from "../../src/client/types.gen.ts";
import { expectAccessible, fakeService, LIBRARY } from "./fakes.ts";

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
