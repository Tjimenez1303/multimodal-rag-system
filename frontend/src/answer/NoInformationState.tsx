import { SearchXIcon, UploadIcon } from "lucide-react";

import type { AnswerBody } from "@/client";
import { Button } from "@/components/ui/button";

/** Props of {@link NoInformationState}. */
export interface NoInformationStateProps {
  /** The not-enough-information response, as returned by the service. */
  response: AnswerBody;
  /** Whether the question was restricted to selected documents. */
  restricted: boolean;
  /** Opens the upload control, offered when no document is ready. */
  onRequestUpload?: (() => void) | undefined;
  /** Asks the same question across all documents, offered for restricted questions. */
  onAskAcrossAll?: (() => void) | undefined;
}

/**
 * The reply when the documents do not contain the answer, set apart from an answer so
 * it is never mistaken for one (FR-021). It shows the service's message and guidance
 * that matches the reason (data-model section 2.1).
 */
export function NoInformationState({
  response,
  restricted,
  onRequestUpload,
  onAskAcrossAll,
}: NoInformationStateProps) {
  const noDocuments = response.reason === "no_searchable_documents";
  return (
    <section
      aria-labelledby="no-information-title"
      data-state="no-information"
      className="flex gap-3 rounded-lg border border-dashed border-muted-foreground/40 bg-muted/50 px-4 py-3"
    >
      <SearchXIcon
        aria-hidden="true"
        className="mt-0.5 size-5 shrink-0 text-muted-foreground"
      />
      <div className="flex min-w-0 flex-col gap-1.5">
        <h3 id="no-information-title" className="text-sm font-semibold">
          No information found
        </h3>
        <p className="text-sm leading-6">{response.answer}</p>
        <p className="text-sm leading-6 text-muted-foreground">
          {noDocuments
            ? "No manual is ready to be asked about yet. Upload one and wait until it is ready."
            : restricted
              ? "The selected documents do not contain this information."
              : "Try rephrasing the question, for example with the names of the parts or systems the manual uses."}
        </p>
        {noDocuments && onRequestUpload !== undefined && (
          <Button
            variant="outline"
            size="sm"
            className="mt-1 w-fit"
            onClick={onRequestUpload}
          >
            <UploadIcon aria-hidden="true" />
            Upload a manual
          </Button>
        )}
        {!noDocuments && restricted && onAskAcrossAll !== undefined && (
          <Button
            variant="outline"
            size="sm"
            className="mt-1 w-fit"
            onClick={onAskAcrossAll}
          >
            Ask across all documents
          </Button>
        )}
      </div>
    </section>
  );
}
