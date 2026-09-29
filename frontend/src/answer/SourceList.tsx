import {
  ChevronDownIcon,
  FileTextIcon,
  ScanTextIcon,
  SparklesIcon,
} from "lucide-react";
import { useState } from "react";

import { useCitations } from "@/answer/useCitations";
import { formatPages, sourceLabel } from "@/answer/sourceLabel";
import { citationSources, uncitedSources } from "@/answer/sources";
import type { AnswerBody, CitationBody, SourceBody } from "@/client";
import {
  Sources,
  SourcesContent,
  SourcesTrigger,
} from "@/components/ai-elements/sources";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { PageDialog } from "@/images/PageDialog";

/**
 * The numbered source lines under an answer (FR-010 to FR-014), and the retrieved
 * passages it does not cite, on demand.
 *
 * @param props - The response, as returned by the service.
 */
export function SourceList({ response }: { response: AnswerBody }) {
  const uncited = uncitedSources(response);
  return (
    <div className="flex flex-col gap-3">
      <ol aria-label="Sources" className="divide-y rounded-lg border bg-card">
        {response.citations.map((citation) => (
          <SourceLine
            key={citation.number}
            citation={citation}
            sources={citationSources(response, citation)}
          />
        ))}
      </ol>
      {uncited.length > 0 && (
        <Sources className="mb-0 text-muted-foreground">
          <SourcesTrigger
            count={uncited.length}
            className="group/uncited rounded-md text-xs font-medium hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            Other retrieved passages ({uncited.length})
            <ChevronDownIcon
              aria-hidden="true"
              className="size-3.5 transition-transform group-data-[state=open]/uncited:rotate-180"
            />
          </SourcesTrigger>
          <SourcesContent className="mt-2 w-full">
            <ul className="divide-y rounded-lg border border-dashed">
              {uncited.map((source) => (
                <UncitedPassage key={source.unit_id} source={source} />
              ))}
            </ul>
          </SourcesContent>
        </Sources>
      )}
    </div>
  );
}

function SourceLine({
  citation,
  sources,
}: {
  citation: CitationBody;
  sources: SourceBody[];
}) {
  const citations = useCitations();
  const [open, setOpen] = useState(false);
  const lowConfidence = sources.some((source) => source.low_confidence_text);
  const generated = sources.some((source) => source.generated_description);
  const unverified = [
    ...new Set(sources.flatMap((source) => source.unverified_identifiers)),
  ];
  return (
    <li
      id={citations?.sourceLineId(citation.number)}
      aria-label={`Source ${citation.number}, ${citation.document_name}, ${formatPages(citation.pages)}`}
      tabIndex={-1}
      data-highlighted={citations?.highlighted === citation.number}
      className="scroll-mt-4 px-3 py-2 outline-none first:rounded-t-lg last:rounded-b-lg focus-visible:ring-3 focus-visible:ring-ring/50 data-[highlighted=true]:bg-primary/8 data-[highlighted=true]:shadow-[inset_3px_0_0_var(--color-primary)]"
    >
      <Collapsible open={open} onOpenChange={setOpen}>
        <div className="flex items-start gap-2.5">
          <span
            aria-hidden="true"
            className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-sm bg-secondary text-[0.7rem] font-medium text-primary tabular-nums"
          >
            {citation.number}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm leading-6 break-words">
              {sourceLabel(citation.document_name, citation.pages)}
            </p>
            {(lowConfidence || generated) && (
              <div className="mt-1 flex flex-col gap-1 text-xs text-muted-foreground">
                {lowConfidence && (
                  <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <Badge
                      variant="outline"
                      className="rounded-sm border-amber-300 bg-amber-50 text-amber-900"
                    >
                      <ScanTextIcon aria-hidden="true" />
                      Low-confidence OCR
                    </Badge>
                    <span>
                      Recognized from a scan with low confidence. Check it against the
                      page.
                    </span>
                  </p>
                )}
                {generated && (
                  <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <Badge
                      variant="outline"
                      className="rounded-sm border-sky-300 bg-sky-50 text-sky-900"
                    >
                      <SparklesIcon aria-hidden="true" />
                      Described automatically
                    </Badge>
                    {unverified.length > 0 && (
                      <span>Unverified identifiers: {unverified.join(", ")}</span>
                    )}
                  </p>
                )}
              </div>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-0.5">
            <PageDialog
              documentId={citation.document_id}
              documentName={citation.document_name}
              pages={citation.pages}
              trigger={
                <Button variant="ghost" size="xs">
                  <FileTextIcon aria-hidden="true" />
                  Open page
                </Button>
              }
            />
            <CollapsibleTrigger asChild>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={open ? "Hide details" : "Show details"}
              >
                <ChevronDownIcon
                  aria-hidden="true"
                  className={
                    open ? "rotate-180 transition-transform" : "transition-transform"
                  }
                />
              </Button>
            </CollapsibleTrigger>
          </div>
        </div>
        <CollapsibleContent className="mt-2 ml-7.5 flex flex-col gap-3">
          {sources.map((source) => (
            <SourceDetails key={source.unit_id} source={source} />
          ))}
        </CollapsibleContent>
      </Collapsible>
    </li>
  );
}

function SourceDetails({ source }: { source: SourceBody }) {
  return (
    <div className="flex flex-col gap-1.5 text-xs">
      {source.section.length > 0 && (
        <p className="font-medium text-muted-foreground">
          {source.section.join(" › ")}
        </p>
      )}
      {source.tables.length > 0 ? (
        source.tables.map((table) => (
          <div key={table.page} className="overflow-x-auto rounded-md border">
            <Table className="text-xs">
              <TableBody>
                {table.rows.map((row, rowIndex) => (
                  <TableRow key={rowIndex}>
                    {row.map((cell, cellIndex) => (
                      <TableCell key={cellIndex} className="py-1">
                        {cell}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ))
      ) : (
        <p className="border-l-2 pl-2.5 leading-5 whitespace-pre-line text-foreground/80">
          {source.excerpt}
        </p>
      )}
    </div>
  );
}

function UncitedPassage({ source }: { source: SourceBody }) {
  return (
    <li className="flex items-start gap-2 px-3 py-2">
      <div className="min-w-0 flex-1 text-foreground">
        <p className="text-sm leading-6">
          {sourceLabel(source.document_name, source.pages)}
        </p>
        <SourceDetails source={source} />
      </div>
      <PageDialog
        documentId={source.document_id}
        documentName={source.document_name}
        pages={source.pages}
        trigger={
          <Button variant="ghost" size="xs">
            <FileTextIcon aria-hidden="true" />
            Open page
          </Button>
        }
      />
    </li>
  );
}
