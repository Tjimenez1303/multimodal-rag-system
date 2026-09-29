import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { NoInformationState } from "@/answer/NoInformationState";
import type { AnswerBody, NotEnoughReason } from "@/client";

function noInformation(reason: NotEnoughReason): AnswerBody {
  return {
    status: "not_enough_information",
    reason,
    answer: "The documents do not contain enough information to answer this question.",
    not_covered: null,
    citations: [],
    sources: [],
    primary_image: null,
    related_images: [],
  };
}

test("it is labeled and styled apart from an answer, with no sources or images", () => {
  const { container } = render(
    <NoInformationState
      response={noInformation("no_relevant_content")}
      restricted={false}
    />,
  );

  const state = screen.getByRole("region", { name: "No information found" });
  expect(state).toHaveAttribute("data-state", "no-information");
  expect(state).toHaveTextContent(
    "The documents do not contain enough information to answer this question.",
  );
  expect(screen.queryByRole("list", { name: "Sources" })).not.toBeInTheDocument();
  expect(container.querySelector("img")).toBeNull();
});

test.each([
  "no_relevant_content",
  "not_answered_by_sources",
  "no_valid_citations",
] as const)("an unrestricted %s reply suggests rephrasing", (reason) => {
  render(<NoInformationState response={noInformation(reason)} restricted={false} />);

  expect(
    screen.getByRole("region", { name: "No information found" }),
  ).toHaveTextContent(/rephras/i);
});

test("with no searchable documents it offers to upload a manual", async () => {
  const user = userEvent.setup();
  let requested = 0;
  render(
    <NoInformationState
      response={noInformation("no_searchable_documents")}
      restricted={false}
      onRequestUpload={() => (requested += 1)}
    />,
  );

  await user.click(screen.getByRole("button", { name: "Upload a manual" }));

  expect(requested).toBe(1);
  expect(
    screen.getByRole("region", { name: "No information found" }),
  ).toHaveTextContent(/no manual is ready/i);
});

test("a restricted question offers to ask across all documents", async () => {
  const user = userEvent.setup();
  let asked = 0;
  render(
    <NoInformationState
      response={noInformation("no_relevant_content")}
      restricted
      onAskAcrossAll={() => (asked += 1)}
    />,
  );

  expect(
    screen.getByRole("region", { name: "No information found" }),
  ).toHaveTextContent(/selected documents/i);
  await user.click(screen.getByRole("button", { name: "Ask across all documents" }));

  expect(asked).toBe(1);
});
