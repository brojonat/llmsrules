"""Evals for the assistant: does it pick the right tools, leave the dashboard in
the right state, quote true numbers, and say only what its tools support?

Each case (evals/cases.toml) runs through the real app in-process — the same
system prompt, tools, warehouse and LLM as production — in a fresh session.
After its turns, checks run against what happened:

  require_tools / forbid_tools   tools that must / must not have been called
  [case.view]      the dataset the assistant left, one set per dimension
                   (`years_from = 2023` means 2023 through the partial year)
  [[case.numbers]] the true value (SQL we run against the warehouse) must
                   appear in the final reply, within `tolerance` (absolute, or
                   a fraction with `relative = true`); one row per acceptable
                   value when the question is ambiguous
  [case.chart]     the last chart's kind, facets, series and points, and
                   optionally that it sums to the session's dataset total
  rubric           a judge model grades the final reply against the rubric
  grounded         a judge model checks every factual claim in the final reply
                   against the tool results and the system prompt (default on
                   whenever a tool ran)

SQL and rubrics may use {setup_filter} (the case's setup dataset as a WHERE
clause, for `tickets` and the rollups alike), {data_through} and
{through_year}, so cases don't go stale as the data grows.

Output: one JSON object per case on stdout, a summary on stderr.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import httpx
from starlette.testclient import TestClient

from .llm import Delta, LLMConfig, LLMError, Usage, stream_chat
from .warehouse import Filter, inline_sql, update_filter, year_range
from .web import SESSION_COOKIE, Config, create_app, system_prompt

DEFAULT_JUDGE = "anthropic/claude-sonnet-5"
DATASTAR = {"Datastar-Request": "true"}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Result:
    id: str
    ok: bool
    checks: list[Check]
    tools: list[dict]
    reply: str
    view: dict
    seconds: float
    cost: float  # the assistant's, as the provider reports it
    judge_cost: float


CASE_KEYS = {"id", "ask", "turns", "setup", "require_tools", "forbid_tools", "view", "numbers", "chart", "rubric",
             "grounded"}  # fmt: skip
VIEW_KEYS = {"products", "plans", "channels", "categories", "states", "years", "years_from", "metric"}
CHART_KEYS = {"kind", "facets", "series", "min_points", "total_equals_dataset"}


def load_cases(path: Path, only: tuple[str, ...] = ()) -> list[dict]:
    """The battery, validated: a typo'd key would silently skip a check."""
    cases = tomllib.loads(path.read_text())["case"]
    ids = set()
    for c in cases:
        where = f"{path}: case {c.get('id', '?')!r}"
        if unknown := set(c) - CASE_KEYS:
            raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
        if unknown := set(c.get("view", {})) - VIEW_KEYS:
            raise ValueError(f"{where}: unknown view keys {sorted(unknown)}")
        if unknown := set(c.get("chart", {})) - CHART_KEYS:
            raise ValueError(f"{where}: unknown chart keys {sorted(unknown)}")
        if ("ask" in c) == ("turns" in c):
            raise ValueError(f"{where}: needs exactly one of ask / turns")
        if c["id"] in ids:
            raise ValueError(f"{where}: duplicate id")
        ids.add(c["id"])
    if only:
        cases = [c for c in cases if any(o in c["id"] for o in only)]
    return cases


class Evaluator:
    def __init__(self, warehouse: Path, llm: LLMConfig, judge: LLMConfig, turn_timeout: float = 180) -> None:
        self.warehouse = warehouse
        self.llm = llm
        self.judge = judge
        self.turn_timeout = turn_timeout
        self._db = duckdb.connect()
        self._db_lock = threading.Lock()
        for f in sorted(warehouse.glob("*.parquet")):
            self._db.execute(f"CREATE VIEW {f.stem} AS SELECT * FROM read_parquet('{f}')")

    def run(self, cases: list[dict], parallel: int = 4, on_result=lambda r: None) -> list[Result]:
        app_db = Path(tempfile.mkdtemp(prefix="eval-")) / "app.sqlite"
        app = create_app(Config(warehouse=self.warehouse, llm=self.llm, app_db=app_db))
        with TestClient(app) as client:
            state = client.app.state.s
            prompt = system_prompt(state)

            def one(case: dict) -> Result:
                result = self._run_case(client, state, prompt, case)
                on_result(result)
                return result

            with ThreadPoolExecutor(max_workers=parallel) as pool:
                return list(pool.map(one, cases))

    # -- one case -------------------------------------------------------------

    def _run_case(self, client: TestClient, state, prompt: str, case: dict) -> Result:
        sid = f"eval-{case['id']}-{time.time_ns()}"
        headers = {**DATASTAR, "Cookie": f"{SESSION_COOKIE}={sid}"}
        started = time.monotonic()
        wh = state.warehouse
        setup = update_filter(Filter(), case.get("setup") or {})
        facts = {
            "setup_filter": inline_sql(*setup.where()),
            "data_through": wh.manifest.get("data_through", "?"),
            "through_year": wh.through_year,
        }

        def fail(why: str) -> Result:
            return Result(case["id"], False, [Check("ran", False, why)], [], "", {}, _secs(started), 0, 0)

        if case.get("setup"):
            r = client.post("/filter", json=case["setup"], headers=headers)
            if r.status_code != 204:
                return fail(f"setup rejected: {r.status_code} {r.text}")
        for turn in case["turns"] if "turns" in case else [case["ask"]]:
            r = client.post("/chat/send", json={"message": turn}, headers=headers)
            if r.status_code != 204:
                return fail(f"send rejected: {r.status_code} {r.text}")
            deadline = time.monotonic() + self.turn_timeout
            while state.chats.get(sid).streaming:
                if time.monotonic() > deadline:
                    return fail(f"no reply within {self.turn_timeout:.0f}s")
                time.sleep(0.2)

        conv = state.chats.get(sid)
        f = state.filters.get(sid, Filter())
        replies = [m.content for m in conv.messages if m.role == "assistant" and m.content and not m.tool_calls]
        reply = replies[-1] if replies else ""
        tools = [{"name": c.name, "arguments": c.arguments} for m in conv.messages for c in m.tool_calls]
        charts = [m.attachment["chart"] for m in conv.messages if m.attachment and "chart" in m.attachment]

        checks: list[Check] = []
        if conv.error:
            checks.append(Check("no_error", False, conv.error))
        if not reply:
            checks.append(Check("replied", False, "no final reply"))
        checks += _check_tools(case, tools)
        if "view" in case:
            checks.append(_check_view(case["view"], f, wh.through_year))
        for spec in case.get("numbers", []):
            checks.append(self._check_number(spec, reply, facts))
        if "chart" in case:
            checks.append(_check_chart(case["chart"], charts, lambda: wh.totals(f).tickets))

        judge_cost = 0.0
        transcript = _render(conv.transcript())
        if rubric := case.get("rubric"):
            check, c = self._judge(_RUBRIC.format(rubric=rubric.format(**facts)), transcript, reply, prompt)
            checks.append(Check("rubric", check.ok, check.detail))
            judge_cost += c
        if case.get("grounded", bool(tools)) and reply:
            check, c = self._judge(_GROUNDED, transcript, reply, prompt)
            checks.append(Check("grounded", check.ok, check.detail))
            judge_cost += c

        return Result(
            id=case["id"],
            ok=all(c.ok for c in checks),
            checks=checks,
            tools=tools,
            reply=reply,
            view={k: list(v) if isinstance(v, tuple) else v for k, v in asdict(f).items()},
            seconds=_secs(started),
            cost=round(conv.cost, 5),
            judge_cost=round(judge_cost, 5),
        )

    def _check_number(self, spec: dict, reply: str, facts: dict) -> Check:
        label = f"number:{spec.get('label', 'value')}"
        with self._db_lock:
            rows = self._db.execute(spec["sql"].format(**facts)).fetchall()
        truths = [float(r[0]) for r in rows if r[0] is not None]  # one row per acceptable answer
        if not truths:
            return Check(label, False, "the truth query returned nothing")
        found = _numbers(reply)
        tol = float(spec.get("tolerance", 0))
        ok = any(abs(n - t) <= tol * (abs(t) if spec.get("relative") else 1) + 1e-9 for t in truths for n in found)
        want = " or ".join(f"{t:g}" for t in truths)
        return Check(label, ok, f"truth {want}" + ("" if ok else f"; reply has {sorted(set(found))[:15]}"))

    def _judge(self, task: str, transcript: str, reply: str, prompt: str) -> tuple[Check, float]:
        # The assistant's system prompt goes in the judge's system message, so
        # the provider caches it across every judge call of a run.
        system = (
            "You grade an AI assistant embedded in a data dashboard. This is the assistant's own system prompt "
            f"(its documentation and build facts):\n\n{prompt}"
        )
        question = (
            f"<conversation>\n{transcript}\n</conversation>\n\n"
            f"<final_reply>\n{reply}\n</final_reply>\n\n{task}\n\n"
            'Answer with JSON only: {"pass": true or false, "reason": "<one or two sentences>"}'
        )
        cost, text, error = 0.0, "", ""
        for _ in range(2):  # one retry: a judge occasionally answers in prose
            try:
                text, c = asyncio.run(_complete(self.judge, system, question))
                cost += c
                verdict = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
                return Check("judge", bool(verdict.get("pass")), str(verdict.get("reason", ""))[:500]), cost
            except (AttributeError, ValueError, httpx.HTTPError, LLMError) as e:
                error = f"{type(e).__name__}: {e}; judge said {text[:200]!r}"
        return Check("judge", False, f"judge error: {error}"), cost


_RUBRIC = """RUBRIC:
{rubric}

Grade the FINAL reply (in the context of the conversation) against the rubric.
It passes only if it meets every requirement in the rubric."""

_GROUNDED = """Check the FINAL reply for groundedness. Every number, ranking, trend,
comparison or other claim about the data must be supported by a tool result in
the conversation or by the assistant's system prompt (its documentation and
build facts). General knowledge is fine; rounding is fine; describing what the
dashboard or a chart now shows is fine when a tool result confirms it. Fail
the reply if it states any specific figure or data claim that nothing
supports, or that contradicts a tool result."""


# -- deterministic checks -------------------------------------------------------


def _check_tools(case: dict, tools: list[dict]) -> list[Check]:
    called = sorted({t["name"] for t in tools})
    out = []
    if need := case.get("require_tools"):
        missing = [t for t in need if t not in called]
        out.append(Check("require_tools", not missing, f"missing {missing}; called {called}" if missing else ""))
    if forbid := case.get("forbid_tools"):
        bad = [t for t in forbid if t in called]
        out.append(Check("forbid_tools", not bad, f"called {bad}" if bad else ""))
    return out


def _check_view(want: dict, f: Filter, through_year: int) -> Check:
    problems = []
    for dim, expected in want.items():
        if dim == "years_from":
            dim, expected = "years", year_range(expected, through_year)
        have = getattr(f, dim)
        ok = have == expected if isinstance(expected, str) else set(have) == set(expected)
        if not ok:
            problems.append(f"{dim}: want {expected}, have {list(have) if isinstance(have, tuple) else have}")
    return Check("view", not problems, "; ".join(problems))


def _check_chart(want: dict, charts: list[dict], dataset_total) -> Check:
    if not charts:
        return Check("chart", False, "no chart drawn")
    c = charts[-1]
    problems = []
    if (kind := want.get("kind")) and c["kind"] not in ([kind] if isinstance(kind, str) else kind):
        problems.append(f"kind {c['kind']}, want {kind}")
    if (facets := want.get("facets")) and len(c["panels"]) != facets:
        problems.append(f"{len(c['panels'])} panels, want {facets}")
    if (series := want.get("series")) and len(c["legend"] or [None]) != series:
        problems.append(f"{len(c['legend'] or [None])} series, want {series}")
    points = [pt for p in c["panels"] for s in p["series"] for pt in s["points"]]
    if (min_points := want.get("min_points")) and len(points) < min_points:
        problems.append(f"{len(points)} points, want at least {min_points}")
    if want.get("total_equals_dataset"):
        total, expected = sum(pt[1] or 0 for pt in points), dataset_total()
        if total != expected:
            problems.append(f"chart sums to {total:g}, the user's dataset has {expected}")
    return Check("chart", not problems, "; ".join(problems))


# -- helpers --------------------------------------------------------------------

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:\s*([KkMm])(?![a-zA-Z]))?")


def _numbers(text: str) -> list[float]:
    """Every number in the text: 1,432 · 1432 · 3.2 · 1.4K · 2.1M."""
    out = []
    for whole, frac, suffix in _NUM.findall(text):
        n = float(whole.replace(",", "") + frac)
        if suffix:
            n *= 1e3 if suffix in "Kk" else 1e6
        out.append(n)
    return out


def _render(transcript: list[dict]) -> str:
    parts = []
    for m in transcript:
        if m["role"] == "tool":
            parts.append(f"[tool result: {m.get('name')}]\n{m['content']}")
            continue
        text = f"[{m['role']}] {m['content']}".rstrip()
        for c in m.get("tool_calls", []):
            text += f"\n[calls {c['name']}] {c['arguments']}"
        parts.append(text)
    return "\n\n".join(parts)


async def _complete(cfg: LLMConfig, system: str, question: str) -> tuple[str, float]:
    text, cost = [], 0.0
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=180)) as http:
        async for event in stream_chat(http, cfg, messages):
            if isinstance(event, Delta):
                text.append(event.text)
            elif isinstance(event, Usage):
                cost += event.cost or 0.0
    return "".join(text), cost


def _secs(started: float) -> float:
    return round(time.monotonic() - started, 1)


def summarize(results: list[Result]) -> str:
    """Pass counts per case (several runs each with --repeat), failures' reasons."""
    by_id: dict[str, list[Result]] = {}
    for r in results:
        by_id.setdefault(r.id, []).append(r)
    passed = sum(r.ok for r in results)
    cost = sum(r.cost for r in results)
    judge = sum(r.judge_cost for r in results)
    lines = [f"evals: {passed}/{len(results)} passed · assistant ${cost:.3f} · judge ${judge:.3f}"]
    for case_id, runs in by_id.items():
        for r in runs:
            if not r.ok:
                failed = "; ".join(f"{c.name}: {c.detail}" for c in r.checks if not c.ok)
                tally = f" [{sum(x.ok for x in runs)}/{len(runs)}]" if len(runs) > 1 else ""
                lines.append(f"  FAIL {case_id}{tally}: {failed[:400]}")
    return "\n".join(lines)


def to_json(r: Result) -> str:
    return json.dumps(asdict(r), ensure_ascii=False)
