"""What the paid models cost, counted here rather than discovered later.

ENYGMA cannot see the bill. Anthropic can, at the end of the month, and by then
it is spent. So this keeps its own count from the token figures every call
returns, and says something the first time that count passes each round number.

Two things it is careful about.

It is an estimate and says so. The figures are real -- they come from the API's
own usage block -- but the prices are written down here by hand and prices
change. A number presented as the bill, that turns out not to be the bill, is
worse than one presented as a guess.

It tells him once per step. Repeating "you have passed ten dollars" on every
answer for the rest of the month is how a warning becomes noise he learns to
scroll past, and the next one, the one that matters, goes past with it.
"""
from __future__ import annotations

from datetime import datetime

from .config import config
from .db import cursor

# Per million tokens, in whole dollars. Checked 2026-09-04. These are written
# down rather than fetched because there is no endpoint for them, which means
# they go stale silently: if the arithmetic here ever disagrees with the real
# invoice, this is the first place to look.
PRICES = {
    "anthropic": {"in": 5.00, "out": 25.00},
    "google":    {"in": 1.50, "out": 9.00},
}
PROVIDER_OF = {"opus": "anthropic", "gemini": "google"}
NAMES = {"anthropic": "Opus", "google": "Gemini"}

MILLICENTS = 100_000        # in a dollar


def price(provider: str, input_tokens: int, output_tokens: int) -> int:
    """Millicents. Integers all the way, because a month of floating point
    addition drifts and this number is shown to him as money."""
    rates = PRICES.get(provider)
    if not rates:
        return 0
    dollars = (input_tokens / 1e6) * rates["in"] + (output_tokens / 1e6) * rates["out"]
    return round(dollars * MILLICENTS)


def month_of(when: datetime | None = None) -> str:
    return (when or datetime.now()).strftime("%Y-%m")


def record(provider: str, model: str, what: str, input_tokens: int,
           output_tokens: int, thread_id: int | None = None) -> dict:
    """Log one call. Returns the month's total and, if this call carried it past
    a round number nobody has been told about yet, the step it passed."""
    cost = price(provider, input_tokens or 0, output_tokens or 0)
    with cursor() as conn:
        conn.execute(
            "INSERT INTO spend (provider, model, what, thread_id, input_tokens, "
            "  output_tokens, cost_millicents) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (provider, model, what, thread_id, input_tokens or 0,
             output_tokens or 0, cost))
    total = this_month(provider)
    return {"cost": cost, "total": total, "step": _step_passed(provider, total)}


def this_month(provider: str | None = None, when: datetime | None = None) -> int:
    """Millicents spent this calendar month."""
    month = month_of(when)
    sql = ("SELECT COALESCE(SUM(cost_millicents), 0) AS total FROM spend "
           "WHERE strftime('%Y-%m', at, 'localtime') = ?")
    args: list = [month]
    if provider:
        sql += " AND provider = ?"
        args.append(provider)
    with cursor() as conn:
        return conn.execute(sql, args).fetchone()["total"]


def _step_passed(provider: str, total: int) -> int | None:
    """The round number this call went past, if he has not been told about it.

    Recorded before it is returned, so two answers arriving close together
    cannot both announce the same ten dollars.
    """
    step = config.SPEND_STEP_DOLLARS * MILLICENTS
    if step <= 0:
        return None
    reached = (total // step) * step
    if reached <= 0:
        return None
    month = month_of()
    with cursor() as conn:
        row = conn.execute(
            "SELECT told_at FROM spend_warnings WHERE provider = ? AND month = ?",
            (provider, month)).fetchone()
        told = row["told_at"] if row else 0
        if reached <= told:
            return None
        conn.execute(
            "INSERT INTO spend_warnings (provider, month, told_at) VALUES (?, ?, ?) "
            "ON CONFLICT(provider, month) DO UPDATE SET told_at = excluded.told_at",
            (provider, month, reached))
    return reached


def as_money(millicents: int) -> str:
    return f"${millicents / MILLICENTS:,.2f}"


def notice(provider: str, step: int, total: int) -> str:
    """What gets added to the answer. Said once, plainly, and honest about being
    ENYGMA's own arithmetic rather than the invoice."""
    return (f"\n\n---\n"
            f"Keep an eye on this: {NAMES.get(provider, provider)} has passed "
            f"{as_money(step)} this month. Estimated total so far "
            f"{as_money(total)}. That is ENYGMA's own count from the tokens each "
            f"answer used, not the bill.")


def summary() -> list[dict]:
    """This month, per provider, for Settings."""
    month = month_of()
    with cursor() as conn:
        rows = conn.execute(
            "SELECT provider, COUNT(*) AS calls, "
            "       SUM(cost_millicents) AS total, "
            "       SUM(input_tokens) AS tin, SUM(output_tokens) AS tout "
            "FROM spend WHERE strftime('%Y-%m', at, 'localtime') = ? "
            "GROUP BY provider ORDER BY total DESC", (month,)).fetchall()
    return [{"provider": r["provider"], "name": NAMES.get(r["provider"], r["provider"]),
             "calls": r["calls"], "total": r["total"] or 0,
             "money": as_money(r["total"] or 0),
             "input_tokens": r["tin"] or 0, "output_tokens": r["tout"] or 0}
            for r in rows]
