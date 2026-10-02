# How-to guides

Recipes for common changes. Paths are relative to `frontend/` unless noted.

## Call a new API endpoint

1. Add the endpoint to the backend, as described in the
   [backend guide](../backend/how-to.md#add-an-endpoint).
2. Export the contract and regenerate the client from the repository root:

   ```bash
   uv run --directory backend python scripts/export_openapi.py ../frontend/openapi.json
   npm --prefix frontend run generate-client
   ```

   The new operation appears in `src/client/sdk.gen.ts` under its `operation_id`, with
   its types in `types.gen.ts` and zod schemas in `zod.gen.ts`.
3. Wrap it in `src/api/`:

   ```ts
   export function getThing(id: string): Promise<ServiceResult<ThingBody>> {
     return callService((options) => getThingOperation({ ...options, path: { id } }));
   }
   ```

   `callService` adds the request id, the timeout and the failure classification.
4. Use it from a component or a hook. For data that is read and refreshed, prefer a
   TanStack Query hook like `useLibrary`. For a one-off command, call it from an event
   handler.
5. Add a default MSW handler in `tests/msw/handlers.ts` so component tests can render
   without a real API.

## Add a failure message

1. Find the problem `code` the API sends.
2. Add it to `PROBLEM_MESSAGES` in `src/failures/messages.ts`, or add a branch to
   `describeProblem` when it needs a different action, such as letting the user edit.
3. Add a case to `src/failures/messages.test.ts`.

## Add a shadcn/ui or AI Elements component

```bash
cd frontend
npx shadcn@latest add <component>
```

The CLI writes the component into `src/components/ui/`, using the aliases in
`components.json`. AI Elements components come from their own registry the same way.
Customize them through props and class names, so a later update can overwrite the file.

## Add a runtime setting

Runtime settings change with the container's environment, without a rebuild.

1. Add the field to `RuntimeConfig` and to `runtimeConfigSchema` in `src/config.ts`.
2. Add it to `public/config.json` for development.
3. Add it to the `/config.json` response in `nginx/default.conf.template`, as a
   `${VARIABLE}` placeholder.
4. Give it a default in the `ENV` of `Dockerfile`, and pass it in the `frontend`
   service of `compose.yaml`. Describe it in `.env.example`.
5. Read it with `useConfig()`.

## Add a conversation state or action

1. Add the state to `TurnState` or the action to `ConversationAction` in
   `src/conversation/state.ts`.
2. Handle it in `conversationReducer`, listing the states the event may leave from in
   the call to `updateTurn`. That list is what keeps late events from overwriting newer
   outcomes.
3. Render the state in `TurnOutcome` (`src/conversation/TurnView.tsx`).
4. Cover the transition in `src/conversation/state.test.ts`.

## Change how answers are rendered

- Element styles and overrides live in the `components` map of
  `src/answer/markdown/AnswerMarkdown.tsx`.
- A new Markdown rule is a remark plugin, like `citationMarkers` or `noRemoteMedia`,
  added to `remarkPlugins`. If it emits a new element, allow it in the sanitize schema
  in the same file.
- Check the result against every reference answer with
  `npm run test -- tests/reference-answers.test.tsx`.
