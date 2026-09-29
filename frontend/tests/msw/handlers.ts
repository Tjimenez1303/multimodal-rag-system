import { http, HttpResponse } from "msw";

import type { AnswerBody, Problem, UploadAccepted } from "@/client";
import type { RuntimeConfig } from "@/config";

import { libraryPage } from "../fixtures/documents/library";

/** The runtime configuration nginx serves by default. */
export const defaultConfig: RuntimeConfig = {
  answerWaitSeconds: 105,
  maxFilterDocuments: 20,
  statusPollSeconds: 2,
};

/** A plain answered response without images, for tests that only need an answer. */
export const plainAnswer: AnswerBody = {
  status: "answered",
  reason: null,
  answer: "Check the ignition leads for chafing and loose terminals [1].",
  not_covered: null,
  citations: [
    {
      number: 1,
      document_id: libraryPage.items[0]!.id,
      document_name: "faa-powerplant-ch4-ignition-electrical.pdf",
      pages: [12],
      unit_ids: ["0b0e7a3c-1f1a-4c8e-9a51-6a9d1f3e2c01"],
    },
  ],
  sources: [
    {
      unit_id: "0b0e7a3c-1f1a-4c8e-9a51-6a9d1f3e2c01",
      rank: 1,
      similarity: 0.82,
      document_id: libraryPage.items[0]!.id,
      document_name: "faa-powerplant-ch4-ignition-electrical.pdf",
      section: ["Ignition System Maintenance", "Ignition Leads"],
      pages: [12],
      content_type: "text",
      excerpt: "Inspect the ignition leads for chafing, burns and loose terminals.",
      cited: true,
      citation_number: 1,
      low_confidence_text: false,
      generated_description: false,
      unverified_identifiers: [],
      tables: [],
      figure_ids: [],
    },
  ],
  primary_image: null,
  related_images: [],
};

/** A 1 × 1 transparent PNG, served for figure and page images. */
export const PNG_1X1 = Uint8Array.from(
  atob(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  ),
  (character) => character.charCodeAt(0),
);

/**
 * Build an RFC 9457 problem response like the API's.
 *
 * @param status - HTTP status.
 * @param code - Problem code.
 * @param options - Detail, request id and extra headers.
 * @returns The problem response.
 */
export function problem(
  status: number,
  code: string,
  options: {
    detail?: string;
    requestId?: string;
    headers?: Record<string, string>;
  } = {},
): HttpResponse<Problem> {
  const body: Problem = {
    type: "about:blank",
    title: "Problem",
    status,
    instance: "/api/v1/questions",
    code,
    request_id: options.requestId ?? "server-generated-id",
    ...(options.detail === undefined ? {} : { detail: options.detail }),
  };
  return HttpResponse.json(body, {
    status,
    headers: { "Content-Type": "application/problem+json", ...options.headers },
  });
}

const uploadAccepted: UploadAccepted = {
  document_id: "5d3ff0f9-f671-4a1b-b3e6-3258071fa024",
  job_id: "5d3ff0f9-0000-4000-8000-00000000000a",
  status: "pending",
  already_ingested: false,
};

/** Default handlers: a healthy service with the library fixture. */
export const handlers = [
  http.get("/config.json", () => HttpResponse.json(defaultConfig)),
  http.get("/api/v1/documents", () => HttpResponse.json(libraryPage)),
  http.get("/api/v1/documents/:documentId", ({ params }) => {
    const document = libraryPage.items.find((item) => item.id === params["documentId"]);
    return document
      ? HttpResponse.json(document)
      : problem(404, "document_not_found", { detail: "No such document." });
  }),
  http.post("/api/v1/questions", () => HttpResponse.json(plainAnswer)),
  http.post("/api/v1/documents", () =>
    HttpResponse.json(uploadAccepted, { status: 202 }),
  ),
  http.get(
    "/api/v1/documents/:documentId/images/:elementId",
    () => new HttpResponse(PNG_1X1, { headers: { "Content-Type": "image/png" } }),
  ),
  http.get(
    "/api/v1/documents/:documentId/pages/:pageNumber/image",
    () => new HttpResponse(PNG_1X1, { headers: { "Content-Type": "image/png" } }),
  ),
];
