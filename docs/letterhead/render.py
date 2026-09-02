#!/usr/bin/env python3
"""The ENYGMA letterhead, as PDF and Word, light and dark.

Stationery, not a document: the frame he types into. Everything here comes from
the same achromatic system as the app, so a letter looks like it came from the
same place as the interface.

The rules that system runs on, and which this obeys:

  * No colour. Hierarchy comes from value, weight and space, never from hue.
  * The mark is the only ornament. It is the 4x4 cipher grid from the app, with
    the same four voids in the same four places, drawn rather than imported so
    it stays crisp at any size in print.
  * Labels are mono, uppercase, widely tracked, and quiet. Prose is not.
  * A rule separates, it does not decorate.

Dark is for screen. It is the app's dark palette exactly, and it will use a
great deal of toner if anybody prints it, which is why the light pair exists and
is the default.

    python3 docs/letterhead/render.py
"""
from __future__ import annotations

import pathlib

HERE = pathlib.Path(__file__).resolve().parent

# Straight out of src/static/css/tokens.css. Not approximations of it.
LIGHT = {
    "name": "light",
    "page": "#FFFFFF", "ground": "#F4F4F6",
    "ink": "#16161A", "dim": "#3D424A", "muted": "#525862",
    "divider": "#E0E0E5", "rest": "#CFCFD6", "accent": "#16161A",
}
DARK = {
    "name": "dark",
    "page": "#0D0D0F", "ground": "#131316",
    "ink": "#E8E8EA", "dim": "#9AA0A6", "muted": "#80858D",
    "divider": "#26262B", "rest": "#33333A", "accent": "#F2F2F4",
}

# The mark: a 4x4 grid with four cells knocked out. Same cells as _mark.html,
# read left to right, top to bottom.
VOIDS = {(0, 0), (1, 2), (2, 1), (3, 3)}

# The example letter. Placeholders are in brackets so it is obvious at a glance
# what he replaces and what is the stationery.
SENDER = ["ENYGMA", "Operator correspondence"]
META = [("FROM", "[Your name]"), ("REF", "[Reference]"), ("DATE", "[2 September 2026]")]
RECIPIENT = ["[Recipient name]", "[Their title]", "[Organisation]", "[Address line]"]
SALUTATION = "Dear [name],"
BODY = [
    "This is the ENYGMA letterhead. The frame is set. Everything below the "
    "rule is yours. Replace this paragraph and the two under it, and leave the "
    "spacing alone: the measure is set to about seventy characters because that "
    "is where a line stops being comfortable to read.",

    "Hierarchy here comes from weight and space rather than from colour. If a "
    "sentence needs to stand out, give it its own paragraph rather than a "
    "different shade. There is no accent colour to reach for, which is the "
    "point: nothing in this system competes with what you are actually saying.",

    "The block on the right carries whatever the letter needs to be found by "
    "later. If a field does not apply, delete the whole line rather than "
    "leaving it empty, so the alignment stays true.",
]
CLOSING = "Yours,"
SIGNOFF = ["[Your name]", "[Your title]"]
FOOTER_LEFT = "ENYGMA"
FOOTER_RIGHT = "spark-4d80 // arkhm.io"


# ---------------------------------------------------------------------- PDF

def pdf(skin: dict, out: pathlib.Path) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas

    W, H = A4
    M = 22 * mm                       # the margin the whole page is hung from
    ink = HexColor(skin["ink"])
    dim = HexColor(skin["dim"])
    muted = HexColor(skin["muted"])
    divider = HexColor(skin["divider"])

    c = pdfcanvas.Canvas(str(out), pagesize=A4)
    c.setTitle("ENYGMA letterhead")
    c.setAuthor("ENYGMA")

    # The page itself. On dark this is the whole point, so it is painted first
    # and edge to edge rather than being left to the reader's viewer.
    c.setFillColor(HexColor(skin["page"]))
    c.rect(0, 0, W, H, stroke=0, fill=1)

    def tracked(text, x, y, font, size, colour, spacing=0.0, right=False):
        """Letter-spaced text.

        Two traps here, both of which bit. Tracking lives on the text object in
        reportlab rather than on the canvas, and a right-aligned run has to be
        measured with the spacing included or it drifts off the margin.

        The one that actually broke the page: Tc is PDF *graphics* state, not
        text-object state, so it survives the end of the object and every plain
        drawString after it inherits the tracking. The letter body came out
        letter-spaced and ran off the right edge. Set it back to zero inside the
        same object, after the text is written.
        """
        width = c.stringWidth(text, font, size) + spacing * max(len(text) - 1, 0)
        obj = c.beginText()
        obj.setFont(font, size)
        obj.setFillColor(colour)
        obj.setCharSpace(spacing)
        obj.setTextOrigin(x - width if right else x, y)
        obj.textOut(text)
        obj.setCharSpace(0)
        c.drawText(obj)
        return width

    def rule(y, x0=M, x1=W - M, colour=None):
        c.setStrokeColor(colour or divider)
        c.setLineWidth(0.6)
        c.line(x0, y, x1, y)

    def label(text, x, y, size=6.6, colour=None, spacing=1.5, right=False):
        return tracked(text.upper(), x, y, "Courier-Bold", size,
                       colour or muted, spacing, right)

    def mark(x, y, cell=3.1 * mm, gap=0.85 * mm):
        """The cipher grid, drawn. Four voids, in the four places the app puts
        them, so this is the same mark and not a picture of one."""
        c.setFillColor(ink)
        for row in range(4):
            for col in range(4):
                if (row, col) in VOIDS:
                    continue
                c.roundRect(x + col * (cell + gap),
                            y - row * (cell + gap) - cell,
                            cell, cell, 0.5 * mm, stroke=0, fill=1)
        return 4 * cell + 3 * gap

    # --- masthead ---------------------------------------------------------
    top = H - M
    width = mark(M, top)
    left = M + width + 9 * mm

    tracked(SENDER[0], left, top - 12.5 * mm, "Helvetica-Bold", 19, ink, 2.2)
    label(SENDER[1], left, top - 17.5 * mm, size=6.4)

    # The meta block hangs off the right margin so the two columns share a
    # baseline and the eye has one edge to run down.
    y = top - 1 * mm
    for name, value in META:
        label(name, W - M - 34 * mm, y, size=6.4, right=True)
        tracked(value, W - M, y, "Helvetica", 9, dim, right=True)
        y -= 5.6 * mm

    rule(top - 26 * mm)

    # --- recipient --------------------------------------------------------
    y = top - 38 * mm
    label("TO", M, y)
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    c.setFillColor(dim)
    for line in RECIPIENT:
        c.drawString(M, y, line)
        y -= 5 * mm

    # --- body -------------------------------------------------------------
    y -= 8 * mm
    c.setFont("Helvetica", 10.5)
    c.setFillColor(ink)
    c.drawString(M, y, SALUTATION)
    y -= 9 * mm

    measure = W - 2 * M
    for para in BODY:
        c.setFont("Helvetica", 10.5)
        c.setFillColor(dim)
        for line in _wrap(c, para, "Helvetica", 10.5, measure):
            c.drawString(M, y, line)
            y -= 5.6 * mm
        y -= 4 * mm

    # --- sign off ---------------------------------------------------------
    y -= 4 * mm
    c.setFont("Helvetica", 10.5)
    c.setFillColor(ink)
    c.drawString(M, y, CLOSING)
    y -= 20 * mm                      # room for a signature
    rule(y + 5 * mm, x0=M, x1=M + 52 * mm, colour=HexColor(skin["rest"]))
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(ink)
    c.drawString(M, y, SIGNOFF[0])
    c.setFont("Helvetica", 9)
    c.setFillColor(muted)
    c.drawString(M, y - 5 * mm, SIGNOFF[1])

    # --- footer -----------------------------------------------------------
    rule(M + 10 * mm)
    label(FOOTER_LEFT, M, M + 4 * mm, size=6.4)
    tracked(FOOTER_RIGHT, W - M, M + 4 * mm, "Courier", 6.4, muted, 1.2, right=True)

    c.showPage()
    c.save()


def _wrap(c, text: str, font: str, size: float, width: float) -> list[str]:
    """Greedy wrap against the real measured width of the font."""
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if c.stringWidth(trial, font, size) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


# --------------------------------------------------------------------- Word

def _mark_png(skin: dict, out: pathlib.Path, cell: int = 26, gap: int = 7) -> pathlib.Path:
    """The mark as an image, because Word has no honest way to draw one.

    Rendered at 4x and downsampled, so the squares have clean edges at the size
    it actually sits at in the header.
    """
    from PIL import Image, ImageDraw
    scale = 4
    size = (4 * cell + 3 * gap) * scale
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    ink = tuple(int(skin["ink"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    for row in range(4):
        for col in range(4):
            if (row, col) in VOIDS:
                continue
            x = col * (cell + gap) * scale
            y = row * (cell + gap) * scale
            draw.rounded_rectangle([x, y, x + cell * scale, y + cell * scale],
                                   radius=int(1.5 * scale), fill=ink)
    img.resize((size // scale, size // scale), Image.LANCZOS).save(out)
    return out


def docx(skin: dict, out: pathlib.Path) -> None:
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, Cm, RGBColor

    def hexrgb(value: str) -> RGBColor:
        return RGBColor.from_string(value.lstrip("#").upper())

    d = Document()
    section = d.sections[0]
    section.top_margin = section.bottom_margin = Cm(2.2)
    section.left_margin = section.right_margin = Cm(2.2)

    # Dark mode in Word is a page background, and Word will not show one unless
    # it is also told to display background shapes. Both, or the file opens
    # white and the whole exercise is pointless.
    if skin["name"] == "dark":
        background = OxmlElement("w:background")
        background.set(qn("w:color"), skin["page"].lstrip("#").upper())
        d.element.insert(0, background)
        settings = d.settings.element
        display = OxmlElement("w:displayBackgroundShape")
        settings.append(display)

    normal = d.styles["Normal"]
    normal.font.name = "Inter"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = hexrgb(skin["dim"])
    normal.paragraph_format.space_after = Pt(10)
    # Inter is not on every machine; name the fallback Word should reach for.
    rpr = normal.element.get_or_add_rPr().get_or_add_rFonts()
    rpr.set(qn("w:ascii"), "Inter")
    rpr.set(qn("w:hAnsi"), "Inter")
    rpr.set(qn("w:cs"), "Calibri")

    def para(text="", size=10.5, colour=None, bold=False, mono=False,
             space_after=10, align=None, spacing=None):
        p = d.add_paragraph()
        p.paragraph_format.space_after = Pt(space_after)
        if align is not None:
            p.alignment = align
        run = p.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
        run.font.color.rgb = hexrgb(colour or skin["dim"])
        if mono:
            run.font.name = "JetBrains Mono"
            run.element.get_or_add_rPr().get_or_add_rFonts().set(
                qn("w:cs"), "Consolas")
        if spacing:
            # Tracking, which python-docx does not expose. w:spacing is in
            # twentieths of a point.
            el = OxmlElement("w:spacing")
            el.set(qn("w:val"), str(int(spacing * 20)))
            run.element.get_or_add_rPr().append(el)
        return p

    def rule(space_before=0, space_after=14):
        p = d.add_paragraph()
        p.paragraph_format.space_before = Pt(space_before)
        p.paragraph_format.space_after = Pt(space_after)
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "4")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), skin["divider"].lstrip("#").upper())
        borders.append(bottom)
        p._p.get_or_add_pPr().append(borders)

    # --- masthead: mark and wordmark on the left, meta on the right --------
    png = _mark_png(skin, out.with_name(f".mark-{skin['name']}.png"))
    # Three columns, not two: the mark sits beside the wordmark exactly as it
    # does in the PDF. Putting both in one cell stacks them, which is a
    # different lockup, and the two files have to be the same letterhead.
    head = d.add_table(rows=1, cols=3)
    head.alignment = WD_TABLE_ALIGNMENT.CENTER
    head.autofit = False
    badge, left, right = head.rows[0].cells
    badge.width = Cm(2.2)
    left.width = Cm(8.2)
    right.width = Cm(6.0)

    holder = badge.paragraphs[0]
    holder.paragraph_format.space_after = Pt(0)
    holder.add_run().add_picture(str(png), width=Cm(1.9))

    name = left.paragraphs[0]
    name.paragraph_format.space_before = Pt(9)
    name.paragraph_format.space_after = Pt(0)
    run = name.add_run(SENDER[0])
    run.bold = True
    run.font.size = Pt(19)
    run.font.color.rgb = hexrgb(skin["ink"])
    tracking = OxmlElement("w:spacing")
    tracking.set(qn("w:val"), "44")
    run.element.get_or_add_rPr().append(tracking)

    sub = left.add_paragraph()
    subrun = sub.add_run(SENDER[1].upper())
    subrun.font.size = Pt(6.5)
    subrun.font.name = "JetBrains Mono"
    subrun.font.color.rgb = hexrgb(skin["muted"])
    sp = OxmlElement("w:spacing"); sp.set(qn("w:val"), "30")
    subrun.element.get_or_add_rPr().append(sp)

    for n, (key, value) in enumerate(META):
        p = right.paragraphs[0] if n == 0 else right.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.space_after = Pt(4)
        k = p.add_run(f"{key}   ")
        k.font.size = Pt(6.5)
        k.font.name = "JetBrains Mono"
        k.font.color.rgb = hexrgb(skin["muted"])
        v = p.add_run(value)
        v.font.size = Pt(9)
        v.font.color.rgb = hexrgb(skin["dim"])

    _strip_borders(head)
    rule(space_before=10, space_after=20)

    # --- recipient --------------------------------------------------------
    para("TO", size=6.5, colour=skin["muted"], mono=True, space_after=6, spacing=1.4)
    for line in RECIPIENT:
        para(line, size=10, space_after=2)

    # --- body -------------------------------------------------------------
    salutation = para(SALUTATION, size=10.5, colour=skin["ink"], space_after=12)
    salutation.paragraph_format.space_before = Pt(18)
    for text in BODY:
        para(text, size=10.5, space_after=12)

    # --- sign off ---------------------------------------------------------
    para(CLOSING, size=10.5, colour=skin["ink"], space_after=40)
    # The line he signs on. Short, and only as wide as a signature needs.
    signature = d.add_paragraph()
    signature.paragraph_format.space_after = Pt(4)
    sig_borders = OxmlElement("w:pBdr")
    sig_bottom = OxmlElement("w:bottom")
    sig_bottom.set(qn("w:val"), "single")
    sig_bottom.set(qn("w:sz"), "4")
    sig_bottom.set(qn("w:space"), "1")
    sig_bottom.set(qn("w:color"), skin["rest"].lstrip("#").upper())
    sig_borders.append(sig_bottom)
    signature._p.get_or_add_pPr().append(sig_borders)
    sig_ind = OxmlElement("w:ind")
    sig_ind.set(qn("w:right"), "6400")        # twips: stop it short of the margin
    signature._p.get_or_add_pPr().append(sig_ind)

    para(SIGNOFF[0], size=10, colour=skin["ink"], bold=True, space_after=2)
    para(SIGNOFF[1], size=9, colour=skin["muted"], space_after=0)

    # --- footer -----------------------------------------------------------
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.LEFT
    f = footer.add_run(f"{FOOTER_LEFT}\t\t{FOOTER_RIGHT}")
    f.font.size = Pt(6.5)
    f.font.name = "JetBrains Mono"
    f.font.color.rgb = hexrgb(skin["muted"])

    d.save(out)
    png.unlink(missing_ok=True)


def _strip_borders(table) -> None:
    """A layout table is scaffolding. It must not be visible."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        borders.append(el)
    table._tbl.tblPr.append(borders)


def main() -> int:
    for skin in (LIGHT, DARK):
        pdf(skin, HERE / f"ENYGMA-letterhead-{skin['name']}.pdf")
        docx(skin, HERE / f"ENYGMA-letterhead-{skin['name']}.docx")
        print(f"  {skin['name']:5}  pdf + docx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
