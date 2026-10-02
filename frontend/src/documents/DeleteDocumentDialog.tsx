import { Trash2Icon } from "lucide-react";
import { useState } from "react";

import { callService } from "@/api/http";
import { deleteDocument, type DocumentBody } from "@/client";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { FailureNotice } from "@/failures/FailureNotice";
import { toDeletionFailure, type DeletionFailure } from "@/failures/messages";

/** Props of {@link DeleteDocumentDialog}. */
export interface DeleteDocumentDialogProps {
  document: DocumentBody;
  /** Called once the document no longer exists on the service. */
  onDeleted: (documentId: string) => void;
}

/**
 * The "Delete" action of a document row and its confirmation, which stays open while
 * the deletion runs and shows why it failed (FR-048, FR-049).
 */
export function DeleteDocumentDialog({
  document,
  onDeleted,
}: DeleteDocumentDialogProps) {
  // Whether the dialog is open, a deletion is running, and its failure if any
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [failure, setFailure] = useState<DeletionFailure | null>(null);

  function changeOpen(next: boolean) {
    // The dialog cannot be closed while the deletion runs
    if (deleting) return;
    setOpen(next);
    if (!next) setFailure(null);
  }

  async function confirm() {
    // Ask the service to delete the document
    setDeleting(true);
    setFailure(null);
    const result = await callService((options) =>
      deleteDocument({ ...options, path: { document_id: document.id } }),
    );
    setDeleting(false);

    // A missing document counts as deleted, other failures stay in the dialog
    const failed = result.ok ? null : toDeletionFailure(result.failure);
    if (failed === null) {
      setOpen(false);
      onDeleted(document.id);
      return;
    }
    setFailure(failed);
  }

  return (
    <AlertDialog open={open} onOpenChange={changeOpen}>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="xs" className="w-fit text-muted-foreground">
          <Trash2Icon aria-hidden="true" />
          Delete
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="break-all">
            Delete {document.file_name}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            The document, its pages and figures are removed, and it can no longer be
            asked about. Earlier answers keep their text. This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {/* Why the deletion failed, with the reference to quote */}
        {failure !== null && (
          <FailureNotice message={failure.message} reference={failure.reference} />
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
          {/* Hide the delete button after a failure that a retry cannot fix */}
          {(failure === null || failure.retryable) && (
            <Button
              variant="destructive"
              disabled={deleting}
              onClick={() => void confirm()}
            >
              {deleting ? (
                <>
                  <Spinner aria-hidden="true" />
                  Deleting…
                </>
              ) : (
                "Delete document"
              )}
            </Button>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
