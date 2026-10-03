"""The source: a synthetic support-ticket feed, standing in for real data.

`generate` writes one gzipped CSV per year of tickets opened
(`tickets-2024.csv.gz`) under data/raw/. It is the write side's first step
and the one to replace: point it at your real source (an API, a bucket, a
vendor's daily dump) and keep the contract:

- files under raw/ with the columns in `schema.RAW_COLUMNS`
- idempotent: a run that finds nothing new leaves every file byte-identical,
  so `build` sees the same content hash and skips
- a file is replaced only when its content changed, by atomic rename

The feed is deterministic. Each day's tickets come from a random stream
seeded by (seed, date), so extending --until appends days without changing
earlier ones, and running twice on the same day reproduces the same bytes.
The one exception is realistic: a ticket still open at --until has no
resolved_at, and gains one on a later run. Run it daily and the warehouse
grows a day at a time, like a real feed.

The world is small but not trivial, so the dashboard and the assistant have
something to find:

- six products, two launching partway through, and ~28% growth a year
- plans (free .. enterprise) that shape channel, resolution time and refunds
- chat (launched March 2020) taking over from phone support
- quiet weekends, a billing spike every January, a lull at Christmas
- a few incidents a year: a burst of one product's tickets in one category,
  with tell-tale wording in the ticket text (search for it)
- resolution time, escalation, satisfaction and refunds that depend on all
  of the above and on each other
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import math
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .schema import RAW_COLUMNS, STATES

EPOCH = date(2019, 1, 1)  # growth is measured from here, whatever --since says
GROWTH = 1.28  # volume multiplier per year
CHAT_LAUNCH = date(2020, 3, 1)


@dataclass(frozen=True)
class Product:
    name: str
    launched: date
    share: float  # relative volume once ramped up
    categories: dict[str, float]  # multipliers on the base category mix
    regions: dict[str, float]  # multipliers on population, by state


PRODUCTS = [
    Product("Ledger", date(2017, 1, 1), 1.0, {"Billing": 2.2, "Integrations": 1.3}, {}),
    Product("Relay", date(2017, 1, 1), 1.3, {"Performance": 1.5, "Access": 1.2}, {}),
    Product("Atlas", date(2017, 1, 1), 0.7, {"Integrations": 2.0, "How-to": 1.4},
            {"CA": 1.8, "WA": 1.8, "OR": 1.6, "CO": 1.5, "UT": 1.4}),
    Product("Harbor", date(2017, 1, 1), 0.9, {"Data loss": 2.5, "Performance": 1.3},
            {"NY": 1.5, "NJ": 1.4, "MA": 1.5, "IL": 1.2}),
    Product("Pulse", date(2021, 6, 1), 0.8, {"Bug": 1.6, "Feature request": 1.5}, {"TX": 1.6, "GA": 1.3}),
    Product("Quill", date(2023, 3, 1), 0.6, {"How-to": 1.8, "Feature request": 2.0}, {}),
]  # fmt: skip

# Base category mix, and each category's severity weights (1 low .. 4 critical).
CATEGORIES = {
    "Billing": (0.13, [0.30, 0.50, 0.17, 0.03]),
    "Access": (0.15, [0.20, 0.45, 0.28, 0.07]),
    "Performance": (0.12, [0.15, 0.45, 0.30, 0.10]),
    "Bug": (0.19, [0.20, 0.45, 0.28, 0.07]),
    "Data loss": (0.04, [0.02, 0.18, 0.45, 0.35]),
    "Integrations": (0.10, [0.25, 0.50, 0.20, 0.05]),
    "How-to": (0.18, [0.70, 0.27, 0.03, 0.00]),
    "Feature request": (0.09, [0.90, 0.10, 0.00, 0.00]),
}

# share, resolution-time factor, channel multipliers, refund range (USD)
PLANS = {
    "Free": (0.46, 1.6, {"phone": 0.0, "chat": 0.6}, None),
    "Pro": (0.30, 1.0, {}, (9, 49)),
    "Team": (0.16, 0.8, {"phone": 1.4}, (40, 400)),
    "Enterprise": (0.08, 0.5, {"phone": 2.5, "chat": 1.3}, (250, 4000)),
}

CHANNEL_SPEED = {"phone": 0.5, "chat": 0.6, "email": 1.0, "web": 1.15}
SEVERITY_HOURS = {1: 30.0, 2: 14.0, 3: 6.0, 4: 2.5}  # median hours to resolve
CATEGORY_SPEED = {"Feature request": 3.0, "How-to": 0.6, "Data loss": 1.4}
ESCALATION = {1: 0.01, 2: 0.04, 3: 0.15, 4: 0.40}

# Hour-of-day weights: business hours, a lunch dip, a long quiet night.
HOURS = [1, 1, 1, 1, 1, 2, 4, 8, 12, 14, 14, 12, 10, 12, 13, 12, 10, 8, 6, 5, 4, 3, 2, 1]

# (product, category, subject, sentence): bursts the assistant can find with search.
INCIDENTS = [
    ("Relay", "Performance", "messages delayed", "Messages are arriving minutes late, sometimes out of order."),
    ("Relay", "Access", "two-factor codes rejected", "Two-factor codes are rejected every time I try to sign in."),
    ("Harbor", "Data loss", "files missing after sync", "Files I uploaded yesterday are missing after the last sync."),
    ("Harbor", "Performance", "uploads stalling", "Uploads stall at 99% and never finish."),
    ("Ledger", "Billing", "double charged", "I was double charged this month: two identical charges on my card."),
    ("Atlas", "Integrations", "API key rejected", "Our API key is suddenly rejected with a 401 and nothing changed."),
    ("Pulse", "Bug", "alerts not firing", "Alerts are not firing; we missed an outage because nothing paged us."),
    ("Quill", "Access", "SSO login loop", "SSO sends us straight back to the login page, in a loop."),
]

# Ticket text: a subject and an opening sentence per category, then a detail.
# {p} is the product; {f} a feature of it.
TEXT = {
    "Billing": (["Question about my invoice", "Charged the wrong amount", "Need a receipt", "Cancel and refund"],
                ["My latest {p} invoice doesn't match my plan.", "I was charged for seats we removed last month.",
                 "Can you send a receipt with our address for {p}?", "We cancelled {p} but were still billed."]),
    "Access": (["Can't log in", "Password reset not arriving", "Locked out", "Invite link expired"],
               ["I can't log in to {p} since this morning.", "The password reset email never arrives.",
                "My account got locked after one wrong password.", "A teammate's invite link to {p} says it expired."]),
    "Performance": (["{p} is slow", "Timeouts", "Dashboard won't load", "Lag when typing"],
                    ["{p} has been very slow all day, especially {f}.", "We keep getting timeouts when opening {f}.",
                     "The {f} page spins forever.", "There's a lag of a few seconds in {f}."]),
    "Bug": (["Error when saving", "Something broke in {f}", "Wrong numbers shown", "Button does nothing"],
            ["Saving in {f} fails with an error.", "Since the last update {f} shows a blank screen.",
             "{p} shows different numbers in {f} than in the export.", "Clicking export in {f} does nothing."]),
    "Data loss": (["Data missing", "Lost my work", "Records disappeared", "Restore request"],
                  ["Some records in {f} are just gone.", "I lost an afternoon of work in {p}.",
                   "Items we created last week have disappeared from {f}.", "Can you restore {f} to yesterday?"]),
    "Integrations": (["Webhook not firing", "API returns errors", "Sync with CRM broken", "Zapier connection"],
                     ["Our webhook from {p} stopped firing.", "The {p} API returns 500s for {f}.",
                      "The CRM sync with {p} stopped updating.", "The Zapier connection to {p} keeps dropping."]),
    "How-to": (["How do I export?", "Setting up {f}", "Where is the setting for this?", "Best way to organize"],
               ["How do I export everything from {f}?", "What's the right way to set up {f} for a team?",
                "I can't find where to change {f} settings.", "Any tips for organizing {f} in {p}?"]),
    "Feature request": (["Feature request", "Please add dark mode", "Bulk edit would help", "Suggestion for {f}"],
                        ["It would be great if {f} supported bulk edits.", "Please add dark mode to {p}.",
                         "Could {f} remember my last filter?", "We'd love keyboard shortcuts in {f}."]),
}  # fmt: skip
FEATURES = {
    "Ledger": ["invoices", "expense reports", "bank sync", "tax settings"],
    "Relay": ["channels", "direct messages", "notifications", "message search"],
    "Atlas": ["the maps API", "geocoding", "route planning", "the usage dashboard"],
    "Harbor": ["shared folders", "file versions", "the desktop sync client", "storage quotas"],
    "Pulse": ["alert rules", "status pages", "the on-call schedule", "uptime checks"],
    "Quill": ["page templates", "comments", "the editor", "workspace permissions"],
}
DETAILS = [
    "", "", "We're blocked until this is fixed.", "This is affecting our whole team.", "Thanks for the help!",
    "It worked fine last week.", "I tried clearing the cache already.", "Happens in Chrome and Safari.",
    "Please advise.", "Screenshots attached.",
]  # fmt: skip


@dataclass(frozen=True)
class Incident:
    start: date
    days: int
    product: str
    category: str
    subject: str
    sentence: str
    peak: float  # extra tickets on day one, as a multiple of the product's normal day

    def intensity(self, d: date) -> float:
        i = (d - self.start).days
        return self.peak * math.exp(-0.7 * i) if 0 <= i < self.days else 0.0


@dataclass
class FileResult:
    file: str
    rows: int
    sha256: str
    changed: bool
    removed: bool = False


class World:
    """Everything about the feed that doesn't change from day to day."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._incidents: dict[int, list[Incident]] = {}
        codes = list(STATES)
        self.states = codes
        self._state_weights = {
            p.name: _cumulative([STATES[s][2] * p.regions.get(s, 1.0) for s in codes]) for p in PRODUCTS
        }

    def incidents(self, year: int) -> list[Incident]:
        """Three incidents a year, from their own seeded stream."""
        if year not in self._incidents:
            rng = random.Random(f"{self.seed}:incidents:{year}")
            out = []
            for _ in range(3):
                start = date(year, 1, 1) + timedelta(days=rng.randrange(365))
                live = [k for k in INCIDENTS if _launched(k[0], start)]
                product, category, subject, sentence = rng.choice(live)
                out.append(Incident(start, rng.randint(2, 6), product, category, subject, sentence,
                                    rng.uniform(1.5, 4.0)))  # fmt: skip
            self._incidents[year] = out
        return self._incidents[year]

    def day(self, d: date, daily: float, as_of: datetime) -> Iterator[list]:
        """One day's tickets as raw CSV rows. Depends only on (seed, d, daily)
        and, for resolved_at, on `as_of`."""
        rng = random.Random(f"{self.seed}:{d.isoformat()}")
        mean = daily * GROWTH ** ((d - EPOCH).days / 365.25)
        if d.weekday() >= 5:
            mean *= 0.45
        if d.month == 1:
            mean *= 1.1
        if d.month == 12 and d.day >= 20:
            mean *= 0.6
        live = [(p, p.share * min(1.0, (d - p.launched).days / 180)) for p in PRODUCTS if _launched(p.name, d)]
        if not live:
            return
        products, product_weights = [p for p, _ in live], _cumulative([w for _, w in live])
        total_share = sum(w for _, w in live)
        n = _poisson(rng, mean)
        seq = 0
        for _ in range(n):
            product = rng.choices(products, cum_weights=product_weights)[0]
            yield self._ticket(rng, d, seq, product, None, as_of)
            seq += 1
        for inc in self.incidents(d.year):
            if (k := inc.intensity(d)) and _launched(inc.product, d):
                share = next(w for p, w in live if p.name == inc.product) / total_share
                product = next(p for p in products if p.name == inc.product)
                for _ in range(_poisson(rng, mean * share * k)):
                    yield self._ticket(rng, d, seq, product, inc, as_of)
                    seq += 1

    def _ticket(self, rng: random.Random, d: date, seq: int, product: Product, inc: Incident | None,
                as_of: datetime) -> list:  # fmt: skip
        if inc:
            category = inc.category
        else:
            mix = {c: base * product.categories.get(c, 1.0) for c, (base, _) in CATEGORIES.items()}
            if d.month == 1:
                mix["Billing"] *= 2.0  # annual renewals
            category = rng.choices(list(mix), weights=list(mix.values()))[0]
        severity = rng.choices([1, 2, 3, 4], weights=CATEGORIES[category][1])[0]
        if inc and rng.random() < 0.6:
            severity = max(severity, 3)
        plan = rng.choices(list(PLANS), weights=[p[0] for p in PLANS.values()])[0]
        share, speed, channel_bias, refund_range = PLANS[plan]
        years = max(0.0, (d - CHAT_LAUNCH).days / 365.25)
        chat = min(0.45, 0.10 + 0.07 * years) if d >= CHAT_LAUNCH else 0.0
        channels = {"email": 0.40, "web": 0.25, "phone": max(0.06, 0.25 - 0.035 * years), "chat": chat}
        channels = {c: w * channel_bias.get(c, 1.0) for c, w in channels.items()}
        channel = rng.choices(list(channels), weights=list(channels.values()))[0]
        state = rng.choices(self.states, cum_weights=self._state_weights[product.name])[0]

        hour = rng.choices(range(24), weights=HOURS)[0]
        opened = datetime(d.year, d.month, d.day, hour, rng.randrange(60), rng.randrange(60))
        escalated = rng.random() < ESCALATION[severity] + (0.10 if inc else 0.0)
        hours = (SEVERITY_HOURS[severity] * speed * CHANNEL_SPEED[channel] * CATEGORY_SPEED.get(category, 1.0)
                 * (1.8 if inc else 1.0) * (2.2 if escalated else 1.0) * math.exp(rng.gauss(0, 0.8)))  # fmt: skip
        resolved = opened + timedelta(hours=hours)
        satisfaction = None
        if resolved <= as_of and rng.random() < (0.50 if escalated else 0.35):
            score = 4.7 - 0.45 * math.log2(1 + hours / 8) - (0.8 if escalated else 0.0) + rng.gauss(0, 0.7)
            satisfaction = min(5, max(1, round(score)))
        refund = 0.0
        if category == "Billing" and refund_range and rng.random() < (0.7 if inc else 0.22):
            refund = round(rng.uniform(*refund_range), 2)

        f = rng.choice(FEATURES[product.name])
        subjects, openers = TEXT[category]
        subject = (f"{product.name}: {inc.subject}" if inc else rng.choice(subjects)).format(p=product.name, f=f)
        body = " ".join(s for s in [
            inc.sentence if inc else rng.choice(openers).format(p=product.name, f=f),
            rng.choice(DETAILS),
        ] if s)  # fmt: skip
        return [
            d.toordinal() * 10_000 + seq,  # stable whatever --since/--until say
            opened.isoformat(sep=" "),
            resolved.replace(microsecond=0).isoformat(sep=" ") if resolved <= as_of else "",
            product.name,
            plan,
            channel,
            category,
            severity,
            state,
            "true" if escalated else "false",
            "" if satisfaction is None else satisfaction,
            f"{refund:.2f}",
            subject[:1].upper() + subject[1:],
            body,
        ]


def generate(raw: Path, since: date, until: date, daily: float = 60.0, seed: int = 1) -> list[FileResult]:
    """Write tickets opened from `since` through `until` (inclusive), one
    file per year, replacing only the files whose content changed. Files for
    years outside the range are removed, so raw/ holds exactly this feed."""
    if since > until:
        raise ValueError(f"--since {since} is after --until {until}")
    raw.mkdir(parents=True, exist_ok=True)
    world = World(seed)
    as_of = datetime.combine(until + timedelta(days=1), datetime.min.time())
    header = [name for name, _ in RAW_COLUMNS]
    results = []
    years = range(since.year, until.year + 1)
    for year in years:
        buf = io.StringIO()
        out = csv.writer(buf, lineterminator="\n")
        out.writerow(header)
        rows = 0
        d = max(since, date(year, 1, 1))
        while d <= min(until, date(year, 12, 31)):
            for row in world.day(d, daily, as_of):
                out.writerow(row)
                rows += 1
            d += timedelta(days=1)
        results.append(_write(raw / f"tickets-{year}.csv.gz", buf.getvalue().encode(), rows))
    for path in sorted(raw.glob("tickets-*.csv.gz")):
        year = path.name.removeprefix("tickets-").removesuffix(".csv.gz")
        if not year.isdigit() or int(year) not in years:
            path.unlink()
            results.append(FileResult(str(path), 0, "", changed=True, removed=True))
    return results


def raw_files(raw: Path) -> list[Path]:
    """The feed's files, in order: what `build` reads and hashes."""
    return sorted(raw.glob("tickets-*.csv.gz"))


def _write(path: Path, text: bytes, rows: int) -> FileResult:
    """Gzip deterministically (no name, no timestamp in the header), and
    replace the file only if the bytes differ, so an unchanged day leaves
    its mtime and hash alone."""
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0) as gz:
        gz.write(text)
    data = buf.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    old = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    if old != sha:
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return FileResult(str(path), rows, sha, changed=old != sha)


def _launched(product: str, d: date) -> bool:
    return next(p for p in PRODUCTS if p.name == product).launched <= d


def _cumulative(weights: list[float]) -> list[float]:
    out, total = [], 0.0
    for w in weights:
        total += w
        out.append(total)
    return out


def _poisson(rng: random.Random, lam: float) -> int:
    """Poisson draws: exact for small means, normal approximation above 30."""
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1
