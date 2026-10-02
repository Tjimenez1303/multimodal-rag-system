import type { AnswerBody, CitationBody, SourceBody } from "@/client";

/**
 * The sources a citation draws on, in the response's rank order (data-model 2.1).
 *
 * @param response - The answer as returned by the service.
 * @param citation - One of its citations.
 * @returns The sources listed in the citation's `unit_ids`.
 */
export function citationSources(
  response: AnswerBody,
  citation: CitationBody,
): SourceBody[] {
  // Sources whose unit the citation points to
  const units = new Set(citation.unit_ids);
  return response.sources.filter((source) => units.has(source.unit_id));
}

/**
 * The retrieved passages the answer does not cite (FR-014).
 *
 * @param response - The answer as returned by the service.
 * @returns The uncited sources, in rank order.
 */
export function uncitedSources(response: AnswerBody): SourceBody[] {
  return response.sources.filter((source) => !source.cited);
}
