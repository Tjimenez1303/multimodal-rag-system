import type { ReactNode } from "react";

import type { AnswerImageBody } from "@/client";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { figureAlt, figureTitle, pageLocation } from "@/images/figures";

/** Props of {@link ImageDialog}. */
export interface ImageDialogProps {
  image: AnswerImageBody;
  /** The control that opens the view, and gets the focus back when it closes. */
  trigger: ReactNode;
}

/**
 * A figure at full size with its caption, document and page (FR-016). Escape or the
 * close button return to the same place in the conversation.
 */
export function ImageDialog({ image, trigger }: ImageDialogProps) {
  return (
    <Dialog>
      {/* The trigger opens the dialog and gets the focus back when it closes */}
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col gap-3 sm:max-w-5xl">
        <DialogHeader className="pr-10">
          <DialogTitle className="leading-6">{figureTitle(image)}</DialogTitle>
          <DialogDescription>
            {pageLocation(image.document_name, image.page)}
          </DialogDescription>
        </DialogHeader>
        {/* The figure at full size, scrolling when larger than the dialog */}
        <div className="min-h-0 flex-1 overflow-auto rounded-md border bg-white">
          <img
            src={image.url}
            alt={figureAlt(image)}
            decoding="async"
            className="mx-auto h-auto max-w-full object-contain"
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
