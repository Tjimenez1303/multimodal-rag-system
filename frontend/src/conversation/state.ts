import type { AnswerBody } from "@/client";
import type { TurnFailure } from "@/failures/messages";

/** Where a turn is in its life (data-model section 1.2). */
export type TurnState =
  "held" | "waiting" | "answered" | "no_information" | "stopped" | "failed";

/** A document a question was restricted to, kept with its name. */
export interface DocumentRef {
  id: string;
  fileName: string;
}

/** One question and its outcome (data-model section 1.2). */
export interface Turn {
  id: string;
  question: string;
  /** Snapshot of the selection when submitted. Empty means all documents. */
  restriction: DocumentRef[];
  state: TurnState;
  /** `X-Request-ID` of the latest attempt, `null` until an attempt ends. */
  requestId: string | null;
  /** The service's body exactly as returned (FR-022). */
  response: AnswerBody | null;
  failure: TurnFailure | null;
  stopReason: "user" | "reload" | null;
}

/** The ordered turns of the current tab (data-model section 1.1). */
export interface Conversation {
  version: 1;
  turns: Turn[];
}

/** Changes to the conversation. */
export type ConversationAction =
  /** A new question: waiting when the queue is free, held otherwise. */
  | { type: "submitted"; turn: Turn }
  /** The queue reached a held turn and sends it. */
  | { type: "sent"; turnId: string }
  /** The service answered, with an answer or not enough information. */
  | { type: "answered"; turnId: string; response: AnswerBody; requestId: string }
  | { type: "failed"; turnId: string; failure: TurnFailure }
  | { type: "stopped"; turnId: string; reason: "user" | "reload" }
  /** A failed or stopped turn goes back to the queue. */
  | { type: "retried"; turnId: string }
  | { type: "cleared" };

/** A conversation without turns. */
export const emptyConversation: Conversation = { version: 1, turns: [] };

/**
 * Create a turn for a question, before it is submitted.
 *
 * @param question - The question as typed. It is trimmed.
 * @param restriction - The selected documents, empty for all documents.
 * @returns The new turn, waiting for its answer.
 */
export function newTurn(question: string, restriction: DocumentRef[] = []): Turn {
  return {
    id: crypto.randomUUID(),
    question: question.trim(),
    restriction,
    state: "waiting",
    requestId: null,
    response: null,
    failure: null,
    stopReason: null,
  };
}

/**
 * Apply an action to the conversation.
 *
 * @param conversation - The current conversation.
 * @param action - What happened.
 * @returns The next conversation. Turns not named by the action are unchanged.
 */
export function conversationReducer(
  conversation: Conversation,
  action: ConversationAction,
): Conversation {
  switch (action.type) {
    case "submitted": {
      // A new turn waits only when no other turn is waiting or held
      const busy = conversation.turns.some(
        (turn) => turn.state === "waiting" || turn.state === "held",
      );
      const turn = { ...action.turn, state: busy ? "held" : "waiting" } as const;
      return { ...conversation, turns: [...conversation.turns, turn] };
    }
    case "sent":
      // At most one turn waits at a time (FR-006).
      if (conversation.turns.some((turn) => turn.state === "waiting"))
        return conversation;
      return updateTurn(conversation, action.turnId, { state: "waiting" }, ["held"]);
    case "answered":
      // Store the answer; a not-enough-information reply gets its own state
      return updateTurn(
        conversation,
        action.turnId,
        {
          state: action.response.status === "answered" ? "answered" : "no_information",
          response: action.response,
          requestId: action.requestId,
        },
        ["waiting"],
      );
    case "failed":
      // Keep the failure and the reference the user can quote
      return updateTurn(
        conversation,
        action.turnId,
        {
          state: "failed",
          failure: action.failure,
          requestId: action.failure.reference,
        },
        ["waiting"],
      );
    case "stopped":
      return updateTurn(
        conversation,
        action.turnId,
        { state: "stopped", stopReason: action.reason },
        ["waiting"],
      );
    case "retried":
      // Put the turn back in the queue with its old outcome cleared
      return updateTurn(
        conversation,
        action.turnId,
        {
          state: "held",
          requestId: null,
          response: null,
          failure: null,
          stopReason: null,
        },
        ["failed", "stopped"],
      );
    case "cleared":
      return emptyConversation;
  }
}

// Applies the changes only when the turn is in one of the states the event leaves
// from, so a late or repeated event never overwrites a newer outcome.
function updateTurn(
  conversation: Conversation,
  turnId: string,
  changes: Partial<Turn>,
  from: readonly TurnState[],
): Conversation {
  return {
    ...conversation,
    turns: conversation.turns.map((turn) =>
      turn.id === turnId && from.includes(turn.state) ? { ...turn, ...changes } : turn,
    ),
  };
}
