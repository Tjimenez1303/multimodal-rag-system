import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";

import { DeleteDocumentDialog } from "@/documents/DeleteDocumentDialog";

import { completedDocument } from "../../tests/fixtures/documents/library";
import { problem } from "../../tests/msw/handlers";
import { server } from "../../tests/msw/server";

const URL = `/api/v1/documents/${completedDocument.id}`;

function renderDialog() {
  const deleted: string[] = [];
  render(
    <DeleteDocumentDialog
      document={completedDocument}
      onDeleted={(documentId) => deleted.push(documentId)}
    />,
  );
  return { deleted };
}

function serveDeletion(respond: () => Response | Promise<Response>) {
  let calls = 0;
  server.use(
    http.delete(URL, () => {
      calls += 1;
      return respond();
    }),
  );
  return { calls: () => calls };
}

async function confirmDeletion(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Delete" }));
  const dialog = screen.getByRole("alertdialog");
  await user.click(within(dialog).getByRole("button", { name: "Delete document" }));
  return dialog;
}

test("the confirmation names the document, and a deletion closes it", async () => {
  const user = userEvent.setup();
  const service = serveDeletion(async () => {
    await delay(20);
    return new HttpResponse(null, { status: 204 });
  });
  const { deleted } = renderDialog();

  await user.click(screen.getByRole("button", { name: "Delete" }));
  const dialog = screen.getByRole("alertdialog", {
    name: `Delete ${completedDocument.file_name}?`,
  });
  await user.click(within(dialog).getByRole("button", { name: "Delete document" }));

  expect(within(dialog).getByRole("button", { name: /Deleting/ })).toBeDisabled();
  await waitFor(() => expect(deleted).toEqual([completedDocument.id]));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(service.calls()).toBe(1);
});

test("a document already deleted elsewhere counts as deleted", async () => {
  const user = userEvent.setup();
  serveDeletion(() => problem(404, "document_not_found"));
  const { deleted } = renderDialog();

  await confirmDeletion(user);

  await waitFor(() => expect(deleted).toEqual([completedDocument.id]));
});

test("a document being processed stays, with the reason and its reference", async () => {
  const user = userEvent.setup();
  serveDeletion(() => problem(409, "ingestion_in_progress"));
  const { deleted } = renderDialog();

  const dialog = await confirmDeletion(user);

  expect(
    await within(dialog).findByText(
      "This document is being processed. It can be deleted once processing ends.",
    ),
  ).toBeVisible();
  expect(within(dialog).getByText(/Reference: [0-9a-f-]{36}/)).toBeVisible();
  expect(
    within(dialog).queryByRole("button", { name: "Delete document" }),
  ).not.toBeInTheDocument();
  expect(deleted).toEqual([]);
});

test("a service failure can be deleted again", async () => {
  const user = userEvent.setup();
  let failing = true;
  serveDeletion(() =>
    failing
      ? problem(503, "search_unavailable")
      : new HttpResponse(null, { status: 204 }),
  );
  const { deleted } = renderDialog();

  const dialog = await confirmDeletion(user);
  expect(
    await within(dialog).findByText("The document could not be deleted."),
  ).toBeVisible();

  failing = false;
  await user.click(within(dialog).getByRole("button", { name: "Delete document" }));

  await waitFor(() => expect(deleted).toEqual([completedDocument.id]));
});

test("cancelling sends nothing", async () => {
  const user = userEvent.setup();
  const service = serveDeletion(() => new HttpResponse(null, { status: 204 }));
  renderDialog();

  await user.click(screen.getByRole("button", { name: "Delete" }));
  await user.click(screen.getByRole("button", { name: "Cancel" }));

  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(service.calls()).toBe(0);
  expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus();
});
