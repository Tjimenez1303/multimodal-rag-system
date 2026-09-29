import type { DocumentBody, DocumentPageBody, JobBody } from "@/client";

const CREATED = "2026-09-29T08:00:00Z";

function job(documentId: string, fields: Partial<JobBody>): JobBody {
  return {
    id: `${documentId.slice(0, 8)}-0000-4000-8000-00000000000a`,
    document_id: documentId,
    status: "pending",
    stage: null,
    attempt: 1,
    max_attempts: 3,
    pages_done: 0,
    pages_total: null,
    failure_code: null,
    failure_reason: null,
    summary: null,
    created_at: CREATED,
    started_at: null,
    finished_at: null,
    ...fields,
  };
}

export const COMPLETED_ID = "9660318f-9004-4fa9-925c-fb616874f516";
export const PROCESSING_ID = "73c717ef-eac1-41a0-9ac9-7665a72f4f5f";
export const PENDING_ID = "06187a89-5984-40cf-a33b-ccc0a4e07aa8";
export const FAILED_ID = "4f6dd233-dcab-4db0-bbd0-91aab80e33d2";

export const completedDocument: DocumentBody = {
  id: COMPLETED_ID,
  file_name: "faa-powerplant-ch4-ignition-electrical.pdf",
  size_bytes: 9_512_331,
  page_count: 71,
  created_at: CREATED,
  latest_job: job(COMPLETED_ID, {
    status: "completed",
    stage: "finalizing",
    pages_done: 71,
    pages_total: 71,
    started_at: CREATED,
    finished_at: CREATED,
    summary: {
      pages: 71,
      text_elements: 1204,
      tables: 4,
      table_chains: 0,
      images: 23,
      figures_described: 20,
      figures_skipped: 3,
      figures_not_described: 0,
      retrieval_units: 311,
      recognized_pages: 0,
    },
  }),
};

export const processingDocument: DocumentBody = {
  id: PROCESSING_ID,
  file_name: "insst-guia-riesgo-electrico.pdf",
  size_bytes: 3_104_556,
  page_count: 71,
  created_at: CREATED,
  latest_job: job(PROCESSING_ID, {
    status: "processing",
    stage: "extracting",
    pages_done: 12,
    pages_total: 71,
    started_at: CREATED,
  }),
};

export const pendingDocument: DocumentBody = {
  id: PENDING_ID,
  file_name: "tm-5-3431-201-10-welding-machine-scanned.pdf",
  size_bytes: 14_201_992,
  page_count: 65,
  created_at: CREATED,
  latest_job: null,
};

export const failedDocument: DocumentBody = {
  id: FAILED_ID,
  file_name: "damaged-manual.pdf",
  size_bytes: 20_480,
  page_count: 3,
  created_at: CREATED,
  latest_job: job(FAILED_ID, {
    status: "failed",
    stage: "extracting",
    failure_code: "corrupt_document",
    failure_reason: "The PDF is damaged and cannot be read.",
    started_at: CREATED,
    finished_at: CREATED,
  }),
};

/** One page of the library with a document in each state. */
export const libraryPage: DocumentPageBody = {
  items: [completedDocument, processingDocument, pendingDocument, failedDocument],
  next_cursor: null,
};
