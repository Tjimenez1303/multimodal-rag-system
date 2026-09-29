import type { GetDocumentPageImageData } from "@/client";
import { client } from "@/client/client.gen";

// Typed by the generated client, so a change to the route breaks compilation.
const PAGE_IMAGE_URL: GetDocumentPageImageData["url"] =
  "/api/v1/documents/{document_id}/pages/{page_number}/image";

/**
 * The address of the rendered image of a document page (getDocumentPageImage).
 *
 * @param documentId - Document the page belongs to.
 * @param pageNumber - 1-based page number.
 * @returns The same-origin URL of the page's PNG.
 */
export function pageImageUrl(documentId: string, pageNumber: number): string {
  // A path on the page's own origin, like the figure URLs the service returns.
  return client.buildUrl({
    baseUrl: "",
    url: PAGE_IMAGE_URL,
    path: { document_id: documentId, page_number: pageNumber },
  });
}
