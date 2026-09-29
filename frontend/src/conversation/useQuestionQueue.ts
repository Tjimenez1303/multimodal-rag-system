import { useCallback, useEffect, useRef, type Dispatch } from "react";

import { askQuestion } from "@/api/questions";
import { useConfig } from "@/config";
import {
  newTurn,
  type Conversation,
  type ConversationAction,
  type DocumentRef,
  type Turn,
} from "@/conversation/state";
import { toTurnFailure } from "@/failures/messages";

/** The actions the conversation offers on its questions. */
export interface QuestionQueue {
  /** Add a question to the conversation. It is held while another one is answered. */
  submit: (question: string, restriction?: DocumentRef[]) => void;
  /** Cancel the question being answered (FR-007). */
  stop: () => void;
  /** Send a failed or stopped question again, with the same restriction (FR-028). */
  retry: (turnId: string) => void;
  /** Whether a question is being answered, which turns the send button into stop. */
  busy: boolean;
}

/** Options of {@link useQuestionQueue}. */
export interface QuestionQueueOptions {
  /** Puts a question back into the input, for editing after a rejection (FR-029). */
  onReturnQuestion?: (question: string) => void;
}

/**
 * Send the conversation's questions one at a time and record their outcomes (FR-005 to
 * FR-007).
 *
 * The waiting turn is sent with the client wait limit. When no turn waits, the oldest
 * held turn is sent next. Stopping aborts the open request, which nginx forwards to the
 * API as a cancellation.
 *
 * @param conversation - The current conversation.
 * @param dispatch - Its dispatcher.
 * @param options - What to do when a question returns to the input.
 * @returns The queue's actions and whether it is busy.
 */
export function useQuestionQueue(
  conversation: Conversation,
  dispatch: Dispatch<ConversationAction>,
  { onReturnQuestion }: QuestionQueueOptions = {},
): QuestionQueue {
  const { answerWaitSeconds } = useConfig();
  const inFlight = useRef<{ turnId: string; controller: AbortController } | null>(null);
  const returnQuestion = useRef(onReturnQuestion);
  useEffect(() => {
    returnQuestion.current = onReturnQuestion;
  }, [onReturnQuestion]);

  const send = useCallback(
    (turn: Turn) => {
      const controller = new AbortController();
      inFlight.current = { turnId: turn.id, controller };
      askQuestion({
        question: turn.question,
        documentIds: turn.restriction.map((document) => document.id),
        signal: controller.signal,
        waitSeconds: answerWaitSeconds,
      }).then(
        (result) => {
          // A stopped question's late result is not shown.
          if (inFlight.current?.controller !== controller) return;
          inFlight.current = null;
          if (result.ok) {
            dispatch({
              type: "answered",
              turnId: turn.id,
              response: result.data,
              requestId: result.requestId,
            });
            return;
          }
          const failure = toTurnFailure(result.failure);
          dispatch({ type: "failed", turnId: turn.id, failure });
          if (failure.kind === "invalid_question")
            returnQuestion.current?.(turn.question);
        },
        (error: unknown) => {
          // Stopping aborts the request on purpose, and the turn is already stopped.
          if (!(error instanceof DOMException && error.name === "AbortError"))
            throw error;
        },
      );
    },
    [answerWaitSeconds, dispatch],
  );

  useEffect(() => {
    const waiting = conversation.turns.find((turn) => turn.state === "waiting");
    if (waiting !== undefined) {
      if (inFlight.current === null) send(waiting);
      return;
    }
    const held = conversation.turns.find((turn) => turn.state === "held");
    if (held !== undefined && inFlight.current === null) {
      dispatch({ type: "sent", turnId: held.id });
    }
  }, [conversation.turns, dispatch, send]);

  const submit = useCallback(
    (question: string, restriction: DocumentRef[] = []) => {
      dispatch({ type: "submitted", turn: newTurn(question, restriction) });
    },
    [dispatch],
  );

  const stop = useCallback(() => {
    const current = inFlight.current;
    if (current === null) return;
    inFlight.current = null;
    current.controller.abort();
    dispatch({ type: "stopped", turnId: current.turnId, reason: "user" });
  }, [dispatch]);

  const retry = useCallback(
    (turnId: string) => dispatch({ type: "retried", turnId }),
    [dispatch],
  );

  const busy = conversation.turns.some((turn) => turn.state === "waiting");
  return { submit, stop, retry, busy };
}
