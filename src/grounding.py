"""One rule about telling the truth, said in one place.

Every prompt in this application had its own hand-written version of "do not
make things up", and they had all drifted. Worse, one of them had drifted into
something actively harmful: the summariser was told to drop any item it could
not timestamp, and since half of a real meeting is commitments that build up
across a stretch of talk with no single moment to point at, it was deleting
about half of every meeting in the name of not inventing.

That is the whole reason this file exists, and why the clause below has two
halves rather than one. Read on its own, "never invent" pushes a model towards
silence, and silence is not accuracy. A summary missing eleven of his fifteen
action items is not more truthful than one that has them; it is wrong in a way
that is harder to notice, because nothing on the screen looks like an error.

So the rule is: do not add what was not there, and do not drop what was. Both
halves, always, in the same breath.
"""

NEVER_INVENT = """What you write is read as fact and acted on, so it has to be
true to the material in front of you.

Do not add. No name, number, date, decision or commitment that is not there. Do
not fill a gap with what would plausibly have been said, and do not smooth an
unclear passage into a confident one. Where something cannot be made out, say so
or leave it: "that part was not clear" is a useful answer and a confident wrong
one is not.

Do not drop, either. Leaving out something that really happened is its own way
of being inaccurate, and it is the easier one to miss because nothing looks
broken. If you are sure of a thing but not of its timing, its exact wording, or
who owns it, keep the thing and leave the rest of it unsaid. Never delete a real
item because you could not pin down a detail of it.

Where you are unsure, be plain about which part you are unsure of. Do not let
that uncertainty either invent a detail or swallow the whole item."""
