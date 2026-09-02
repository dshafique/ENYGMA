"""How ENYGMA writes when it writes as him.

One module, because there are now two things that produce prose he will hand to
somebody else -- the Friday note and every document -- and two copies of a rule
is one rule and one bug waiting.

The whole aim is that nothing leaving this app announces that a machine wrote
it. There are three ways it announces that, and they need three different
answers.

  Words.       A vocabulary almost nobody uses out loud: leverage, delve,
               streamline, robust, seamless. Caught by list.

  Typography.  The em dash, the semicolon in casual prose, curly quotes. Nobody
               reaches for an em dash on a phone keyboard. Caught by rewriting.

  Shape.       "Here is your document." "In conclusion." Every bullet opening
               with a bolded label and a colon. Three bullets per section,
               always exactly three. A document can contain no banned word at
               all and still be unmistakable. Caught by pattern.

What is deliberately NOT caught: his actual field. I2C, MOSFET, EZO, pull-up
resistor, diarization and bus address are the substance of the work, and a
filter that flattens those has made the writing worse, not more human. The rule
is no *management* vocabulary, not no *technical* vocabulary. Every word below
is one a person would only use to sound impressive; none of them is a thing.
"""
from __future__ import annotations

import re

# Words nobody says out loud. Substrings, so "leveraging" is caught by
# "leverag" -- but each entry has to be long enough not to fire inside an
# ordinary word, which is why this is a list of stems and phrases rather than a
# clever rule.
BANNED = (
    # The consultancy register.
    "leverag", "utilis", "utiliz", "synerg", "holistic", "impactful",
    "streamlin", "robust", "seamless", "spearhead", "facilitat", "actionable",
    "best practice", "value add", "value-add", "core competenc", "bandwidth for",
    "deep dive", "circle back", "touch base", "reach out to sync",
    "moving forward", "going forward", "at the end of the day",
    "key learnings", "key takeaway", "learnings", "deliverable",
    # The assistant register: the sound of a chat window.
    "delve", "delving", "in today's", "in the world of", "it is important to note",
    "it's important to note", "it is worth noting", "i hope this helps",
    "certainly!", "great question", "let me know if", "feel free to",
    "i'd be happy to", "i would be happy to", "as an ai",
    "excited to share", "pleased to report", "thrilled to",
    "i had the opportunity to", "embark on", "navigate the",
    "in the realm of", "a testament to", "game changer", "game-changer",
    "unlock the potential", "supercharge", "revolutionis", "revolutioniz",
    "cutting-edge", "state-of-the-art", "world-class", "best-in-class",
    "elevate your", "empower", "unparalleled", "myriad of",
    # The summing-up reflex.
    "in conclusion", "in summary", "to summarise", "to summarize",
    "overall, this", "this document aims", "this report aims",
)

# Shape rather than vocabulary. Each of these is a thing a person writing a
# note to their manager does not do, and a language model does constantly.
TELLS = (
    (re.compile(r"^\s*\*\*[^*]{1,40}:?\*\*\s*[:\-]?\s*\S"),
     "a bullet that opens with a bolded label and a colon"),
    (re.compile(r"^\s*(here (is|are) your|here'?s your|below (is|are))\b", re.I),
     "handing the document over inside the document"),
    (re.compile(r"^\s*(introduction|conclusion|overview|summary)\s*:?\s*$", re.I),
     "an essay frame around a note"),
    (re.compile(r"[\U0001F300-\U0001FAFF✀-➿☀-⛿]"),
     "an emoji"),
    (re.compile(r"\b(firstly|secondly|thirdly|furthermore|moreover|"
                r"additionally|nevertheless)\b", re.I),
     "an essay connective"),
)

_DASHES = re.compile(r"\s*[—–]\s*")
_SEMICOLON = re.compile(r"\s*;\s*")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_BOLD_LEAD = re.compile(r"^\s*\*\*([^*]{1,60}?):?\*\*\s*[:\-]?\s*")


def plain(text: str) -> str:
    """Strip the typography a person typing on a phone would not produce.

    An em dash becomes a comma, which is never wrong and only sometimes weaker
    than the full stop it might have deserved. Getting that choice exactly right
    needs a parser; getting it right enough needs a comma.
    """
    text = (text or "").translate(_QUOTES)
    text = _DASHES.sub(", ", text)
    text = _SEMICOLON.sub(", ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r",\s*,", ",", text)


def unbold_lead(text: str) -> str:
    """"**Technical decisions:** we moved to..." becomes "Technical decisions:
    we moved to...". The information survives; the tic does not."""
    return _BOLD_LEAD.sub(lambda m: f"{m.group(1)}: ", text or "")


def offences(lines) -> list[str]:
    """Which banned words survived, as he would actually read them.

    The list holds stems, so "leverag" catches leverage, leveraged and
    leveraging in one entry. But a retry that says "you used 'leverag'" is worse
    feedback than one that says "you used 'leveraged'", so the whole word is
    recovered from the text and that is what gets reported.
    """
    if isinstance(lines, str):
        lines = [lines]
    joined = " ".join(str(x) for x in lines)
    lowered = joined.lower()
    found = set()
    for stem in BANNED:
        if stem not in lowered:
            continue
        if " " in stem or "-" in stem or stem.endswith("!"):
            found.add(stem)                       # a phrase is already whole
            continue
        whole = re.findall(rf"[A-Za-z']*{re.escape(stem)}[A-Za-z']*", lowered)
        found.update(whole or [stem])
    return sorted(found)


def tells(lines) -> list[str]:
    """Which structural habits survived, described rather than matched."""
    if isinstance(lines, str):
        lines = [lines]
    found = []
    for line in lines:
        for pattern, description in TELLS:
            if pattern.search(str(line)) and description not in found:
                found.append(description)
    return found


def complaints(lines) -> list[str]:
    """Everything wrong with this prose, in words a model can act on."""
    out = [f"the word {word!r}" for word in offences(lines)]
    return out + tells(lines)


def tidy(text: str) -> str:
    """One line, put right mechanically. The last resort, after asking twice."""
    return plain(unbold_lead(str(text or "")))


_FENCE = re.compile(r"^\s*```")


def tidy_markdown(text: str) -> str:
    """A whole reply, put right, without touching anything inside a fence.

    Chat answers are markdown and routinely contain shell commands and file
    contents. Rewriting semicolons and dashes inside those would corrupt the
    very thing he asked for, so fenced blocks pass through byte for byte and
    only the prose around them is touched.
    """
    out, inside = [], False
    for line in (text or "").splitlines():
        if _FENCE.match(line):
            inside = not inside
            out.append(line)
            continue
        if inside:
            out.append(line)
            continue
        if not line.strip():
            out.append("")
            continue
        # Indented four spaces is also code, by markdown's older rule.
        if line.startswith("    ") and not line.lstrip().startswith(("-", "*", "1.")):
            out.append(line)
            continue
        leading = line[:len(line) - len(line.lstrip())]
        marker = ""
        body = line.lstrip()
        bullet = re.match(r"^([-*+]|\d+[.)])\s+", body)
        if bullet:
            marker = bullet.group(0)
            body = body[len(marker):]
        out.append(f"{leading}{marker}{tidy(body)}")
    return "\n".join(out)


def prose_lines(text: str) -> list[str]:
    """The lines of a markdown answer that are meant to read as English.

    Fenced and indented code is left out, so a command containing a banned
    substring or a semicolon never makes the answer look like it needs redoing.
    """
    out, inside = [], False
    for line in (text or "").splitlines():
        if _FENCE.match(line):
            inside = not inside
            continue
        if inside or (line.startswith("    ") and line.strip()):
            continue
        if line.strip():
            out.append(line)
    return out
