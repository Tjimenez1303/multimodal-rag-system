import type { DocumentBody } from "@/client";

/** The status a document shows, from its latest job. */
export type DisplayStatus = "pending" | "processing" | "ready" | "failed";

/**
 * The status of a document as the client shows it.
 *
 * @param document - The document as returned by the service.
 * @returns Pending (also without a job), processing, ready or failed.
 */
export function displayStatus(document: DocumentBody): DisplayStatus {
  switch (document.latest_job?.status) {
    case undefined:
    case "pending":
      return "pending";
    case "processing":
      return "processing";
    case "completed":
      return "ready";
    case "failed":
      return "failed";
  }
}
