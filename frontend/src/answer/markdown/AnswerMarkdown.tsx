import type { Root } from "hast";
import type { Schema } from "hast-util-sanitize";
import { memo, useMemo, type ReactNode } from "react";
import type { Pluggable, Plugin } from "unified";
import {
  defaultRehypePlugins,
  defaultRemarkPlugins,
  type Components,
} from "streamdown";

import { MessageResponse } from "@/components/ai-elements/message";

import { CitationMarker } from "./CitationMarker";
import { CITATION_ATTRIBUTE, CITATION_TAG, citationMarkers } from "./citationMarkers";
import { noRemoteMedia } from "./noRemoteMedia";

// Streamdown's link confirmation is off; links open in a new tab instead
const LINK_SAFETY = { enabled: false };

// Streamdown's sanitizer, with its own schema extended to let the citation element
// through.
const [sanitize, schema] = defaultRehypePlugins["sanitize"] as [
  Plugin<[Schema], Root>,
  Schema,
];
const citationSanitize: Pluggable = [
  sanitize,
  {
    ...schema,
    tagNames: [...(schema.tagNames ?? []), CITATION_TAG],
    attributes: { ...schema.attributes, [CITATION_TAG]: [CITATION_ATTRIBUTE] },
  } satisfies Schema,
];
// Without rehype-raw, Streamdown turns raw HTML into text itself (FR-009).
const REHYPE_PLUGINS = [citationSanitize, defaultRehypePlugins["harden"]!];

// Element overrides: emphasis, citation markers, links and tables
const components: Components = {
  // Bold as <strong>, so assistive technology conveys the emphasis.
  strong: ({ children }) => (
    <strong className="font-semibold">{children as ReactNode}</strong>
  ),
  [CITATION_TAG]: ({ [CITATION_ATTRIBUTE]: number }) => (
    <CitationMarker number={Number(number)} />
  ),

  // External links open in a new tab without access to this page
  a: ({ href, children }) => (
    <a
      href={href as string | undefined}
      target="_blank"
      rel="noopener noreferrer"
      className="font-medium text-primary underline underline-offset-3"
    >
      {children as ReactNode}
    </a>
  ),
  // Wide tables scroll sideways within the answer instead of widening the page.
  table: ({ children }) => (
    <section
      aria-label="Table"
      // A scrollable region must be reachable with the keyboard (WCAG 2.1.1).
      // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      className="my-3 overflow-x-auto rounded-md border focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <table className="w-full border-collapse text-sm [&_td]:border-t [&_td]:px-3 [&_td]:py-1.5 [&_th]:bg-muted [&_th]:px-3 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-medium">
        {children as ReactNode}
      </table>
    </section>
  ),
};

/** Props of {@link AnswerMarkdown}. */
export interface AnswerMarkdownProps {
  /** The answer's Markdown, as returned by the service. */
  answer: string;
  /** Numbers of the response's citations, whose `[n]` markers become links. */
  citationNumbers: readonly number[];
}

/**
 * The answer rendered from Markdown with AI Elements' `MessageResponse` (research
 * section 9). Raw markup is shown as text, images are never loaded, and markers of
 * existing citations become citation links.
 */
export const AnswerMarkdown = memo(function AnswerMarkdown({
  answer,
  citationNumbers,
}: AnswerMarkdownProps) {
  // Rebuild the plugins only when the cited numbers change
  const numbersKey = citationNumbers.join(",");
  const remarkPlugins = useMemo(
    (): Pluggable[] => [
      ...Object.values(defaultRemarkPlugins),
      noRemoteMedia,
      [citationMarkers, { numbers: numbersKey.split(",").filter(Boolean).map(Number) }],
    ],
    [numbersKey],
  );
  return (
    // Rendered once, in full: the service answers in one JSON body, not a stream
    <MessageResponse
      className="h-auto text-[0.9375rem] leading-7"
      mode="static"
      parseIncompleteMarkdown={false}
      controls={false}
      linkSafety={LINK_SAFETY}
      rehypePlugins={REHYPE_PLUGINS}
      remarkPlugins={remarkPlugins}
      components={components}
    >
      {answer}
    </MessageResponse>
  );
});
