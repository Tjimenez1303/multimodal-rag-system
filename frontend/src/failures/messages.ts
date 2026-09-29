import type { ServiceFailure } from "@/api/http";

/** What went wrong with a question, as shown to the user (contracts/client.md section 3). */
export type FailureKind =
  | "invalid_question"
  | "restriction"
  | "rejected"
  | "busy"
  | "answer_model"
  | "search"
  | "deadline"
  | "service"
  | "unreachable"
  | "timed_out"
  | "unreadable";

/**
 * What the user can do about a failed question: send it again, edit it in the input,
 * or nothing, when the question text was already returned to the input.
 */
export type FailureAction = "retry" | "edit" | "none";

/** A failed question as shown under its turn (data-model section 1.3). */
export interface TurnFailure {
  kind: FailureKind;
  message: string;
  action: FailureAction;
  retryable: boolean;
  retryAfterSeconds: number | null;
  reference: string;
}

/** A failed upload as shown next to its file. */
export interface UploadFailure {
  state: "rejected" | "failed";
  message: string;
  /** The upload's `X-Request-ID`, or `null` when the client refused the file itself. */
  reference: string | null;
  action: "upload_again" | "none";
}

const PROBLEM_MESSAGES: Record<string, { kind: FailureKind; message: string }> = {
  answer_model_unavailable: {
    kind: "answer_model",
    message: "The answer model is not responding.",
  },
  answer_model_timeout: {
    kind: "answer_model",
    message: "The answer model took too long to answer.",
  },
  answer_model_invalid_response: {
    kind: "answer_model",
    message: "The answer model could not produce an answer.",
  },
  search_unavailable: { kind: "search", message: "Search is not available right now." },
  search_timeout: { kind: "search", message: "Search took too long to respond." },
  answer_deadline_exceeded: {
    kind: "deadline",
    message: "The question took longer than the time limit.",
  },
};

const RESTRICTION_CODES = new Set(["unknown_documents", "documents_not_ready"]);
const UNREACHABLE = "The service could not be reached.";
const UNREADABLE = "The service sent a response that could not be read.";
const TIMED_OUT = "The service did not answer in time.";

/**
 * Translate a failed question into its plain-English message and action (FR-024).
 *
 * @param failure - The failure of the question's latest attempt.
 * @returns The message, the action offered and the reference to show.
 */
export function toTurnFailure(failure: ServiceFailure): TurnFailure {
  const { kind, message, action, retryAfterSeconds = null } = describe(failure);
  return {
    kind,
    message,
    action,
    retryable: action === "retry",
    retryAfterSeconds,
    reference: failure.requestId,
  };
}

function describe(failure: ServiceFailure): Omit<
  TurnFailure,
  "retryable" | "reference" | "retryAfterSeconds"
> & {
  retryAfterSeconds?: number | null;
} {
  switch (failure.kind) {
    case "unreachable":
      return { kind: "unreachable", message: UNREACHABLE, action: "retry" };
    case "timed_out":
      return { kind: "timed_out", message: TIMED_OUT, action: "retry" };
    case "unreadable":
      return { kind: "unreadable", message: UNREADABLE, action: "retry" };
    case "problem":
      return describeProblem(failure);
  }
}

function describeProblem(
  failure: Extract<ServiceFailure, { kind: "problem" }>,
): ReturnType<typeof describe> {
  const { code, detail, status } = failure;
  if (code === "invalid_question") {
    return { kind: "invalid_question", message: detail ?? "", action: "none" };
  }
  if (RESTRICTION_CODES.has(code)) {
    return { kind: "restriction", message: detail ?? "", action: "edit" };
  }
  if (code === "answering_busy") {
    const wait =
      failure.retryAfterSeconds === null
        ? "a few seconds"
        : `${failure.retryAfterSeconds} seconds`;
    return {
      kind: "busy",
      message: `The system is busy answering other questions. You can retry in ${wait}.`,
      action: "retry",
      retryAfterSeconds: failure.retryAfterSeconds,
    };
  }
  const known = PROBLEM_MESSAGES[code];
  if (known !== undefined) return { ...known, action: "retry" };
  if (status < 500) {
    const message = ["The question could not be sent.", detail]
      .filter(Boolean)
      .join(" ");
    return { kind: "rejected", message, action: "retry" };
  }
  return {
    kind: "service",
    message: "Something went wrong on the service.",
    action: "retry",
  };
}

/** A failed deletion as shown in its confirmation (FR-049). */
export interface DeletionFailure {
  message: string;
  reference: string;
  /** Whether "Delete document" is offered again. */
  retryable: boolean;
}

/**
 * Translate a failed deletion into its message (contracts/client.md section 3).
 *
 * @param failure - The failure of the deletion.
 * @returns The message and whether the deletion can be asked for again, or `null`
 *   when the document no longer exists, which is what the user asked for.
 */
export function toDeletionFailure(failure: ServiceFailure): DeletionFailure | null {
  const reference = failure.requestId;
  switch (failure.kind) {
    case "unreachable":
      return { message: UNREACHABLE, reference, retryable: true };
    case "timed_out":
      return { message: TIMED_OUT, reference, retryable: true };
    case "unreadable":
      return { message: UNREADABLE, reference, retryable: true };
    case "problem":
      break;
  }
  if (failure.code === "document_not_found") return null;
  if (failure.code === "ingestion_in_progress") {
    return {
      message:
        "This document is being processed. It can be deleted once processing ends.",
      reference,
      retryable: false,
    };
  }
  const detail = failure.status < 500 ? failure.detail : null;
  const message = ["The document could not be deleted.", detail]
    .filter(Boolean)
    .join(" ");
  return { message, reference, retryable: true };
}

/** The client's own refusal of a file that is not a PDF (FR-032). */
export const NOT_A_PDF: UploadFailure = {
  state: "rejected",
  message: "Only PDF files can be uploaded.",
  reference: null,
  action: "none",
};

/**
 * Translate a failed upload into its message and action (FR-036, FR-037).
 *
 * @param failure - The failure of the upload.
 * @returns Whether the service rejected the file or the upload failed, with the message.
 */
export function toUploadFailure(failure: ServiceFailure): UploadFailure {
  const reference = failure.requestId;
  if (failure.kind === "problem" && failure.status < 500) {
    return {
      state: "rejected",
      message: failure.detail ?? "The service rejected the file.",
      reference,
      action: "none",
    };
  }
  const message =
    failure.kind === "problem"
      ? "The file could not be stored."
      : failure.kind === "unreadable"
        ? UNREADABLE
        : UNREACHABLE;
  return { state: "failed", message, reference, action: "upload_again" };
}
