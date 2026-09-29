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
  const [open, setOpen] = useState(() => !loadPanelCollapsed());
  const uploadFocus = useRef<(() => void) | null>(null);
  const changeOpen = useCallback((next: boolean) => {
    setOpen(next);
    savePanelCollapsed(!next);
  }, []);
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
      <SidebarProvider open={open} onOpenChange={changeOpen} style={PANEL_STYLE}>
        {children}
      </SidebarProvider>
    </DocumentPanelContext>
  );
}
