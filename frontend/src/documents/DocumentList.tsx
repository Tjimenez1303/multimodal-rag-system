import { FileTextIcon, RotateCcwIcon } from "lucide-react";

import type { DocumentBody } from "@/client";
import { Button } from "@/components/ui/button";
import { DeleteDocumentDialog } from "@/documents/DeleteDocumentDialog";
import { DocumentStatus } from "@/documents/DocumentStatus";
import { displayStatus } from "@/documents/status";
import { PageDialog } from "@/images/PageDialog";

/** Props of {@link DocumentList}. */
export interface DocumentListProps {
  documents: readonly DocumentBody[];
  isLoading: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  /** Open the file picker to send a failed document's file again (FR-037). */
  onUploadAgain: () => void;
  /** Called once a document was deleted (FR-048). */
  onDeleted: (documentId: string) => void;
}

/** Every page number of a ready document, from its page count or its job's summary. */
function everyPage(document: DocumentBody): number[] {
  const count = document.page_count ?? document.latest_job?.summary?.pages ?? 0;
  return Array.from({ length: count }, (_, index) => index + 1);
}

/**
 * Every document the service knows, newest first, with its status, loading further
 * documents on demand (FR-033, FR-034). Ready documents open in the page view, and
 * ready or failed ones can be deleted (FR-047, FR-048).
 */
export function DocumentList({
  documents,
  isLoading,
  hasMore,
  onLoadMore,
  onUploadAgain,
  onDeleted,
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
        {documents.map((document) => {
          const status = displayStatus(document);
          return (
            <li key={document.id} className="flex flex-col gap-1.5 px-3 py-2.5">
              <span className="truncate text-sm font-medium" title={document.file_name}>
                {document.file_name}
              </span>
              <DocumentStatus document={document} />
              {(status === "ready" || status === "failed") && (
                <div className="flex flex-wrap items-center gap-1.5">
                  {status === "ready" ? (
                    <PageDialog
                      trigger={
                        <Button variant="outline" size="xs" className="w-fit">
                          <FileTextIcon aria-hidden="true" />
                          View document
                        </Button>
                      }
                      documentId={document.id}
                      documentName={document.file_name}
                      pages={everyPage(document)}
                      scope="document"
                    />
                  ) : (
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
                  <DeleteDocumentDialog document={document} onDeleted={onDeleted} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {hasMore && (
        <Button variant="ghost" size="sm" onClick={onLoadMore}>
          Load more
        </Button>
      )}
    </div>
  );
}
