import { WifiOffIcon } from "lucide-react";

import { useServiceReachable } from "@/api/connection";
import { Alert, AlertTitle } from "@/components/ui/alert";

/**
 * A banner shown while the service cannot be reached, cleared without a reload once a
 * call gets a response again (FR-030).
 */
export function ConnectionNotice({ forceVisible = false }: { forceVisible?: boolean }) {
  const reachable = useServiceReachable();
  if (reachable && !forceVisible) return null;
  // <output> is a polite live region with the status role, so the notice is announced.
  return (
    <output className="block">
      <Alert role="none" className="border-amber-300 bg-amber-50 text-amber-950">
        <WifiOffIcon aria-hidden="true" />
        <AlertTitle>Can&apos;t reach the service. Retrying…</AlertTitle>
      </Alert>
    </output>
  );
}
