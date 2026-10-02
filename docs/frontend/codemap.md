# Frontend codemap

A map of `frontend/`, one heading per folder. Each test sits next to the file it tests
as `*.test.ts` or `*.test.tsx`, and is left out of the tables below.

## Project root

| Path | Purpose |
| --- | --- |
| `index.html` | The page shell with the `#root` element |
| `package.json`, `package-lock.json` | Dependencies and scripts |
| `vite.config.ts` | Vite plugins, the `@` alias, the dev proxy to the API and the Vitest configuration with the coverage gate |
| `tsconfig*.json` | Strict TypeScript, including `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes` |
| `openapi.json` | The API contract exported from the backend, input of the generated client |
| `openapi-ts.config.ts` | How the client in `src/client/` is generated |
| `components.json` | shadcn/ui configuration: style, aliases and paths |
| `playwright.config.ts` | End-to-end tests on Chromium, Firefox and WebKit |
| `.oxlintrc.json`, `.prettierrc.json` | Lint and format rules |
| `Dockerfile`, `nginx/default.conf.template` | The production image and its nginx configuration |
| `public/config.json` | Runtime configuration used by `npm run dev` and `npm run preview` |
| `scripts/capture-answers.ts` | Records reference answers from a running system as test fixtures |
| `tests/` | Shared test setup, MSW handlers, fixtures and end-to-end specs |

## `src/` root

| File | Purpose |
| --- | --- |
| `main.tsx` | Entry point: applies the CSP nonce, loads the runtime config with backoff, renders `App` |
| `App.tsx` | The provider stack and the two-column layout |
| `config.ts` | `RuntimeConfig`, `loadConfig`, `ConfigContext`, `useConfig` |
| `csp.ts` | `applyStyleNonce`, which hands nginx's nonce to Radix's injected styles |
| `index.css` | Tailwind imports and the theme tokens |

## `src/api/`

The transport layer, the only folder that talks to the network.

| File | Purpose |
| --- | --- |
| `http.ts` | `callService`: request id, timeout, abort and failure classification for every SDK call. Also points the generated client at the page's origin |
| `questions.ts` | `askQuestion`, `POST /api/v1/questions` with the long answer wait |
| `upload.ts` | `uploadDocument` over XMLHttpRequest for progress, and `isPdf` |
| `images.ts` | `pageImageUrl`, typed by the generated route |
| `connection.ts` | The reachability store: `reportReachable`, `reportUnreachable`, `useServiceReachable` |

## `src/conversation/`

| File | Purpose |
| --- | --- |
| `state.ts` | `Turn`, `TurnState`, `ConversationAction`, `newTurn` and the pure `conversationReducer` |
| `persistence.ts` | Loading and saving the conversation in `sessionStorage` |
| `useConversation.ts` | The reducer plus saving after every change |
| `useQuestionQueue.ts` | Sends one question at a time: `submit`, `stop`, `retry`, `busy` |
| `turnActions.ts` | `TurnActionsContext`, the actions turns can call |
| `ConversationView.tsx` | Header with "New conversation", the turns and the input |
| `QuestionInput.tsx` | The prompt input, whose send button becomes stop while busy |
| `TurnView.tsx` | One turn, rendered by state, and the two-column answered layout |

## `src/answer/`

| File | Purpose |
| --- | --- |
| `citations.tsx` | `CitationProvider`: the highlighted citation and scrolling to its source line |
| `useCitations.ts` | `CitationContext` and `useCitations` |
| `sources.ts` | `citationSources`, `uncitedSources` |
| `sourceLabel.ts` | `formatPages` ("pages 3–5, 8") and `sourceLabel` |
| `SourceList.tsx` | Numbered source lines with quality badges, details and "Open page" |
| `NoInformationState.tsx` | The view of a not-enough-information answer |
| `NotCoveredNote.tsx` | The note for the part of a question the documents leave unanswered |
| `markdown/AnswerMarkdown.tsx` | Streamdown with sanitizing, our plugins and element overrides |
| `markdown/citationMarkers.ts` | Remark plugin that turns `[n]` into citation elements |
| `markdown/CitationMarker.tsx` | The clickable badge with its hover card |
| `markdown/noRemoteMedia.ts` | Remark plugin that replaces Markdown images with their alt text |

## `src/images/`

| File | Purpose |
| --- | --- |
| `figures.ts` | Titles, alt texts and locations of figures |
| `ImageColumn.tsx` | The primary figure, then the related ones |
| `FigureCard.tsx` | One figure with its caption, a fallback when it fails, and its dialogs |
| `ImageDialog.tsx` | A figure at full size |
| `PageDialog.tsx` | The rendered pages of a source or of a whole document |

## `src/documents/`

| File | Purpose |
| --- | --- |
| `useLibrary.ts` | The library with TanStack Query: paging, polling unfinished documents, refresh and remove |
| `status.ts` | `displayStatus`: pending, processing, ready or failed |
| `panelState.ts` | Saving whether the panel is collapsed |
| `documentPanelContext.ts` | `DocumentPanelContext`: `requestUpload`, `registerUploadFocus` |
| `DocumentPanelProvider.tsx` | Open state and the shadcn `SidebarProvider` |
| `DocumentPanel.tsx` | The sidebar holding the upload control and the list |
| `DocumentList.tsx` | Rows with status, "View document", "Upload again" and "Delete" |
| `DocumentStatus.tsx` | Badge, stage, progress, summary or failure reason |
| `UploadControl.tsx` | The file picker and the rows of uploads in progress |
| `DeleteDocumentDialog.tsx` | The confirmation dialog that deletes a document |

## `src/failures/`

| File | Purpose |
| --- | --- |
| `messages.ts` | `toTurnFailure`, `toDeletionFailure`, `toUploadFailure`, `NOT_A_PDF` |
| `FailureNotice.tsx` | A failure with its copyable reference and an optional action |
| `ConnectionNotice.tsx` | The banner shown while the API cannot be reached |

## `src/lib/`

| File | Purpose |
| --- | --- |
| `utils.ts` | `cn`, the class name helper shadcn components import |
| `plural.ts` | `nounFor` and `counted`, with English plural rules |

## Generated and vendored code

| Path | Origin | Edited by hand |
| --- | --- | --- |
| `src/client/` | Generated by `npm run generate-client` from `openapi.json`: `sdk.gen.ts` (one function per endpoint), `types.gen.ts`, `zod.gen.ts` and the fetch runtime | Never |
| `src/components/ui/` | shadcn/ui components on Radix, added with `npx shadcn add` | Rarely, and only for styling |
| `src/components/ai-elements/` | Vercel AI Elements: `PromptInput`, `Message`, `Conversation`, `InlineCitation`, `Sources` | Rarely |

## `tests/`

| Path | Purpose |
| --- | --- |
| `setup.ts` | Testing Library matchers, browser stand-ins, MSW lifecycle and per-test resets |
| `render.tsx` | `renderWithProviders`, with config, a fresh query client and tooltips |
| `msw/` | The mock API server and its default handlers |
| `fixtures/` | Answers captured from the real system or written to the contract, library pages and failure cases |
| `reference-answers.test.tsx` | Renders every reference answer and checks the result |
| `e2e/` | Playwright specs and the faked API they run against |
