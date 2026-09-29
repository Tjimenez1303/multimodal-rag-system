import { render, screen } from "@testing-library/react";

import type { DocumentBody, JobStage } from "@/client";
import { DocumentStatus } from "@/documents/DocumentStatus";

import {
  completedDocument,
  failedDocument,
  pendingDocument,
  processingDocument,
} from "../../tests/fixtures/documents/library";

function withJob(
  fields: Partial<NonNullable<DocumentBody["latest_job"]>>,
): DocumentBody {
  return {
    ...processingDocument,
    latest_job: { ...processingDocument.latest_job!, ...fields },
  };
}

test("a document without a job yet is pending", () => {
  render(<DocumentStatus document={pendingDocument} />);

  expect(screen.getByText("Pending")).toBeInTheDocument();
});

test("a pending job is pending", () => {
  render(<DocumentStatus document={withJob({ status: "pending", stage: null })} />);

  expect(screen.getByText("Pending")).toBeInTheDocument();
});

test.each<[JobStage, string]>([
  ["extracting", "Reading pages"],
  ["describing_figures", "Describing figures"],
  ["building_units", "Organizing content"],
  ["embedding", "Preparing search"],
  ["indexing", "Indexing"],
  ["finalizing", "Finishing"],
])("processing at %s shows %s with the page count", (stage, words) => {
  render(<DocumentStatus document={withJob({ stage })} />);

  expect(screen.getByText("Processing")).toBeInTheDocument();
  expect(screen.getByText(words, { exact: false })).toBeInTheDocument();
  expect(screen.getByText("12 of 71 pages", { exact: false })).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "17");
});

test("a retried job says it is retrying", () => {
  render(<DocumentStatus document={withJob({ attempt: 2, max_attempts: 3 })} />);

  expect(screen.getByText("Retrying (2 of 3)")).toBeInTheDocument();
});

test("a completed document is ready with a summary of what was captured", () => {
  render(<DocumentStatus document={completedDocument} />);

  expect(screen.getByText("Ready")).toBeInTheDocument();
  expect(screen.getByText("71 pages, 4 tables, 23 images")).toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

test("a failed document shows the service's reason", () => {
  render(<DocumentStatus document={failedDocument} />);

  expect(screen.getByText("Failed")).toBeInTheDocument();
  expect(
    screen.getByText("The PDF is damaged and cannot be read."),
  ).toBeInTheDocument();
});
