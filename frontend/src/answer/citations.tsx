import { useCallback, useMemo, useState, type ReactNode } from "react";

import { CitationContext } from "@/answer/useCitations";
import type { AnswerBody } from "@/client";

/**
 * Connects an answer's citation markers to its source lines (FR-011).
 *
 * @param props - The turn's id, its response, and the answer's content.
 */
export function CitationProvider({
  turnId,
  response,
  children,
}: {
  turnId: string;
  response: AnswerBody;
  children: ReactNode;
}) {
  // The citation number currently highlighted in this answer
  const [highlighted, setHighlighted] = useState<number | null>(null);

  // Every source line gets an id unique to its turn
  const sourceLineId = useCallback(
    (number: number) => `turn-${turnId}-source-${number}`,
    [turnId],
  );

  // Highlight a citation, then scroll to its source line and focus it
  const activate = useCallback(
    (number: number) => {
      setHighlighted(number);
      const line = document.getElementById(sourceLineId(number));
      line?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      line?.focus({ preventScroll: true });
    },
    [sourceLineId],
  );

  // Share the answer and the helpers with the markers and the source lines
  const value = useMemo(
    () => ({ response, highlighted, sourceLineId, activate }),
    [response, highlighted, sourceLineId, activate],
  );
  return <CitationContext value={value}>{children}</CitationContext>;
}
