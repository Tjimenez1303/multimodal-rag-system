import { PanelLeftCloseIcon, PanelLeftOpenIcon } from "lucide-react";
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  useSidebar,
} from "@/components/ui/sidebar";
import { DocumentList } from "@/documents/DocumentList";
import { displayStatus } from "@/documents/status";
import { UploadControl, type UploadControlHandle } from "@/documents/UploadControl";
import { useLibrary } from "@/documents/useLibrary";

/**
 * The collapsible panel on the left of the chat: upload, the document list and its
 * statuses. Collapsed, it keeps a count of the documents still processing (FR-031).
 */
export function DocumentPanel() {
  const { open, toggleSidebar } = useSidebar();
  const library = useLibrary();
  const upload = useRef<UploadControlHandle>(null);
  const processing = library.documents.filter((document) => {
    const status = displayStatus(document);
    return status === "pending" || status === "processing";
  }).length;
  return (
    <Sidebar collapsible="icon" aria-label="Documents panel">
      <SidebarHeader className="flex-row items-center justify-between gap-2 border-b px-3 py-2 group-data-[collapsible=icon]:flex-col group-data-[collapsible=icon]:px-1.5">
        <h2 className="text-sm font-semibold group-data-[collapsible=icon]:hidden">
          Documents
        </h2>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={open ? "Hide documents" : "Show documents"}
          aria-expanded={open}
          onClick={toggleSidebar}
        >
          {open ? (
            <PanelLeftCloseIcon aria-hidden="true" />
          ) : (
            <PanelLeftOpenIcon aria-hidden="true" />
          )}
        </Button>
      </SidebarHeader>
      {!open && processing > 0 && (
        <p className="mx-auto mt-3 rounded-sm bg-primary/8 px-1 py-2 text-xs font-medium text-primary [writing-mode:vertical-rl]">
          {processing} processing
        </p>
      )}
      <SidebarContent className="gap-4 p-3 group-data-[collapsible=icon]:hidden">
        <UploadControl
          ref={upload}
          documents={library.documents}
          onAccepted={() => void library.refresh()}
        />
        <DocumentList
          documents={library.documents}
          isLoading={library.isLoading}
          hasMore={library.hasMore}
          onLoadMore={() => void library.loadMore()}
          onUploadAgain={() => upload.current?.openFilePicker()}
        />
      </SidebarContent>
    </Sidebar>
  );
}
