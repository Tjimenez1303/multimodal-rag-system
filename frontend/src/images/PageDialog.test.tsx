import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PageDialog } from "@/images/PageDialog";

const DOCUMENT_ID = "9660318f-9004-4fa9-925c-fb616874f516";
const NAME = "faa-powerplant-ch4-ignition-electrical.pdf";

function pageUrl(page: number): string {
  return `/api/v1/documents/${DOCUMENT_ID}/pages/${page}/image`;
}

function Opener({ pages, initialPage }: { pages: number[]; initialPage?: number }) {
  return (
    <PageDialog
      trigger={<button type="button">Open page</button>}
      documentId={DOCUMENT_ID}
      documentName={NAME}
      pages={pages}
      {...(initialPage === undefined ? {} : { initialPage })}
    />
  );
}

test("it shows the rendered page with the document name and page number", async () => {
  const user = userEvent.setup();
  render(<Opener pages={[12]} />);

  await user.click(screen.getByRole("button", { name: "Open page" }));

  const dialog = screen.getByRole("dialog", { name: `${NAME}, page 12` });
  expect(within(dialog).getByRole("img")).toHaveAttribute("src", pageUrl(12));
  expect(
    within(dialog).queryByRole("button", { name: "Next page" }),
  ).not.toBeInTheDocument();
});

test("a multi-page source steps only between its own pages", async () => {
  const user = userEvent.setup();
  render(<Opener pages={[13, 12]} />);

  await user.click(screen.getByRole("button", { name: "Open page" }));
  const dialog = screen.getByRole("dialog");
  const previous = within(dialog).getByRole("button", { name: "Previous page" });
  const next = within(dialog).getByRole("button", { name: "Next page" });

  expect(dialog).toHaveAccessibleName(`${NAME}, page 12`);
  expect(previous).toBeDisabled();
  await user.click(next);
  expect(dialog).toHaveAccessibleName(`${NAME}, page 13`);
  expect(within(dialog).getByRole("img")).toHaveAttribute("src", pageUrl(13));
  expect(next).toBeDisabled();
  await user.click(previous);
  expect(dialog).toHaveAccessibleName(`${NAME}, page 12`);
});

test("it can open on a given page of the source", async () => {
  const user = userEvent.setup();
  render(<Opener pages={[3, 4, 9]} initialPage={9} />);

  await user.click(screen.getByRole("button", { name: "Open page" }));

  expect(screen.getByRole("dialog")).toHaveAccessibleName(`${NAME}, page 9`);
});

test("a page that cannot be loaded says so and keeps its document and page", async () => {
  const user = userEvent.setup();
  render(<Opener pages={[12]} />);
  await user.click(screen.getByRole("button", { name: "Open page" }));
  const dialog = screen.getByRole("dialog");

  fireEvent.error(within(dialog).getByRole("img"));

  expect(dialog).toHaveTextContent("Page unavailable");
  expect(dialog).toHaveTextContent(`${NAME}, page 12`);
});

test("Escape closes the page view and returns focus to the opener", async () => {
  const user = userEvent.setup();
  render(<Opener pages={[12]} />);
  const opener = screen.getByRole("button", { name: "Open page" });

  await user.click(opener);
  await user.keyboard("{Escape}");

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(opener).toHaveFocus());
});
