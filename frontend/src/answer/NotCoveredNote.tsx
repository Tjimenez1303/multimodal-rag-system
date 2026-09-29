import { InfoIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * The part of the question the documents do not cover, attached to a partial answer
 * (FR-020).
 *
 * @param props - The service's `not_covered` text.
 */
export function NotCoveredNote({ text }: { text: string }) {
  return (
    <Alert role="note" className="border-dashed bg-muted/40">
      <InfoIcon aria-hidden="true" />
      <AlertTitle>Not covered by the documents</AlertTitle>
      <AlertDescription className="leading-6">{text}</AlertDescription>
    </Alert>
  );
}
