import { createContext, useContext } from "react";

import type { AnswerBody } from "@/client";

/** What an answer's markers and source lines share. */
export interface CitationContextValue {
  response: AnswerBody;
  highlighted: number | null;
  sourceLineId: (number: number) => string;
  activate: (number: number) => void;
}

export const CitationContext = createContext<CitationContextValue | null>(null);

/**
 * Read the citations of the surrounding answer.
 *
 * @returns The context, or `null` outside a `CitationProvider`.
 */
export function useCitations(): CitationContextValue | null {
  return useContext(CitationContext);
}
