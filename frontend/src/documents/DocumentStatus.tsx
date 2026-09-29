import type { DocumentBody, JobStage } from "@/client";
import { displayStatus, type DisplayStatus } from "@/documents/status";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

/** Plain words for each processing stage (data-model section 2.2). */
const STAGE_WORDS: Record<JobStage, string> = {
  extracting: "Reading pages",
  describing_figures: "Describing figures",
  building_units: "Organizing content",
  embedding: "Preparing search",
  indexing: "Indexing",
  finalizing: "Finishing",
};

const BADGE: Record<DisplayStatus, { label: string; className: string }> = {
  pending: {
    label: "Pending",
    className: "border-border bg-muted text-muted-foreground",
  },
  processing: {
    label: "Processing",
    className: "border-primary/30 bg-primary/8 text-primary",
  },
  ready: {
    label: "Ready",
    className: "border-emerald-300 bg-emerald-50 text-emerald-800",
  },
  failed: {
    label: "Failed",
    className: "border-destructive/30 bg-destructive/8 text-destructive",
  },
};

/**
 * A document's processing status: its stage and pages while processing, a retry in
 * progress, a summary once ready, or the reason it failed (FR-034).
 *
 * @param props - The document as returned by the service.
 */
export function DocumentStatus({ document }: { document: DocumentBody }) {
  const status = displayStatus(document);
  const job = document.latest_job;
  const badge = BADGE[status];
  const retrying =
    job !== null && job.attempt > 1 && status !== "ready" && status !== "failed";
  const percent = job?.pages_total
    ? Math.round((job.pages_done / job.pages_total) * 100)
    : undefined;
  return (
    <div className="flex min-w-0 flex-col gap-1 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="outline" className={cn("rounded-sm", badge.className)}>
          {badge.label}
        </Badge>
        {retrying && (
          <span className="text-muted-foreground">
            Retrying ({job.attempt} of {job.max_attempts})
          </span>
        )}
      </div>
      {status === "processing" && job !== null && (
        <>
          <p className="text-muted-foreground">
            {job.stage ? STAGE_WORDS[job.stage] : "Starting"}
            {job.pages_total ? `, ${job.pages_done} of ${job.pages_total} pages` : ""}
          </p>
          <Progress
            value={percent ?? 0}
            aria-label={`Processing ${document.file_name}`}
            className="h-1"
          />
        </>
      )}
      {status === "ready" && job?.summary && (
        <p className="text-muted-foreground">
          {job.summary.pages} pages, {job.summary.tables} tables, {job.summary.images}{" "}
          images
        </p>
      )}
      {status === "failed" && job?.failure_reason && (
        <p className="leading-5 text-destructive">{job.failure_reason}</p>
      )}
    </div>
  );
}
