import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { SidebarInset } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ConfigContext, type RuntimeConfig } from "@/config";
import { ConversationView } from "@/conversation/ConversationView";
import { useDocumentPanel } from "@/documents/documentPanelContext";
import { DocumentPanel } from "@/documents/DocumentPanel";
import { DocumentPanelProvider } from "@/documents/DocumentPanelProvider";
import { ConnectionNotice } from "@/failures/ConnectionNotice";

/**
 * The application shell: providers, the document panel on the left and the
 * conversation, laid out for desktop windows of 1280 px or wider (FR-043).
 */
export function App({ config }: { config: RuntimeConfig }) {
  // One query cache for the lifetime of the page
  const [queryClient] = useState(() => new QueryClient());
  return (
    // Providers, outermost first: config, query cache, tooltips, document panel
    <ConfigContext value={config}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <DocumentPanelProvider>
            <Layout />
          </DocumentPanelProvider>
        </TooltipProvider>
      </QueryClientProvider>
    </ConfigContext>
  );
}

function Layout() {
  // The panel's controls, so the conversation can ask it to open the upload
  const panel = useDocumentPanel();
  return (
    <div className="flex h-dvh w-full min-w-[1280px] bg-background text-foreground">
      {/* Document panel on the left, conversation on the right */}
      <DocumentPanel />
      <SidebarInset className="min-w-0">
        <div className="px-6 pt-3 empty:hidden">
          <ConnectionNotice />
        </div>
        <div className="min-h-0 flex-1">
          <ConversationView onRequestUpload={panel?.requestUpload} />
        </div>
      </SidebarInset>
    </div>
  );
}
