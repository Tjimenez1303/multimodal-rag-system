import { act, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { callService } from "@/api/http";
import { listDocuments } from "@/client";
import { ConnectionNotice } from "@/failures/ConnectionNotice";

import { server } from "../../tests/msw/server";

test("the notice appears after the service cannot be reached and clears on success", async () => {
  render(<ConnectionNotice />);
  expect(screen.queryByText(/Can't reach the service/)).not.toBeInTheDocument();

  server.use(http.get("/api/v1/documents", () => HttpResponse.error(), { once: true }));
  await act(() => callService((options) => listDocuments(options)));

  expect(screen.getByRole("status")).toHaveTextContent(
    "Can't reach the service. Retrying…",
  );

  await act(() => callService((options) => listDocuments(options)));

  expect(screen.queryByText(/Can't reach the service/)).not.toBeInTheDocument();
});

test("a problem response proves the service is reachable", async () => {
  render(<ConnectionNotice />);
  server.use(http.get("/api/v1/documents", () => HttpResponse.error(), { once: true }));
  await act(() => callService((options) => listDocuments(options)));
  expect(screen.getByRole("status")).toBeInTheDocument();

  server.use(
    http.get(
      "/api/v1/documents",
      () =>
        HttpResponse.json(
          {
            title: "Bad Request",
            status: 400,
            instance: "/",
            code: "x",
            request_id: "r",
          },
          { status: 400, headers: { "Content-Type": "application/problem+json" } },
        ),
      { once: true },
    ),
  );
  await act(() => callService((options) => listDocuments(options)));

  expect(screen.queryByText(/Can't reach the service/)).not.toBeInTheDocument();
});
