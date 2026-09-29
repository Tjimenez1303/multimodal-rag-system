# 0006. A browser chat client served next to the API

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: project maintainer

## Context and problem statement

Technicians need to ask questions about the manuals and read each answer with the
document and page it comes from and the figure it depends on, right next to it. They
also need to add manuals and follow their processing without leaving the conversation.
The client must start with the rest of the system in one command, must never send
questions or documents to an outside service, and must show the service's answers
exactly as returned, with no answering logic of its own.

What is the client built with, and how does it reach the service?

## Decision drivers

- The answer, its sources and its figure are readable at a glance on a desktop screen.
- Nothing is loaded from, or sent to, a service outside the system (FR-046).
- Text that came from a document is never executed or rendered as active content (FR-009).
- One start command, with the client reporting its own health.
- Failures are explained in plain words, with a reference that locates them in the logs.
- The interface is built from maintained component libraries rather than written by hand.

## Considered options

1. A single-page React client, served by nginx on the same address as the API.
2. A Next.js application with its own server process.
3. A Streamlit application.

## Decision outcome

Chosen option: **a single-page React client served by nginx on the same address as the
API**. The interface is composed from shadcn/ui components and Vercel AI Elements, the
chat components built on them. The browser only ever talks to the client's own address,
and nginx forwards the API calls. A strict content security policy forbids every other
source.

### Consequences

- Good, because the conversation, the answer with its figure, the source lines and the
  page views come from maintained components, and the feature's own code only holds its
  logic.
- Good, because there is no cross-origin setup, and image addresses returned by the
  service work unchanged.
- Good, because `docker compose up` starts the client with a health check, and the
  runtime settings come from the environment, not from the build.
- Good, because every failure shows a reference that is the same identifier the API
  writes in its logs.
- Bad, because the answer renderer's defaults render raw HTML and load remote images,
  so the client configures it explicitly and tests that configuration.
- Bad, because a library that injects styles at runtime needs a per-request nonce in the
  security policy.

## Annex: technical evidence

### Stack

| Concern | Choice | Version |
|---|---|---|
| Framework and build | React with Vite and TypeScript (strict) | 19.3, 8.3, 6.0 |
| Components | shadcn/ui on Radix primitives, Tailwind CSS, lucide icons | CLI 4.21, Tailwind 4.3 |
| Chat components | Vercel AI Elements: Conversation, Message, MessageResponse (Streamdown), PromptInput, InlineCitation, Sources | 1.9, Streamdown 2.6 |
| Server state | TanStack Query | 5.104 |
| Typed API client | `@hey-api/openapi-ts`, generated from the API's OpenAPI description, responses validated with zod | 0.99 |
| Lint, format | oxlint, Prettier | 1.86, 3.9 |
| Tests | Vitest with Testing Library and MSW, Playwright with axe | 5.0, 1.63 |
| Serving | `nginx:1.30-alpine`, templates rendered from the environment | 1.30 |

### Answer rendering and content safety

- Streamdown runs in static mode with incomplete-Markdown repair off, so the text is
  shown exactly as returned.
- Without `rehype-raw` in its rehype chain, Streamdown turns raw HTML into text. Images
  are rendered as their alt text by a remark plugin, because the default hardening
  allows every remote image and adds a preload link for it.
- `[n]` markers become citation links through a remark plugin whose numbers travel as
  plugin options, because Streamdown caches its processor by plugin name and options.
- A prototype confirmed the defaults rendered `<b>`, loaded a remote image and repaired
  `**unclosed`. The configured renderer showed all three as written.

### Serving

- nginx proxies `/api/` with request buffering off and no body limit, so uploads stream
  to the API, and its read timeout stays above the client's 105-second wait limit.
- Docker's DNS is re-read every 10 seconds, so a recreated API container is found again.
- `/config.json` carries the runtime settings, `/healthz` answers the Compose health
  check, and access logs are JSON lines without client addresses or query strings.
- The security policy is `default-src 'self'` with `style-src 'self' 'nonce-…'`. Radix
  locks page scrolling behind dialogs with an injected `<style>` element. The policy
  blocked it until nginx started writing each response's `$request_id` into the
  placeholder that Vite's `html.cspNonce` option leaves in the page, and the client
  started handing that nonce to `get-nonce`.

### Measurements on the reference machine

Apple M4 Pro, the Compose stack, 2026-09-29.

| Criterion | Target | Result |
|---|---|---|
| SC-006 working indicator | 0.5 s | Rendered with the turn, before the request starts. End-to-end test under 500 ms |
| SC-009 status change shown | 95% within 5 s | 9 of 9 changes shown within 1.97 s, 2-second polling |
| SC-010 50 turns with images | Typing 100 ms, image 300 ms | Both under their limits in the end-to-end test |
| SC-011 page view | 3 s | Page PNG served in 12 to 14 ms |

### Sources

- https://ui.shadcn.com/docs/installation/vite
- https://ai-sdk.dev/elements
- https://streamdown.ai
- https://vite.dev/config/shared-options#html-cspnonce
- https://nginx.org/en/docs/http/ngx_http_sub_module.html
- https://github.com/fastapi/full-stack-fastapi-template
- Full analysis: `specs/003-visual-chat-client/research.md`, sections 1 to 5, 9, 11,
  13 and 14
