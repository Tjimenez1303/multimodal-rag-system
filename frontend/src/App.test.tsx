import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { App } from "@/App";
import { PANEL_KEY } from "@/documents/panelState";

import { answer } from "../tests/fixtures/answers/load";
import { defaultConfig } from "../tests/msw/handlers";
import { server } from "../tests/msw/server";

test("the shell renders the document panel and the conversation", async () => {
  render(<App config={defaultConfig} />);

  expect(screen.getByRole("main")).toBeInTheDocument();
  expect(await screen.findByRole("list", { name: "Documents" })).toBeInTheDocument();
  expect(
    screen.getByRole("textbox", { name: "Ask a question about your manuals" }),
  ).toBeInTheDocument();
});

test("'Upload a manual' opens the collapsed panel and focuses the upload control", async () => {
  sessionStorage.setItem(PANEL_KEY, JSON.stringify({ collapsed: true }));
  server.use(
    http.post("/api/v1/questions", () =>
      HttpResponse.json(answer("no-information-no-documents")),
    ),
  );
  const user = userEvent.setup();
  render(<App config={defaultConfig} />);

  await user.type(
    screen.getByRole("textbox", { name: "Ask a question about your manuals" }),
    "How is a shunt generator wired?{Enter}",
  );
  await user.click(await screen.findByRole("button", { name: "Upload a manual" }));

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Upload a PDF" })).toHaveFocus(),
  );
  expect(screen.getByRole("button", { name: "Hide documents" })).toBeInTheDocument();
});
