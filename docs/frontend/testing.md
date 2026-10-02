# Testing the frontend

```bash
npm --prefix frontend run test
npm --prefix frontend run test:coverage
npm --prefix frontend run test:e2e
```

CI fails when line coverage of the hand-written code drops below 90%. The generated
client, the vendored components and `main.tsx` are left out of the measure.

## Unit and component tests

[Vitest](https://vitest.dev) runs in jsdom, with
[Testing Library](https://testing-library.com) for components. Tests sit next to the
code they test as `*.test.ts` or `*.test.tsx`.

- [`tests/setup.ts`](../../frontend/tests/setup.ts) adds the jest-dom matchers, stands
  in for browser APIs jsdom lacks, starts the MSW server and resets handlers,
  `sessionStorage` and the reachability store after each test.
- [MSW](https://mswjs.io) answers the API at the network level. Default handlers in
  `tests/msw/handlers.ts` serve the config, the library, a plain answer, uploads and
  images. A test overrides one handler to reproduce a case, and any request without a
  handler fails the test.
- `renderWithProviders` in `tests/render.tsx` renders a component with the config, a
  fresh query client without retries and the tooltip provider.

## Fixtures

- `tests/fixtures/answers/` holds answers in the exact API format. Some were captured
  from the running system with `scripts/capture-answers.ts`, others were written by hand
  for cases the system rarely produces. Every fixture is validated against the generated
  zod schema, so a fixture that drifts from the contract fails.
- `tests/reference-answers.test.tsx` renders every reference answer and checks that no
  Markdown syntax leaks, that citations link to their source lines, and similar
  properties.
- `tests/fixtures/documents/` and `tests/fixtures/failures/` hold library pages and
  question failures.

## End-to-end tests

[Playwright](https://playwright.dev) builds the client, serves it with
`vite preview` and drives it in Chromium, Firefox and WebKit at 1280×720. The API is
faked with `page.route` in `tests/e2e/fakes.ts`, with a catch-all that refuses any
request the test did not expect, so the suite never needs a backend.

`expectAccessible` runs [axe](https://github.com/dequelabs/axe-core) against WCAG 2.1 A
and AA once animations settle, and every spec expects zero violations.

| Spec | Covers |
| --- | --- |
| `ask-and-read.spec.ts` | Answers, citations, Markdown, figure and page dialogs |
| `states-and-failures.spec.ts` | Waiting, no information, failures, busy, stop, held turns, reload, connection notice |
| `documents.spec.ts` | Upload lifecycle, failed and non-PDF files, collapsed panel, viewing and deleting |
| `accessibility.spec.ts` | axe checks and a keyboard-only flow |
| `long-conversation.spec.ts` | Fifty turns stay responsive |
