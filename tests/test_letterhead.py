"""The letterhead.

Stationery is a build artefact like anything else here: it is generated from a
script, so the script has to keep working. These are cheap checks that it
produced four real files with the right ink in them, not a review of the design.
"""
import sys, pathlib, tempfile, subprocess, io

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
ROOT = pathlib.Path(__file__).resolve().parent.parent
LETTERHEAD = ROOT / "docs/letterhead"


def _render(tmp: pathlib.Path):
    """Run the real script, into a copy so the committed files are untouched."""
    import shutil
    work = tmp / "letterhead"
    work.mkdir()
    shutil.copy(LETTERHEAD / "render.py", work / "render.py")
    out = subprocess.run([sys.executable, str(work / "render.py")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return work


def test_it_makes_four_files_and_they_are_what_they_claim():
    tmp = pathlib.Path(tempfile.mkdtemp())
    work = _render(tmp)
    for name in ("light", "dark"):
        pdf = work / f"ENYGMA-letterhead-{name}.pdf"
        docx = work / f"ENYGMA-letterhead-{name}.docx"
        assert pdf.exists() and docx.exists(), name
        assert pdf.read_bytes().startswith(b"%PDF-")
        assert docx.read_bytes().startswith(b"PK")


def test_the_dark_one_really_has_a_dark_page():
    """A dark letterhead that opens white is not a dark letterhead. Word needs
    both a background colour and permission to display it, and the PDF has to
    paint the page rather than leave it to the reader's viewer."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    work = _render(tmp)

    import zipfile
    with zipfile.ZipFile(work / "ENYGMA-letterhead-dark.docx") as z:
        document = z.read("word/document.xml").decode()
        settings = z.read("word/settings.xml").decode()
    assert "w:background" in document and "0D0D0F" in document
    assert "displayBackgroundShape" in settings, "Word will open it white"

    with zipfile.ZipFile(work / "ENYGMA-letterhead-light.docx") as z:
        assert "w:background" not in z.read("word/document.xml").decode()


def test_the_letter_body_is_not_letter_spaced():
    """Tc is PDF graphics state, so tracking set for a label survives the text
    object and every plain string after it inherits it. That put the body in
    wide tracking and ran it off the right margin."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    work = _render(tmp)
    out = subprocess.run(["pdftotext", "-layout",
                          str(work / "ENYGMA-letterhead-light.pdf"), "-"],
                         capture_output=True, text=True)
    assert out.returncode == 0
    lines = [l.rstrip() for l in out.stdout.splitlines() if l.strip()]
    body = [l for l in lines if "letterhead" in l or "Hierarchy" in l]
    assert body, out.stdout[:400]
    # A4 at 22mm margins is about 96 characters of this size. Tracked out, the
    # same words spill past it.
    for line in body:
        assert len(line) < 100, f"line ran long, tracking has leaked: {line!r}"


def test_the_mark_has_its_four_voids():
    """It is the app's mark or it is a different mark."""
    sys.path.insert(0, str(LETTERHEAD))
    import importlib.util
    spec = importlib.util.spec_from_file_location("lh", LETTERHEAD / "render.py")
    lh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lh)
    assert lh.VOIDS == {(0, 0), (1, 2), (2, 1), (3, 3)}

    # And it matches what the app renders, cell for cell.
    macro = (ROOT / "src/templates/_mark.html").read_text()
    cells = macro[macro.index('aria-label="ENYGMA"'):macro.index("</div>")]
    flags = [("void" in piece) for piece in cells.split("<i")[1:]]
    from_app = {(n // 4, n % 4) for n, is_void in enumerate(flags) if is_void}
    assert from_app == lh.VOIDS, f"app says {from_app}, letterhead says {lh.VOIDS}"
