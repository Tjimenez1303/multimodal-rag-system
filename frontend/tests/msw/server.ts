import { setupServer } from "msw/node";

import { handlers } from "./handlers";

/** Network fake shared by every Vitest test, started in `tests/setup.ts`. */
export const server = setupServer(...handlers);
