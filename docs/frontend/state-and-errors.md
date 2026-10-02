# State and errors

## Where state lives

Each kind of state has one home, chosen by who owns it and how long it lives.

| State | Home | Why there |
| --- | --- | --- |
| Document library and statuses | TanStack Query cache, in `documents/useLibrary.ts` | Server state that needs caching, retries, paging and polling |
| The conversation | `useReducer` with `conversationReducer`, saved to `sessionStorage` | Client state that must survive a reload of the tab but not leak to other tabs |
| The text in the question input | AI Elements' `PromptInputProvider` | Shared between the input and the code that puts a rejected question back |
| Whether the panel is collapsed | `DocumentPanelProvider`, saved to `sessionStorage` | Survives a reload |
| Whether the API is reachable | A small store in `api/connection.ts`, read with `useSyncExternalStore` | Written by every call, read by the global notice |
| Runtime configuration | `ConfigContext` | Loaded once at boot |
| Uploads in progress, dialogs, broken images | Local `useState` in the component | Nobody else needs them |

Questions do not use TanStack Query on purpose. A question is a one-off command with a
long wait, a stop button and a strict order, which the reducer and the queue model
directly.

### The conversation reducer

[`conversation/state.ts`](../../frontend/src/conversation/state.ts) holds the turn
states and the pure reducer that moves turns between them:

```
submitted ──> waiting ──> answered | no_information | failed | stopped
          └─> held ──(sent)──┘
failed | stopped ──(retried)──> held
```

Every transition names the states it may leave from, and `updateTurn` ignores an event
for a turn in any other state. A late answer to a question the user already stopped is
therefore dropped instead of overwriting the stopped turn. A turn saved as `waiting` is
restored as stopped after a reload, because its request died with the old page.

### Contexts

| Context | Provides | Used by |
| --- | --- | --- |
| `ConfigContext` | Runtime configuration | `useConfig()` everywhere |
| `DocumentPanelContext` | `requestUpload`, which opens the panel and focuses the upload button | The conversation's "Upload a manual" buttons |
| `TurnActionsContext` | Retry, edit, ask across all documents, request upload | Turns, which are memoized and must not re-render when the actions change |
| `CitationContext` | The highlighted citation of one answer and how to activate it | `CitationMarker` and `SourceList` |

## How failures are handled

Failures are handled in three layers, so components never inspect HTTP themselves.

1. **Classification.** `callService` (`api/http.ts`) and `uploadDocument`
   (`api/upload.ts`) sort every outcome into a `ServiceFailure`:

   | Kind | Meaning |
   | --- | --- |
   | `problem` | The API answered an RFC 9457 problem. Carries its status, `code`, `detail` and `Retry-After` |
   | `unreachable` | No response, or nginx answered 502, 503 or 504 because the API is down |
   | `timed_out` | The client's own timer expired |
   | `unreadable` | A response arrived but its body could not be read |

   Every failure carries the `X-Request-ID` the client sent. Each response also updates
   the reachability store, which shows or hides the global `ConnectionNotice`.

2. **Messages.** [`failures/messages.ts`](../../frontend/src/failures/messages.ts) turns
   a failure into a plain-English message and the action it allows. Questions use
   `toTurnFailure` (retry, edit or nothing, with specific messages for a busy system,
   the answer model, search or the deadline), deletions use `toDeletionFailure` and
   uploads use `toUploadFailure`. Messages never show codes or internal details.

3. **Display.** `FailureNotice` shows the message, the reference with a copy button, and
   the action, inside the turn, the upload row or the delete dialog.

An aborted request, such as a stopped question, is not a failure. It throws an
`AbortError` that the caller expects and ignores.
