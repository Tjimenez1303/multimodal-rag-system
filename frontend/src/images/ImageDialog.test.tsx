import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ImageColumn } from "@/images/ImageColumn";

import { answerWithFigures } from "../../tests/fixtures/answers/sample";

test("the full-size view shows the image with its caption, document and page", async () => {
  const user = userEvent.setup();
  render(<ImageColumn primary={answerWithFigures.primary_image} related={[]} />);

  await user.click(screen.getByRole("button", { name: "View full size" }));

  const dialog = screen.getByRole("dialog", {
    name: "Figure 4-12. Shunt generator circuit",
  });
  expect(within(dialog).getByRole("img")).toHaveAttribute(
    "src",
    answerWithFigures.primary_image!.url,
  );
  expect(dialog).toHaveTextContent(
    "faa-powerplant-ch4-ignition-electrical.pdf, page 12",
  );
});

test("Escape closes the view and returns focus to the opener", async () => {
  const user = userEvent.setup();
  render(<ImageColumn primary={answerWithFigures.primary_image} related={[]} />);
  const opener = screen.getByRole("button", { name: "View full size" });

  await user.click(opener);
  await user.keyboard("{Escape}");

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(opener).toHaveFocus());
});

test("the close button closes the view and returns focus to the opener", async () => {
  const user = userEvent.setup();
  render(<ImageColumn primary={answerWithFigures.primary_image} related={[]} />);
  const opener = screen.getByRole("button", { name: "View full size" });

  await user.click(opener);
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }),
  );

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(opener).toHaveFocus());
});

test("a figure without a caption is titled by its document and page", async () => {
  const user = userEvent.setup();
  render(<ImageColumn primary={answerWithFigures.related_images[0]!} related={[]} />);

  await user.click(screen.getByRole("button", { name: "View full size" }));

  expect(
    screen.getByRole("dialog", {
      name: "Figure without caption",
    }),
  ).toHaveTextContent("faa-powerplant-ch4-ignition-electrical.pdf, page 13");
});
