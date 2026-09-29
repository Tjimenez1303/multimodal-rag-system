import { ChevronLeftIcon, ChevronRightIcon, FileWarningIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { pageImageUrl } from "@/api/images";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { pageLocation } from "@/images/figures";

/** Props of {@link PageDialog}. */
export interface PageDialogProps {
  /** The control that opens the view, and gets the focus back when it closes. */
  trigger: ReactNode;
  documentId: string;
  documentName: string;
  /** The pages of the source or figure the view was opened from. */
  pages: readonly number[];
  /** The page shown first, the lowest page by default. */
  initialPage?: number;
  /**
   * Whether the pages are those of a source or figure, or every page of the document
   * (FR-047), which only changes the counter under the page.
   */
  scope?: "source" | "document";
}

/**
 * The rendered page of the original PDF at full size, stepping only between the pages
 * of the source it was opened from (FR-018), or through a whole document (FR-047).
 */
export function PageDialog({ trigger, ...page }: PageDialogProps) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      {/* Mounted only while open, so each opening starts on the first page. */}
      {open && <PageView {...page} />}
    </Dialog>
  );
}

function PageView({
  documentId,
  documentName,
  pages,
  initialPage,
  scope = "source",
}: Omit<PageDialogProps, "trigger">) {
  const sorted = [...new Set(pages)].sort((a, b) => a - b);
  const [index, setIndex] = useState(() =>
    Math.max(0, initialPage === undefined ? 0 : sorted.indexOf(initialPage)),
  );
  const [failed, setFailed] = useState<ReadonlySet<number>>(new Set());
  const page = sorted[index] ?? sorted[0] ?? 1;
  const location = pageLocation(documentName, page);
  return (
    <DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col gap-3 sm:max-w-4xl">
      <DialogHeader className="pr-10">
        <DialogTitle>{location}</DialogTitle>
        <DialogDescription className="sr-only">
          The rendered page of the original document.
        </DialogDescription>
      </DialogHeader>
      <div className="min-h-0 flex-1 overflow-auto rounded-md border bg-muted/40">
        {failed.has(page) ? (
          <div className="flex h-72 flex-col items-center justify-center gap-2 text-muted-foreground">
            <FileWarningIcon aria-hidden="true" className="size-6" />
            <p className="font-medium">Page unavailable</p>
            <p className="text-xs">{location}</p>
          </div>
        ) : (
          <img
            key={page}
            src={pageImageUrl(documentId, page)}
            alt={`Page ${page} of ${documentName}`}
            decoding="async"
            className="mx-auto h-auto max-w-full bg-white"
            onError={() => setFailed((current) => new Set(current).add(page))}
          />
        )}
      </div>
      {sorted.length > 1 && (
        <div className="flex items-center justify-between">
          <Button
            variant="outline"
            size="sm"
            disabled={index === 0}
            onClick={() => setIndex(index - 1)}
          >
            <ChevronLeftIcon aria-hidden="true" />
            Previous page
          </Button>
          <span className="text-xs text-muted-foreground tabular-nums">
            {scope === "document"
              ? `Page ${page} of ${sorted.length}`
              : `${index + 1} of ${sorted.length} pages in this source`}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={index === sorted.length - 1}
            onClick={() => setIndex(index + 1)}
          >
            Next page
            <ChevronRightIcon aria-hidden="true" />
          </Button>
        </div>
      )}
    </DialogContent>
  );
}
