"""The assistant's system prompt.

Four parts, most stable first (so provider-side prompt caching can reuse the
prefix across users and turns):

1. docs/assistant.md: role, tools, how to drive the UI, how to query
2. Data tables: generated from the live warehouse (DESCRIBE + row counts),
   annotated with TABLE_NOTES / COLUMN_NOTES, so the schema the model sees
   can't drift from the data
3. docs/methodology.md: how every number is made
4. Current build facts

It's rebuilt only when the warehouse build changes.
"""

from __future__ import annotations

from importlib.resources import files

from .sql import SqlSandbox

TABLE_NOTES = {
    "tickets": "ONE ROW PER TICKET. count(*) counts tickets. Start here for anything about individual tickets "
    "or their text.",
    "tickets_state_year": "Rollup: tickets per product × plan × channel × category × state × year opened (every "
    "dashboard dimension). Fastest table for counts and sums by any of those. Averages must be "
    "re-derived from the sums: sum(resolution_hours) / sum(resolved), sum(csat_points) / "
    "sum(csat_responses).",
    "product_month": "Rollup: tickets per product × category × plan × channel × month opened (no state). "
    "Use it for monthly trends.",
    "states": "US states: USPS code, FIPS code, name, 2020 Census population (the per-capita denominator).",
}

COLUMN_NOTES = {
    "ticket_id": "unique id",
    "opened_at": "when the customer opened the ticket",
    "resolved_at": "null while the ticket is open",
    "year": "year opened (the dashboard's 'Opened' dimension)",
    "month": "first day of the month opened",
    "product": "the product the ticket is about",
    "plan": "the customer's plan: Free, Pro, Team, Enterprise",
    "channel": "how it came in: email, web, phone, chat",
    "category": "what it's about",
    "severity": "1 low .. 4 critical",
    "state": "customer's state, USPS code",
    "escalated": "handed to a specialist team",
    "resolved": "resolved_at is set",
    "resolution_hours": "opened to resolved, hours (null while open). In rollups: the SUM over resolved tickets",
    "satisfaction": "1..5 survey score; null when the customer didn't answer",
    "csat_responses": "tickets with a survey answer",
    "csat_points": "sum of their scores",
    "refund_usd": "refund issued, USD (0 when none)",
    "refunds_usd": "sum of refunds, USD",
    "subject": "ticket subject",
    "body": "what the customer wrote. Slow to ILIKE at scale; prefer search_text",
    "population": "2020 Census residents",
}

# Rollups first, then the detail table, then lookups.
TABLE_ORDER = ["tickets_state_year", "product_month", "tickets", "states"]


def doc(name: str) -> str:
    return files(__package__).joinpath(f"docs/{name}").read_text()


def data_tables(sb: SqlSandbox) -> str:
    out = ["# Data tables", "", "Every table is a DuckDB view; query them with `query_data`.", ""]
    names = [t for t in TABLE_ORDER if t in sb.tables] + sorted(set(sb.tables) - set(TABLE_ORDER))
    for name in names:
        out.append(f"## {name} ({sb.row_counts.get(name, 0):,} rows)")
        if note := TABLE_NOTES.get(name):
            out.append(note)
        cols = sb.tables[name]
        noted = [f"- `{c}` {t}: {COLUMN_NOTES[c]}" for c, t in cols if c in COLUMN_NOTES]
        rest = [f"`{c}` {t}" for c, t in cols if c not in COLUMN_NOTES]
        out += noted
        if rest:
            out.append("- also: " + ", ".join(rest))
        out.append("")
    # The vocabularies, so the model filters on values that exist.
    if "tickets_state_year" in sb.tables:
        for col in ("product", "plan", "channel", "category"):
            values = sb.query(
                f"SELECT {col}, sum(tickets) FROM tickets_state_year GROUP BY 1 ORDER BY 2 DESC"
            )  # fmt: skip
            out.append(f"Values of `{col}`, most tickets first: " + ", ".join(str(v) for v, _ in values) + ".")
    return "\n".join(out)


def build(sb: SqlSandbox | None, facts: list[str]) -> str:
    parts = [doc("assistant.md")]
    if sb is not None and sb.tables:
        parts.append(data_tables(sb))
    parts += [doc("methodology.md"), "# Current build facts\n\n" + "\n".join(f"- {f}" for f in facts)]
    return "\n\n".join(parts)
