import type { ServiceFailure } from "@/api/http";
import { NOT_A_PDF, toTurnFailure, toUploadFailure } from "@/failures/messages";

const ID = "3f1c2d7e-1111-4222-8333-444455556666";

function problem(
  status: number,
  code: string,
  detail: string | null = null,
  retryAfterSeconds: number | null = null,
): ServiceFailure {
  return { kind: "problem", status, code, detail, requestId: ID, retryAfterSeconds };
}

describe("question failures (contracts/client.md section 3)", () => {
  test.each([
    [
      problem(400, "invalid_question", "The question is longer than 2000 characters."),
      "invalid_question",
      "The question is longer than 2000 characters.",
      "none",
    ],
    [
      problem(400, "unknown_documents", "Unknown documents: a.pdf."),
      "restriction",
      "Unknown documents: a.pdf.",
      "edit",
    ],
    [
      problem(409, "documents_not_ready", "Not ready: b.pdf."),
      "restriction",
      "Not ready: b.pdf.",
      "edit",
    ],
    [
      problem(400, "invalid_request", "Invalid or missing fields: body.question"),
      "rejected",
      "The question could not be sent. Invalid or missing fields: body.question",
      "retry",
    ],
    [
      problem(413, "payload_too_large"),
      "rejected",
      "The question could not be sent.",
      "retry",
    ],
    [
      problem(503, "answering_busy", "Busy.", 7),
      "busy",
      "The system is busy answering other questions. You can retry in 7 seconds.",
      "retry",
    ],
    [
      problem(503, "answer_model_unavailable", "The answer model is unavailable."),
      "answer_model",
      "The answer model is not responding.",
      "retry",
    ],
    [
      problem(504, "answer_model_timeout"),
      "answer_model",
      "The answer model took too long to answer.",
      "retry",
    ],
    [
      problem(502, "answer_model_invalid_response"),
      "answer_model",
      "The answer model could not produce an answer.",
      "retry",
    ],
    [
      problem(503, "search_unavailable"),
      "search",
      "Search is not available right now.",
      "retry",
    ],
    [
      problem(504, "search_timeout"),
      "search",
      "Search took too long to respond.",
      "retry",
    ],
    [
      problem(504, "answer_deadline_exceeded"),
      "deadline",
      "The question took longer than the time limit.",
      "retry",
    ],
    [
      problem(500, "internal_error"),
      "service",
      "Something went wrong on the service.",
      "retry",
    ],
    [
      { kind: "unreachable", requestId: ID } as const,
      "unreachable",
      "The service could not be reached.",
      "retry",
    ],
    [
      { kind: "timed_out", requestId: ID } as const,
      "timed_out",
      "The service did not answer in time.",
      "retry",
    ],
    [
      { kind: "unreadable", requestId: ID } as const,
      "unreadable",
      "The service sent a response that could not be read.",
      "retry",
    ],
  ])("%o maps to %s", (failure, kind, message, action) => {
    const turnFailure = toTurnFailure(failure);

    expect(turnFailure).toMatchObject({ kind, message, action, reference: ID });
    expect(turnFailure.retryable).toBe(action === "retry");
  });

  test("the busy failure keeps the Retry-After seconds", () => {
    expect(
      toTurnFailure(problem(503, "answering_busy", null, 7)).retryAfterSeconds,
    ).toBe(7);
    expect(
      toTurnFailure(problem(503, "search_unavailable")).retryAfterSeconds,
    ).toBeNull();
  });

  test("a busy failure without Retry-After still says it can be retried", () => {
    expect(toTurnFailure(problem(503, "answering_busy")).message).toBe(
      "The system is busy answering other questions. You can retry in a few seconds.",
    );
  });

  test("messages never carry the status or the code", () => {
    const failure = toTurnFailure(problem(503, "search_unavailable", "qdrant down"));

    expect(failure.message).not.toMatch(/503|search_unavailable|qdrant/);
  });
});

describe("upload failures (contracts/client.md section 3)", () => {
  test.each([
    [
      problem(400, "invalid_file_name", "The file name is empty."),
      "The file name is empty.",
    ],
    [
      problem(413, "file_too_large", "The file exceeds 200 MB."),
      "The file exceeds 200 MB.",
    ],
    [
      problem(415, "unsupported_media_type", "The file is not a PDF."),
      "The file is not a PDF.",
    ],
    [
      problem(422, "page_limit_exceeded", "The PDF has more than 500 pages."),
      "The PDF has more than 500 pages.",
    ],
  ])("the rejection %o shows the service's detail", (failure, message) => {
    expect(toUploadFailure(failure)).toEqual({
      state: "rejected",
      message,
      reference: ID,
      action: "none",
    });
  });

  test.each([
    [problem(500, "internal_error"), "The file could not be stored."],
    [problem(503, "storage_unavailable"), "The file could not be stored."],
    [
      { kind: "unreachable", requestId: ID } as const,
      "The service could not be reached.",
    ],
    [
      { kind: "timed_out", requestId: ID } as const,
      "The service could not be reached.",
    ],
    [
      { kind: "unreadable", requestId: ID } as const,
      "The service sent a response that could not be read.",
    ],
  ])("the failure %o can be uploaded again", (failure, message) => {
    expect(toUploadFailure(failure)).toEqual({
      state: "failed",
      message,
      reference: ID,
      action: "upload_again",
    });
  });

  test("the PDF pre-check has its own message and no reference", () => {
    expect(NOT_A_PDF).toEqual({
      state: "rejected",
      message: "Only PDF files can be uploaded.",
      reference: null,
      action: "none",
    });
  });
});
