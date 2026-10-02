import { CheckIcon, CircleAlertIcon, CopyIcon } from "lucide-react";
import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

/** An action offered under a failure, such as "Retry". */
export interface FailureNoticeAction {
  label: string;
  onAction: () => void;
}

/** Props of {@link FailureNotice}. */
export interface FailureNoticeProps {
  /** Plain-English message, without codes or internal details (FR-024). */
  message: string;
  /** The request's `X-Request-ID`, or `null` when no request was sent (FR-025). */
  reference: string | null;
  action?: FailureNoticeAction | undefined;
  className?: string | undefined;
}

/**
 * A failed question or upload: the message, a copyable reference that locates the
 * request in the service's logs, and an optional action.
 */
export function FailureNotice({
  message,
  reference,
  action,
  className,
}: FailureNoticeProps) {
  // Whether the reference was copied, to confirm it on the button
  const [copied, setCopied] = useState(false);

  async function copyReference(value: string) {
    await navigator.clipboard.writeText(value);
    setCopied(true);
  }

  return (
    <Alert variant="destructive" className={className}>
      <CircleAlertIcon aria-hidden="true" />
      {/* The message, then the reference to quote and an optional action */}
      <AlertTitle className="leading-6">{message}</AlertTitle>
      {(reference !== null || action !== undefined) && (
        <AlertDescription className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          {reference !== null && (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <span>Reference: {reference}</span>
              <Button
                variant="ghost"
                size="xs"
                aria-label="Copy reference"
                onClick={() => void copyReference(reference)}
              >
                {copied ? (
                  <CheckIcon aria-hidden="true" />
                ) : (
                  <CopyIcon aria-hidden="true" />
                )}
                {copied ? "Copied" : "Copy"}
              </Button>
            </span>
          )}
          {action !== undefined && (
            <Button variant="outline" size="sm" onClick={action.onAction}>
              {action.label}
            </Button>
          )}
        </AlertDescription>
      )}
    </Alert>
  );
}
