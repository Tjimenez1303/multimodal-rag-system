import { useSyncExternalStore } from "react";

// Whether the latest call reached the service. Shared by every caller of the API.
let reachable = true;
const listeners = new Set<() => void>();

function publish(next: boolean): void {
  // Notify the subscribers only when the value changes
  if (next === reachable) return;
  reachable = next;
  for (const listener of listeners) listener();
}

/** Record that a call failed before any response from the service. */
export function reportUnreachable(): void {
  publish(false);
}

/** Record that a call received a response from the service. */
export function reportReachable(): void {
  publish(true);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Follow whether the service can be reached (FR-030).
 *
 * @returns `true` until a call fails to reach the service, and again after any call
 *   gets a response.
 */
export function useServiceReachable(): boolean {
  return useSyncExternalStore(subscribe, () => reachable);
}
