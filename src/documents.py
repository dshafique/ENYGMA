"""Documents ENYGMA can hand him.

He asked for a markdown file and got a fenced code block on a phone screen,
which he would then have had to select by hand, on a folding phone, without
losing the indentation. That is the problem this file solves: when he asks for a
file, he gets a file.

Six formats, one document. Everything is built from a single format-agnostic
structure rather than six separate generators, because six generators means six
chances for the model to produce something that renders in one of them and not
the others. The structure is boring on purpose: headings, paragraphs, bullets,
numbered lists, tables, code and quotes. Everything a work document is actually
made of, and nothing that only one format can express.

Every dependency here installs with pip and needs no system packages, which is
the constraint that matters: the Spark builds its venv from requirements.txt
during the install, and a renderer that wants LibreOffice or a headless browser
would turn a two minute deploy into an afternoon.
"""
from __future__ import annotations

import io
import re
from html import escape

from . import voice, grounding

# md and html need nothing. The other four are imported where they are used, so
# a missing wheel takes down one format with a clear message rather than the
# whole module -- and, more to the point, the app still starts.
FORMATS = ("md", "html", "docx", "pptx", "xlsx", "pdf")

MIMES = {
    "md": "text/markdown",
    "html": "text/html",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}

NAMES = {
    "md": "Markdown", "html": "Web page", "docx": "Word document",
    "pptx": "Slide deck", "xlsx": "Spreadsheet", "pdf": "PDF",
}

# How he actually asks. Extensions first, because ".md file" is unambiguous and
# a word like "sheet" is not.
_SPOKEN = {
    "docx": r"\.docx\b|\bword\b|\bword doc\w*",
    "pptx": r"\.pptx\b|\bpower ?point\b|\bslide ?deck\b|\bslides?\b|\bdeck\b|\bpresentation\b",
    "xlsx": r"\.xlsx?\b|\bexcel\b|\bspread ?sheet\b|\bworkbook\b",
    "pdf": r"\.pdf\b|\bpdf\b",
    "md": r"\.md\b|\bmarkdown\b|\bmd file\b",
    "html": r"\.html?\b|\bweb ?page\b|\bhtml\b",
}
# Asking for a document at all, without naming a kind.
_ANY = re.compile(
    r"\b(make|write|create|build|generate|draft|put (?:it|that|this) in(?:to)?|"
    r"turn (?:it|that|this) into|give me|send me|export|save (?:it|that|this) as)\b"
    r".{0,60}?\b(file|document|doc|report|sheet|deck|memo|write ?up|template)\b",
    re.I | re.S)


def detect(text: str) -> str | None:
    """Which format he asked for, if he asked for one at all.

    A named format wins outright. Failing that, a general request for "a file"
    or "a document" is answered in markdown, which is the format that survives
    being pasted anywhere and is what he asked for the first time.
    """
    text = text or ""
    for fmt in ("docx", "pptx", "xlsx", "pdf", "md", "html"):
        if re.search(_SPOKEN[fmt], text, re.I):
            return fmt
    return "md" if _ANY.search(text) else None


# ------------------------------------------------------------ the structure

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string",
                             "enum": ["heading", "paragraph", "bullets",
                                      "numbered", "table", "code", "quote"]},
                    "level": {"type": "integer"},
                    "text": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "string"}},
                    "columns": {"type": "array", "items": {"type": "string"}},
                    "rows": {"type": "array",
                             "items": {"type": "array", "items": {"type": "string"}}},
                },
                "required": ["type"],
            },
        },
    },
    "required": ["title", "blocks"],
}


def normalise(raw: dict) -> dict:
    """Whatever came back, made safe to render.

    Every renderer downstream assumes the keys it needs are present and are the
    type it expects. Enforcing that once here is the difference between a bad
    model response producing a plain document and producing a traceback.
    """
    blocks = []
    for block in (raw.get("blocks") or []):
        if not isinstance(block, dict):
            continue
        kind = str(block.get("type") or "paragraph")
        if kind not in ("heading", "paragraph", "bullets", "numbered",
                        "table", "code", "quote"):
            kind = "paragraph"
        text = str(block.get("text") or "").strip()
        items = [str(x).strip() for x in (block.get("items") or []) if str(x).strip()]
        columns = [str(x) for x in (block.get("columns") or [])]
        rows = [[str(c) for c in row] for row in (block.get("rows") or [])
                if isinstance(row, (list, tuple))]
        if kind == "heading" and not text:
            continue
        if kind in ("paragraph", "code", "quote") and not text:
            continue
        if kind in ("bullets", "numbered") and not items:
            continue
        if kind == "table" and not rows:
            continue
        blocks.append({"type": kind, "text": text, "items": items,
                       "columns": columns, "rows": rows,
                       "level": min(max(int(block.get("level") or 2), 1), 3)})
    return {"title": str(raw.get("title") or "Untitled").strip()[:200],
            "subtitle": str(raw.get("subtitle") or "").strip()[:300],
            "blocks": blocks}


def filename(doc: dict, fmt: str) -> str:
    """A name he can find again on a phone, which means words, not a hash."""
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", doc.get("title") or "document").strip("-").lower()
    return f"{(stem or 'document')[:60]}.{fmt}"


def as_text(doc: dict) -> str:
    """The document as plain prose. This is what goes into the Library, so a
    question answered next month can quote a file made today."""
    out = [doc["title"]]
    if doc.get("subtitle"):
        out.append(doc["subtitle"])
    for b in doc["blocks"]:
        if b["type"] in ("heading", "paragraph", "quote", "code"):
            out.append(b["text"])
        elif b["type"] in ("bullets", "numbered"):
            out += b["items"]
        elif b["type"] == "table":
            if b["columns"]:
                out.append(" | ".join(b["columns"]))
            out += [" | ".join(r) for r in b["rows"]]
    return "\n\n".join(x for x in out if x)


# ------------------------------------------------------------- the renderers
#
# Two looks. Plain is the default and is what goes to his manager or into his
# employer's repository: neutral, unbranded, indistinguishable from something
# typed in Word. ENYGMA is the house style, for the things he keeps.

PLAIN = {"font": "Calibri", "mono": "Consolas", "ink": "#111111",
         "dim": "#555555", "rule": "#cccccc", "accent": "#111111"}
HOUSE = {"font": "Inter", "mono": "JetBrains Mono", "ink": "#16161a",
         "dim": "#525862", "rule": "#cfcfd6", "accent": "#16161a"}


def _skin(style: str) -> dict:
    return HOUSE if style == "enygma" else PLAIN


def render(doc: dict, fmt: str, style: str = "plain") -> bytes:
    if fmt not in FORMATS:
        raise ValueError(f"{fmt!r} is not one of {', '.join(FORMATS)}")
    return globals()[f"_{fmt}"](doc, _skin(style), style)


def _md(doc: dict, skin: dict, style: str) -> bytes:
    out = [f"# {doc['title']}"]
    if doc["subtitle"]:
        out.append(f"*{doc['subtitle']}*")
    for b in doc["blocks"]:
        if b["type"] == "heading":
            out.append("#" * (b["level"] + 1) + " " + b["text"])
        elif b["type"] == "paragraph":
            out.append(b["text"])
        elif b["type"] == "bullets":
            out.append("\n".join(f"- {x}" for x in b["items"]))
        elif b["type"] == "numbered":
            out.append("\n".join(f"{n}. {x}" for n, x in enumerate(b["items"], 1)))
        elif b["type"] == "quote":
            out.append("\n".join(f"> {line}" for line in b["text"].splitlines()))
        elif b["type"] == "code":
            out.append(f"```\n{b['text']}\n```")
        elif b["type"] == "table":
            cols = b["columns"] or [f"Column {n}" for n in range(1, len(b["rows"][0]) + 1)]
            out.append("| " + " | ".join(cols) + " |")
            out.append("| " + " | ".join("---" for _ in cols) + " |")
            out += ["| " + " | ".join(r) + " |" for r in b["rows"]]
    return ("\n\n".join(out) + "\n").encode("utf-8")


def _html(doc: dict, skin: dict, style: str) -> bytes:
    body = []
    for b in doc["blocks"]:
        if b["type"] == "heading":
            body.append(f"<h{b['level'] + 1}>{escape(b['text'])}</h{b['level'] + 1}>")
        elif b["type"] == "paragraph":
            body.append(f"<p>{escape(b['text'])}</p>")
        elif b["type"] in ("bullets", "numbered"):
            tag = "ul" if b["type"] == "bullets" else "ol"
            items = "".join(f"<li>{escape(x)}</li>" for x in b["items"])
            body.append(f"<{tag}>{items}</{tag}>")
        elif b["type"] == "quote":
            body.append(f"<blockquote>{escape(b['text'])}</blockquote>")
        elif b["type"] == "code":
            body.append(f"<pre><code>{escape(b['text'])}</code></pre>")
        elif b["type"] == "table":
            cols = b["columns"] or [""] * len(b["rows"][0])
            head = "".join(f"<th>{escape(c)}</th>" for c in cols)
            rows = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in r) + "</tr>"
                           for r in b["rows"])
            body.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
    sub = f"<p class='sub'>{escape(doc['subtitle'])}</p>" if doc["subtitle"] else ""
    # One file, no external anything: it has to open from a Downloads folder on
    # a phone with no signal.
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(doc['title'])}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: {skin['font']}, -apple-system, "Segoe UI", sans-serif;
         color: {skin['ink']}; background: #fff; line-height: 1.6;
         max-width: 46rem; margin: 0 auto; padding: 3rem 1.25rem 6rem; }}
  h1 {{ font-size: 2rem; line-height: 1.2; margin: 0 0 .5rem; }}
  h2 {{ font-size: 1.35rem; margin: 2.5rem 0 .5rem; }}
  h3, h4 {{ font-size: 1.1rem; margin: 2rem 0 .5rem; }}
  .sub {{ color: {skin['dim']}; margin: 0 0 2.5rem; }}
  blockquote {{ margin: 1.5rem 0; padding-left: 1rem;
                border-left: 3px solid {skin['rule']}; color: {skin['dim']}; }}
  pre {{ background: #f5f5f7; padding: 1rem; border-radius: 6px; overflow-x: auto; }}
  code {{ font-family: {skin['mono']}, ui-monospace, monospace; font-size: .9em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1.5rem 0; display: block;
           overflow-x: auto; }}
  th, td {{ border: 1px solid {skin['rule']}; padding: .5rem .75rem; text-align: left; }}
  th {{ background: #f5f5f7; font-weight: 600; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #111; color: #eee; }}
    pre, th {{ background: #1c1c1f; }}
    th, td {{ border-color: #333; }}
  }}
</style></head><body>
<h1>{escape(doc['title'])}</h1>{sub}
{chr(10).join(body)}
</body></html>
""".encode("utf-8")


def _docx(doc: dict, skin: dict, style: str) -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    d = Document()
    normal = d.styles["Normal"]
    normal.font.name = skin["font"]
    normal.font.size = Pt(11)

    d.add_heading(doc["title"], level=0)
    if doc["subtitle"]:
        p = d.add_paragraph(doc["subtitle"])
        p.runs[0].font.color.rgb = RGBColor.from_string(skin["dim"].lstrip("#").upper())
        p.runs[0].italic = True

    for b in doc["blocks"]:
        if b["type"] == "heading":
            d.add_heading(b["text"], level=b["level"])
        elif b["type"] == "paragraph":
            d.add_paragraph(b["text"])
        elif b["type"] == "bullets":
            for x in b["items"]:
                d.add_paragraph(x, style="List Bullet")
        elif b["type"] == "numbered":
            for x in b["items"]:
                d.add_paragraph(x, style="List Number")
        elif b["type"] == "quote":
            p = d.add_paragraph(b["text"])
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.left_indent = Pt(24)
            p.runs[0].italic = True
        elif b["type"] == "code":
            p = d.add_paragraph()
            run = p.add_run(b["text"])
            run.font.name = skin["mono"]
            run.font.size = Pt(9.5)
        elif b["type"] == "table":
            cols = b["columns"] or [""] * len(b["rows"][0])
            table = d.add_table(rows=1, cols=len(cols))
            table.style = "Table Grid"
            for cell, name in zip(table.rows[0].cells, cols):
                cell.text = name
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.bold = True
            for row in b["rows"]:
                cells = table.add_row().cells
                for cell, value in zip(cells, row):
                    cell.text = value
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _pptx(doc: dict, skin: dict, style: str) -> bytes:
    """Blocks become slides. A level 1 or 2 heading starts a new one and
    everything under it becomes that slide's body, which is how a document turns
    into a deck without the model having to think in slides."""
    from pptx import Presentation
    from pptx.util import Pt, Inches

    prs = Presentation()
    title_layout, bullet_layout = prs.slide_layouts[0], prs.slide_layouts[1]

    opening = prs.slides.add_slide(title_layout)
    opening.shapes.title.text = doc["title"]
    if len(opening.placeholders) > 1:
        opening.placeholders[1].text = doc["subtitle"] or ""

    def new_slide(heading: str):
        slide = prs.slides.add_slide(bullet_layout)
        slide.shapes.title.text = heading
        frame = slide.placeholders[1].text_frame
        frame.clear()
        frame.word_wrap = True
        return frame

    frame, first = None, True

    def line(text: str, level: int = 0):
        nonlocal first
        if frame is None:
            return
        para = frame.paragraphs[0] if first else frame.add_paragraph()
        para.text = text
        para.level = level
        para.font.size = Pt(18)
        first = False

    for b in doc["blocks"]:
        if b["type"] == "heading" and b["level"] <= 2:
            frame, first = new_slide(b["text"]), True
            continue
        if frame is None:                      # content before any heading
            frame, first = new_slide(doc["title"]), True
        if b["type"] == "heading":
            line(b["text"])
        elif b["type"] in ("paragraph", "quote"):
            line(b["text"])
        elif b["type"] in ("bullets", "numbered"):
            for n, x in enumerate(b["items"], 1):
                line(f"{n}. {x}" if b["type"] == "numbered" else x, level=1)
        elif b["type"] == "code":
            for row in b["text"].splitlines():
                line(row, level=1)
        elif b["type"] == "table":
            if b["columns"]:
                line(" | ".join(b["columns"]))
            for row in b["rows"]:
                line(" | ".join(row), level=1)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _xlsx(doc: dict, skin: dict, style: str) -> bytes:
    """Tables become sheets of their own, because that is the only reason to ask
    for a spreadsheet. Everything else goes on one readable sheet rather than
    being thrown away."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment

    wb = Workbook()
    bold = Font(bold=True)
    tables = [b for b in doc["blocks"] if b["type"] == "table"]

    sheet = wb.active
    sheet.title = "Document"[:31]
    sheet["A1"] = doc["title"]
    sheet["A1"].font = Font(bold=True, size=14)
    row = 3 if not doc["subtitle"] else 4
    if doc["subtitle"]:
        sheet["A2"] = doc["subtitle"]

    for b in doc["blocks"]:
        if b["type"] == "table":
            continue
        if b["type"] == "heading":
            sheet.cell(row=row, column=1, value=b["text"]).font = bold
        elif b["type"] in ("paragraph", "quote", "code"):
            cell = sheet.cell(row=row, column=1, value=b["text"])
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        elif b["type"] in ("bullets", "numbered"):
            for n, x in enumerate(b["items"], 1):
                sheet.cell(row=row, column=1,
                           value=(f"{n}. " if b["type"] == "numbered" else "- ") + x)
                row += 1
            row += 1
            continue
        row += 2
    sheet.column_dimensions["A"].width = 90

    for n, b in enumerate(tables, 1):
        name = (b["text"] or f"Table {n}")[:31] or f"Table {n}"
        ws = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", " ", name))
        cols = b["columns"] or [f"Column {i}" for i in range(1, len(b["rows"][0]) + 1)]
        ws.append(cols)
        for cell in ws[1]:
            cell.font = bold
        for r in b["rows"]:
            ws.append(r)
        for i, col in enumerate(cols, 1):
            longest = max([len(str(col))] + [len(str(r[i - 1])) for r in b["rows"]
                                             if len(r) >= i] or [10])
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = \
                min(max(longest + 2, 10), 60)
        ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pdf(doc: dict, skin: dict, style: str) -> bytes:
    """Built directly rather than printed from HTML.

    Printing HTML means a headless browser, which means a browser install on the
    Spark and a deploy that can fail on a machine with no display. reportlab is
    a pip wheel and produces a real, selectable, searchable PDF.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, Preformatted)

    ink = colors.HexColor(skin["ink"])
    dim = colors.HexColor(skin["dim"])
    rule = colors.HexColor(skin["rule"])
    base = getSampleStyleSheet()

    # Helvetica and Courier are built in, so the PDF carries no font files and
    # opens identically everywhere.
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica",
                          fontSize=10.5, leading=15.5, textColor=ink,
                          spaceAfter=7, alignment=TA_LEFT)
    styles = {
        "title": ParagraphStyle("title", parent=body, fontName="Helvetica-Bold",
                                fontSize=21, leading=25, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", parent=body, fontSize=11,
                                   textColor=dim, spaceAfter=18),
        "h1": ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold",
                             fontSize=15, leading=19, spaceBefore=16, spaceAfter=5),
        "h2": ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold",
                             fontSize=12.5, leading=17, spaceBefore=13, spaceAfter=4),
        "h3": ParagraphStyle("h3", parent=body, fontName="Helvetica-Bold",
                             fontSize=11, leading=15, spaceBefore=11, spaceAfter=3),
        "bullet": ParagraphStyle("bullet", parent=body, leftIndent=13,
                                 bulletIndent=3, spaceAfter=3),
        "quote": ParagraphStyle("quote", parent=body, leftIndent=14,
                                textColor=dim, borderPadding=0, spaceBefore=6,
                                spaceAfter=8, fontName="Helvetica-Oblique"),
        "code": ParagraphStyle("code", parent=body, fontName="Courier",
                               fontSize=8.5, leading=11.5, leftIndent=8,
                               backColor=colors.HexColor("#f5f5f7"),
                               borderPadding=6, spaceBefore=6, spaceAfter=8),
    }

    def esc(text: str) -> str:
        return escape(text or "", quote=False)

    flow = [Paragraph(esc(doc["title"]), styles["title"])]
    if doc["subtitle"]:
        flow.append(Paragraph(esc(doc["subtitle"]), styles["subtitle"]))

    for b in doc["blocks"]:
        if b["type"] == "heading":
            flow.append(Paragraph(esc(b["text"]), styles[f"h{b['level']}"]))
        elif b["type"] == "paragraph":
            flow.append(Paragraph(esc(b["text"]), body))
        elif b["type"] == "bullets":
            for x in b["items"]:
                flow.append(Paragraph(esc(x), styles["bullet"], bulletText="•"))
        elif b["type"] == "numbered":
            for n, x in enumerate(b["items"], 1):
                flow.append(Paragraph(esc(x), styles["bullet"], bulletText=f"{n}."))
        elif b["type"] == "quote":
            flow.append(Paragraph(esc(b["text"]), styles["quote"]))
        elif b["type"] == "code":
            flow.append(Preformatted(b["text"], styles["code"]))
        elif b["type"] == "table":
            cols = b["columns"] or [""] * len(b["rows"][0])
            cell = ParagraphStyle("cell", parent=body, fontSize=9, leading=12,
                                  spaceAfter=0)
            head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold")
            data = [[Paragraph(esc(c), head) for c in cols]]
            data += [[Paragraph(esc(c), cell) for c in r] for r in b["rows"]]
            table = Table(data, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, rule),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f5f7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            flow += [Spacer(1, 6), table, Spacer(1, 10)]

    buf = io.BytesIO()
    SimpleDocTemplate(
        buf, pagesize=A4, title=doc["title"], author="ENYGMA",
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    ).build(flow)
    return buf.getvalue()


# ------------------------------------------------------------ the content

BRIEF = """You are preparing a document for an engineering intern to hand to
somebody at work. Write it as him. It must not read as though a machine wrote
it, because he is putting his name on it.

How to write:
  * Plain words. If a shorter word does the job, use it.
  * Say the thing, give the number if there is one, then stop.
  * Short sentences, one idea each.
  * No selling and no throat-clearing. "Fixed the login bug" is finished.
  * Do not introduce the document inside the document. No "here is your report",
    no "this document aims to", no closing summary of what was just said.
  * Do not open a bullet with a bolded label and a colon. Write the sentence.
  * No emoji. No em dashes. No semicolons in ordinary prose.

Never use these: leverage, utilise, delve, streamline, robust, seamless,
spearhead, facilitate, synergy, holistic, impactful, actionable, deep dive,
circle back, moving forward, key learnings, best practices, in conclusion,
in summary, it is important to note, excited to share, I hope this helps.

Technical words are not the problem and must not be avoided. I2C, MOSFET, pull-up
resistor, bus address, calibration drift and the rest are what the document is
about. Cut management vocabulary, never the engineering.

What to produce:
  * A title, then blocks of headings, paragraphs, bullets, numbered lists,
    tables, code and quotes.
  * Use the material. Do not invent facts, names, numbers or dates that are not
    in it. Where the material leaves a blank, write a clearly marked placeholder
    in square brackets rather than a plausible guess.
  * Anything with repeating fields goes in a table. A table survives every
    format; a paragraph describing rows does not.
  * Commands, code and file contents go in a code block, never in a paragraph."""
BRIEF += "\n\n" + grounding.NEVER_INVENT



# Blocks whose contents are data or code rather than prose. Rewriting the
# typography inside these corrupts them: a shell command loses its semicolons,
# a row of bus addresses loses its separators. Code is exempt from the word
# check too, because a variable can legitimately be called leverage_ratio.
_NOT_PROSE = {"code", "table"}
_NEVER_READ = {"code"}


def prose_of(doc: dict) -> list[str]:
    """Every line in the document that is meant to read as English."""
    lines = [doc.get("title", ""), doc.get("subtitle", "")]
    for block in doc.get("blocks", []):
        if block["type"] in _NEVER_READ:
            continue
        lines.append(block.get("text", ""))
        lines += block.get("items", [])
        if block["type"] == "table":
            lines += block.get("columns", [])
            for row in block.get("rows", []):
                lines += row
    return [line for line in lines if line]


def enforce(doc: dict) -> dict:
    """Put the prose right mechanically, leaving code and data alone.

    The last resort, after the model has been asked twice. A document that still
    says "leveraged" here keeps the word -- dropping a sentence out of a report
    would change what it says -- but the typography and the bolded lead-in tic
    are rewritten, because those change nothing except how it reads.
    """
    doc = dict(doc)
    doc["title"] = voice.tidy(doc.get("title", ""))
    doc["subtitle"] = voice.tidy(doc.get("subtitle", ""))
    blocks = []
    for block in doc.get("blocks", []):
        block = dict(block)
        if block["type"] not in _NOT_PROSE:
            block["text"] = voice.tidy(block.get("text", ""))
            block["items"] = [voice.tidy(x) for x in block.get("items", [])]
        blocks.append(block)
    doc["blocks"] = blocks
    return doc


def compose(brief: str, context: str = "", backend=None,
            fallback_title: str = "") -> dict:
    """Ask for a document, and hand back a structure the renderers can trust."""
    from .config import config
    if config.PIPELINE != "gemini":
        return _stub(brief, context, fallback_title)
    from .pipeline.gemini import GeminiBackend
    backend = backend or GeminiBackend()
    ask = f"{BRIEF}\n\nWhat he asked for:\n{brief}\n"
    if context:
        ask += f"\nThe material:\n{context}\n"
    doc = _one(backend, ask)

    # Asked once, then asked again naming exactly what was wrong. A bare retry
    # repeats the mistake with more confidence; naming it is what makes the
    # second attempt different. Only the prose is read, so a command in a code
    # block and a column of bus addresses cannot trigger a rewrite of the whole
    # document.
    wrong = voice.complaints(prose_of(doc))
    if wrong:
        retry = _one(backend, ask + (
            "\n\nYour last attempt had these in it: " + "; ".join(wrong) +
            ". Write it again without them. Keep every technical term and every "
            "number exactly as it was; it is only the way it is written that is "
            "wrong."))
        # Keep the retry only if it is actually better. A second attempt that
        # reads worse is not an improvement just because it is second.
        if len(voice.complaints(prose_of(retry))) < len(wrong) and retry["blocks"]:
            doc = retry

    doc = enforce(doc)
    if not doc["blocks"]:
        # A document with nothing in it is worse than an honest refusal, because
        # it downloads and opens and looks like the feature worked.
        raise ValueError("The model did not return anything that could be made "
                         "into a document. Try asking again, more specifically.")
    return doc


def _one(backend, ask: str) -> dict:
    import json
    raw = backend._ask([{"type": "text", "text": ask}], schema=SCHEMA)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    return normalise(parsed)


# The asking, as opposed to the thing asked for. "Can you make me a .md file for
# the tent logbook" is a request for a document about the tent logbook, and the
# file should be named for that rather than for the sentence he typed. A regex
# over the whole phrase was tried first and kept leaving fragments like "up a
# report on"; dropping known filler words from the front until a real one turns
# up is duller and gets it right.
# Two lists, not one, and the reason is "write up a report on the tent build".
# "build" is a word he uses to ask for things and also the name of the thing
# itself, so stripping it from both ends turned that into "tent". The front of
# the sentence is where the asking lives; the back is where the format lives.
_LEADING = {
    "can", "could", "would", "will", "you", "please", "pls",
    "make", "made", "write", "writing", "create", "build", "generate", "draft",
    "give", "send", "export", "turn", "put", "save", "prepare", "produce", "get",
    "me", "us", "my", "our", "i", "want", "need", "like",
    "a", "an", "the", "this", "that", "it", "these", "those", "all",
    "into", "in", "as", "out", "of", "from", "for", "about", "on", "covering",
    "up", "with", "to", "and", "based",
    "file", "files", "document", "doc", "report", "sheet", "deck", "memo",
    "page", "answer", "version", "copy", "conversation", "thread", "chat",
    "markdown", "md", "word", "docx", "excel", "xlsx", "spreadsheet", "workbook",
    "powerpoint", "pptx", "slide", "slides", "presentation", "pdf", "html", "web",
}
# The back of the sentence: the format he wants and the words joining it on.
# Nothing here is ever the subject of a document.
_TRAILING = {
    "a", "an", "the", "this", "that", "it",
    "into", "in", "as", "of", "from", "for", "to", "out", "with", "and", "please",
    "file", "files", "document", "doc", "sheet", "deck", "memo", "page",
    "version", "copy", "format",
    "markdown", "md", "word", "docx", "excel", "xlsx", "spreadsheet", "workbook",
    "powerpoint", "pptx", "slide", "slides", "presentation", "pdf", "html", "web",
}


def _bare(word: str) -> str:
    return word.strip(".,:;!?-\u2019'\"").lstrip(".").lower()


def title_from_request(brief: str) -> str:
    """What he wants it to be about, with the asking taken off the front and the
    format taken off the back."""
    first = ((brief or "").strip().splitlines() or [""])[0]
    words = re.findall(r"[^\s]+", first)
    while words and (not _bare(words[0]) or _bare(words[0]) in _LEADING):
        words.pop(0)
    while words and (not _bare(words[-1]) or _bare(words[-1]) in _TRAILING):
        words.pop()
    kept = " ".join(words).strip(" .:,-\u2013\u2014")
    return (kept or "Document")[:80]


def _stub(brief: str, context: str, fallback_title: str = "") -> dict:
    """No model. The material itself, formatted, so the whole path stays
    testable and the app still hands him a real file."""
    blocks = [{"type": "heading", "level": 1, "text": "What was asked for",
               "items": [], "columns": [], "rows": []},
              {"type": "paragraph", "text": brief.strip() or "A document.",
               "items": [], "columns": [], "rows": []}]
    if context.strip():
        blocks += [{"type": "heading", "level": 1, "text": "The material",
                    "items": [], "columns": [], "rows": []}]
        blocks += [{"type": "paragraph", "text": para.strip(), "items": [],
                    "columns": [], "rows": []}
                   for para in context.split("\n\n") if para.strip()][:40]
    # "put that in a spreadsheet" names no subject, so the thread does. A folder
    # of document.xlsx and document.docx is a folder he cannot search.
    #
    # The thread's own title is trimmed the same way, because a thread is named
    # after its first message and that message is often itself a request for a
    # file. Without this the fallback hands back exactly the sentence the
    # trimming existed to remove.
    title = title_from_request(brief)
    if title == "Document" and fallback_title.strip().lower() not in ("", "new conversation"):
        borrowed = title_from_request(fallback_title)
        if borrowed != "Document":
            title = borrowed
    return normalise({"title": title, "subtitle": "", "blocks": blocks})
