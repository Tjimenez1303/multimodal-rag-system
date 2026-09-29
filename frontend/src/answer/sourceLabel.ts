import { nounFor } from "@/lib/plural";

/**
 * Format the pages of a citation, sorted and listed once, with runs of consecutive
 * pages joined by an en dash (data-model section 2.1).
 *
 * @param pages - Page numbers in any order, possibly repeated.
 * @returns "page 12", "pages 12–13" or "pages 3–4, 9".
 */
export function formatPages(pages: readonly number[]): string {
  const sorted = [...new Set(pages)].sort((a, b) => a - b);
  const runs: string[] = [];
  let start = sorted[0];
  for (let index = 0; start !== undefined && index < sorted.length; index += 1) {
    const current = sorted[index]!;
    const next = sorted[index + 1];
    if (next !== current + 1) {
      runs.push(start === current ? `${current}` : `${start}–${current}`);
      start = next;
    }
  }
  return `${nounFor(sorted.length, "page")} ${runs.join(", ")}`;
}

/**
 * The label of a source line, such as "Source: Motor_Manual.pdf, page 12" (FR-010).
 *
 * @param documentName - File name of the document.
 * @param pages - Pages of the citation.
 * @returns The label shown on the source line.
 */
export function sourceLabel(documentName: string, pages: readonly number[]): string {
  return `Source: ${documentName}, ${formatPages(pages)}`;
}
