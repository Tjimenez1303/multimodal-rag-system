import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { FailureNotice } from "@/failures/FailureNotice";

const REFERENCE = "3f1c2d7e-1111-4222-8333-444455556666";

test("it shows the message and the reference below it", () => {
  render(
    <FailureNotice
      message="The answer model is not responding."
      reference={REFERENCE}
    />,
  );

  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent("The answer model is not responding.");
  expect(alert).toHaveTextContent(`Reference: ${REFERENCE}`);
});

test("the reference can be copied", async () => {
  const user = userEvent.setup();
  render(
    <FailureNotice message="The service could not be reached." reference={REFERENCE} />,
  );

  await user.click(screen.getByRole("button", { name: "Copy reference" }));

  await expect(navigator.clipboard.readText()).resolves.toBe(REFERENCE);
  expect(screen.getByRole("button", { name: "Copy reference" })).toHaveTextContent(
    "Copied",
  );
});

test("the action button is rendered only when an action is given", async () => {
  const user = userEvent.setup();
  const { rerender } = render(
    <FailureNotice message="The question is too long." reference={REFERENCE} />,
  );
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();

  let retried = 0;
  rerender(
    <FailureNotice
      message="The service did not answer in time."
      reference={REFERENCE}
      action={{ label: "Retry", onAction: () => (retried += 1) }}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Retry" }));

  expect(retried).toBe(1);
});

test("a failure without a reference shows no reference line", () => {
  render(<FailureNotice message="Only PDF files can be uploaded." reference={null} />);

  expect(screen.getByRole("alert")).not.toHaveTextContent("Reference");
  expect(
    screen.queryByRole("button", { name: "Copy reference" }),
  ).not.toBeInTheDocument();
});
