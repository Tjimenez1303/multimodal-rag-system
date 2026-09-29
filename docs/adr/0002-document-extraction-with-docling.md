# 0002. Document extraction with Docling

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: project maintainer

## Context and problem statement

Answers must cite the page a fact comes from and show the diagram it refers to. That is
only possible if ingestion keeps, for every piece of text, table and image, its page and
its position on the page. The manuals include digital and scanned pages, in English and
Spanish, and the diagrams carry labels such as valve codes that users search for.
Everything must run on a laptop, without paid services, and with licenses that allow
commercial use.

Which component reads the PDFs?

## Decision drivers

- A page and a position for every element.
- Tables kept as tables, and images kept as images with the text printed inside them.
- Text recognition for scanned pages in English and Spanish.
- Runs on a laptop CPU inside a container.
- Permissive license for both the code and the models.

## Considered options

1. Docling.
2. Parsers built on vision-language models (PaddleOCR-VL, MinerU, GLM-OCR).
3. Marker, Surya or Chandra.
4. olmOCR or Nanonets.
5. Docling as a separate service (docling-serve).

## Decision outcome

Chosen option: **Docling inside the worker**, because it is the only candidate that
meets every driver at once. It is reached only through the project's own extraction
interface, so a different parser can replace it without touching the rest of the system.

### Consequences

- Good, because every element carries its page and position, tables keep their rows and
  columns, and the labels inside diagrams stay attached to their figure.
- Good, because scanned pages are recognized in English and Spanish with 97.5% word
  recall.
- Good, because the models are part of the container image, so the worker starts without
  network access.
- Bad, because the image weighs 4.3 GB, and a 100-page manual takes about 2.5 to 5.3
  minutes to extract on CPU.
- Bad, because Docling does not join a table that continues on the next page. The
  project does it with its own rule (ADR 0004).

## Annex: technical evidence

### Comparison on the hard requirements

2026-09-28.

| Candidate | License of code and weights | Page and box per element | CPU in a linux/arm64 container |
|---|---|---|---|
| Docling 2.130 | MIT | Yes, with explicit `coord_origin` | Yes |
| PaddleOCR-VL-1.6 (OmniDocBench v1.6: 96.3) | Apache 2.0 | Yes | Needs a GPU or Metal to be practical |
| MinerU2.5-Pro (95.8) | License with user and revenue caps | Yes | Needs a GPU to be practical |
| GLM-OCR (95.2) | Open | Yes | Needs a GPU to be practical |
| Marker, Surya, Chandra | Weights with revenue caps | Yes | Yes |
| olmOCR, Nanonets | Open | No, Markdown only | Varies |
| dots.ocr, DeepSeek-OCR | Open | Yes | CUDA only |

### Measured extraction on the reference machine

Apple M4 Pro, container limited to 8 CPUs and 10 GB.

| Document | Pages | Seconds | s/page | Tables | Figures |
|---|---|---|---|---|---|
| FAA-H-8083-32B ch. 4 (digital) | 71 | 105.3 | 1.48 | 8 | 117 |
| INSST electrical risk guide (digital) | 86 | 148.6 | 1.73 | 21 | 50 |
| TM 5-3431-201-10 (scanned) | 65 | 207.0 | 3.18 | 19 | 98 |

### Spanish recognition

On ten INSST pages rendered as images (5,629 words): RapidOCR reached 0.975 word recall
and 0.948 on accented words, and Tesseract `spa+eng` 0.956.

### Integration details

Docling boxes use a bottom-left origin and are converted to top-left PDF points. Pages
are converted in batches of `EXTRACTION_PAGE_BATCH` for progress reporting and bounded
memory, each with a 120-second timeout, as Docling recommends for production. Encrypted
and damaged files are told apart with pypdfium2, whose error codes distinguish them, and
every PDFium call holds Docling's own lock because PDFium is not thread-safe. The API
never imports Docling, which would load torch.

### Sources

- https://github.com/docling-project/docling/releases
- https://arxiv.org/abs/2501.17887
- https://docling-project.github.io/docling/usage/advanced_options/
- https://github.com/docling-project/docling-serve/blob/main/Containerfile
- https://github.com/opendatalab/OmniDocBench
- https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6
- Full analysis: `specs/001-async-pdf-ingestion/research.md`, sections 6 and 15
