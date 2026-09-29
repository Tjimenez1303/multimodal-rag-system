import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";

import type { DocumentBody } from "@/client";
import { ConfigContext } from "@/config";
import { useLibrary } from "@/documents/useLibrary";

import {
  completedDocument,
  COMPLETED_ID,
  FAILED_ID,
  libraryPage,
  PENDING_ID,
  PROCESSING_ID,
  processingDocument,
} from "../../tests/fixtures/documents/library";
import { defaultConfig } from "../../tests/msw/handlers";
import { server } from "../../tests/msw/server";

// A short interval keeps the tests fast. The production default is 2 seconds.
const POLL_SECONDS = 0.05;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <ConfigContext value={{ ...defaultConfig, statusPollSeconds: POLL_SECONDS }}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ConfigContext>
  );
}

function countPolls() {
  const polls = new Map<string, number>();
  server.events.on("request:start", ({ request }) => {
    const match = /\/api\/v1\/documents\/([^/]+)$/.exec(new URL(request.url).pathname);
    if (match) polls.set(match[1]!, (polls.get(match[1]!) ?? 0) + 1);
  });
  return polls;
}

afterEach(() => {
  server.events.removeAllListeners();
});

test("only pending and processing documents are followed", async () => {
  const polls = countPolls();
  const { result } = renderHook(() => useLibrary(), { wrapper });

  await waitFor(() => expect(result.current.documents).toHaveLength(4));
  await waitFor(() => {
    expect(polls.get(PROCESSING_ID)).toBeGreaterThanOrEqual(2);
    expect(polls.get(PENDING_ID)).toBeGreaterThanOrEqual(2);
  });
  expect(polls.get(COMPLETED_ID)).toBeUndefined();
  expect(polls.get(FAILED_ID)).toBeUndefined();
});

test("following stops once the job finishes, and the list shows the new status", async () => {
  const polls = countPolls();
  const finished: DocumentBody = {
    ...processingDocument,
    latest_job: { ...completedDocument.latest_job!, document_id: PROCESSING_ID },
  };
  server.use(
    http.get(`/api/v1/documents/${PROCESSING_ID}`, () => HttpResponse.json(finished)),
  );
  const { result } = renderHook(() => useLibrary(), { wrapper });

  await waitFor(() =>
    expect(
      result.current.documents.find((d) => d.id === PROCESSING_ID)?.latest_job?.status,
    ).toBe("completed"),
  );
  const count = polls.get(PROCESSING_ID);
  await new Promise((resolve) => setTimeout(resolve, POLL_SECONDS * 1000 * 4));

  expect(polls.get(PROCESSING_ID)).toBe(count);
});

test("more documents are loaded on demand", async () => {
  const second: DocumentBody = {
    ...completedDocument,
    id: "11111111-2222-4333-8444-555555555555",
    file_name: "older.pdf",
  };
  server.use(
    http.get("/api/v1/documents", ({ request }) =>
      new URL(request.url).searchParams.get("cursor") === "next"
        ? HttpResponse.json({ items: [second], next_cursor: null })
        : HttpResponse.json({ ...libraryPage, next_cursor: "next" }),
    ),
  );
  const { result } = renderHook(() => useLibrary(), { wrapper });
  await waitFor(() => expect(result.current.hasMore).toBe(true));

  await act(() => result.current.loadMore());

  await waitFor(() =>
    expect(result.current.documents.map((d) => d.file_name)).toContain("older.pdf"),
  );
  expect(result.current.hasMore).toBe(false);
});

test("after a reload, unfinished documents are followed again", async () => {
  const first = renderHook(() => useLibrary(), { wrapper });
  await waitFor(() => expect(first.result.current.documents).toHaveLength(4));
  first.unmount();
  const polls = countPolls();

  renderHook(() => useLibrary(), { wrapper });

  await waitFor(() => expect(polls.get(PROCESSING_ID)).toBeGreaterThanOrEqual(1));
});
