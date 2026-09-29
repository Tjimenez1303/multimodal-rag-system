import { reportReachable, reportUnreachable } from "@/api/connection";
import type { ServiceFailure } from "@/api/http";
import type { UploadAccepted, UploadDocumentData } from "@/client";
import { zProblem, zUploadAccepted } from "@/client/zod.gen";
import { toUploadFailure, type UploadFailure } from "@/failures/messages";

/** An upload fails when no transfer progress arrives for this long (research section 7). */
export const UPLOAD_STALL_SECONDS = 60;

// Typed by the generated client, so a change to the route breaks compilation.
const UPLOAD_URL: UploadDocumentData["url"] = "/api/v1/documents";

/** Outcome of an upload, with the same shapes as the generated SDK's results. */
export type UploadResult =
  | { ok: true; data: UploadAccepted; requestId: string }
  | { ok: false; failure: UploadFailure };

/**
 * Whether a file can be sent as a PDF: its type says so, or its name ends in `.pdf`
 * (FR-032). Every other limit is checked by the service.
 *
 * @param file - The chosen file.
 * @returns `true` for a PDF.
 */
export function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

/**
 * Send a PDF to the service with transfer progress (FR-032).
 *
 * `fetch` exposes no upload progress, so the file goes through `XMLHttpRequest` as
 * `multipart/form-data`, field `file`, with an `X-Request-ID`.
 *
 * @param file - The PDF to upload.
 * @param options - `onProgress` receives the sent fraction, from 0 to 1.
 * @returns The accepted upload, or why it was rejected or failed.
 */
export function uploadDocument(
  file: File,
  { onProgress }: { onProgress: (sentFraction: number) => void },
): Promise<UploadResult> {
  const requestId = crypto.randomUUID();
  const body = new FormData();
  body.append("file", file);
  return new Promise((resolve) => {
    const request = new XMLHttpRequest();
    let stall: ReturnType<typeof setTimeout> | undefined;
    const fail = (failure: ServiceFailure) => {
      clearTimeout(stall);
      resolve({ ok: false, failure: toUploadFailure(failure) });
    };
    // A transfer that makes no progress for a minute is given up.
    const watchStall = () => {
      clearTimeout(stall);
      stall = setTimeout(() => {
        request.abort();
        reportUnreachable();
        fail({ kind: "unreachable", requestId });
      }, UPLOAD_STALL_SECONDS * 1000);
    };
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && event.total > 0)
        onProgress(event.loaded / event.total);
      watchStall();
    });
    request.upload.addEventListener("load", () => onProgress(1));
    request.addEventListener("error", () => {
      reportUnreachable();
      fail({ kind: "unreachable", requestId });
    });
    request.addEventListener("load", () => {
      clearTimeout(stall);
      resolve(outcome(request, requestId));
    });
    request.open("POST", UPLOAD_URL);
    request.setRequestHeader("X-Request-ID", requestId);
    onProgress(0);
    watchStall();
    request.send(body);
  });
}

function outcome(request: XMLHttpRequest, requestId: string): UploadResult {
  const body = parseJson(request.responseText);
  if (request.status >= 200 && request.status < 300) {
    reportReachable();
    const accepted = zUploadAccepted.safeParse(body);
    return accepted.success
      ? { ok: true, data: accepted.data as UploadAccepted, requestId }
      : { ok: false, failure: toUploadFailure({ kind: "unreadable", requestId }) };
  }
  const problem = zProblem.safeParse(body);
  if (problem.success) {
    reportReachable();
    return {
      ok: false,
      failure: toUploadFailure({
        kind: "problem",
        status: request.status,
        code: problem.data.code,
        detail: problem.data.detail ?? null,
        requestId,
        retryAfterSeconds: null,
      }),
    };
  }
  // nginx answers with its own page when the API is down.
  reportUnreachable();
  return { ok: false, failure: toUploadFailure({ kind: "unreachable", requestId }) };
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
