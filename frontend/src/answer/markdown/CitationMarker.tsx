import { citationSources } from "@/answer/sources";
import { useCitations } from "@/answer/useCitations";
import { sourceLabel } from "@/answer/sourceLabel";
import {
  InlineCitation,
  InlineCitationCard,
  InlineCitationCardBody,
  InlineCitationSource,
} from "@/components/ai-elements/inline-citation";
import { badgeVariants } from "@/components/ui/badge";
import { HoverCardTrigger } from "@/components/ui/hover-card";
import { cn } from "@/lib/utils";

/**
 * A numbered marker in the answer text. Activating it brings the matching source line
 * into view and highlights it (FR-011), and hovering previews the source.
 *
 * @param props - The citation number.
 */
export function CitationMarker({ number }: { number: number }) {
  const citations = useCitations();
  const citation = citations?.response.citations.find((item) => item.number === number);
  const link = (
    <a
      href={`#${citations?.sourceLineId(number) ?? `citation-${number}`}`}
      aria-label={`Citation ${number}`}
      className={cn(
        badgeVariants({ variant: "secondary" }),
        "mx-0.5 h-4.5 min-w-4.5 rounded-sm px-1 align-text-top text-[0.7rem] leading-none text-primary tabular-nums no-underline",
      )}
      onClick={(event) => {
        event.preventDefault();
        citations?.activate(number);
      }}
    >
      {number}
    </a>
  );
  if (citations === null || citation === undefined) return link;
  const excerpt = citationSources(citations.response, citation)[0]?.excerpt;
  return (
    <InlineCitation>
      <InlineCitationCard>
        <HoverCardTrigger asChild>{link}</HoverCardTrigger>
        <InlineCitationCardBody>
          <InlineCitationSource
            className="p-3"
            title={sourceLabel(citation.document_name, citation.pages)}
            {...(excerpt ? { description: excerpt } : {})}
          />
        </InlineCitationCardBody>
      </InlineCitationCard>
    </InlineCitation>
  );
}
