import {
  conversationReducer,
  emptyConversation,
  newTurn,
  type Conversation,
} from "@/conversation/state";

import { answerWithFigures } from "../../tests/fixtures/answers/sample";

test("submitting adds a waiting turn with the trimmed question and no restriction", () => {
  const turn = newTurn("  How is a shunt generator wired?\n");

  const next = conversationReducer(emptyConversation, { type: "submitted", turn });

  expect(next.turns).toEqual([
    {
      id: turn.id,
      question: "How is a shunt generator wired?",
      restriction: [],
      state: "waiting",
      requestId: null,
      response: null,
      failure: null,
      stopReason: null,
    },
  ]);
});

test("an answered response moves the turn to answered and is stored unchanged", () => {
  const turn = newTurn("How is a shunt generator wired?");
  const waiting = conversationReducer(emptyConversation, { type: "submitted", turn });

  const next = conversationReducer(waiting, {
    type: "answered",
    turnId: turn.id,
    response: answerWithFigures,
    requestId: "req-1",
  });

  expect(next.turns[0]).toMatchObject({ state: "answered", requestId: "req-1" });
  expect(next.turns[0]!.response).toBe(answerWithFigures);
});

test("a new conversation clears the turns", () => {
  const turn = newTurn("Question");
  const withTurn = conversationReducer(emptyConversation, { type: "submitted", turn });

  expect(conversationReducer(withTurn, { type: "cleared" }).turns).toEqual([]);
});

test("each turn gets its own id", () => {
  expect(newTurn("a").id).not.toBe(newTurn("a").id);
});

describe("turn transitions (data-model section 1.2)", () => {
  const failure = {
    kind: "answer_model",
    message: "The answer model is not responding.",
    action: "retry",
    retryable: true,
    retryAfterSeconds: null,
    reference: "req-9",
  } as const;

  function submit(conversation: Conversation, question: string) {
    const turn = newTurn(question);
    return {
      turn,
      next: conversationReducer(conversation, { type: "submitted", turn }),
    };
  }

  function states(conversation: Conversation) {
    return conversation.turns.map((turn) => turn.state);
  }

  test("a question submitted while another waits is held, and is sent when the queue reaches it", () => {
    const first = submit(emptyConversation, "first");
    const second = submit(first.next, "second");

    expect(states(second.next)).toEqual(["waiting", "held"]);
    expect(second.next.turns[1]!.requestId).toBeNull();

    const answered = conversationReducer(second.next, {
      type: "answered",
      turnId: first.turn.id,
      response: answerWithFigures,
      requestId: "req-1",
    });
    const sent = conversationReducer(answered, {
      type: "sent",
      turnId: second.turn.id,
    });
    expect(states(sent)).toEqual(["answered", "waiting"]);
  });

  test("a question submitted while another is held is held too", () => {
    const first = submit(emptyConversation, "first");
    const held = submit(first.next, "second");
    const third = submit(held.next, "third");

    expect(states(third.next)).toEqual(["waiting", "held", "held"]);
  });

  test("a not-enough-information response moves the turn to no_information", () => {
    const { turn, next } = submit(emptyConversation, "bicycle");
    const response = {
      ...answerWithFigures,
      status: "not_enough_information" as const,
    };

    const after = conversationReducer(next, {
      type: "answered",
      turnId: turn.id,
      response,
      requestId: "req-2",
    });

    expect(after.turns[0]).toMatchObject({
      state: "no_information",
      requestId: "req-2",
    });
    expect(after.turns[0]!.response).toBe(response);
  });

  test("a failure moves the waiting turn to failed with its reference", () => {
    const { turn, next } = submit(emptyConversation, "question");

    const after = conversationReducer(next, {
      type: "failed",
      turnId: turn.id,
      failure,
    });

    expect(after.turns[0]).toMatchObject({
      state: "failed",
      failure,
      requestId: "req-9",
    });
  });

  test.each(["user", "reload"] as const)(
    "a waiting turn can be stopped (%s)",
    (reason) => {
      const { turn, next } = submit(emptyConversation, "question");

      const after = conversationReducer(next, {
        type: "stopped",
        turnId: turn.id,
        reason,
      });

      expect(after.turns[0]).toMatchObject({ state: "stopped", stopReason: reason });
    },
  );

  test.each(["failed", "stopped"] as const)(
    "a %s turn goes back to held on retry, keeping its question and restriction",
    (from) => {
      const { turn, next } = submit(emptyConversation, "question");
      const ended =
        from === "failed"
          ? conversationReducer(next, { type: "failed", turnId: turn.id, failure })
          : conversationReducer(next, {
              type: "stopped",
              turnId: turn.id,
              reason: "user",
            });

      const retried = conversationReducer(ended, { type: "retried", turnId: turn.id });

      expect(retried.turns[0]).toMatchObject({
        id: turn.id,
        question: "question",
        restriction: [],
        state: "held",
        requestId: null,
        failure: null,
        stopReason: null,
      });
    },
  );

  test("at most one turn is waiting, whatever the order of events", () => {
    let conversation = emptyConversation;
    const turns = ["a", "b", "c"].map((question) => {
      const result = submit(conversation, question);
      conversation = result.next;
      return result.turn;
    });
    conversation = conversationReducer(conversation, {
      type: "stopped",
      turnId: turns[0]!.id,
      reason: "user",
    });
    conversation = conversationReducer(conversation, {
      type: "retried",
      turnId: turns[0]!.id,
    });
    conversation = conversationReducer(conversation, {
      type: "sent",
      turnId: turns[1]!.id,
    });
    // A second "sent" while one turn waits is ignored.
    conversation = conversationReducer(conversation, {
      type: "sent",
      turnId: turns[2]!.id,
    });

    expect(states(conversation).filter((state) => state === "waiting")).toHaveLength(1);
  });
});
