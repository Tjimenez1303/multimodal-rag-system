import { RotateCcwIcon } from "lucide-react";

import type { DocumentBody } from "@/client";
import { Button } from "@/components/ui/button";
import { DocumentStatus } from "@/documents/DocumentStatus";
import { displayStatus } from "@/documents/status";

/** Props of {@link DocumentList}. */
export interface DocumentListProps {
  documents: readonly DocumentBody[];
  isLoading: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  /** Open the file picker to send a failed document's file again (FR-037). */
  onUploadAgain: () => void;
}

/**
 * Every document the service knows, newest first, with its status, loading further
 * documents on demand (FR-033, FR-034).
 */
export function DocumentList({
  documents,
  isLoading,
  hasMore,
  onLoadMore,
  onUploadAgain,
}: DocumentListProps) {
  if (isLoading) {
    return <p className="px-1 text-xs text-muted-foreground">Loading documents…</p>;
  }
  if (documents.length === 0) {
    return (
      <p className="px-1 text-xs leading-5 text-muted-foreground">
        No documents yet. Upload a PDF manual to ask about it.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <ul
        aria-label="Documents"
        className="flex flex-col divide-y rounded-lg border bg-background"
      >
        {documents.map((document) => (
          <li key={document.id} className="flex flex-col gap-1.5 px-3 py-2.5">
            <span className="truncate text-sm font-medium" title={document.file_name}>
              {document.file_name}
            </span>
            <DocumentStatus document={document} />
            {displayStatus(document) === "failed" && (
              <Button
                variant="outline"
                size="xs"
                className="w-fit"
                onClick={onUploadAgain}
              >
                <RotateCcwIcon aria-hidden="true" />
                Upload again
              </Button>
            )}
          </li>
        ))}
      </ul>
      {hasMore && (
        <Button variant="ghost" size="sm" onClick={onLoadMore}>
          Load more
        </Button>
      )}
    </div>
  );
}
