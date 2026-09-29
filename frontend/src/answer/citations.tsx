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
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const sourceLineId = useCallback(
    (number: number) => `turn-${turnId}-source-${number}`,
    [turnId],
  );
  const activate = useCallback(
    (number: number) => {
      setHighlighted(number);
      const line = document.getElementById(sourceLineId(number));
      line?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      line?.focus({ preventScroll: true });
    },
    [sourceLineId],
  );
  const value = useMemo(
    () => ({ response, highlighted, sourceLineId, activate }),
    [response, highlighted, sourceLineId, activate],
  );
  return <CitationContext value={value}>{children}</CitationContext>;
}
