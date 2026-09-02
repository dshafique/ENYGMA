"""Render the manual to PDF with headless Chromium.

preferCSSPageSize honours the @page size and margin, which is what lets the
cover and the part dividers run full bleed.

The footer comes from the stylesheet's @page margin boxes, not from a footer
template. It used to come from the template, because Chromium ignored @page
margin boxes when this was written. It does not ignore them any more, so both
were drawing and every page carried two identical footers, one under the other.
Keeping the CSS half is the better of the two: the rule is in the document, so
the HTML prints correctly straight from a browser, and @page :first can drop the
footer from the cover, which the template had no way to do.

    python3 docs/manual/render.py
"""
import pathlib, sys
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "ENYGMA-OPERATORS-MANUAL.html"
OUT = HERE / "ENYGMA-OPERATORS-MANUAL.pdf"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

FOOTER_UNUSED = """
<div style="width:100%;font-family:'JetBrains Mono',monospace;font-size:7.5pt;
            color:#525862;padding:0 0.9in;display:flex;
            justify-content:space-between;-webkit-print-color-adjust:exact">
  <span style="letter-spacing:.14em">ENYGMA // OPERATOR'S MANUAL</span>
  <span class="pageNumber"></span>
</div>"""
EMPTY = "<div></div>"

def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        page = browser.new_page()
        page.goto(SRC.as_uri(), wait_until="networkidle")
        page.emulate_media(media="print")
        page.wait_for_timeout(1200)          # let the webfonts settle
        page.pdf(path=str(OUT),
                 prefer_css_page_size=True,
                 print_background=True,
                 display_header_footer=True,
                 header_template=EMPTY,
                 footer_template=EMPTY)
        browser.close()
    kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT.name}  ({kb:.0f} KB)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
