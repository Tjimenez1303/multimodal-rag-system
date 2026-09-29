import type { Problem } from "@/client";

/** A problem response the question route can answer, as the service writes it. */
export interface QuestionFailureFixture {
  name: string;
  status: number;
  body: Problem;
  retryAfter?: string;
  /** The plain-English message the client shows (contracts/client.md section 3). */
  message: string;
  retryable: boolean;
}

function problem(status: number, code: string, detail: string): Problem {
  return {
    type: "about:blank",
    title: "Problem",
    status,
    detail,
    instance: "/api/v1/questions",
    code,
    request_id: "service-request-id",
  };
}

/** Every question failure code of contracts/client.md section 3. */
export const questionFailures: QuestionFailureFixture[] = [
  {
    name: "invalid question",
    status: 400,
    body: problem(
      400,
      "invalid_question",
      "The question is longer than 2000 characters.",
    ),
    message: "The question is longer than 2000 characters.",
    retryable: false,
  },
  {
    name: "unknown documents",
    status: 400,
    body: problem(400, "unknown_documents", "These documents do not exist: a.pdf."),
    message: "These documents do not exist: a.pdf.",
    retryable: false,
  },
  {
    name: "documents not ready",
    status: 409,
    body: problem(409, "documents_not_ready", "These documents are not ready: b.pdf."),
    message: "These documents are not ready: b.pdf.",
    retryable: false,
  },
  {
    name: "invalid request",
    status: 400,
    body: problem(400, "invalid_request", "Invalid or missing fields: body.question"),
    message: "The question could not be sent. Invalid or missing fields: body.question",
    retryable: true,
  },
  {
    name: "busy",
    status: 503,
    body: problem(503, "answering_busy", "Too many questions are being answered."),
    retryAfter: "7",
    message:
      "The system is busy answering other questions. You can retry in 7 seconds.",
    retryable: true,
  },
  {
    name: "answer model unavailable",
    status: 503,
    body: problem(503, "answer_model_unavailable", "The answer model is unavailable."),
    message: "The answer model is not responding.",
    retryable: true,
  },
  {
    name: "answer model timeout",
    status: 504,
    body: problem(504, "answer_model_timeout", "The answer model timed out."),
    message: "The answer model took too long to answer.",
    retryable: true,
  },
  {
    name: "answer model invalid response",
    status: 502,
    body: problem(502, "answer_model_invalid_response", "The answer model failed."),
    message: "The answer model could not produce an answer.",
    retryable: true,
  },
  {
    name: "search unavailable",
    status: 503,
    body: problem(503, "search_unavailable", "Search is unavailable."),
    message: "Search is not available right now.",
    retryable: true,
  },
  {
    name: "search timeout",
    status: 504,
    body: problem(504, "search_timeout", "Search timed out."),
    message: "Search took too long to respond.",
    retryable: true,
  },
  {
    name: "answer deadline exceeded",
    status: 504,
    body: problem(504, "answer_deadline_exceeded", "The question took too long."),
    message: "The question took longer than the time limit.",
    retryable: true,
  },
  {
    name: "internal error",
    status: 500,
    body: problem(500, "internal_error", "Internal error."),
    message: "Something went wrong on the service.",
    retryable: true,
  },
];
