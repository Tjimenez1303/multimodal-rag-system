import type { AnswerImageBody } from "@/client";
import { FigureCard } from "@/images/FigureCard";

/** Props of {@link ImageColumn}. */
export interface ImageColumnProps {
  primary: AnswerImageBody | null;
  related: readonly AnswerImageBody[];
}

/**
 * The turn's image column: the primary figure first, then the related figures as a
 * secondary group, in the order the service returned them (FR-015, FR-017).
 */
export function ImageColumn({ primary, related }: ImageColumnProps) {
  if (primary === null && related.length === 0) return null;
  return (
    <div className="flex flex-col gap-4">
      {primary !== null && <FigureCard image={primary} />}
      {related.length > 0 && (
        <section
          role="group"
          aria-labelledby="related-images"
          className="flex flex-col gap-2"
        >
          <h3 id="related-images" className="text-xs font-medium text-muted-foreground">
            Related images
          </h3>
          <div className="grid grid-cols-2 gap-2">
            {related.map((image) => (
              <FigureCard key={image.element_id} image={image} size="related" />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
