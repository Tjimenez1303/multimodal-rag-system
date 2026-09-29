import type { AnswerImageBody } from "@/client";

/**
 * "{document}, page {n}", the location shown under every figure and page.
 *
 * @param documentName - File name of the document.
 * @param page - 1-based page number.
 * @returns The location label.
 */
export function pageLocation(documentName: string, page: number): string {
  return `${documentName}, page ${page}`;
}

/**
 * The figure's title: its caption, or a note that it has none (FR-015).
 *
 * @param image - The figure as returned by the service.
 * @returns The caption or "Figure without caption".
 */
export function figureTitle(image: AnswerImageBody): string {
  return image.caption ?? "Figure without caption";
}

/**
 * The text alternative of a figure, from its caption, document and page (FR-044).
 *
 * @param image - The figure as returned by the service.
 * @returns For example "Figure 4-12, Ignition harness. FAA.pdf, page 12".
 */
export function figureAlt(image: AnswerImageBody): string {
  return `${figureTitle(image)}. ${pageLocation(image.document_name, image.page)}`;
}
