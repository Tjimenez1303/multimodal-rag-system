import { FileTextIcon, ImageOffIcon, Maximize2Icon } from "lucide-react";
import { useId, useState } from "react";

import type { AnswerImageBody } from "@/client";
import { Button } from "@/components/ui/button";
import { ImageDialog } from "@/images/ImageDialog";
import { PageDialog } from "@/images/PageDialog";
import { figureAlt, pageLocation } from "@/images/figures";
import { cn } from "@/lib/utils";

/** Props of {@link FigureCard}. */
export interface FigureCardProps {
  image: AnswerImageBody;
  /** Primary figures are shown larger than related ones. */
  size?: "primary" | "related";
}

/**
 * One figure with its caption and "document, page n" below it, a full-size view and
 * the page it comes from (FR-015 to FR-018). The image URL is used as returned.
 */
export function FigureCard({ image, size = "primary" }: FigureCardProps) {
  // Link the caption to the figure, and remember whether the image failed to load
  const captionId = useId();
  const [broken, setBroken] = useState(false);
  const primary = size === "primary";
  return (
    <figure
      aria-labelledby={captionId}
      className="flex flex-col overflow-hidden rounded-lg border bg-card"
    >
      <div
        className={cn(
          "flex items-center justify-center border-b bg-white",
          primary ? "max-h-80 min-h-40" : "max-h-40 min-h-24",
        )}
      >
        {/* A placeholder replaces an image that failed to load */}
        {broken ? (
          <div className="flex flex-col items-center gap-1.5 py-8 text-muted-foreground">
            <ImageOffIcon aria-hidden="true" className="size-5" />
            <span className="text-xs font-medium">Image unavailable</span>
          </div>
        ) : (
          <img
            src={image.url}
            alt={figureAlt(image)}
            loading="lazy"
            decoding="async"
            className={cn(
              "h-auto max-w-full object-contain",
              primary ? "max-h-80" : "max-h-40",
            )}
            onError={() => setBroken(true)}
          />
        )}
      </div>
      {/* Caption and location under the image */}
      <figcaption id={captionId} className="flex flex-col gap-0.5 px-3 pt-2 text-xs">
        <span
          className={cn(
            "leading-5",
            image.caption ? "font-medium" : "text-muted-foreground",
          )}
        >
          {image.caption ?? "No caption"}
        </span>
        <span className="text-muted-foreground">
          {pageLocation(image.document_name, image.page)}
        </span>
      </figcaption>
      {/* Open the figure full size, or the page it comes from */}
      <div className="flex gap-1 px-2 pt-1 pb-2">
        <ImageDialog
          image={image}
          trigger={
            <Button variant="ghost" size="xs" disabled={broken}>
              <Maximize2Icon aria-hidden="true" />
              View full size
            </Button>
          }
        />
        <PageDialog
          documentId={image.document_id}
          documentName={image.document_name}
          pages={[image.page]}
          trigger={
            <Button variant="ghost" size="xs">
              <FileTextIcon aria-hidden="true" />
              Open page
            </Button>
          }
        />
      </div>
    </figure>
  );
}
