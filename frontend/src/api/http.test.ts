import { delay, http, HttpResponse } from "msw";

import { callService, SERVICE_CALL_TIMEOUT_SECONDS } from "@/api/http";
import { deleteDocument, getDocument, listDocuments } from "@/client";

import { libraryPage } from "../../tests/fixtures/documents/library";
import { problem } from "../../tests/msw/handlers";
import { server } from "../../tests/msw/server";

const REQUEST_ID = /^[A-Za-z0-9._:-]{1,128}$/;

function recordRequestIds(): string[] {
  const ids: string[] = [];
  server.events.on("request:start", ({ request }) => {
    ids.push(request.headers.get("X-Request-ID") ?? "");
  });
  return ids;
}

afterEach(() => {
  server.events.removeAllListeners();
});

test("every request carries its own X-Request-ID, returned with the result", async () => {
  const sent = recordRequestIds();

  const first = await callService((options) => listDocuments(options));
  const second = await callService((options) => listDocuments(options));

  expect(sent).toHaveLength(2);
  expect(sent[0]).toMatch(REQUEST_ID);
  expect(sent[1]).toMatch(REQUEST_ID);
  expect(sent[0]).not.toBe(sent[1]);
  expect(first).toEqual({ ok: true, data: libraryPage, requestId: sent[0] });
  expect(second.ok && second.requestId).toBe(sent[1]);
});

test("a problem response becomes a problem failure with its Retry-After", async () => {
  const sent = recordRequestIds();
  server.use(
    http.get("/api/v1/documents", () =>
      problem(503, "answering_busy", {
        detail: "Too many questions.",
        requestId: "ignored",
        headers: { "Retry-After": "7" },
      }),
    ),
  );

  const result = await callService((options) => listDocuments(options));

  expect(result).toEqual({
    ok: false,
    failure: {
      kind: "problem",
      status: 503,
      code: "answering_busy",
      detail: "Too many questions.",
      requestId: sent[0],
      retryAfterSeconds: 7,
    },
  });
});

test("a problem without Retry-After or detail has null for both", async () => {
  server.use(
    http.get("/api/v1/documents/:id", () => problem(404, "document_not_found")),
  );

  const result = await callService((options) =>
    getDocument({ ...options, path: { document_id: libraryPage.items[0]!.id } }),
  );

  expect(result.ok).toBe(false);
  expect(!result.ok && result.failure).toMatchObject({
    kind: "problem",
    status: 404,
    code: "document_not_found",
    detail: null,
    retryAfterSeconds: null,
  });
});

test("a problem whose request_id differs keeps the sent id as the reference", async () => {
  const sent = recordRequestIds();
  server.use(
    http.get("/api/v1/documents", () =>
      problem(500, "internal_error", { requestId: "other-id" }),
    ),
  );

  const result = await callService((options) => listDocuments(options));

  expect(!result.ok && result.failure.requestId).toBe(sent[0]);
});

test.each([
  ["a network error", () => HttpResponse.error()],
  [
    "a 502 without a problem body",
    () => new HttpResponse("Bad Gateway", { status: 502 }),
  ],
  [
    "a 504 without a problem body",
    () => new HttpResponse("<html>Gateway Timeout</html>", { status: 504 }),
  ],
])("%s is an unreachable service", async (_case, resolver) => {
  const sent = recordRequestIds();
  server.use(http.get("/api/v1/documents", resolver));

  const result = await callService((options) => listDocuments(options));

  expect(result).toEqual({
    ok: false,
    failure: { kind: "unreachable", requestId: sent[0] },
  });
});

test("a success whose body breaks the contract is unreadable", async () => {
  server.use(
    http.get("/api/v1/documents", () => HttpResponse.json({ next_cursor: null })),
  );

  const result = await callService((options) => listDocuments(options));

  expect(!result.ok && result.failure.kind).toBe("unreadable");
});

test("a success that is not JSON is unreadable", async () => {
  server.use(
    http.get(
      "/api/v1/documents",
      () => new HttpResponse("<html></html>", { status: 200 }),
    ),
  );

  const result = await callService((options) => listDocuments(options));

  expect(!result.ok && result.failure.kind).toBe("unreadable");
});

test("a success with no content succeeds without a body", async () => {
  const id = libraryPage.items[0]!.id;
  server.use(
    http.delete(
      `/api/v1/documents/${id}`,
      () => new HttpResponse(null, { status: 204 }),
    ),
  );

  const result = await callService((options) =>
    deleteDocument({ ...options, path: { document_id: id } }),
  );

  expect(result.ok).toBe(true);
});

test("a call that gets no answer times out after the service call timeout", async () => {
  vi.useFakeTimers();
  try {
    server.use(
      http.get("/api/v1/documents", async () => {
        await delay("infinite");
        return HttpResponse.json(libraryPage);
      }),
    );

    const pending = callService((options) => listDocuments(options));
    await vi.advanceTimersByTimeAsync(SERVICE_CALL_TIMEOUT_SECONDS * 1000);

    expect(SERVICE_CALL_TIMEOUT_SECONDS).toBe(10);
    const result = await pending;
    expect(!result.ok && result.failure.kind).toBe("timed_out");
  } finally {
    vi.useRealTimers();
  }
});

test("a custom timeout replaces the default one", async () => {
  vi.useFakeTimers();
  try {
    server.use(
      http.get("/api/v1/documents", async () => {
        await delay("infinite");
        return HttpResponse.json(libraryPage);
      }),
    );

    const pending = callService((options) => listDocuments(options), {
      timeoutSeconds: 1,
    });
    await vi.advanceTimersByTimeAsync(1000);

    const result = await pending;
    expect(!result.ok && result.failure.kind).toBe("timed_out");
  } finally {
    vi.useRealTimers();
  }
});
