# Research: Visual Chat Client

Decisions taken during planning, with the alternatives considered and the evidence behind
each one. Versions are the latest published on 2026-09-29 unless a compatibility
constraint is stated. Section numbers are referenced from [plan.md](plan.md) and
[data-model.md](data-model.md).

## 1. Framework and language

- **Decision**: a static single-page application written in TypeScript with React 19.3,
  built with Vite 8.3 and `@vitejs/plugin-react` 6.1. TypeScript is pinned to `~6.0`.
- **Rationale**:
  - The maintainer chose it over Next.js, Vue and Streamlit during planning.
  - It is the stack of the official FastAPI reference codebase,
    `fastapi/full-stack-fastapi-template` (React 19, Vite 8, TypeScript, TanStack Query).
  - Everything the client does happens in the browser. The history lives in the tab and
    no page needs server rendering, so a framework with its own server process adds a
    runtime without a requirement behind it.
- **TypeScript version**: TypeScript 7.0 is the latest release, but the official Vite
  `react-ts` template still pins `~6.0.2`, and part of the tooling (for example
  `typescript-eslint`, peer `<6.1.0`) has not caught up. `~6.0` follows the official
  template.
- **Alternatives considered**:
  - **Next.js**: server rendering and file routes that this single-screen client does
    not use, plus a Node server in Compose.
  - **Vue with Vite**: technically equivalent, but it departs from the reference
    template.
  - **Streamlit**: the two-column turn, the keyboard-operable viewers, the linked `[n]`
    markers and Markdown sanitizing all work against the framework's layout model.

## 2. Node, package manager and lockfile

- **Decision**: Node 24 (the "Krypton" LTS line, 24.21 at planning time), pinned in
  `frontend/.node-version` and in the build image. npm is the package manager, with a
  committed `package-lock.json` and `npm ci` in CI and in the image.
- **Rationale**:
  - Node 24 is the active LTS line. Node 26 becomes LTS only in October 2026.
  - npm ships with Node, so no extra tool is installed. A committed lockfile mirrors the
    backend's `uv.lock` rule.
- **Alternatives considered**: Bun, which the reference template uses. It is one more
  runtime to install, and nothing here needs its speed.

## 3. Lint, format and type checking

- **Decision**:
  - **oxlint** 1.86 lints, with its `react`, `typescript`, `jsx-a11y` and `import`
    plugins. The `react` plugin implements `rules-of-hooks` and `exhaustive-deps`.
  - **Prettier** 3.9 formats.
  - `tsc -b` type-checks in strict mode.
- **Rationale**:
  - The constitution asks for the official linter and formatter of the chosen framework.
  - The official Vite scaffold (`create-vite`, template `react-ts`) ships oxlint as its
    `lint` script.
  - react.dev's editor setup page recommends Prettier for formatting and the hooks
    rules for linting.
- **Alternatives considered**:
  - **ESLint with typescript-eslint**: it works with TypeScript 6.0, but it replaces the
    scaffold's choice with a slower toolchain for the same rules.
  - **Biome**, used by the reference template: it is neither the scaffold's choice nor
    react.dev's recommendation.

## 4. Serving: nginx on the same origin as the API

- **Decision**: a `frontend` Compose service built in two stages. A `node:24-alpine`
  stage runs `npm ci` and `npm run build`, and an `nginx:1.30-alpine` stage (stable line)
  serves `dist/`. nginx reverse-proxies `/api/` to `http://api:8000`, and the browser only
  ever talks to the frontend origin.
- **Rationale**: the maintainer chose it during planning.
  - No CORS is needed.
  - `AnswerImage.url` and element image URLs are relative paths and work unchanged.
  - `X-Request-ID` and `Retry-After` are readable without `Access-Control-Expose-Headers`.
  - Principle IX lists the frontend as its own service.
- **nginx configuration** (official image):
  - **Templating**: the image renders `/etc/nginx/templates/*.template` with `envsubst`
    at start, so runtime values come from the environment.
  - **Upload streaming**: `/api/` sets `proxy_request_buffering off` and
    `client_max_body_size 0`. Uploads stream to the API, whose own body limits answer
    with problem details, instead of nginx rejecting them with an HTML page.
  - **Timeouts**: `proxy_read_timeout` comes from `NGINX_PROXY_READ_TIMEOUT`, 120 s by
    default, which is the client wait limit plus 15 s (section 11). nginx then never
    cuts a question the client is still waiting for.
  - **Runtime configuration**: the official image renders templates only into
    `conf.d`, so `/config.json` is answered by `location = /config.json` with
    `return 200` and a JSON body filled from the environment, in the same template.
  - **Cancellation**: `proxy_ignore_client_abort` stays at its default `off`, so when
    the browser aborts a question nginx closes the upstream connection, and the API's
    disconnect listener (feature 002) cancels the question. This is verified in the
    quickstart.
  - **Security headers**: `Content-Security-Policy` with `default-src 'self'`,
    `img-src 'self' data: blob:`, `connect-src 'self'`, `script-src 'self'`,
    `style-src 'self'`, `object-src 'none'`, `base-uri 'none'` and
    `frame-ancestors 'none'`. It enforces FR-046 (no external resources) and backs up
    FR-009. The same headers add `X-Content-Type-Options: nosniff` and
    `Referrer-Policy: no-referrer`.
  - **Routing**: `try_files $uri /index.html` for the single route, long-lived caching
    for hashed assets and `no-cache` for `index.html`.
  - **Health**: `/healthz` returns 200 from nginx itself, and the Compose healthcheck
    probes it with BusyBox `wget`.
  - **Logging** (Principle VII): a `log_format` with `escape=json` writes one JSON line
    per request to standard output. It holds `$time_iso8601`, the level `info`, the
    logger name `nginx.access`, `$request_method`, `$uri` (the path without the query
    string), `$status`, `$request_time` and `$http_x_request_id`. It never holds
    `$remote_addr` or request bodies. `/healthz` is not logged, like the API's quiet
    health routes.
- **Development**: `npm run dev` uses Vite's `server.proxy` for `/api`, so the dev server
  is same-origin too.
- **Alternatives considered**:
  - **Separate origins with CORS**: needs `CORSMiddleware`, exposed headers and absolute
    image URLs.
  - **FastAPI serving the build**, as the reference template now does: it mixes a Node
    build into the Python image and removes the frontend service that Principle IX
    names.

## 5. Typed API client

- **Decision**:
  - `@hey-api/openapi-ts` 0.99 generates the TypeScript types and a fetch-based SDK into
    `frontend/src/client/`.
  - The input is `frontend/openapi.json`, exported from the backend's FastAPI app by
    `backend/scripts/export_openapi.py`.
  - Generated files are committed, and CI regenerates them and fails on any difference.
- **Rationale**:
  - This is the reference template's flow (`scripts/generate-client.sh` exports
    `app.openapi()`, then `openapi-ts` generates the client).
  - The backend contract tests already prove the served document equals the feature
    contracts, so the client is typed from the contracts without parsing three
    cross-referenced YAML files.
- **Plugins**: `@hey-api/client-fetch`, `@hey-api/typescript`, `zod` and
  `@hey-api/sdk` with `validator: { request: false, response: "zod" }`. They are declared
  explicitly rather than relying on the default plugin list. The SDK then validates every
  response body against the contract schema with zod 4.6, which the reference template
  also uses. A body that fails validation becomes the `unreadable` failure.
- **Client behavior**:
  - A request interceptor adds `X-Request-ID` (section 10).
  - Every call has a timeout. A question uses the wait limit of section 11, an upload
    the stall timeout of section 7, and every other call (`/config.json`,
    `listDocuments`, `getDocument`) `SERVICE_CALL_TIMEOUT_SECONDS`, 10 s, through
    `AbortSignal.timeout`. A timed-out call is the `timed_out` failure, and TanStack
    Query retries it with backoff.
  - Every call accepts an `AbortSignal`.
  - A response interceptor turns `application/problem+json` bodies into a typed
    `ServiceFailure` (data-model section 2.4).
- **Alternatives considered**: `openapi-typescript` 7.13 with `openapi-fetch`. Its peer
  range is `typescript ^5.x`, which conflicts with TypeScript 6 under npm's strict peer
  resolution.

## 6. Server state and polling

- **Decision**: TanStack Query 5.104 for the document library.
  - The list uses an infinite query over `listDocuments` (50 per page, newest first).
  - Every document whose latest job is `pending` or `processing` has its own query on
    `getDocument` with `refetchInterval: 2000`. The interval stops when the job reaches
    `completed` or `failed`, and the result updates the list cache.
- **Rationale**: SC-009 asks for status changes to show within 5 s in 95% of cases, and a
  2 s interval gives at most 2 s plus one round trip. Polling only unfinished documents
  keeps the cost independent of library size. A reload re-derives the unfinished set from
  the list, which satisfies FR-035. Refetch on window focus and on reconnect are kept.
- **Questions do not use TanStack Query**. They go through the question queue (section 8)
  and call the generated SDK with an `AbortController` directly, because their ordering,
  holding and cancellation rules are specific to this feature.
- **Alternatives considered**: a server push channel (Server-Sent Events). It needs a new
  backend endpoint and a LISTEN/NOTIFY bridge for a gain of about one second over
  polling.

## 7. Upload with transfer progress

- **Decision**: uploads use `XMLHttpRequest` with `FormData` and `upload.onprogress`,
  wrapped in a small typed function that returns the same `UploadAccepted` or
  `ServiceFailure` shapes as the generated SDK. Every other call uses `fetch`.
- **Rationale**: `fetch` exposes no upload progress events. Streaming request bodies need
  `duplex: "half"` and are limited to Chromium over HTTP/2, which FR-043 excludes.
- **Pre-check**: the client refuses a file whose type is not `application/pdf` and whose
  name does not end in `.pdf`, as FR-032 allows. Size and page limits stay with the
  service.
- **Stalled transfers**: a 200 MB transfer has no meaningful total deadline, so the
  upload fails as "could not be reached" when no progress event arrives for 60 s
  (`UPLOAD_STALL_SECONDS` in the client constants). The server response after the last
  byte is bounded by the API's own timeouts.

## 8. Conversation state, question queue and persistence

- **Decision**:
  - **State**: one `useReducer` holds the conversation (data-model section 1), and a
    queue hook sends one question at a time.
  - **Persistence**: an effect writes the conversation to `sessionStorage` under a
    versioned key.
- **Rationale**: `sessionStorage` matches the clarified behavior exactly, as defined in
  the HTML Living Standard. It survives reloads of the same tab and is discarded when the
  tab closes. Other tabs start empty, except a tab created with "Duplicate tab", which
  gets a copy (browser-defined).
- **Queue rules**:
  - The oldest `held` turn is sent when no turn is `waiting`.
  - The stop button aborts the `waiting` turn's request. A retry re-enters the queue as a
    held turn in its original position in the conversation.
- **Reload rules**:
  - A turn restored as `waiting` lost its request with the old page, so it becomes
    `stopped` with the reason "interrupted by a reload" and a retry action.
  - `held` turns keep their order and are sent afterwards.
- **Storage limits**: a 50-turn conversation with full responses measures in the low
  hundreds of kilobytes, below the usual 5 MB `sessionStorage` quota. A
  `QuotaExceededError` keeps the conversation in memory and shows a notice that it will
  not survive a reload, instead of failing silently.
- **Alternatives considered**:
  - **A state library (Redux Toolkit, Zustand)**: the state is one reducer with a
    handful of actions.
  - **`localStorage` or IndexedDB**: both outlive the tab, which contradicts the
    clarification.

## 9. Markdown rendering and content safety

- **Decision**: `react-markdown` 10.1 with `remark-gfm` 4.0 (tables, strikethrough and
  task lists), and three small remark plugins in `src/answer/markdown/`:
  - **`htmlAsText`** turns mdast `html` nodes into `text` nodes. Raw markup is then shown
    literally (FR-009) instead of being dropped, which is `react-markdown`'s default.
  - **`citationMarkers`** uses `mdast-util-find-and-replace` 3.0, the utility
    `remark-gfm` itself relies on, to turn `[n]` in text nodes into citation nodes when
    `n` is a citation number of the response. Code spans and code blocks are not text
    nodes, so markers inside code stay literal. Other bracketed numbers stay text.
  - **`noRemoteMedia`** renders Markdown images as their alt text and never as `<img>`,
    so no answer can make the browser load an external resource (FR-046).
- **Rationale**: `react-markdown` builds React elements from a syntax tree and never uses
  `dangerouslySetInnerHTML`. Its default `urlTransform` removes `javascript:` and other
  unsafe URLs. Links keep their text and open in a new tab with
  `rel="noopener noreferrer"`. The CSP (section 4) is the second layer.
- **Wide tables**: they scroll horizontally inside a wrapper, not the page.
- **Performance**: the rendered answer is memoized per turn, so typing in the input does
  not re-parse 50 answers (SC-010).
- **Alternatives considered**:
  - **`marked` with DOMPurify**: it produces HTML strings that React must inject.
  - **`rehype-sanitize`**: it removes markup instead of showing it as text.

## 10. Request references

- **Decision**: the client creates the correlation identifier itself with
  `crypto.randomUUID()` and sends it as `X-Request-ID` on every call. It stores the
  identifier on the turn or upload, and shows it as "Reference: <id>" under a failure
  (FR-025).
- **Rationale**: the API echoes a safe incoming id (`RequestContextMiddleware` accepts
  `[A-Za-z0-9._:-]{1,128}`, which a UUID satisfies) and binds it to every log line of the
  request. Generating it in the browser means a reference exists even when the request
  never reached the service. Problem bodies also carry `request_id`, and the client
  checks that it matches.

## 11. Client wait limit and runtime configuration

- **Decision**:
  - nginx serves `/config.json`, rendered from environment variables at container start
    (data-model section 3). It holds:
    - `answerWaitSeconds`: `ANSWER_WAIT_SECONDS`, 105 s by default, which is the
      service's 90 s `ANSWER_DEADLINE_SECONDS` plus 15 s.
    - `maxFilterDocuments`: `MAX_FILTER_DOCUMENTS`, 20 by default.
    - `statusPollSeconds`: `STATUS_POLL_SECONDS`, 2 by default.
  - The client loads it once before rendering.
  - `.env.example` declares `MAX_FILTER_DOCUMENTS` once, and Compose passes it to both
    `api` and `frontend`, so the two cannot drift. Compose cannot add numbers, so
    `ANSWER_WAIT_SECONDS` is its own variable, documented next to
    `ANSWER_DEADLINE_SECONDS` with the rule "keep it 15 s above the deadline".
- **Rationale**:
  - The spec asks for a configurable wait limit longer than the service deadline.
  - Principle IX asks for environment-specific values to come from the environment, not
    from the build. Vite `import.meta.env` values are baked in at build time.
  - The margin covers the waiting line and network time. The service's own deadline
    already includes waiting, so a longer margin only delays reporting a lost
    connection.
- **Failure**: when `/config.json` is unreachable or invalid, the client shows the
  connection notice (FR-030) and retries. It never starts with guessed values.

## 12. Page images produced at ingestion

- **Decision**:
  - The worker stores a PNG of every page while it extracts the document.
    `DoclingExtractor` sets Docling's `generate_page_images=True`. The page images come
    from the same render Docling already makes at `images_scale=2.0` (144 dpi) to crop
    figures.
  - `ExtractionBatch` gains `page_images: dict[int, bytes]`, and `ProcessDocument` saves
    them under `pages/{document_id}/{page}.png` in the existing blob storage.
  - A new route, `GET /api/v1/documents/{document_id}/pages/{page_number}/image`, serves
    them for completed documents. It is the only backend change of this feature.
- **Rationale**:
  - AGENTS.md and Principle III keep PDF processing out of HTTP requests. Rendering on
    demand in the API would run PDFium inside a request, under the process-wide
    `pypdfium2_lock` shared with uploads.
  - At ingestion the render already exists, so the cost is encoding and storage only.
  - Keys are derived from the document id and page number, so a retried job overwrites
    the same objects, which keeps jobs idempotent.
- **Measurements** (reference machine, sample manuals, 144 dpi, pages 1 to 24):

  | Manual | Page size (px) | PNG median | PNG max | Encode median |
  |---|---|---|---|---|
  | FAA powerplant, ch. 4 (digital) | 1188 × 1548 | 497 KB | 855 KB | 21 ms |
  | INSST electrical risk guide (digital) | 1191 × 1684 | 464 KB | 658 KB | 19 ms |
  | TM 5-3431 welding machine (scanned) | 1126 × 1488 | 351 KB | 1169 KB | 17 ms |

  About 0.45 MB per page, so a 100-page manual adds about 45 MB, and 100 such manuals add
  about 4.5 GB to the blob volume. Encoding adds about 2 s to a 100-page job.
- **Route behavior**:
  - Unknown document: 404 `document_not_found`.
  - Latest job not completed: 409 `ingestion_not_completed`, as the elements route does.
  - Page outside 1 to `page_count`: 404 `page_not_found`.
  - Stored page missing for a completed document: 500 `data_inconsistency`, as a missing
    figure crop is (Principle VI).
- **Existing data**: documents completed before this change have no page images. In this
  pre-release project the blob and database volumes are recreated
  (`docker compose down -v`), which the quickstart states. No backfill job is built.
- **Alternatives considered**:

  | Alternative | Size per page | Encode time | Why rejected |
  |---|---|---|---|
  | Lossless WebP, effort 2 | 113 to 197 KB | 48 to 339 ms | About 3 times smaller, but up to 16 times slower to encode, adding up to 30 s to a 100-page job. The storage saving does not matter on a local volume |
  | Lossy WebP, quality 85 | 140 to 201 KB | 57 to 68 ms | Compression artifacts around small print defeat the purpose of checking recognized text against the page |
  | JPEG, quality 85 | 220 to 351 KB | 2 to 3 ms | Same artifacts, larger than WebP |
  | Render on request in the API, with a cache | none stored until viewed | 22 to 75 ms render | PDF processing inside an HTTP request, contention on the PDFium lock |
  | Render in the worker with pypdfium2 | same as PNG | render plus encode | Renders every page a second time, since Docling already rendered it |
  | Download of the original PDF | none | none | Clarified as option C and not chosen. It opens a separate viewer and loses the conversation context |

## 13. Image and page viewers

- **Decision**:
  - The full-size image view and the page view use the native `<dialog>` element opened
    with `showModal()`. Images in the conversation use `loading="lazy"` and
    `decoding="async"`.
  - The page view shows one page at a time, with previous and next controls limited to
    the pages of the source it was opened from. For a figure, those are its own page.
- **Rationale**:
  - `showModal()` puts the dialog in the top layer, makes the rest of the page inert,
    moves focus into the dialog, closes on Escape and returns focus to the opener. That
    covers FR-016, FR-018 and FR-044 without a dialog library, and it is Baseline widely
    available.
  - Lazy loading keeps a 50-turn conversation from loading every image at once (SC-010).
- **Text alternatives**: every image's alt text is built from its caption, document name
  and page, for example "Figure 4-12, Ignition harness. FAA_Powerplant.pdf, page 12"
  (FR-044).
- **Alternatives considered**: Radix Dialog, which the reference template uses. It adds a
  dependency for behavior the platform provides.

## 14. Layout and styling

- **Decision**: CSS Modules (built into Vite) with design tokens as CSS custom
  properties. No UI kit.
  - **Layout**: a CSS grid with the collapsible document panel on the left and the
    conversation on the right (FR-031).
  - **Turns**: each turn is a two-column grid, with the answer text and source lines on
    the left and the image column on the right. The grid collapses to one column when the
    response has no images (FR-015).
  - **Minimum size**: 1280 × 720 (FR-043).
- **Rationale**: the interface is one screen with a few components, and CSS Modules keep
  styles scoped without a build dependency. The palette meets WCAG 2.1 AA contrast, which
  the axe checks in section 15 verify.
- **Alternatives considered**: Tailwind CSS with shadcn/ui, as in the reference template.
  It suits larger applications with many screens.

## 15. Testing

- **Unit and component tests**: Vitest 5.0 with jsdom 30, React Testing Library 16 and
  `user-event` 14.
  - **Fakes**: HTTP is faked at the network level with MSW 3 handlers that serve
    contract-shaped fixtures. This is the frontend counterpart of `respx`. Modules are not
    replaced with `vi.mock`, and test doubles are not `vi.fn()` spies asserted on call
    sequences, following Principle VIII's spirit.
  - **Coverage**: `@vitest/coverage-v8` enforces a 90% line coverage gate on `src/`,
    excluding the generated client.
- **Reference answer set**: `frontend/tests/fixtures/answers/` holds at least 20
  responses, as described in the spec's Success Criteria.
  - `frontend/scripts/capture-answers.ts` captures them from a running system. It runs
    with Node's built-in TypeScript type stripping (unflagged in Node 24).
  - Hand-written fixtures cover the failures a live system cannot produce on demand.
  - Every fixture is type-checked against the generated client types.
  - Component tests drive SC-001, SC-002, SC-003 and SC-007 over the whole set.
- **End-to-end tests**: Playwright 1.63 against `vite preview`. The API is faked with
  Playwright route handlers that serve the same fixtures.
  - **Browsers**: Chromium, Firefox and WebKit projects (FR-043).
  - **Scenarios**: every user story's happy path, reload persistence (SC-008), stop and
    retry, held questions, and the viewers.
  - **Accessibility**: `@axe-core/playwright` 4.13 checks WCAG 2.1 AA rules on the main
    states (FR-044).
- **Backend**: pytest tests for the page image route, the new use case and the extractor
  change, with the existing fakes and contract helpers. `tests/contract/contract.py`
  registers the 003 contract. The 90% backend gate stays.
- **Live checks**: the quickstart covers the manual and timing criteria (SC-004, SC-005,
  SC-006, SC-009, SC-010, SC-011, SC-012) against the running system.

## 16. Tooling and CI

- **pre-commit**: new local hooks run `npm --prefix frontend run lint`, `format:check` and
  `typecheck` on `^frontend/` changes. The existing typos, end-of-file and
  trailing-whitespace hooks cover frontend files too.
- **CI**:
  - The `checks` job sets up Node from `frontend/.node-version` with `actions/setup-node`
    pinned by SHA and runs `npm ci` before pre-commit.
  - A new `frontend` job runs the Vitest coverage gate, the generated-client drift
    check, the production build and Playwright with its three browsers.
  - Workflows stay audited by zizmor.
- **Typos**: generated client files are excluded in `_typos.toml`.

## 17. Walkthrough for SC-004 and SC-005

- **Decision**: a scripted walkthrough in the quickstart.
  - Five people who have not used the client get the three sample manuals already
    ingested.
  - They get four tasks: find a source's page, open the image at full size, tell a
    no-information reply apart from an answer, and upload a manual then ask about it.
  - The facilitator records the times and the outcome of each task.
- **Rationale**: these criteria are about people, not code. A fixed script keeps the
  measurement repeatable.
