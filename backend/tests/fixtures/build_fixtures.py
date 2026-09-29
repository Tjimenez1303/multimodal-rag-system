"""Generate the small PDFs used by extraction and upload tests.

Run from ``backend/`` with ``uv run python tests/fixtures/build_fixtures.py``. Output is
deterministic, so regenerating the files produces no diff unless this script changes.
"""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Image as FlowImage,
)
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

rl_config.invariant = 1

FIXTURES = Path(__file__).parent
STYLES = getSampleStyleSheet()
HEADER = ["Part", "Code", "Torque (N·m)", "Interval"]
CAPTION = ParagraphStyle(
    "Caption", parent=STYLES["Italic"], fontSize=9, leading=11, alignment=TA_CENTER
)
TABLE_STYLE = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]
)


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _diagram_png() -> bytes:
    """A dense raster schematic whose labels exist only as pixels inside the image.

    The drawing fills its frame with shaded components, wiring and a ground rail, like
    a figure in a real manual, so layout models classify it as a picture on every
    platform instead of treating a sparse drawing as decoration.
    """
    image = Image.new("RGB", (1200, 640), (246, 246, 240))
    draw = ImageDraw.Draw(image)
    for x in range(0, 1200, 40):
        draw.line((x, 0, x, 640), fill=(226, 226, 220), width=1)
    for y in range(0, 640, 40):
        draw.line((0, y, 1200, y), fill=(226, 226, 220), width=1)
    draw.rectangle((10, 10, 1190, 630), outline="black", width=6)
    boxes = {
        "MAGNETO": ((60, 120), (180, 200, 230)),
        "V-12": ((470, 120), (240, 210, 170)),
        "P-1": ((880, 120), (190, 225, 190)),
        "COIL": ((60, 400), (220, 220, 220)),
        "PLUG": ((470, 400), (220, 220, 220)),
        "GND": ((880, 400), (220, 220, 220)),
    }
    for label, ((x, y), fill) in boxes.items():
        draw.rectangle((x, y, x + 260, y + 150), fill=fill, outline="black", width=5)
        draw.text((x + 30, y + 50), label, fill="black", font=_font(48))
    for y in (195, 475):
        draw.line((320, y, 470, y), fill="black", width=6)
        draw.line((730, y, 880, y), fill="black", width=6)
    for x in (190, 600, 1010):
        draw.line((x, 270, x, 400), fill="black", width=6)
    draw.line((40, 590, 1160, 590), fill="black", width=8)
    for x in (190, 600, 1010):
        draw.line((x, 550, x, 590), fill="black", width=6)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _parts_table(rows: list[list[str]]) -> Table:
    table = Table(
        [HEADER, *rows], colWidths=[1.6 * inch, 1.1 * inch, 1.3 * inch, 1.3 * inch]
    )
    table.setStyle(TABLE_STYLE)
    return table


def _part_rows(start: int, count: int) -> list[list[str]]:
    return [
        [f"Spark plug {n}", f"SP-{n:03d}", f"{20 + n % 7}", f"{100 * (1 + n % 4)} h"]
        for n in range(start, start + count)
    ]


def build_digital(path: Path) -> None:
    """Heading, paragraphs, a table and a labeled diagram with its caption."""
    story = [
        Paragraph("Ignition System Maintenance", STYLES["Title"]),
        Paragraph("1. Magneto inspection", STYLES["Heading2"]),
        Paragraph(
            "The magneto generates the high voltage that fires the spark plugs. "
            "Inspect the breaker points every 100 hours and check the timing "
            "against the engine data plate.",
            STYLES["BodyText"],
        ),
        Spacer(1, 12),
        _parts_table(_part_rows(1, 4)),
        Spacer(1, 18),
        FlowImage(io.BytesIO(_diagram_png()), width=6 * inch, height=3.2 * inch),
        Spacer(1, 6),
        Paragraph(
            "Figure 1. Magneto primary circuit with valve V-12 and pump P-1.",
            CAPTION,
        ),
        Paragraph(
            "Replace any component whose resistance falls outside the limits "
            "listed in the table above.",
            STYLES["BodyText"],
        ),
    ]
    SimpleDocTemplate(str(path), pagesize=LETTER).build(story)


def build_split_table(path: Path) -> None:
    """A table that starts at the bottom of page 1 and continues on page 2."""
    story = [
        Paragraph("Torque Specifications", STYLES["Title"]),
        Paragraph(
            "Apply the torque values below with a calibrated wrench. "
            "The table continues on the next page.",
            STYLES["BodyText"],
        ),
        Spacer(1, 3.9 * inch),
        _parts_table(_part_rows(1, 12)),
        PageBreak(),
        _parts_table(_part_rows(13, 6)),
        Paragraph("Table 1 (continued). Torque specifications.", STYLES["Italic"]),
    ]
    SimpleDocTemplate(str(path), pagesize=LETTER).build(story)


def build_scanned(path: Path) -> None:
    """Two image-only pages with no text layer, like a scanned manual."""
    width, height = int(LETTER[0] * 2), int(LETTER[1] * 2)
    pages = [
        [
            "OPERATOR'S MANUAL",
            "WELDING MACHINE, ARC",
            "Section 1. Controls",
            "Set the current switch to LOW",
            "before starting the engine.",
        ],
        [
            "Section 2. Lubrication",
            "Check the oil level every 8 hours.",
            "Use grade OE-30 above 32 F.",
        ],
    ]
    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    for lines in pages:
        image = Image.new("L", (width, height), 255)
        draw = ImageDraw.Draw(image)
        for number, line in enumerate(lines):
            draw.text((120, 150 + number * 90), line, fill=0, font=_font(52))
        pdf.drawImage(ImageReader(image), 0, 0, width=LETTER[0], height=LETTER[1])
        pdf.showPage()
    pdf.save()


def build_encrypted(source: Path, path: Path) -> None:
    """A copy of the digital fixture protected with a user password."""
    writer = PdfWriter()
    for page in PdfReader(source).pages:
        writer.add_page(page)
    writer.encrypt(user_password="secret", owner_password="owner-secret")
    with path.open("wb") as handle:
        writer.write(handle)


def build_not_a_pdf(path: Path) -> None:
    """Plain text saved with a .pdf name."""
    path.write_text("This is a plain text file, not a PDF.\n")


def main() -> None:
    """Regenerate every fixture next to this script."""
    digital = FIXTURES / "digital.pdf"
    build_digital(digital)
    build_split_table(FIXTURES / "split_table.pdf")
    build_scanned(FIXTURES / "scanned.pdf")
    build_encrypted(digital, FIXTURES / "encrypted.pdf")
    build_not_a_pdf(FIXTURES / "not_a_pdf.pdf")


if __name__ == "__main__":
    main()
