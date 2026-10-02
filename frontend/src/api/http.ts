import { reportReachable, reportUnreachable } from "@/api/connection";
import { client } from "@/client/client.gen";
import { zProblem } from "@/client/zod.gen";

// The page's own origin: nginx serves the client and proxies /api on it. It is spelled
// out because fetch outside a browser, as in the tests, needs an absolute URL.
client.setConfig({ baseUrl: window.location.origin });

/** Timeout of every call except questions and uploads (research section 5). */
export const SERVICE_CALL_TIMEOUT_SECONDS = 10;

// nginx answers these statuses with its own page when the API is down.
const GATEWAY_STATUSES = new Set([502, 503, 504]);

/** Why a call to the service failed (data-model section 2.4). */
export type ServiceFailure =
  | {
      kind: "problem";
      status: number;
      code: string;
      detail: string | null;
      requestId: string;
      retryAfterSeconds: number | null;
    }
  | { kind: "unreachable"; requestId: string }
  | { kind: "timed_out"; requestId: string }
  | { kind: "unreadable"; requestId: string };

/** Outcome of a call, carrying the `X-Request-ID` it was sent with. */
export type ServiceResult<T> =
  { ok: true; data: T; requestId: string } | { ok: false; failure: ServiceFailure };

/** What a call to the generated SDK receives from `callService`. */
export interface CallOptions {
  headers: Record<string, string>;
  signal: AbortSignal;
}

/** The shape every generated SDK function resolves to when it does not throw. */
export interface SdkResult<T> {
  data?: T | undefined;
  error?: unknown;
  response?: Response | undefined;
}

/**
 * Call the service through the generated SDK and classify the outcome.
 *
 * The call carries a fresh `X-Request-ID`, which is also the failure reference shown to
 * the user (FR-025), and a timeout. A caller that aborts through `signal` gets the
 * platform's `AbortError`, as with `fetch`.
 *
 * @param operation - Calls one SDK function with the given options.
 * @param options - `signal` to abort the call, and `timeoutSeconds`, 10 s by default.
 * @returns The response body, or the failure.
 * @throws {DOMException} `AbortError` when `signal` aborts the call.
 */
export async function callService<T>(
  operation: (options: CallOptions) => Promise<SdkResult<T>>,
  {
    signal,
    timeoutSeconds = SERVICE_CALL_TIMEOUT_SECONDS,
  }: { signal?: AbortSignal; timeoutSeconds?: number } = {},
): Promise<ServiceResult<T>> {
  // Tag the call with an id the user can quote, and prepare to abort it
  const requestId = crypto.randomUUID();
  const controller = new AbortController();
  let timedOut = false;
  // A timer of our own, rather than AbortSignal.timeout, so fake timers control it.
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutSeconds * 1000);

  // Abort as well when the caller aborts, for example with the stop button
  const abortFromCaller = () => controller.abort(signal?.reason);
  if (signal?.aborted) abortFromCaller();
  signal?.addEventListener("abort", abortFromCaller, { once: true });
  try {
    // Run the generated SDK call with the id header and the abort signal
    const result = await operation({
      headers: { "X-Request-ID": requestId },
      signal: controller.signal,
    });

    // Our own timer fired: report a timeout, not an abort
    if (timedOut) {
      return { ok: false, failure: { kind: "timed_out", requestId } };
    }

    // The caller aborted: let them handle it
    if (signal?.aborted) {
      throw new DOMException("The call was aborted.", "AbortError");
    }

    // Sort the response into success or one kind of failure
    return classify(result, requestId);
  } finally {
    // Always clear the timer and the abort listener
    clearTimeout(timer);
    signal?.removeEventListener("abort", abortFromCaller);
  }
}

function classify<T>(result: SdkResult<T>, requestId: string): ServiceResult<T> {
  // No response at all: the network or nginx could not be reached
  const { response } = result;
  if (response === undefined) {
    reportUnreachable();
    return { ok: false, failure: { kind: "unreachable", requestId } };
  }

  // A success status still needs a readable JSON body
  if (response.ok) {
    reportReachable();
    // A deletion answers 204 with no body, so there is nothing to read.
    if (response.status === 204) {
      return { ok: true, data: undefined as T, requestId };
    }
    const isJson = response.headers.get("Content-Type")?.includes("json") ?? false;
    if (result.error !== undefined || !isJson) {
      return { ok: false, failure: { kind: "unreadable", requestId } };
    }
    return { ok: true, data: result.data as T, requestId };
  }

  // An error with an RFC 9457 body comes from the API itself
  const problem = zProblem.safeParse(result.error);
  if (problem.success) {
    reportReachable();
    return {
      ok: false,
      failure: {
        kind: "problem",
        status: response.status,
        code: problem.data.code,
        detail: problem.data.detail ?? null,
        // The sent id is the reference, even if the body names another one.
        requestId,
        retryAfterSeconds: retryAfterSeconds(response),
      },
    };
  }

  // A gateway error without a problem body means the API is down
  if (GATEWAY_STATUSES.has(response.status)) {
    reportUnreachable();
    return { ok: false, failure: { kind: "unreachable", requestId } };
  }

  // Anything else answered, but could not be read
  reportReachable();
  return { ok: false, failure: { kind: "unreadable", requestId } };
}

function retryAfterSeconds(response: Response): number | null {
  // Only a whole number of seconds is accepted
  const header = response.headers.get("Retry-After");
  if (header === null || !/^\d+$/.test(header.trim())) return null;
  return Number(header.trim());
}
