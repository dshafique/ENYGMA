"""One rule about telling the truth, and why it has two halves.

This file exists because of a real failure. The summariser was told "if you
cannot point at a moment, leave the item out", and since half of a real meeting
is commitments that build up across a stretch of talk with no single moment,
it was deleting about half of every meeting -- in the name of not inventing.

So every test here is about the same thing: a clause that only says "do not
invent" pushes towards silence, and silence is not accuracy.
"""
import os, sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("ENYGMA_SESSION_SECRET", "test-secret")

from src.grounding import NEVER_INVENT                      # noqa: E402


def flat(text: str) -> str:
    """Whitespace-insensitive. Where a prompt happens to wrap a line is not
    something a test should have an opinion about."""
    return " ".join(text.lower().split())

# Every prompt that produces something he reads as fact and acts on.
def _prompts() -> dict:
    from src.pipeline import gemini
    from src import chat, documents, weeknote
    return {
        "transcribe": gemini.TRANSCRIBE_PROMPT,
        "summarise": gemini.SUMMARISE_PROMPT,
        "notes": gemini.NOTES_PROMPT,
        "chat": chat.VOICE,
        "documents": documents.BRIEF,
        "weeknote": weeknote.VOICE,
        "weeknote free text": weeknote.WORDS,
    }


def test_the_clause_forbids_inventing():
    lowered = flat(NEVER_INVENT)
    assert "do not add" in lowered
    assert "not fill a gap" in lowered


def test_the_clause_also_forbids_dropping():
    """The half that matters most, and the half a naive version leaves out.

    A summary missing eleven of his fifteen action items is not more truthful
    than one that has them. It is wrong in a way that is harder to notice,
    because nothing on the screen looks like an error.
    """
    lowered = flat(NEVER_INVENT)
    assert "do not drop" in lowered
    assert "never delete a real item" in lowered
    assert "leaving out" in lowered and "inaccurate" in lowered


def test_it_says_what_to_do_when_only_a_detail_is_missing():
    """The exact case that caused the bug: sure of the thing, unsure of when."""
    assert "keep the thing and leave the rest of it unsaid" in flat(NEVER_INVENT)


def test_every_prompt_that_states_facts_carries_it():
    missing = [name for name, text in _prompts().items()
               if "do not drop, either" not in flat(text)]
    assert not missing, f"these prompts can invent or omit unchecked: {missing}"


def test_no_prompt_still_says_to_delete_what_it_cannot_place():
    """The rule that started all this, in whatever wording."""
    for name, text in _prompts().items():
        assert "leave the item out" not in flat(text), f"{name} deletes again"


def test_the_clause_is_written_once():
    """Six hand-written versions of "do not make things up" is how one of them
    drifts into something harmful without anyone noticing."""
    root = pathlib.Path(__file__).resolve().parent.parent
    defined = [p for p in (root / "src").rglob("*.py")
               if "NEVER_INVENT = " in p.read_text()]
    assert [p.name for p in defined] == ["grounding.py"]
