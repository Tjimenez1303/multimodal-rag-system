import { callService, type ServiceResult } from "@/api/http";
import { askQuestion as askQuestionOperation, type AnswerBody } from "@/client";

/** What {@link askQuestion} sends. */
export interface QuestionRequest {
  question: string;
  /** Ids of the documents the question is restricted to. Empty for all documents. */
  documentIds: readonly string[];
  /** Aborts the question, as the stop button does. */
  signal?: AbortSignal;
  /** Client wait limit, above the service's own deadline (FR-027). */
  waitSeconds: number;
}

/**
 * Send one question to the service, without earlier turns (FR-005).
 *
 * @param request - The question, its restriction, the stop signal and the wait limit.
 * @returns The answer, or the failure. A wait limit reached is `timed_out`.
 * @throws {DOMException} `AbortError` when `signal` aborts the question.
 */
export function askQuestion({
  question,
  documentIds,
  signal,
  waitSeconds,
}: QuestionRequest): Promise<ServiceResult<AnswerBody>> {
  return callService(
    (options) =>
      askQuestionOperation({
        ...options,
        body: {
          question,
          ...(documentIds.length > 0 ? { document_ids: [...documentIds] } : {}),
        },
      }),
    { ...(signal === undefined ? {} : { signal }), timeoutSeconds: waitSeconds },
  );
}
