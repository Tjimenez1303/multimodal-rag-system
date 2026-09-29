import type { Root, Text } from "mdast";
import { findAndReplace } from "mdast-util-find-and-replace";

/** Name of the element a citation marker becomes. */
export const CITATION_TAG = "citation-ref";

/** Attribute that carries the citation number to the rendered element. */
export const CITATION_ATTRIBUTE = "number";

/** Options of {@link citationMarkers}. */
export interface CitationMarkerOptions {
  /** Numbers of the response's citations. */
  numbers: readonly number[];
}

/**
 * Remark plugin that turns `[n]` markers into citation elements when `n` is a citation
 * number of the response (FR-011). Markers in code stay literal, since code is not a
 * text node, and other bracketed numbers stay text.
 *
 * Use it as `[citationMarkers, { numbers }]`: Streamdown caches its processor by plugin
 * name and options, so the numbers must travel as options, never in a closure.
 *
 * @param options - The response's citation numbers.
 * @returns The tree transformer.
 */
export function citationMarkers({ numbers }: CitationMarkerOptions) {
  const citationNumbers = new Set(numbers);
  return (tree: Root) => {
    findAndReplace(tree, [
      /\[(\d+)\]/g,
      (marker: string, number: string) => {
        if (!citationNumbers.has(Number(number))) return false;
        const node: Text = {
          type: "text",
          value: marker,
          data: {
            hName: CITATION_TAG,
            hProperties: { [CITATION_ATTRIBUTE]: number },
            hChildren: [{ type: "text", value: number }],
          },
        };
        return node;
      },
    ]);
  };
}
