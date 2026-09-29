import { delay, http, HttpResponse } from "msw";

import { isPdf, UPLOAD_STALL_SECONDS, uploadDocument } from "@/api/upload";
import type { UploadAccepted } from "@/client";

import { problem } from "../../tests/msw/handlers";
import { server } from "../../tests/msw/server";

const accepted: UploadAccepted = {
  document_id: "998496fb-02ce-4d4a-a178-37f0914ce20b",
  job_id: "27e7cbe8-7dc9-4866-8f9f-f96bf505a35f",
  status: "pending",
  already_ingested: false,
};

function pdf(name = "manual.pdf"): File {
  return new File(["%PDF-1.7 content"], name, { type: "application/pdf" });
}

test("progress is reported from 0 to 1 and a 202 resolves to the accepted upload", async () => {
  const fractions: number[] = [];
  let requestId: string | null = null;
  server.use(
    http.post("/api/v1/documents", ({ request }) => {
      requestId = request.headers.get("X-Request-ID");
      return HttpResponse.json(accepted, { status: 202 });
    }),
  );

  const result = await uploadDocument(pdf(), { onProgress: (f) => fractions.push(f) });

  expect(result).toEqual({ ok: true, data: accepted, requestId });
  expect(requestId).toMatch(/^[0-9a-f-]{36}$/);
  expect(fractions[0]).toBe(0);
  expect(fractions.at(-1)).toBe(1);
  expect([...fractions].sort((a, b) => a - b)).toEqual(fractions);
});

test("a 200 for content already ingested resolves with already_ingested", async () => {
  server.use(
    http.post("/api/v1/documents", () =>
      HttpResponse.json({ ...accepted, status: "completed", already_ingested: true }),
    ),
  );

  const result = await uploadDocument(pdf(), { onProgress: () => {} });

  expect(result.ok && result.data.already_ingested).toBe(true);
});

test.each([
  [400, "invalid_file_name", "The file name is empty."],
  [413, "file_too_large", "The file exceeds 200 MB."],
  [415, "unsupported_media_type", "The file is not a PDF."],
  [422, "page_limit_exceeded", "The PDF has more than 500 pages."],
])(
  "a %i %s problem is a rejection with the service's reason",
  async (status, code, detail) => {
    server.use(http.post("/api/v1/documents", () => problem(status, code, { detail })));

    const result = await uploadDocument(pdf(), { onProgress: () => {} });

    expect(result.ok).toBe(false);
    expect(!result.ok && result.failure).toMatchObject({
      state: "rejected",
      message: detail,
      action: "none",
    });
    expect(!result.ok && result.failure.reference).toMatch(/^[0-9a-f-]{36}$/);
  },
);

test.each([
  [
    "a 5xx problem",
    () => problem(503, "storage_unavailable"),
    "The file could not be stored.",
  ],
  ["a network error", () => HttpResponse.error(), "The service could not be reached."],
  [
    "a 502 without a problem body",
    () => new HttpResponse("Bad Gateway", { status: 502 }),
    "The service could not be reached.",
  ],
])("%s is a failure that can be uploaded again", async (_case, resolver, message) => {
  server.use(http.post("/api/v1/documents", resolver));

  const result = await uploadDocument(pdf(), { onProgress: () => {} });

  expect(!result.ok && result.failure).toMatchObject({
    state: "failed",
    message,
    action: "upload_again",
  });
});

test("a transfer with no progress for the stall limit fails as unreachable", async () => {
  vi.useFakeTimers();
  try {
    server.use(
      http.post("/api/v1/documents", async () => {
        await delay("infinite");
        return HttpResponse.json(accepted, { status: 202 });
      }),
    );

    const pending = uploadDocument(pdf(), { onProgress: () => {} });
    await vi.advanceTimersByTimeAsync(UPLOAD_STALL_SECONDS * 1000);

    expect(UPLOAD_STALL_SECONDS).toBe(60);
    const result = await pending;
    expect(!result.ok && result.failure).toMatchObject({
      state: "failed",
      message: "The service could not be reached.",
    });
  } finally {
    vi.useRealTimers();
  }
});

test.each([
  [new File(["x"], "manual.pdf", { type: "application/pdf" }), true],
  [new File(["x"], "MANUAL.PDF", { type: "" }), true],
  [new File(["x"], "scan", { type: "application/pdf" }), true],
  [new File(["x"], "notes.txt", { type: "text/plain" }), false],
  [new File(["x"], "image.png", { type: "image/png" }), false],
])("isPdf(%o) is %s", (file, expected) => {
  expect(isPdf(file)).toBe(expected);
});
