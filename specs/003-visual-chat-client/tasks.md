---

description: "Task list for the visual chat client"
---

# Tasks: Visual Chat Client

**Input**: Design documents from `specs/003-visual-chat-client/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/openapi.yaml](contracts/openapi.yaml),
[contracts/client.md](contracts/client.md), [quickstart.md](quickstart.md)

**Tests**: Test tasks are REQUIRED for every user story (constitution Principle VIII).

- **Backend**: unit tests use the fakes in `backend/tests/fakes.py`, which implement the
  ports. Never use `MagicMock` or `Mock`. Backend coverage MUST stay at or above 90%.
- **Frontend**:
  - Tests fake HTTP at the network level with the MSW handlers in `frontend/tests/msw/`
    (Vitest) or Playwright route handlers (end to end), serving contract-shaped
    fixtures.
  - Modules are never replaced with `vi.mock`, and tests never assert on `vi.fn()` call
    sequences. They assert what the user sees through Testing Library queries by role,
    label and text.
  - Frontend line coverage MUST stay at or above 90%, excluding `frontend/src/client/`.
- Write each story's tests first and confirm they fail before implementing.

**Organization**: tasks are grouped by user story, so each story can be implemented,
tested and demonstrated on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: the user story the task belongs to (US1 to US4)
- Every description names the exact file

## Path Conventions

- **Frontend code**: `frontend/src/`, with unit and component tests next to the code as
  `*.test.ts(x)`. Fixtures, MSW handlers and Playwright specs live in `frontend/tests/`.
- **Frontend service access**: only `frontend/src/api/` and the generated
  `frontend/src/client/` talk to the service. Components never call `fetch` or
  `XMLHttpRequest`.
- **Backend**: code lives in `backend/src/multimodal_rag/` and tests in `backend/tests/`.
- **Commands**: run from the repository root, as listed in `AGENTS.md`. Frontend commands
  use `npm --prefix frontend run <script>`.
- **Documentation**: exported TypeScript functions and components carry TSDoc comments,
  and Python code carries Google-style docstrings.

---

## Phase 1: Setup

**Purpose**: frontend project, toolchain, generated client and hooks

- [X] T001 Scaffold the frontend project in `frontend/`, following the official Vite `react-ts` template (research sections 1 and 2):
  - `frontend/.node-version` with `24`.
  - `frontend/package.json` with `"type": "module"`, `"engines": { "node": ">=24 <25" }` and these scripts:

    | Script | Command |
    |---|---|
    | `dev` | `vite` |
    | `build` | `tsc -b && vite build` |
    | `preview` | `vite preview` |
    | `lint` | `oxlint` |
    | `format` | `prettier --write .` |
    | `format:check` | `prettier --check .` |
    | `typecheck` | `tsc -b --noEmit` |
    | `test` | `vitest run` |
    | `test:coverage` | `vitest run --coverage` |
    | `test:e2e` | `playwright test` |
    | `generate-client` | `openapi-ts` |

  - Install runtime dependencies with `npm --prefix frontend install`: `react@19.3` `react-dom@19.3` `@tanstack/react-query@5` `mdast-util-find-and-replace@3` `unist-util-visit@5` `zod@4` `tailwindcss@4` `@tailwindcss/vite@4`.
  - Install dev dependencies with `npm --prefix frontend install -D`: `vite@8` `@vitejs/plugin-react@6` `typescript@~6.0` `@types/react@19.3` `@types/react-dom@19.3` `@types/mdast@4` `@types/node@24` `oxlint@1` `prettier@3` `vitest@5` `@vitest/coverage-v8@5` `jsdom@30` `@testing-library/react@16` `@testing-library/user-event@14` `@testing-library/jest-dom@7` `msw@3` `@playwright/test@1.63` `@axe-core/playwright@4` `@hey-api/openapi-ts@0.99`.
  - Initialize shadcn/ui with `npx shadcn@latest init -t vite -b radix -p nova` in `frontend/` (research section 14), after T002 and T004 add the `@` alias: Radix primitives, neutral base color, CSS variables, `src/index.css` as the stylesheet. It writes `frontend/components.json`, `frontend/src/lib/utils.ts` and the theme tokens, and adds `lucide-react`, `radix-ui`, `class-variance-authority`, `cn`, `shadcn`, `tw-animate-css` and `@fontsource-variable/geist`.
  - Install the AI Elements components with `npx ai-elements@latest add conversation message prompt-input inline-citation sources`, and the shadcn/ui components with `npx shadcn@latest add alert alert-dialog badge button card checkbox collapsible dialog input progress sidebar spinner table`. Then adapt the installed files as research section 14's component map states, and remove the npm packages the adaptations leave unused (`ai`, `@streamdown/*`).
  - Commit `frontend/package-lock.json`.
  - Add `frontend/index.html` with `lang="en"` and the title "Manual Assistant", plus a placeholder `frontend/src/main.tsx`.
- [X] T002 [P] Configure TypeScript in `frontend/tsconfig.json`, `frontend/tsconfig.app.json` and `frontend/tsconfig.node.json`:
  - Project references as in the Vite template.
  - `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`, `jsx: "react-jsx"` and the `vitest/globals` types for test files.
  - `paths` mapping `@/*` to `./src/*`, in `tsconfig.json` and `tsconfig.app.json`, as the shadcn/ui Vite installation requires. `baseUrl` is left out because TypeScript 6 deprecates it.
- [X] T003 [P] Configure lint and format:
  - `frontend/.oxlintrc.json` enables the `react`, `typescript`, `jsx-a11y` and `import` plugins, with `react/rules-of-hooks` and `react/exhaustive-deps` as errors.
  - `frontend/.prettierrc.json` sets `printWidth: 88` to match the backend's line length.
  - `frontend/.prettierignore` excludes `src/client/`, `openapi.json`, `dist/`, `coverage/`, `playwright-report/` and `test-results/`.
  - `frontend/.oxlintrc.json` also ignores `src/client/` and the registry code the shadcn/ui and AI Elements CLIs install (`src/components/ui/`, `src/components/ai-elements/`), as the coverage gate does (research section 15). Prettier and the type check still cover it.
- [X] T004 [P] Configure Vite and Vitest in `frontend/vite.config.ts`:
  - `@vitejs/plugin-react`, `@tailwindcss/vite`, the `@` alias to `./src`, and `server.proxy` sending `/api` to `http://localhost:8000` (research section 4).
  - A `test` block with `environment: "jsdom"` and `setupFiles: ["./tests/setup.ts"]`.
  - `coverage` with the `v8` provider, `include: ["src/**"]`, `exclude: ["src/client/**", "src/components/ui/**", "src/components/ai-elements/**", "src/main.tsx", "**/*.test.*"]` and `thresholds: { lines: 90 }` (research section 15).
  - Create `frontend/tests/setup.ts`, which imports `@testing-library/jest-dom/vitest`, installs minimal `ResizeObserver` and `Element.scrollIntoView` stand-ins for jsdom, starts the MSW server from `frontend/tests/msw/server.ts` with `onUnhandledFrame: "error"` (MSW 3's name for unhandled requests), and resets handlers and `sessionStorage` after each test.
- [X] T005 [P] Configure Playwright in `frontend/playwright.config.ts`:
  - `webServer` runs `npm run build && npm run preview -- --port 4173`, with `baseURL` `http://localhost:4173`.
  - Three projects, `chromium`, `firefox` and `webkit`, all with viewport `1280 × 720` (FR-043).
  - `testDir: "tests/e2e"`.
- [X] T006 Export the API description and generate the typed client (research section 5):
  - Create `backend/scripts/export_openapi.py`. It builds the app as `backend/tests/contract/test_openapi_matches_contract.py` does (`create_app(readiness_checks={}, routers=(ingestion_router, documents_router, questions_router))`) and writes `app.openapi()` as indented JSON to the path given as its only argument.
  - Run `uv run --directory backend python scripts/export_openapi.py ../frontend/openapi.json`.
  - Create `frontend/openapi-ts.config.ts` with `input: "./openapi.json"`, `output` at `./src/client` with a `// @ts-nocheck` file header (the generated code is not written for `exactOptionalPropertyTypes`), and these plugins, declared explicitly (research section 5): `@hey-api/client-fetch`, `@hey-api/typescript`, `zod`, and `{ name: "@hey-api/sdk", validator: { request: false, response: "zod" } }`.
  - Run `npm --prefix frontend run generate-client` and commit `frontend/src/client/`.
- [X] T007 [P] Update repository hygiene:
  - In `_typos.toml`, exclude `frontend/src/client/`, `frontend/openapi.json`, `frontend/package-lock.json` and the captured answers in `frontend/tests/fixtures/answers/*.json`, which are kept verbatim.
  - In `.gitignore`, add `frontend/coverage/`, `frontend/playwright-report/` and `frontend/test-results/`.
- [X] T008 Add local hooks to `.pre-commit-config.yaml`, each with `language: system`, `pass_filenames: false` and `files: ^frontend/`:
  - `frontend-lint`: `npm --prefix frontend run lint`
  - `frontend-format`: `npm --prefix frontend run format:check`
  - `frontend-typecheck`: `npm --prefix frontend run typecheck`
  - Confirm `uv run --project backend pre-commit run --all-files` passes.

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: runtime configuration, the service access layer, failure messages, test
fakes, the application shell and the `frontend` Compose service. Every story needs them.

**⚠️ CRITICAL**: no user story work can begin until this phase is complete

### Tests for the foundation

- [X] T009 [P] Write `frontend/src/config.test.ts`:
  - A valid `/config.json` loads into `RuntimeConfig`.
  - Loading fails with a typed error when the file is unreachable, when a field is missing, or when `answerWaitSeconds` or `statusPollSeconds` is not greater than 0, or `maxFilterDocuments` is not an integer of at least 1 (contracts/client.md section 1).
- [X] T010 [P] Write `frontend/src/api/http.test.ts` with MSW:
  - **Request id.** Every request carries an `X-Request-ID` matching `^[A-Za-z0-9._:-]{1,128}$`, and two requests carry different ids.
  - **Problem responses** become `ServiceFailure` `problem` with `status`, `code`, `detail`, `requestId` and `retryAfterSeconds`. The last is read from `Retry-After` and is `null` when the header is absent.
  - **No usable response.** A network error, and a 502 or 504 without a problem body (nginx with the API down), become `unreachable`.
  - **Bad body.** A 200 whose body does not match the expected shape becomes `unreadable`.
  - **Id mismatch.** A problem body whose `request_id` differs from the sent id keeps the sent id as the reference.
  - **Timeouts.** A `listDocuments` handler that never answers fails as `timed_out` after `SERVICE_CALL_TIMEOUT_SECONDS` (10 s, with fake timers).
  - **Validation.** A 200 `listDocuments` body missing `items` fails the generated zod validation and becomes `unreadable`.
- [X] T011 [P] Write `frontend/src/failures/messages.test.ts`. For every row of contracts/client.md section 3, the mapping returns the documented kind, message (the problem `detail` where the table says "detail"), retry action, and the `Retry-After` seconds inserted into the busy message.
- [X] T012 [P] Write `frontend/src/failures/FailureNotice.test.tsx`:
  - It renders the message and "Reference: {id}" below it.
  - The reference can be copied with a button labeled "Copy reference".
  - The action button is rendered only when an action is given.
- [X] T013 [P] Write `frontend/src/api/connection.test.tsx`:
  - `ConnectionNotice` appears after an `unreachable` failure is reported.
  - It disappears once any later request succeeds, without a reload (FR-030).

### Implementation for the foundation

- [X] T014 [P] Set the theme in `frontend/src/index.css` (research section 14):
  - The shadcn/ui theme tokens as CSS custom properties: a neutral base with one restrained blue `--primary`, radii and the answer text's line height, with text and control colors that meet WCAG 2.1 AA contrast.
  - The preset's Geist font, bundled from `@fontsource-variable/geist` and served from the client's origin (FR-046), a visible focus ring, and an `@source` line so Tailwind picks up the classes Streamdown renders.
- [X] T015 [P] Implement `frontend/src/config.ts` (data-model section 3). `loadConfig()` fetches `/config.json` with `cache: "no-store"`, validates the three fields with the constraints in T009, and returns `RuntimeConfig`. A `ConfigContext` provides the loaded values.
- [X] T016 Implement `frontend/src/api/http.ts` (research sections 5 and 10, data-model section 2.4):
  - Configure the generated client with an empty `baseUrl`, so requests are same-origin.
  - A request interceptor sets `X-Request-ID` to `crypto.randomUUID()` and exposes the id to the caller.
  - A response interceptor produces `ServiceFailure` with the variants `problem`, `unreachable`, `timed_out` and `unreadable`. A zod validation error from the SDK maps to `unreadable`.
  - Export `SERVICE_CALL_TIMEOUT_SECONDS = 10`. Every call except questions and uploads passes `AbortSignal.timeout(SERVICE_CALL_TIMEOUT_SECONDS * 1000)`, and a timeout maps to `timed_out`.
  - Export `callService<T>()`, which returns `{ ok: true, data, requestId } | { ok: false, failure }`.
- [X] T017 Implement `frontend/src/api/connection.ts`, a small store with `reportUnreachable()` and `reportReachable()` that `http.ts` calls, and `frontend/src/failures/ConnectionNotice.tsx`, a `role="status"` banner composed from the shadcn/ui `Alert`, saying "Can't reach the service. Retrying…".
- [X] T018 [P] Implement `frontend/src/failures/messages.ts` exactly as contracts/client.md section 3.
  - `toTurnFailure(failure, { requestId })` returns `TurnFailure` with `kind`, `message`, `retryable`, `retryAfterSeconds` and `reference`.
  - An `action` field is one of `"retry"`, `"edit"` or `"none"`.
  - `toUploadFailure(failure)` returns the upload message and state (`rejected` or `failed`).
- [X] T019 [P] Implement `frontend/src/failures/FailureNotice.tsx` from the shadcn/ui `Alert` and `Button`. It shows the message and "Reference: {id}" in smaller muted text, a copy button using `navigator.clipboard.writeText`, and an optional action button.
- [X] T020 [P] Create the test fakes:
  - `frontend/tests/msw/handlers.ts` and `frontend/tests/msw/server.ts`, with default handlers for `/config.json`, `listDocuments`, `getDocument`, `askQuestion`, `uploadDocument` and the image routes. The image routes serve a 1 × 1 PNG.
  - `frontend/tests/fixtures/documents/`, holding a library page with one completed, one processing (`stage: extracting`, `pages_done: 12`, `pages_total: 71`), one pending (`latest_job: null`) and one failed document.
  - Every fixture is typed with the generated client types, so a contract change breaks compilation.
- [X] T021 Build the application shell:
  - `frontend/src/main.tsx` imports `index.css`, calls `loadConfig()` and renders `ConnectionNotice` while it fails, retrying with backoff of 1, 2, 4 and at most 10 seconds.
  - `frontend/src/App.tsx` renders inside `QueryClientProvider` and `ConfigContext`: a layout with a left panel slot and the conversation area, and a minimum layout width of 1280 px.
- [X] T022 Add the frontend container (research section 4, contracts/client.md section 1):
  - `frontend/Dockerfile`: a `node:24-alpine` stage runs `npm ci` and `npm run build`, and an `nginx:1.30-alpine` stage copies `dist/` to `/usr/share/nginx/html` and the templates below to `/etc/nginx/templates/`.
  - `frontend/nginx/default.conf.template`:
    - `listen 80` and `/healthz` returning `200 ok` with `access_log off`.
    - JSON access logs (Principle VII, research section 4): `log_format json_access escape=json` with `time` (`$time_iso8601`), `level` (`info`), `logger` (`nginx.access`), `method` (`$request_method`), `path` (`$uri`, never `$request_uri`), `status`, `duration_ms` from `$request_time`, and `request_id` (`$http_x_request_id`). Use `access_log /dev/stdout json_access`, and never log `$remote_addr`.
    - `location /api/` proxies to `http://api:8000` with `proxy_request_buffering off`, `client_max_body_size 0`, `proxy_read_timeout ${NGINX_PROXY_READ_TIMEOUT}s` and `proxy_set_header X-Request-ID $http_x_request_id`.
    - `try_files $uri /index.html`.
    - `Cache-Control` per route as in contracts/client.md.
    - The security headers of research section 4 with `always`, including `'nonce-$request_id'` in `style-src`, and `sub_filter` replacing the `__CSP_NONCE__` placeholder that Vite's `html.cspNonce` writes into `index.html` (research section 14).
  - In the same template, `location = /config.json` answers `default_type application/json` and `return 200` with a JSON body that fills `answerWaitSeconds`, `maxFilterDocuments` and `statusPollSeconds` from `${ANSWER_WAIT_SECONDS}`, `${MAX_FILTER_DOCUMENTS}` and `${STATUS_POLL_SECONDS}`. The official image renders templates only into `conf.d`, so the configuration lives in the server block rather than in a separate file.
  - `frontend/.dockerignore` excludes `node_modules`, `coverage`, `playwright-report` and `test-results`.
- [X] T023 Wire the service into `compose.yaml` and `.env.example`:
  - `compose.yaml` gains a `frontend` service built from `./frontend` and published on `127.0.0.1:${FRONTEND_PUBLISHED_PORT:-3000}:80`.
    - Its environment sets `ANSWER_WAIT_SECONDS: ${ANSWER_WAIT_SECONDS:-105}`, `NGINX_PROXY_READ_TIMEOUT: ${NGINX_PROXY_READ_TIMEOUT:-120}`, `MAX_FILTER_DOCUMENTS: ${MAX_FILTER_DOCUMENTS:-20}` and `STATUS_POLL_SECONDS: ${STATUS_POLL_SECONDS:-2}`.
    - Its healthcheck is `wget -q --spider http://127.0.0.1/healthz`.
    - It has `depends_on: api: condition: service_healthy` and `restart: unless-stopped`.
  - The `api` service reads `MAX_FILTER_DOCUMENTS` from the same variable.
  - `.env.example` documents `FRONTEND_PUBLISHED_PORT=3000`, `ANSWER_WAIT_SECONDS=105` ("keep it at least 15 s above ANSWER_DEADLINE_SECONDS"), `NGINX_PROXY_READ_TIMEOUT=120` ("keep it above ANSWER_WAIT_SECONDS"), `MAX_FILTER_DOCUMENTS=20` and `STATUS_POLL_SECONDS=2`.
  - Move `MAX_FILTER_DOCUMENTS` out of the commented list of API defaults in `.env.example` into the active frontend section, so it appears once.
  - Check that port 3000 is free, then confirm `docker compose up -d --build --wait` reports `frontend` healthy and `curl -s localhost:3000/config.json` returns the three values.

**Checkpoint**: the shell loads at <http://localhost:3000> through Compose, and the service
access layer and failure messages are tested

---

## Phase 3: User Story 1 - Ask a question and read the cited answer with its image (Priority: P1) 🎯 MVP

**Goal**: a technician asks a question and reads the rendered answer with numbered
source lines, the primary figure beside it, the related figures, and full-size figure
and page views. The history stays in the tab. The backend stores page images at
ingestion and serves them.

**Independent Test**: with a sample manual ingested, ask "How is a shunt generator
wired?". The answer renders its formatting and cites the FAA manual's page. The expected
figure shows beside it with caption and page. The figure and the page open at full size.
A second question keeps the first turn visible (quickstart scenario 2).

### Tests for User Story 1 (REQUIRED) ⚠️

- [X] T024 [P] [US1] Add backend unit tests in `backend/tests/unit/ingestion/test_library.py` for `GetPageImage`, with the existing fakes:
  - It returns the stored PNG bytes for a completed document.
  - `DocumentNotFoundError` for an unknown id.
  - `IngestionNotCompletedError` when the latest job is pending, processing or failed, or missing.
  - `PageNotFoundError` for page 0, a negative page and `page_count + 1`.
  - `DataInconsistencyError` when the blob is missing for a completed document.
- [X] T025 [P] [US1] Add backend unit tests in `backend/tests/unit/ingestion/test_process_job_extraction.py`:
  - **Storage.** Every page image of every batch from `FakeExtractor` is saved under `pages/{document_id}/{page}.png`.
  - **Retries.** A retried job overwrites the same keys, so the number of stored objects is unchanged (Principle III idempotency).
- [X] T026 [P] [US1] Add `backend/tests/contract/test_page_image_contract.py`:
  - Register `specs/003-visual-chat-client/contracts/openapi.yaml` in `CONTRACT_FILES` of `backend/tests/contract/contract.py`.
  - Assert with `assert_matches_contract` that `GET /api/v1/documents/{document_id}/pages/{page_number}/image` answers 200 `image/png`, 404 `document_not_found`, 404 `page_not_found`, 409 `ingestion_not_completed` and 400 for a non-numeric page.
  - Add the new route to `backend/tests/contract/test_openapi_matches_contract.py` through `documents_router`, so the served description must match.
- [X] T027 [P] [US1] Extend `backend/tests/integration/test_docling_extractor.py`. Extracting a sample fixture PDF yields `page_images` with one valid PNG per page of each batch, whose pixel size is the page size in points times 2.
- [X] T028 [P] [US1] Write `frontend/src/answer/sourceLabel.test.ts` (data-model section 2.1):
  - `[12]` gives "Source: X.pdf, page 12".
  - `[12, 13]` gives "pages 12–13".
  - `[3, 4, 9]` gives "pages 3–4, 9".
  - `[9, 3, 4]` is sorted first.
  - Duplicates are listed once.
- [X] T029 [P] [US1] Write `frontend/src/answer/markdown/AnswerMarkdown.test.tsx`:
  - **Formatting.** Headings, ordered, unordered and nested lists, a GFM table, inline code, a fenced code block, bold and italic render as their elements with no literal `#`, `*` or `|` left (FR-008, SC-002).
  - **Markers.** `[1]` with citation 1 present becomes a link named "Citation 1". `[7]` with no citation 7 stays text. `[1]` inside inline code or a code block stays literal.
  - **Raw markup.** `<script>alert(1)</script>` and `<img src=x onerror=…>` appear as visible text, and no `script` or `img` element is created (FR-009).
  - **Images and links.** `![alt](http://example.com/a.png)` renders the text "alt" and no `img` (FR-046). A `javascript:` link is not rendered as a link.
  - **Wide tables.** A wide table is wrapped in a horizontally scrollable region.
- [X] T030 [P] [US1] Write `frontend/src/answer/SourceList.test.tsx`:
  - **Source lines.** Each citation renders one numbered source line with its label (FR-010).
  - **Details.** Expanding a line shows the section path, the excerpt and, for a table source, a `table` with its rows (FR-012).
  - **Low confidence.** A `low_confidence_text` source shows a "Low-confidence OCR" mark with the explanation that it should be checked against the page (FR-013).
  - **Generated descriptions.** A `generated_description` source shows a "Described automatically" mark and lists `unverified_identifiers`.
  - **Uncited passages.** They are under a collapsed "Other retrieved passages" disclosure (FR-014).
  - **Highlight.** Activating a marker highlights the matching line and moves focus to it (FR-011).
  - **Page action.** Every source line has an "Open page" button.
- [X] T031 [P] [US1] Write `frontend/src/images/ImageColumn.test.tsx`:
  - **Primary image.** It renders with caption, or "No caption" when `caption` is null, and "{document_name}, page {page}" below it. Its `alt` is built from caption, document and page (FR-015, FR-044).
  - **Related images.** They render as a group labeled "Related images" under the primary image, in the returned order (FR-017).
  - **Broken images.** An image that fails to load shows "Image unavailable" and keeps its caption, document and page.
  - **No images.** A response without images renders no column.
- [X] T032 [P] [US1] Write `frontend/src/images/ImageDialog.test.tsx` and `frontend/src/images/PageDialog.test.tsx`:
  - **Image dialog.** Opening shows a modal dialog with the full-size image, caption, document and page. Escape and the close button close it, and focus returns to the opener (FR-016).
  - **Page dialog.** It requests `/api/v1/documents/{id}/pages/{n}/image` and shows "{document_name}, page {n}". For a source with pages `[12, 13]` it offers "Next page" and "Previous page" limited to those pages. A load error shows "Page unavailable" with the document and page (FR-018).
- [X] T033 [P] [US1] Write `frontend/src/conversation/state.test.ts` and `frontend/src/conversation/persistence.test.ts` for the answered path:
  - **Submitting.** It adds a `waiting` turn with a trimmed `question` and an empty `restriction`.
  - **Answers.** An `answered` response moves the turn to `answered` with `response` stored unchanged.
  - **New conversation.** It clears the turns.
  - **Persistence.** The state is written to `sessionStorage` under `multimodal-rag.conversation.v1` with `version: 1` and read back identically. A stored value with another version is discarded.
  - **Storage full.** A `QuotaExceededError` keeps the state in memory and raises the "won't survive a reload" notice.
- [X] T034 [P] [US1] Write `frontend/src/conversation/ConversationView.test.tsx`:
  - **Sending.** Typing a question and pressing Enter sends it, while Shift+Enter inserts a new line. The send button is disabled for an empty or blank question (FR-001).
  - **Order.** The question appears, then the answer, and earlier turns stay in order (FR-002).
  - **Scrolling.** The new answer is scrolled into view. jsdom has no layout, so this is asserted in `frontend/tests/e2e/ask-and-read.spec.ts` with `toBeInViewport`.
  - **New conversation.** It asks for confirmation before clearing (FR-004).
  - **Two columns.** An answered turn with a primary image lays out the text and the image column side by side, and a turn without images uses the full width (FR-015).
- [X] T035 [US1] Create the reference answer set (research section 15):
  - Write `frontend/scripts/capture-answers.ts`. It reads questions from `frontend/scripts/reference-questions.json`, posts each to a running system at `BASE_URL` (default `http://localhost:3000`), and writes every response to `frontend/tests/fixtures/answers/<slug>.json`.
  - Run it against the three sample manuals to capture at least 12 answered responses. They must cover each FR-008 Markdown element, primary and related images, a response without images, multi-page citations, low-confidence and generated sources, and a partial answer with `not_covered`.
  - Add `frontend/tests/fixtures/answers/index.ts`, which exports every fixture typed as the generated `Answer`.
- [X] T036 [US1] Write `frontend/tests/reference-answers.test.tsx`. For every answered fixture it renders the turn and asserts SC-001, SC-002 and SC-003:
  - Every citation has its source line with the exact document name and pages.
  - The primary image, when present, is beside the answer with caption and page.
  - No formatting characters remain.
  - Every flagged source carries its mark.
  - An answer written in Spanish is shown unchanged, while every interface label around it stays in English (FR-042).
- [X] T037 [P] [US1] Write `frontend/tests/e2e/ask-and-read.spec.ts` with Playwright route fakes serving the fixtures. It walks US1 scenarios 1 to 13 and runs an axe WCAG 2.1 AA check on the answered turn and on each open dialog.

### Implementation for User Story 1

- [X] T038 [P] [US1] Add `PageNotFoundError` to `backend/src/multimodal_rag/ingestion/errors.py` as a subclass of the existing not-found family with `code = "page_not_found"`, so the existing single mapping answers 404.
- [X] T039 [P] [US1] Add `ExtractedElement.page_image_key_for(*, document_id: uuid.UUID, page_number: int) -> str`, returning `pages/{document_id}/{page_number}.png`, in `backend/src/multimodal_rag/ingestion/domain.py`, next to `image_key_for`.
- [X] T040 [US1] Add `page_images: dict[int, bytes] = field(default_factory=dict)`, with its docstring ("PNG bytes of each page of the batch, keyed by 1-based page number"), to `ExtractionBatch` in `backend/src/multimodal_rag/ingestion/ports.py`. Make `FakeExtractor` in `backend/tests/fakes.py` fill it with a tiny valid PNG per page.
- [X] T041 [US1] Produce the page images in `backend/src/multimodal_rag/adapters/docling/extractor.py` (research section 12):
  - Set `generate_page_images=True` in `PdfPipelineOptions`, with a one-line comment saying the render already exists for figure crops.
  - Encode `result.document.pages[n].image.pil_image` of every page of the batch as PNG into `ExtractionBatch.page_images`.
  - A missing page image is a `CorruptDocumentError` naming the page.
- [X] T042 [US1] Store the page images in `ProcessJob._collect` in `backend/src/multimodal_rag/ingestion/use_cases/processing.py`, saving each with `self._blobs.save_bytes(ExtractedElement.page_image_key_for(...), png)` during the extraction stage.
- [X] T043 [US1] Add `GetPageImage` to `backend/src/multimodal_rag/ingestion/use_cases/library.py`, following data-model section 4.3 step by step, with a Google-style docstring listing each raised error.
- [X] T044 [US1] Expose the route:
  - `GetPageImageDep` in `backend/src/multimodal_rag/adapters/http/dependencies.py`.
  - `get_document_page_image` in `backend/src/multimodal_rag/adapters/http/routes_documents.py`: `GET /documents/{document_id}/pages/{page_number}/image`, `operation_id="getDocumentPageImage"`, `page_number: Annotated[int, Path(ge=1)]`, responses `{200: _PNG_RESPONSE, **problem_responses(400, 404, 409)}`.
  - Wire the use case in `backend/src/multimodal_rag/bootstrap.py`.
  - Rerun T006's export and `npm --prefix frontend run generate-client`.
- [X] T045 [P] [US1] Implement `frontend/src/answer/sourceLabel.ts` as tested in T028.
- [X] T046 [P] [US1] Implement the Markdown rendering in `frontend/src/answer/markdown/` (research section 9):
  - `citationMarkers.ts` turns `/\[(\d+)\]/g` in text nodes into `citation-ref` elements with `mdast-util-find-and-replace`, only for the numbers given as plugin options (`[citationMarkers, { numbers }]`, never in a closure, since Streamdown caches processors by plugin name and options).
  - `noRemoteMedia.ts` turns `image` nodes into their alt text.
  - `CitationMarker.tsx` renders a marker as an AI Elements `InlineCitation` link named "Citation {n}", with an `InlineCitationCard` preview of the source label and excerpt.
  - `AnswerMarkdown.tsx` renders AI Elements' `MessageResponse` with `mode="static"`, `parseIncompleteMarkdown={false}`, `controls={false}`, link safety off, Streamdown's `defaultRemarkPlugins` followed by the two plugins, and the rehype chain of Streamdown's `sanitize` (its schema extended with `citation-ref`) and `harden` without `rehype-raw`, so Streamdown shows raw HTML as text. Its `components` render `citation-ref` with `CitationMarker`, `strong` as `<strong>`, wrap tables in a scrollable region with `tabIndex=0`, and open links in a new tab with `rel="noopener noreferrer"`. It is wrapped in `React.memo`.
- [X] T047 [US1] Implement `frontend/src/answer/SourceList.tsx` as tested in T030, after T049 provides `PageDialog`, composing the shadcn/ui `Collapsible`, `Badge`, `Table` and `Button` for each source line and the AI Elements `Sources` disclosure for the other retrieved passages:
  - A citation's details come from the sources in its `unit_ids`, in rank order.
  - The flag marks come from `low_confidence_text`, `generated_description` and `unverified_identifiers`.
  - Each line's "Open page" opens `PageDialog` with the citation's pages.
  - `highlight(n)` is exposed through a ref.
- [X] T048 [P] [US1] Implement `frontend/src/answer/NotCoveredNote.tsx`, a shadcn/ui `Alert` labeled "Not covered by the documents" showing `not_covered` (FR-020).
- [X] T049 [P] [US1] Implement the viewers in `frontend/src/images/`:
  - `ImageDialog.tsx` and `PageDialog.tsx` use the shadcn/ui `Dialog`, opened through a `DialogTrigger` that wraps the opener, closed by Escape or a "Close" button, with focus returned to the opener (research section 13).
  - `PageDialog` builds the page URL from the generated client's path for `getDocumentPageImage` and steps only within the pages it was given.
  - Both use `FigureCard`'s unavailable state on load errors.
- [X] T050 [US1] Implement `frontend/src/images/FigureCard.tsx` and `frontend/src/images/ImageColumn.tsx` from the shadcn/ui `Card` and `Button`, as tested in T031:
  - Images use `loading="lazy"` and `decoding="async"` and the `url` returned by the service unchanged.
  - Each figure has "View full size" (opens `ImageDialog`) and "Open page" (opens `PageDialog` at the figure's page).
- [X] T051 [US1] Implement the conversation state:
  - `frontend/src/conversation/state.ts` holds the `Turn` and `Conversation` types exactly as data-model sections 1.1 and 1.2 (`state` is one of `held`, `waiting`, `answered`, `no_information`, `stopped` or `failed`), and a reducer with the actions `submitted`, `answered` and `cleared`.
  - `frontend/src/conversation/persistence.ts` loads and saves under `multimodal-rag.conversation.v1`, with the version and quota rules of data-model section 1.1.
- [X] T052 [US1] Implement `frontend/src/api/questions.ts`. `askQuestion({ question, documentIds, signal, waitSeconds })` calls the generated `askQuestion` through `callService`, omits `document_ids` when empty, and aborts with a `timed_out` failure after `waitSeconds`.
- [X] T053 [US1] Implement `frontend/src/conversation/useQuestionQueue.ts` for the single-question path. `submit(question)` dispatches `submitted`, calls `askQuestion` with `config.answerWaitSeconds`, and dispatches `answered` with the response and the attempt's `requestId`.
- [X] T054 [US1] Implement the conversation UI from AI Elements and shadcn/ui components (research section 14):
  - `frontend/src/conversation/QuestionInput.tsx`: AI Elements `PromptInputProvider`, `PromptInput`, `PromptInputTextarea` and `PromptInputSubmit`, with the textarea labeled "Ask a question about your manuals", Enter to send, Shift+Enter for a new line, and a disabled send for blank text.
  - `frontend/src/conversation/TurnView.tsx`: the question and the answer as AI Elements `Message` blocks, the answer in a two-column grid, with `AnswerMarkdown`, `NotCoveredNote` and `SourceList` on the left, and `ImageColumn` on the right only when the response has images.
  - `frontend/src/conversation/ConversationView.tsx`: AI Elements `Conversation`, `ConversationContent`, `ConversationEmptyState` and `ConversationScrollButton`, turns in order, the new answer scrolled into view, and "New conversation" with a shadcn/ui `AlertDialog` confirmation.
  - Mount it in `frontend/src/App.tsx`.
- [X] T055 [US1] Run `npm --prefix frontend run test:coverage`, `uv run --directory backend pytest --cov` and `npm --prefix frontend run test:e2e -- ask-and-read`. Then run quickstart scenario 2 against `docker compose up` after `docker compose down -v` and re-ingesting the FAA manual.

**Checkpoint**: User Story 1 works on its own. Answers render with sources, figures and
pages, and the history survives in the tab

---

## Phase 4: User Story 2 - Understand when the system cannot answer, is working or has failed (Priority: P1)

**Goal**: waiting, no-information and failure states are unmistakable. Stop, hold, retry
and reload never lose the conversation.

**Independent Test**: ask a question absent from every manual and see the distinct
no-information state. With the answer model pointed at a dead port, see the working
state, then "The answer model is not responding." with a reference and a retry. Restore
the model, retry, and the answer replaces the failure in the same turn (quickstart
scenarios 4 to 6).

### Tests for User Story 2 (REQUIRED) ⚠️

- [X] T056 [P] [US2] Extend `frontend/src/conversation/state.test.ts` with every transition in data-model section 1.2:
  - `held` to `waiting`, and `waiting` to `no_information`, `failed`, `stopped` (`user`) and `stopped` (`reload`).
  - `failed` or `stopped` to `held` on retry.
  - Invariants: at most one turn is `waiting`, and `requestId` is `null` while `held`.
- [X] T057 [P] [US2] Write `frontend/src/conversation/useQuestionQueue.test.tsx` with MSW delayed handlers:
  - **Holding.** Two questions submitted while one is waiting show as "Waiting to be sent" and are sent one at a time in order (FR-006).
  - **Stopping.** Stop cancels the open request: the turn becomes stopped with "Retry", its late answer is never shown, and the next held question starts (FR-007). MSW 3 stops forwarding aborts to handlers after earlier requests of the same test file, so the network abort is asserted in T061 through Playwright's `requestfailed` event.
  - **Retrying.** Retry sends the same question and restriction again, and the result replaces the failure in the same turn while other turns are unchanged (FR-028).
  - **Wait limit.** With `answerWaitSeconds` set to 1 and a handler that never answers, the turn fails with "The service did not answer in time." (FR-027).
- [X] T058 [P] [US2] Extend `frontend/src/conversation/persistence.test.ts`. A stored `waiting` turn loads as `stopped` with `stopReason: "reload"` and the text "Interrupted by a page reload". Stored `held` turns keep their order and are sent afterwards.
- [X] T059 [P] [US2] Write `frontend/src/answer/NoInformationState.test.tsx` (FR-021):
  - It has the "No information found" label, a distinct style (a `data-state="no-information"` attribute) and no source lines or images.
  - Its guidance matches data-model section 2.1: "upload" for `no_searchable_documents`, "Ask across all documents" for a restricted turn, "rephrase" otherwise.
  - Activating "Ask across all documents" submits the same question with an empty restriction.
- [X] T060 [P] [US2] Add failure fixtures to `frontend/tests/fixtures/answers/`:
  - Every `not_enough_information` reason (`no_searchable_documents`, `no_relevant_content`, `not_answered_by_sources` and `no_valid_citations`) as captured bodies.
  - A problem body for every question code in contracts/client.md section 3, including `answering_busy` with `Retry-After: 7`, so the reference set reaches at least 20 responses.
  - Extend `frontend/tests/reference-answers.test.tsx` to assert SC-007 for every failure fixture: the plain-English message, the reference, and a retry action where retryable.
- [X] T061 [P] [US2] Write `frontend/tests/e2e/states-and-failures.spec.ts`:
  - The working indicator appears within 500 ms of sending (SC-006).
  - The no-information state, the answer model failure with its reference and retry, and the busy message.
  - Stop and retry, and held questions.
  - A reload keeps every turn (SC-008).
  - A new browser context starts empty.
  - The connection notice appears when `/api` is unreachable and clears when it answers.

### Implementation for User Story 2

- [X] T062 [US2] Extend the reducer in `frontend/src/conversation/state.ts` with `held`, `sent`, `notEnoughInformation`, `failed`, `stopped` and `retried`, following data-model section 1.2, and keep `failure` as a `TurnFailure` from `toTurnFailure`.
- [X] T063 [US2] Extend `frontend/src/conversation/useQuestionQueue.ts` with holding, a single open `AbortController`, `stop()`, `retry(turnId)`, and the reload rule of T058.
  - For 400 `invalid_question`, return the question text to the input (FR-029).
  - For the `restriction` kind, the "Edit and ask again" action returns the text to the input.
- [X] T064 [US2] Update `frontend/src/conversation/persistence.ts` with the reload rule, which turns `waiting` into `stopped` (`reload`) on load.
- [X] T065 [P] [US2] Implement `frontend/src/answer/NoInformationState.tsx` from the shadcn/ui `Alert`, visually distinct from answers (a different background, border and lucide icon, labeled "No information found"). It shows the service's `answer` message and the guidance of data-model section 2.1. The "Upload a manual" action calls an `onRequestUpload` prop that US3 wires.
- [X] T066 [US2] Update the turn and input:
  - `frontend/src/conversation/TurnView.tsx` renders `waiting` as a working indicator with `role="status"`, the shadcn/ui `Spinner` and the text "Preparing the answer…", `held` as "Waiting to be sent", `stopped` with its reason and "Retry", `failed` with `FailureNotice`, and `no_information` with `NoInformationState`.
  - `frontend/src/conversation/QuestionInput.tsx` turns the send button into a "Stop" button while a turn is waiting, through `PromptInputSubmit`'s `status` and `onStop`.
- [X] T067 [US2] Mount `ConnectionNotice` in `frontend/src/App.tsx` above the conversation.
- [X] T068 [US2] Run the unit and e2e suites for US2, then quickstart scenarios 4 to 6, including the `grep` of a failure reference in `docker compose logs api` and the cancellation through nginx.

**Checkpoint**: User Stories 1 and 2 both work. Every non-answer outcome is clear and
recoverable

---

## Phase 5: User Story 3 - Upload a manual and follow its processing (Priority: P2)

**Goal**: a collapsible document panel uploads PDFs with transfer progress, lists the
library, and follows unfinished documents until ready or failed.

**Independent Test**: upload a sample manual from the panel. See it go from pending to
processing, with its stage and page count, to ready. Reload mid-way and it is still
followed. A non-PDF file and a corrupt PDF show readable reasons (quickstart scenario 1).

### Tests for User Story 3 (REQUIRED) ⚠️

- [X] T069 [P] [US3] Write `frontend/src/api/upload.test.ts` with MSW (which intercepts `XMLHttpRequest`):
  - **Progress.** Events report `sentFraction` from 0 to 1.
  - **Accepted.** 202 and 200 bodies resolve to `UploadAccepted`, including `already_ingested: true`.
  - **Rejected.** 400, 413, 415 and 422 problems resolve to `rejected` with the service `detail`.
  - **Failed.** A 5xx or a network error resolves to `failed`.
  - **Stalled.** No progress for `UPLOAD_STALL_SECONDS` (60 s, with fake timers) aborts as `failed` with "The service could not be reached.".
  - **Request id.** The request carries `X-Request-ID`.
- [X] T070 [P] [US3] Write `frontend/src/documents/DocumentStatus.test.tsx` for each row of data-model section 2.2:
  - Pending, including `latest_job: null`.
  - Processing, with each stage's plain words and "12 of 71 pages".
  - "Retrying (2 of 3)" when `attempt > 1`.
  - Ready, with "71 pages, 4 tables, 23 images".
  - Failed, with `failure_reason`.
- [X] T071 [P] [US3] Write `frontend/src/documents/useLibrary.test.tsx` with fake timers:
  - Only pending and processing documents are polled, every `statusPollSeconds`.
  - Polling stops once a job is completed or failed, and the list cache reflects the new status.
  - "Load more" fetches the next cursor page.
  - After a remount (a reload), unfinished documents are followed again (FR-035).
- [X] T072 [P] [US3] Write `frontend/src/documents/DocumentPanel.test.tsx`:
  - **Collapsing.** The panel starts open and collapses with a button labeled "Hide documents". The collapsed state shows a badge "{n} processing" and persists under `multimodal-rag.panel.v1` (FR-031).
  - **Uploads.** A non-PDF file is refused with "Only PDF files can be uploaded." before any request. An accepted upload shows its progress, then the document as pending. An `already_ingested` upload says "Already ingested". A rejected upload shows the service reason and adds nothing to the list (FR-032, FR-036).
  - **Failed documents.** They offer "Upload again" (FR-037).
  - **Duplicate uploads.** The same file uploaded twice at once, with both responses naming the same `document_id`, ends as one document in the list (spec edge cases).
- [X] T073 [P] [US3] Write `frontend/tests/e2e/documents.spec.ts` with route fakes that move a job through its states, covering US3 scenarios 1 to 10 and an axe check of the open and collapsed panel.

### Implementation for User Story 3

- [X] T074 [P] [US3] Implement `frontend/src/api/upload.ts` (research section 7, data-model section 1.6):
  - `uploadDocument(file, { onProgress })` with `XMLHttpRequest`, `FormData` field `file`, `X-Request-ID`, `upload.onprogress` and the 60 s stall timeout.
  - It returns `UploadAccepted` or the failure from `toUploadFailure`.
  - Export `isPdf(file)`, which accepts `type === "application/pdf"` or a name ending in `.pdf`, case-insensitive.
- [X] T075 [P] [US3] Implement `frontend/src/documents/DocumentStatus.tsx` with the labels of data-model section 2.2, a shadcn/ui `Badge` for the status, and a shadcn/ui `Progress` bar (`role="progressbar"` with `aria-valuenow`) while processing.
- [X] T076 [US3] Implement `frontend/src/documents/useLibrary.ts` with TanStack Query (research section 6):
  - `useInfiniteQuery` over `listDocuments` with `limit: 50`.
  - `useQueries` over `getDocument` for unfinished documents, with `refetchInterval: config.statusPollSeconds * 1000`, writing results into the list cache.
  - Default `retry` with exponential backoff, reporting unreachable failures to the connection store.
- [X] T077 [US3] Implement `frontend/src/documents/UploadControl.tsx`. A labeled native file input ("Upload a PDF"), opened by a shadcn/ui `Button`, holds the tracked uploads of data-model section 1.6 in component state. It shows transfer progress with `Progress`, rejections and failures with `FailureNotice`, and "Already ingested". Accepted uploads leave the list once their document appears in the library.
- [X] T078 [US3] Implement `frontend/src/documents/DocumentList.tsx` (rows with name and `DocumentStatus`, "Load more", "Upload again" on failed rows) and `frontend/src/documents/DocumentPanel.tsx`, the shadcn/ui `Sidebar` with `collapsible="icon"`, the processing badge in its collapsed rail, and its open state persisted under `multimodal-rag.panel.v1` instead of the component's cookie. Mount the panel in the left slot of `frontend/src/App.tsx` inside `SidebarProvider`.
- [X] T079 [US3] Wire `NoInformationState`'s `onRequestUpload` in `frontend/src/App.tsx` so it opens the panel and focuses the upload control.
- [X] T080 [US3] Run the US3 unit and e2e suites, then quickstart scenario 1 against the running system. Measure SC-009 with the worker log timestamps.

**Checkpoint**: User Stories 1, 2 and 3 work. Manuals can be added and followed from the
client

---

## Phase 6: User Story 4 - Restrict questions to selected documents (Priority: P3)

**Out of scope**: the maintainer left this story out on 2026-09-29. The question route
does not accept `document_ids` until User Story 6 of
`specs/002-grounded-question-answering` (tasks T062 to T065) is implemented. The tasks
below stay open for a later feature.

**Goal**: the technician selects ready documents to restrict the next questions. The
selection is visible and clearable, and each restricted turn shows its documents.

**Independent Test**: with two ready manuals, select one and ask a question. The turn
shows the restriction, and every source and image comes from that manual. Clear the
selection, and the next question uses all documents (quickstart scenario 7).

### Tests for User Story 4 (REQUIRED) ⚠️

- [ ] T081 [P] [US4] Write `frontend/src/documents/selection.test.ts` (data-model section 1.4):
  - Only documents whose latest job is `completed` can be added.
  - Adding beyond `maxFilterDocuments` is refused with "You can select up to {n} documents".
  - The selection persists under `multimodal-rag.selection.v1`.
  - Pruning removes documents that are missing or not completed and returns a notice naming each one (FR-041).
- [ ] T082 [P] [US4] Write `frontend/src/documents/DocumentList.selection.test.tsx`:
  - **Checkboxes.** Ready documents have a checkbox labeled with the file name, and non-ready documents have a disabled one whose description is the status (FR-038).
  - **Filter.** Typing "ins" in "Filter documents" shows only matching names.
  - **Chips.** The selection shows as removable chips next to the question input with "Clear selection" (FR-039).
- [ ] T083 [P] [US4] Extend `frontend/src/conversation/useQuestionQueue.test.tsx`:
  - A question sent with a selection carries `document_ids` equal to the selected ids.
  - The turn shows "Restricted to {names}" (FR-040).
  - A retry reuses the turn's snapshot even after the selection changed.
  - A 400 `unknown_documents` or 409 `documents_not_ready` prunes the selection and offers "Edit and ask again".
- [ ] T084 [P] [US4] Write `frontend/tests/e2e/restrict.spec.ts` covering US4 scenarios 1 to 6.

### Implementation for User Story 4

- [ ] T085 [US4] Implement `frontend/src/documents/selection.ts`: a selection store with `DocumentRef` items (`{ id, fileName }`), `add`, `remove`, `clear` and `prune(library)`, the `maxFilterDocuments` limit and `sessionStorage` persistence under `multimodal-rag.selection.v1`.
- [ ] T086 [US4] Add the filter box (shadcn/ui `Input`) and selection checkboxes (shadcn/ui `Checkbox`) to `frontend/src/documents/DocumentList.tsx`. Call `prune` from `frontend/src/documents/useLibrary.ts` on every library update and show its notices in the panel.
- [ ] T087 [US4] Show the selection chips (shadcn/ui `Badge` with a remove button) and "Clear selection" in `frontend/src/conversation/QuestionInput.tsx`, and snapshot the selection into `Turn.restriction` on submit in `frontend/src/conversation/useQuestionQueue.ts`.
- [ ] T088 [US4] Show "Restricted to {names}" in `frontend/src/conversation/TurnView.tsx`, and on `restriction` failures call `prune` before offering "Edit and ask again".
- [ ] T089 [US4] Run the US4 unit and e2e suites, then quickstart scenario 7.

**Checkpoint**: all user stories work on their own and together

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: CI, performance, accessibility, documentation and final validation

- [X] T090 Extend `.github/workflows/ci.yml`:
  - In `checks`, add `actions/setup-node` pinned by full commit SHA with `node-version-file: frontend/.node-version`, `cache: npm` and `cache-dependency-path: frontend/package-lock.json`, plus `npm --prefix frontend ci` before pre-commit.
  - Add a `frontend` job (`ubuntu-24.04`, `permissions: contents: read`, `persist-credentials: false`). It runs:
    - `npm ci`
    - The client drift check: `uv run --directory backend python scripts/export_openapi.py ../frontend/openapi.json && npm run generate-client && git diff --exit-code frontend/openapi.json frontend/src/client`, with uv set up as in `checks`.
    - `npm run test:coverage`
    - `npm run build`
    - `npx playwright install --with-deps`
    - `npm run test:e2e`
  - Confirm `uvx zizmor --persona=pedantic .github/workflows/` reports nothing.
- [X] T091 [P] Write `frontend/tests/e2e/long-conversation.spec.ts` (SC-010). It restores 50 answered turns with primary images into `sessionStorage`, reloads, and asserts the SC-010 thresholds: a typed character shows in the input within 100 ms, and an image dialog opens within 300 ms. Scrolling to the first turn completes.
- [X] T092 [P] Write `frontend/tests/e2e/accessibility.spec.ts`. It runs axe WCAG 2.1 AA over every main state: empty, answered with images, no information, failed, panel collapsed and each dialog. It also completes a question-to-page-view flow with the keyboard only (FR-044).
- [X] T093 [P] Write ADR `docs/adr/0006-chat-client-stack-and-serving.md`: a static React client served by nginx on the API's origin. It is written in business language, with the technical evidence from research sections 1 to 5, 11 and 14 in a final annex.
- [X] T094 [P] Write ADR `docs/adr/0007-page-images-at-ingestion.md`: page images kept from ingestion rather than rendered on request, with the measurements and alternatives of research section 12 in a final annex.
- [X] T095 Update `docs/images/architecture.drawio.svg` with the `frontend` (nginx) service in front of the API, using draw.io with official icons as the existing diagram does. Keep it editable, and start every label with a capital letter.
- [X] T096 Update `README.md`:
  - Features: the chat client.
  - Architecture: the frontend and the browser flow.
  - Getting started: open <http://localhost:3000>, and run `docker compose down -v` once when upgrading from a version without page images.
  - Usage: the client first, `curl` second.
  - Development: `npm --prefix frontend run dev`, and tests.
  - Design decisions: links to ADRs 0006 and 0007.
- [X] T097 [P] Add the frontend rows to the Commands table in `AGENTS.md`:
  - Install with `npm --prefix frontend ci`.
  - Develop with `npm --prefix frontend run dev`.
  - Lint, format and type check.
  - Test with coverage, and the end-to-end tests.
  - Regenerate the client after an API change.
- [X] T098 Run `npm --prefix frontend run test:coverage`, `uv run --directory backend pytest --cov` and `uv run --project backend pre-commit run --all-files`. Add unit tests wherever frontend coverage is below 90% or backend coverage below 90%.
- [ ] T099 Run the full `quickstart.md` against a fresh `docker compose down -v && docker compose up -d --build --wait`, including the walkthrough (scenario 9). Record the SC-004, SC-005, SC-009, SC-011 and SC-012 results in the pull request's Test plan.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies. T006 needs the backend installed with `uv sync --project backend`.
- **Foundational (Phase 2)**: depends on Setup and blocks every user story.
- **User stories (Phases 3 to 6)**: each depends on Foundational only. They can proceed in parallel or in priority order (US1 → US2 → US3 → US4).
- **Polish (Phase 7)**: depends on the stories being delivered. T090 can start as soon as the test scripts exist.

### User Story Dependencies

- **US1 (P1)**: independent. It carries the backend page image route, which only US1 displays.
- **US2 (P1)**: independent of US1 for its tests, which build turns directly with the reducer. It extends the files US1 creates (`state.ts`, `useQuestionQueue.ts`, `TurnView.tsx` and `QuestionInput.tsx`), so run it after US1 when one person works on both.
- **US3 (P2)**: independent. T079 wires a prop that US2 defines, and it is skipped if US2 is not delivered.
- **US4 (P3)**: needs the document list of US3 (`DocumentList.tsx` and `useLibrary.ts`) for selection. Its turn and queue changes are independent.

### Within Each User Story

- Tests first, and they must fail before implementation.
- Backend: errors, domain and ports, then the adapter and use case, then the route, then the client regeneration.
- Frontend: pure functions and state, then components, then the App wiring.

### Parallel Opportunities

- **Setup**: T002, T003, T004, T005 and T007 in parallel after T001.
- **Foundational**: tests T009 to T013 in parallel. Then T014, T015, T018, T019 and T020 in parallel, followed by T016, T017, T021, T022 and T023 in order.
- **US1**: the backend track (T024 to T027 and T038 to T044) and the frontend track (T028 to T037 and T045 to T054) run in parallel. Only T044's client regeneration joins them before T049, and T047 follows T049.
- **US3 and US4 tests** can be written while US2 is implemented.

---

## Parallel Example: User Story 1

```bash
# Backend and frontend tests together:
Task: "Backend unit tests for GetPageImage in backend/tests/unit/ingestion/test_library.py"
Task: "Contract test for getDocumentPageImage in backend/tests/contract/test_page_image_contract.py"
Task: "Source label tests in frontend/src/answer/sourceLabel.test.ts"
Task: "Markdown rendering tests in frontend/src/answer/markdown/AnswerMarkdown.test.tsx"
Task: "Image column tests in frontend/src/images/ImageColumn.test.tsx"

# Independent implementations together:
Task: "PageNotFoundError in backend/src/multimodal_rag/ingestion/errors.py"
Task: "page_image_key_for in backend/src/multimodal_rag/ingestion/domain.py"
Task: "sourceLabel in frontend/src/answer/sourceLabel.ts"
Task: "Markdown plugins and AnswerMarkdown in frontend/src/answer/markdown/"
Task: "NotCoveredNote in frontend/src/answer/NotCoveredNote.tsx"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) and Phase 2 (Foundational). The shell runs in Compose.
2. Complete Phase 3 (US1). Questions render with sources, the figure beside the answer,
   and full-size figure and page views.
3. **Stop and validate** with quickstart scenario 2. This already meets the challenge's
   key user-experience criterion.

### Incremental Delivery

1. **US1**: the cited answer with its image and page.
2. **US2**: clear waiting, no-information and failure states, with stop, hold, retry and
   reload.
3. **US3**: upload and processing from the client.
4. **US4**: restricting questions to selected documents.
5. **Polish**: CI, performance and accessibility checks, ADRs, README, and the full
   quickstart.

---

## Notes

- [P] tasks touch different files and depend on no unfinished task.
- The generated client in `frontend/src/client/` is never edited by hand. Regenerate it
  after any backend route change (T006, T044).
- The client displays the service's responses as returned (FR-022). Any change to the
  answer's content belongs to feature 002.
- Commit only when the maintainer asks, in Conventional Commits with a scope such as
  `feat(client): ...` or `feat(ingestion): ...`.
