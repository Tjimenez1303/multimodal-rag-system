import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { DocumentPanelContext } from "@/documents/documentPanelContext";
import { loadPanelCollapsed, savePanelCollapsed } from "@/documents/panelState";

// Wide enough for long manual names next to their status.
const PANEL_STYLE = { "--sidebar-width": "22rem" } as CSSProperties;

/**
 * Holds the document panel's open state, kept in `sessionStorage`, around the panel
 * and the conversation (FR-031).
 *
 * @param props - The layout the panel belongs to.
 */
export function DocumentPanelProvider({ children }: { children: ReactNode }) {
  // Open unless the user collapsed the panel earlier in this tab
  const [open, setOpen] = useState(() => !loadPanelCollapsed());
  const uploadFocus = useRef<(() => void) | null>(null);

  // Every open or close is saved for the next reload
  const changeOpen = useCallback((next: boolean) => {
    setOpen(next);
    savePanelCollapsed(!next);
  }, []);

  // Controls the rest of the client uses to open the panel and focus the upload
  const controls = useMemo(
    () => ({
      requestUpload: () => {
        changeOpen(true);
        // The control is shown on the next frame, once the panel has opened.
        requestAnimationFrame(() => uploadFocus.current?.());
      },
      registerUploadFocus: (focus: (() => void) | null) => {
        uploadFocus.current = focus;
      },
    }),
    [changeOpen],
  );
  return (
    <DocumentPanelContext value={controls}>
      {/* shadcn's sidebar holds the open state and the panel width */}
      <SidebarProvider open={open} onOpenChange={changeOpen} style={PANEL_STYLE}>
        {children}
      </SidebarProvider>
    </DocumentPanelContext>
  );
}
