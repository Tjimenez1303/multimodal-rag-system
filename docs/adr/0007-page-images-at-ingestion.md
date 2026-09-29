# 0007. Page images kept from ingestion

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: project maintainer

## Context and problem statement

A technician who reads a source line or a figure wants to see the original page, to
check a recognized value against the scan or to read a figure in its context. The page
must open quickly from the conversation, keep its document name and page number in
view, and let the technician step through the pages of a source. Processing a PDF inside
a web request is not allowed: it would compete with uploads for the PDF library and slow
the API down.

How does the client get the image of a page?

## Decision drivers

- A page opens within 3 seconds (SC-011).
- No PDF is processed while answering a request (Principle III).
- A retried ingestion job produces the same result, with nothing duplicated.
- Small print stays legible, so recognized text can be checked against the page.

## Considered options

1. Keep the page images the extraction already renders, as PNG.
2. Render the page on request in the API, with a cache.
3. Render every page again in the worker with the PDF library.
4. Offer the original PDF for download.

## Decision outcome

Chosen option: **keep the page images the extraction already renders**. While it
extracts a document, the worker stores a PNG of every page at 144 dpi, and the API
serves it for completed documents. The client opens it in a page view labeled with the
document and page, with previous and next limited to the pages of the source.

### Consequences

- Good, because a page is a stored file served in milliseconds, far inside SC-011.
- Good, because extraction already renders each page to crop its figures, so keeping it
  only adds the PNG encoding, about 2 seconds for a 100-page manual.
- Good, because each image is stored under the document and page, so a retried job
  overwrites it instead of adding a copy.
- Bad, because pages take about 0.45 MB each, about 4.5 GB for 100 manuals of 100 pages.
- Bad, because documents ingested before this change have no page images, and the
  system's volumes are recreated once when upgrading.
- Bad, because the backend image carries about 20 MB of fonts. Many PDFs name the
  standard fonts (Helvetica, Times, Courier) without embedding them, and the page
  renderer needs a substitute to draw their text.

## Annex: technical evidence

### Measurements

Reference machine, sample manuals, 144 dpi, pages 1 to 24.

| Manual | Page size (px) | PNG median | PNG max | Encode median |
|---|---|---|---|---|
| FAA powerplant, ch. 4 (digital) | 1188 × 1548 | 497 KB | 855 KB | 21 ms |
| INSST electrical risk guide (digital) | 1191 × 1684 | 464 KB | 658 KB | 19 ms |
| TM 5-3431 welding machine (scanned) | 1126 × 1488 | 351 KB | 1169 KB | 17 ms |

After the change, the page image route answered `200 image/png` with a 1188 × 1548 page
in 12 ms, and `404 page_not_found` for a page past the end of the document.

### Fonts for non-embedded standard fonts

Docling's parser renders pages with the fonts installed in the image. The slim Python
image has none, so a PDF set in non-embedded Helvetica rendered every glyph as a box, in
the stored page and in the image the layout model reads. With `fonts-urw-base35`, the
free clones of the standard fonts, the same page rendered correctly and its extraction
went from 4 elements to 9.

### Alternatives

| Alternative | Size per page | Encode time | Why rejected |
|---|---|---|---|
| Lossless WebP, effort 2 | 113 to 197 KB | 48 to 339 ms | About 3 times smaller, but up to 16 times slower to encode, adding up to 30 s to a 100-page job |
| Lossy WebP, quality 85 | 140 to 201 KB | 57 to 68 ms | Compression artifacts around small print |
| JPEG, quality 85 | 220 to 351 KB | 2 to 3 ms | Same artifacts, larger than WebP |
| Render on request in the API | none stored | 22 to 75 ms render | PDF processing inside an HTTP request, contention on the PDF library's lock |
| Render in the worker with pypdfium2 | same as PNG | render plus encode | Renders every page a second time |
| Download of the original PDF | none | none | Opens a separate viewer and loses the conversation context |

### Route behavior

`GET /api/v1/documents/{document_id}/pages/{page_number}/image`

| Case | Answer |
|---|---|
| Completed document, page in range | 200 `image/png` |
| Unknown document | 404 `document_not_found` |
| Latest job not completed | 409 `ingestion_not_completed` |
| Page outside 1 to the page count | 404 `page_not_found` |
| Stored page missing for a completed document | 500 `data_inconsistency` |

### Sources

- https://docling-project.github.io/docling/reference/pipeline_options/
- Full analysis: `specs/003-visual-chat-client/research.md`, section 12, and
  `specs/003-visual-chat-client/data-model.md`, section 4
