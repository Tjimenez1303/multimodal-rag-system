/** `sessionStorage` key of the document panel's state (data-model section 1.5). */
export const PANEL_KEY = "multimodal-rag.panel.v1";

/**
 * Whether the document panel was collapsed in this tab. It starts open (FR-031).
 *
 * @returns `true` when the panel was collapsed.
 */
export function loadPanelCollapsed(): boolean {
  try {
    // Read the saved state; anything unreadable means expanded
    const stored = JSON.parse(sessionStorage.getItem(PANEL_KEY) ?? "null") as {
      collapsed?: unknown;
    } | null;
    return stored?.collapsed === true;
  } catch {
    return false;
  }
}

/**
 * Keep the document panel's state for the rest of the tab's life.
 *
 * @param collapsed - Whether the panel is collapsed.
 */
export function savePanelCollapsed(collapsed: boolean): void {
  try {
    sessionStorage.setItem(PANEL_KEY, JSON.stringify({ collapsed }));
  } catch {
    // A full storage only costs the panel state on reload.
  }
}
