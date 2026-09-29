import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";

import type { DocumentBody, UploadAccepted } from "@/client";
import { DocumentPanel } from "@/documents/DocumentPanel";
import { DocumentPanelProvider } from "@/documents/DocumentPanelProvider";
import { PANEL_KEY } from "@/documents/panelState";

import { libraryPage } from "../../tests/fixtures/documents/library";
import { problem } from "../../tests/msw/handlers";
import { server } from "../../tests/msw/server";
import { renderWithProviders } from "../../tests/render";

const NEW_ID = "998496fb-02ce-4d4a-a178-37f0914ce20b";
const newDocument: DocumentBody = {
  id: NEW_ID,
  file_name: "new-manual.pdf",
  size_bytes: 1024,
  page_count: 12,
  created_at: "2026-09-29T09:00:00Z",
  latest_job: null,
};

function renderPanel() {
  return renderWithProviders(
    <DocumentPanelProvider>
      <DocumentPanel />
    </DocumentPanelProvider>,
  );
}

function pdf(name = "new-manual.pdf"): File {
  return new File(["%PDF-1.7"], name, { type: "application/pdf" });
}

/** Serve the library, adding the new document once the upload was accepted. */
function acceptUploads(accepted: Partial<UploadAccepted> = {}) {
  let uploaded = 0;
  server.use(
    http.post("/api/v1/documents", async () => {
      uploaded += 1;
      await delay(20);
      return HttpResponse.json(
        {
          document_id: NEW_ID,
          job_id: "27e7cbe8-7dc9-4866-8f9f-f96bf505a35f",
          status: "pending",
          already_ingested: false,
          ...accepted,
        },
        { status: 202 },
      );
    }),
    http.get("/api/v1/documents", () =>
      HttpResponse.json({
        items: uploaded > 0 ? [newDocument, ...libraryPage.items] : libraryPage.items,
        next_cursor: null,
      }),
    ),
    http.get(`/api/v1/documents/${NEW_ID}`, () => HttpResponse.json(newDocument)),
  );
  return { uploads: () => uploaded };
}

function documentRows() {
  return within(screen.getByRole("list", { name: "Documents" })).getAllByRole(
    "listitem",
  );
}

test("the panel starts open, collapses, and keeps a processing count when collapsed", async () => {
  const user = userEvent.setup();
  renderPanel();
  await waitFor(() => expect(documentRows()).toHaveLength(4));

  await user.click(screen.getByRole("button", { name: "Hide documents" }));

  expect(screen.getByText("2 processing")).toBeVisible();
  expect(JSON.parse(sessionStorage.getItem(PANEL_KEY)!)).toEqual({ collapsed: true });
  await user.click(screen.getByRole("button", { name: "Show documents" }));
  expect(JSON.parse(sessionStorage.getItem(PANEL_KEY)!)).toEqual({ collapsed: false });
});

test("a collapsed panel stays collapsed after a reload", async () => {
  sessionStorage.setItem(PANEL_KEY, JSON.stringify({ collapsed: true }));

  renderPanel();

  expect(await screen.findByRole("button", { name: "Show documents" })).toBeVisible();
});

test("a file that is not a PDF is refused before any request", async () => {
  const user = userEvent.setup({ applyAccept: false });
  const service = acceptUploads();
  renderPanel();

  await user.upload(
    screen.getByLabelText("Upload a PDF"),
    new File(["x"], "notes.txt", { type: "text/plain" }),
  );

  expect(await screen.findByText("Only PDF files can be uploaded.")).toBeVisible();
  expect(service.uploads()).toBe(0);
});

test("an accepted upload shows its transfer, then the document as pending", async () => {
  const user = userEvent.setup();
  acceptUploads();
  renderPanel();
  await waitFor(() => expect(documentRows()).toHaveLength(4));

  await user.upload(screen.getByLabelText("Upload a PDF"), pdf());

  expect(
    await screen.findByRole("progressbar", { name: "Sending new-manual.pdf" }),
  ).toBeInTheDocument();
  await waitFor(() => expect(documentRows()).toHaveLength(5));
  expect(documentRows()[0]).toHaveTextContent("new-manual.pdf");
  expect(documentRows()[0]).toHaveTextContent("Pending");
  await waitFor(() =>
    expect(
      screen.queryByRole("progressbar", { name: "Sending new-manual.pdf" }),
    ).not.toBeInTheDocument(),
  );
});

test("content already ingested is reported as such", async () => {
  const user = userEvent.setup();
  acceptUploads({
    already_ingested: true,
    status: "completed",
    document_id: libraryPage.items[0]!.id,
  });
  renderPanel();

  await user.upload(screen.getByLabelText("Upload a PDF"), pdf("again.pdf"));

  expect(await screen.findByText(/Already ingested/)).toBeVisible();
});

test("a rejected upload shows the service's reason and adds nothing", async () => {
  const user = userEvent.setup();
  server.use(
    http.post("/api/v1/documents", () =>
      problem(413, "file_too_large", { detail: "The file exceeds 200 MB." }),
    ),
  );
  renderPanel();
  await waitFor(() => expect(documentRows()).toHaveLength(4));

  await user.upload(screen.getByLabelText("Upload a PDF"), pdf("huge.pdf"));

  expect(await screen.findByText("The file exceeds 200 MB.")).toBeVisible();
  expect(screen.getByText(/Reference: [0-9a-f-]{36}/)).toBeVisible();
  expect(documentRows()).toHaveLength(4);
});

test("a failed document offers to upload the file again", async () => {
  renderPanel();
  await waitFor(() => expect(documentRows()).toHaveLength(4));

  const failed = documentRows().find((row) =>
    row.textContent?.includes("damaged-manual.pdf"),
  )!;

  expect(within(failed).getByRole("button", { name: "Upload again" })).toBeEnabled();
});

test("the same file uploaded twice at once ends as one document", async () => {
  const user = userEvent.setup();
  acceptUploads();
  renderPanel();
  await waitFor(() => expect(documentRows()).toHaveLength(4));

  await user.upload(screen.getByLabelText("Upload a PDF"), [pdf(), pdf()]);

  await waitFor(() => expect(documentRows()).toHaveLength(5));
  expect(
    documentRows().filter((row) => row.textContent?.includes("new-manual.pdf")),
  ).toHaveLength(1);
});
