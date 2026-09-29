import { createContext, useContext } from "react";

/** What the rest of the client can ask of the document panel. */
export interface DocumentPanelControls {
  /** Open the panel and move the focus to the upload control (FR-021). */
  requestUpload: () => void;
  /** Let the upload control register how it takes the focus. */
  registerUploadFocus: (focus: (() => void) | null) => void;
}

/** Provides the document panel's controls. */
export const DocumentPanelContext = createContext<DocumentPanelControls | null>(null);

/**
 * Read the document panel's controls.
 *
 * @returns The controls, or `null` outside a `DocumentPanelProvider`.
 */
export function useDocumentPanel(): DocumentPanelControls | null {
  return useContext(DocumentPanelContext);
}
