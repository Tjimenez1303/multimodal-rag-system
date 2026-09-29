import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";

import { reportReachable } from "@/api/connection";

import { server } from "./msw/server";

// jsdom lacks these browser APIs. The stand-ins do the least the client relies on.
class ResizeObserverStandIn implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStandIn;
/** Elements passed to `scrollIntoView`, most recent last, so tests can see what scrolled. */
export const scrolledIntoView: Element[] = [];
Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
  scrolledIntoView.push(this);
};

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  sessionStorage.clear();
  scrolledIntoView.length = 0;
  reportReachable();
});

afterAll(() => {
  server.close();
});
