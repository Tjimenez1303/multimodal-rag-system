import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { ConversationView } from "@/conversation/ConversationView";

import {
  answerWithFigures,
  answerWithoutImages,
} from "../../tests/fixtures/answers/sample";
import { plainAnswer } from "../../tests/msw/handlers";
import { server } from "../../tests/msw/server";
import { renderWithProviders } from "../../tests/render";
import { fillSessionStorage } from "../../tests/storage";

function input(): HTMLElement {
  return screen.getByRole("textbox", { name: "Ask a question about your manuals" });
}

function turns(): HTMLElement[] {
  return screen.queryAllByRole("article");
}

test("Enter sends the question, and Shift+Enter inserts a new line", async () => {
  const user = userEvent.setup();
  renderWithProviders(<ConversationView />);

  await user.type(input(), "How do I check{Shift>}{Enter}{/Shift}the leads?");
  expect(input()).toHaveValue("How do I check\nthe leads?");
  await user.keyboard("{Enter}");

  expect(await screen.findByText(/Check the ignition leads/)).toBeInTheDocument();
  expect(turns()[0]).toHaveTextContent("How do I check the leads?");
  expect(input()).toHaveValue("");
});

test("an empty or blank question cannot be sent", async () => {
  const user = userEvent.setup();
  renderWithProviders(<ConversationView />);
  const send = screen.getByRole("button", { name: "Send question" });

  expect(send).toBeDisabled();
  await user.type(input(), "   ");
  expect(send).toBeDisabled();
  await user.keyboard("{Enter}");
  expect(turns()).toHaveLength(0);
});

test("the question appears, then its answer, and earlier turns stay in order", async () => {
  const user = userEvent.setup();
  renderWithProviders(<ConversationView />);

  await user.type(input(), "First question{Enter}");
  expect(await screen.findByText(/Check the ignition leads/)).toBeInTheDocument();
  server.use(
    http.post("/api/v1/questions", () => HttpResponse.json(answerWithoutImages)),
  );
  await user.type(input(), "Second question{Enter}");

  expect(await screen.findByText(/connected/)).toBeInTheDocument();
  const [first, second] = turns();
  expect(first).toHaveTextContent("First question");
  expect(first).toHaveTextContent(/Check the ignition leads/);
  expect(second).toHaveTextContent("Second question");
});

test("a new conversation asks for confirmation before clearing", async () => {
  const user = userEvent.setup();
  renderWithProviders(<ConversationView />);
  await user.type(input(), "First question{Enter}");
  await screen.findByText(/Check the ignition leads/);

  await user.click(screen.getByRole("button", { name: "New conversation" }));
  const confirm = screen.getByRole("alertdialog", {
    name: "Start a new conversation?",
  });
  await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
  expect(turns()).toHaveLength(1);

  await user.click(screen.getByRole("button", { name: "New conversation" }));
  await user.click(screen.getByRole("button", { name: "Clear conversation" }));
  expect(turns()).toHaveLength(0);
});

test("an answer with a primary image lays out the text and the image column side by side", async () => {
  const user = userEvent.setup();
  server.use(
    http.post("/api/v1/questions", () => HttpResponse.json(answerWithFigures)),
  );
  renderWithProviders(<ConversationView />);

  await user.type(input(), "How is a shunt generator wired?{Enter}");

  const answer = await screen.findByRole("region", { name: "Answer" });
  expect(answer).toHaveAttribute("data-layout", "with-images");
  expect(
    within(answer).getByRole("complementary", { name: "Figures" }),
  ).toBeInTheDocument();
});

test("an answer without images uses the full width", async () => {
  const user = userEvent.setup();
  renderWithProviders(<ConversationView />);

  await user.type(input(), "How do I check the leads?{Enter}");

  const answer = await screen.findByRole("region", { name: "Answer" });
  expect(answer).toHaveAttribute("data-layout", "text-only");
  expect(within(answer).queryByRole("complementary")).not.toBeInTheDocument();
  expect(plainAnswer.primary_image).toBeNull();
});

test("the conversation survives a remount, as after a reload of the tab", async () => {
  const user = userEvent.setup();
  const { unmount } = renderWithProviders(<ConversationView />);
  await user.type(input(), "First question{Enter}");
  await screen.findByText(/Check the ignition leads/);

  unmount();
  renderWithProviders(<ConversationView />);

  expect(turns()[0]).toHaveTextContent("First question");
  expect(turns()[0]).toHaveTextContent(/Check the ignition leads/);
});

test("a full storage shows that the conversation will not survive a reload", async () => {
  const user = userEvent.setup();
  fillSessionStorage();
  renderWithProviders(<ConversationView />);

  await user.type(input(), "First question{Enter}");
  await screen.findByText(/Check the ignition leads/);

  expect(screen.getByRole("status")).toHaveTextContent(
    "This conversation won't survive a reload",
  );
});
