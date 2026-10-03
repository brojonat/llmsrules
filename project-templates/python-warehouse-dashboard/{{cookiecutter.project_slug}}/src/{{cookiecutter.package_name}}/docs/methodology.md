# Methodology

This page explains where every number on the dashboard comes from, what is
measured, what is derived, and where the data is weak. The chat assistant is
given this page verbatim.

## Source data

**The data is synthetic.** It comes from a seeded generator (`generate`),
standing in for a real support-ticket export until one is wired in. It is
deterministic: the same seed and dates produce the same tickets, and each run
appends the days since the last one. Nothing in it describes real customers.

The generator models a company with six products (Ledger, Relay, Atlas,
Harbor, Pulse and Quill; Pulse launched in June 2021 and Quill in March
2023), four plans (Free, Pro, Team, Enterprise) and four channels (email,
web, phone, chat; chat launched in March 2020 and has been replacing phone
support since). Volume grows about 28% a year, is lower at weekends and over
Christmas, and billing tickets spike every January. A few times a year an
**incident** produces a burst of one product's tickets in one category,
with tell-tale wording in the ticket text.

Customers' states follow population, with some products more popular in
some regions. Resolution time depends on severity, plan, channel and
category; escalated tickets take longer; satisfaction falls as resolution
time rises and after an escalation.

## What counts as a ticket

One row per ticket. A ticket's **year** is the year it was opened, and every
filter and chart uses that year. The current year is partial: it runs
through the latest day in the data (see the build facts).

## Measures

- **Tickets:** a count of tickets.
- **Escalated:** the share of tickets handed to a specialist team.
- **Time to resolve:** the mean of hours from opened to resolved, over
  **resolved** tickets only. Tickets still open (recent ones, mostly) count
  toward volume but not toward resolution time, so the latest weeks lean
  toward fast resolutions until the slow ones close.
- **Satisfaction (CSAT):** the mean 1–5 survey score over the tickets whose
  customer answered the survey, roughly a third to a half of resolved
  tickets. Customers with an escalated ticket answer more often.
- **Refunds:** the sum of refunds issued, in USD. Only billing tickets carry
  refunds, and Free customers never pay, so they're never refunded.

Rollup tables store sums (hours, survey points, responses), never averages,
so any subset can be re-aggregated exactly: mean hours =
sum(resolution_hours) / sum(resolved), mean satisfaction =
sum(csat_points) / sum(csat_responses).

## The map

States are the customer's home state.

- **Tickets:** raw counts. Mostly a population map.
- **Per 100k residents:** tickets in the window ÷ the state's 2020 Census
  population ÷ the number of years the window covers. A partial first or
  last year counts as the fraction of it the data covers, so a window
  ending in the current year isn't understated.
- **vs. national mix:** (the selection's share of its tickets that are in
  the state) ÷ (everyone's share there, in the same years). 1× is like
  everyone; 2× is twice as concentrated. It needs a product, plan, channel
  or category selected, or it is 1× everywhere.
- **Resolution time, satisfaction, escalation rate:** the measures above,
  per state.

States with fewer than the minimum number of tickets (see the build facts)
are hatched rather than colored: a rate or mean over a handful of tickets is
mostly noise.

## How the data is kept current

`generate` rewrites a year's file only when its content changes, and `build`
rebuilds only when the files' content or the build's own code (its "recipe")
changed. A build that would have 2% fewer tickets than the current one, or
end on an earlier day, is refused: a source that shrinks overnight is
broken, and the site keeps serving the last good build. The dashboard picks
up a new build within a second or two, without a restart.
