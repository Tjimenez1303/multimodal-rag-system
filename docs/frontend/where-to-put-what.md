# Where to put what

Find the row that matches what you are adding. Paths are relative to `frontend/src/`.

| I want to add | It goes in | Notes |
| --- | --- | --- |
| A call to an API endpoint | A function in `api/`, wrapping the generated SDK function with `callService` | Components never call `fetch` or the SDK directly |
| A type of a request or response body | Nowhere: import it from `client/` | Regenerate the client after an API change instead of writing types by hand |
| A component of the conversation | `conversation/` | Turns read their actions from `TurnActionsContext` |
| Part of how an answer is rendered | `answer/`, or `answer/markdown/` for Markdown | A Markdown rule is a remark plugin passed to `AnswerMarkdown` |
| A figure or page viewer | `images/` | `PageDialog` is shared by answers and documents |
| Something in the document panel | `documents/` | Server data goes through `useLibrary` |
| A user-facing failure message | `failures/messages.ts` | Keyed by the API's problem `code` |
| A small helper with no React or feature knowledge | `lib/` | Check the installed libraries first |
| A conversation state or transition | `conversation/state.ts` | Keep the reducer pure, and list the states each event may leave from |
| A runtime setting | `RuntimeConfig` and its schema in `config.ts`, `public/config.json`, the `/config.json` location in `nginx/default.conf.template`, and the Dockerfile and compose environment | See [How-to guides](how-to.md#add-a-runtime-setting) |
| A shadcn/ui or AI Elements component | `components/ui/` or `components/ai-elements/`, through the shadcn CLI | Never write one by hand when the registry has it |
| A shared test helper | `tests/` | MSW handlers in `tests/msw/handlers.ts`, fixtures in `tests/fixtures/` |
| An end-to-end scenario | `tests/e2e/` | The API is faked in `tests/e2e/fakes.ts` |

## What never goes where

- Nothing edits `client/` by hand. It is overwritten on the next generation.
- Components do not inspect HTTP statuses. They receive a `ServiceFailure` already
  classified and a message from `failures/`.
- Answer Markdown never gets `rehype-raw` or any other way to render raw HTML.
