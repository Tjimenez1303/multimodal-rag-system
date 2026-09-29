import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";

import type { AnswerBody } from "@/client";
import { ConversationView } from "@/conversation/ConversationView";

import { problem } from "../../tests/msw/handlers";
import { server } from "../../tests/msw/server";
import { renderWithProviders } from "../../tests/render";

function answerFor(question: string): AnswerBody {
  return {
    status: "answered",
    reason: null,
    answer: `Answer to ${question}`,
    not_covered: null,
    citations: [],
    sources: [],
    primary_image: null,
    related_images: [],
  };
}

/** Answers each question when the test releases it, and records what reached it. */
function gatedService() {
  const received: string[] = [];
  const gates = new Map<string, Array<() => void>>();
  server.use(
    http.post("/api/v1/questions", async ({ request }) => {
      const { question } = (await request.clone().json()) as { question: string };
      received.push(question);
      await new Promise<void>((release) =>
        gates.set(question, [...(gates.get(question) ?? []), release]),
      );
      return HttpResponse.json(answerFor(question));
    }),
  );
  return {
    received,
    /** Answer the oldest open request for the question. */
    release: async (question: string) => {
      await waitFor(() => expect(gates.get(question)?.length).toBeGreaterThan(0));
      gates.get(question)!.shift()!();
    },
  };
}

function input(): HTMLElement {
  return screen.getByRole("textbox", { name: "Ask a question about your manuals" });
}

function turn(question: string): HTMLElement {
  return screen.getByRole("article", { name: `Question: ${question}` });
}

test("questions submitted while one is answered are held and sent one at a time", async () => {
  const user = userEvent.setup();
  const service = gatedService();
  renderWithProviders(<ConversationView />);

  await user.type(input(), "first{Enter}");
  await user.type(input(), "second{Enter}");
  await user.type(input(), "third{Enter}");

  expect(within(turn("first")).getByRole("status")).toHaveTextContent(
    "Preparing the answer…",
  );
  expect(turn("second")).toHaveTextContent("Waiting to be sent");
  expect(turn("third")).toHaveTextContent("Waiting to be sent");
  await waitFor(() => expect(service.received).toEqual(["first"]));

  await service.release("first");
  await screen.findByText("Answer to first");
  await waitFor(() => expect(service.received).toEqual(["first", "second"]));
  await service.release("second");
  await screen.findByText("Answer to second");
  await service.release("third");
  await screen.findByText("Answer to third");
  expect(service.received).toEqual(["first", "second", "third"]);
});

test("the send button becomes a stop button that cancels the question", async () => {
  const user = userEvent.setup();
  const service = gatedService();
  renderWithProviders(<ConversationView />);

  await user.type(input(), "slow question{Enter}");
  await user.type(input(), "next question{Enter}");
  await waitFor(() => expect(service.received).toEqual(["slow question"]));
  await user.click(screen.getByRole("button", { name: "Stop" }));

  expect(turn("slow question")).toHaveTextContent("Stopped");
  // The stopped question's late answer is never shown. The network abort itself is
  // asserted in tests/e2e/states-and-failures.spec.ts, since MSW 3 stops forwarding
  // aborts to handlers after earlier requests of the same file.
  await service.release("slow question");
  expect(
    within(turn("slow question")).getByRole("button", { name: "Retry" }),
  ).toBeEnabled();
  await waitFor(() =>
    expect(service.received).toEqual(["slow question", "next question"]),
  );
  await service.release("next question");
  await screen.findByText("Answer to next question");
  expect(screen.queryByText("Answer to slow question")).not.toBeInTheDocument();
  expect(turn("slow question")).toHaveTextContent("Stopped");
  expect(input()).toBeEnabled();
});

test("a retry sends the same question again and replaces the failure in the same turn", async () => {
  const user = userEvent.setup();
  server.use(
    http.post(
      "/api/v1/questions",
      () => problem(503, "answer_model_unavailable", { detail: "down" }),
      { once: true },
    ),
    http.post("/api/v1/questions", async ({ request }) => {
      const { question } = (await request.json()) as { question: string };
      return HttpResponse.json(answerFor(question));
    }),
  );
  renderWithProviders(<ConversationView />);

  await user.type(input(), "flaky question{Enter}");
  const failed = await screen.findByText("The answer model is not responding.");
  expect(failed.closest("article")).toHaveTextContent(/Reference: [0-9a-f-]{36}/);
  await user.click(
    within(turn("flaky question")).getByRole("button", { name: "Retry" }),
  );

  expect(
    await within(turn("flaky question")).findByText("Answer to flaky question"),
  ).toBeVisible();
  expect(
    screen.queryByText("The answer model is not responding."),
  ).not.toBeInTheDocument();
  expect(screen.getAllByRole("article")).toHaveLength(1);
});

test("a question with no answer within the wait limit fails as not answered in time", async () => {
  const user = userEvent.setup();
  server.use(
    http.post("/api/v1/questions", async () => {
      await delay("infinite");
      return HttpResponse.json(answerFor("never"));
    }),
  );
  renderWithProviders(<ConversationView />, { answerWaitSeconds: 1 });

  await user.type(input(), "slow question{Enter}");

  expect(
    await screen.findByText(
      "The service did not answer in time.",
      {},
      { timeout: 3000 },
    ),
  ).toBeVisible();
  expect(
    within(turn("slow question")).getByRole("button", { name: "Retry" }),
  ).toBeEnabled();
});

test("an invalid question shows the reason and returns the text to the input", async () => {
  const user = userEvent.setup();
  server.use(
    http.post("/api/v1/questions", () =>
      problem(400, "invalid_question", {
        detail: "The question is longer than 2000 characters.",
      }),
    ),
  );
  renderWithProviders(<ConversationView />);

  await user.type(input(), "a very long question{Enter}");

  expect(
    await screen.findByText("The question is longer than 2000 characters."),
  ).toBeVisible();
  expect(input()).toHaveValue("a very long question");
  expect(
    within(turn("a very long question")).queryByRole("button", { name: "Retry" }),
  ).not.toBeInTheDocument();
});

test("the busy message says when the question can be retried", async () => {
  const user = userEvent.setup();
  server.use(
    http.post("/api/v1/questions", () =>
      problem(503, "answering_busy", {
        detail: "busy",
        headers: { "Retry-After": "7" },
      }),
    ),
  );
  renderWithProviders(<ConversationView />);

  await user.type(input(), "busy question{Enter}");

  expect(
    await screen.findByText(
      "The system is busy answering other questions. You can retry in 7 seconds.",
    ),
  ).toBeVisible();
});

test("a turn interrupted by a reload says so and can be retried", async () => {
  const user = userEvent.setup();
  const service = gatedService();
  const { unmount } = renderWithProviders(<ConversationView />);
  await user.type(input(), "interrupted question{Enter}");
  await waitFor(() => expect(service.received).toEqual(["interrupted question"]));

  unmount();
  renderWithProviders(<ConversationView />);

  expect(turn("interrupted question")).toHaveTextContent(
    "Interrupted by a page reload",
  );
  await user.click(
    within(turn("interrupted question")).getByRole("button", { name: "Retry" }),
  );
  await waitFor(() =>
    expect(service.received).toEqual(["interrupted question", "interrupted question"]),
  );
  await service.release("interrupted question");
  await service.release("interrupted question");
  expect(await screen.findByText("Answer to interrupted question")).toBeVisible();
});
