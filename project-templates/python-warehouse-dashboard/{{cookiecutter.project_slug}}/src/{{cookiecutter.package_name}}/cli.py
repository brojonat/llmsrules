"""{{cookiecutter.project_slug}}: generate, build, query, serve, and load-test the warehouse.

JSON on stdout, progress on stderr, non-zero exit on failure.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import decimal
import json
import os
import sys
from pathlib import Path

import click

DATA = Path(os.environ.get("DATA_DIR", "data"))


def _json_default(v: object) -> object:
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    raise TypeError(f"not JSON serializable: {type(v).__name__}")


def _emit(obj: object) -> None:
    if dataclasses.is_dataclass(obj):
        obj = dataclasses.asdict(obj)
    click.echo(json.dumps(obj, default=_json_default))


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """{{cookiecutter.description}}"""


@main.command()
@click.option("--raw", type=click.Path(file_okay=False, path_type=Path), default=DATA / "raw", show_default=True)
@click.option("--since", type=click.DateTime(["%Y-%m-%d"]), default="2019-01-01", envvar="GENERATE_SINCE",
              show_default=True, help="First day of tickets.")  # fmt: skip
@click.option("--until", type=click.DateTime(["%Y-%m-%d"]), default=None, envvar="GENERATE_UNTIL",
              help="Last day of tickets (default: today, UTC).")  # fmt: skip
@click.option("--daily", type=float, default=25.0, envvar="GENERATE_DAILY", show_default=True,
              help="Mean tickets per weekday in 2019; volume grows from there.")  # fmt: skip
@click.option("--seed", type=int, default=1, envvar="GENERATE_SEED", show_default=True)
def generate(raw: Path, since: dt.datetime, until: dt.datetime | None, daily: float, seed: int) -> None:
    """Write the synthetic ticket feed: one gzipped CSV per year under --raw.

    Deterministic: the same seed and dates give byte-identical files, and a
    file is only replaced when its content changes, so `build` skips when
    nothing moved. Run it daily and the feed grows by a day. This is the step
    to replace with a fetch of your real data. One JSON line per file.
    """
    from . import generate as gen

    try:
        results = gen.generate(raw, since.date(), until.date() if until else _today(), daily=daily, seed=seed)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    for r in results:
        _emit(r)


@main.command()
@click.option("--raw", type=click.Path(path_type=Path), default=DATA / "raw", show_default=True)
@click.option("--warehouse", type=click.Path(path_type=Path), default=DATA / "warehouse", show_default=True)
@click.option("--threads", type=int, default=None, envvar="BUILD_THREADS", help="DuckDB threads (default: all cores).")
@click.option("--memory-limit", default=None, envvar="BUILD_MEMORY",
              help="DuckDB memory cap for the build, e.g. 1GB (spills to disk past it).")  # fmt: skip
@click.option("--force", is_flag=True, help="Rebuild even if source and recipe are unchanged; publish even if smaller.")
def build(raw: Path, warehouse: Path, threads: int | None, memory_limit: str | None, force: bool) -> None:
    """Build typed Parquet, the read models and the text index from raw/.

    Skipped ("skipped": true) when the warehouse was already built from the
    same content with the same recipe. A running server picks up a new build
    on its own. Refuses (exit 1) to replace the warehouse with one that has
    2%+ fewer tickets or an earlier latest ticket; --force overrides.
    """
    from . import ingest

    try:
        result = ingest.build(raw, warehouse, threads=threads, force=force, memory_limit=memory_limit)
    except (ingest.ShrinkError, FileNotFoundError) as e:
        raise click.ClickException(str(e)) from e
    _emit(result)


@main.command()
@click.argument("sql", required=False)
@click.option("--warehouse", type=click.Path(exists=True, path_type=Path), default=DATA / "warehouse",
              show_default=True)  # fmt: skip
def query(sql: str | None, warehouse: Path) -> None:
    """Run SQL against the warehouse; one JSON object per row.

    Every Parquet file is a view named after it (tickets, tickets_state_year,
    product_month, states). SQL comes from the argument or stdin.

        {{cookiecutter.project_slug}} query "select product, count(*) n from tickets group by 1 order by 2 desc"
    """
    import duckdb

    sql = sql or sys.stdin.read()
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    for f in sorted(warehouse.glob("*.parquet")):
        con.execute(f"CREATE VIEW {f.stem} AS SELECT * FROM read_parquet('{f}')")
    try:
        cur = con.execute(sql)
    except duckdb.Error as e:
        raise click.ClickException(str(e)) from e
    if cur.description is None:
        return
    cols = [d[0] for d in cur.description]
    while rows := cur.fetchmany(10_000):
        for row in rows:
            _emit(dict(zip(cols, row, strict=True)))


@main.command()
@click.option("--host", default=os.environ.get("HOST", "127.0.0.1"), show_default=True)
@click.option("--port", type=int, default=int(os.environ.get("PORT", "{{cookiecutter.default_port}}")), show_default=True)
@click.option("--warehouse", type=click.Path(path_type=Path), default=DATA / "warehouse", show_default=True)
@click.option("--reload", is_flag=True, help="Restart on source changes (development).")
def serve(host: str, port: int, warehouse: Path, reload: bool) -> None:
    """Serve the dashboard and /admin diagnostics.

    Config is environment variables (see README). LOG_LEVEL sets verbosity;
    LOG_FORMAT=json for structured logs.
    """
    import uvicorn

    from .logs import configure
    from .metrics import raise_open_files_limit

    configure()
    raise_open_files_limit()
    os.environ["WAREHOUSE"] = str(warehouse)
    uvicorn.run(
        f"{__package__}.web:app_from_env",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(Path(__file__).parent)] if reload else None,
        reload_includes=["*.py", "*.html", "*.md", "*.js"] if reload else None,
        log_config=None,
        access_log=False,
        # SSE streams never finish on their own; don't wait on them forever
        # at shutdown. No keep-alive or response timeouts: those would sever
        # streams mid-flight.
        timeout_graceful_shutdown=3,
    )


APP_DB = Path(os.environ.get("APP_DB", str(DATA / "app.sqlite")))


@main.command()
@click.option("--db", type=click.Path(path_type=Path), default=APP_DB, show_default=True)
@click.option("--limit", type=int, default=100, show_default=True)
@click.option("--since", default="", help="Only feedback created on or after this ISO date.")
@click.option("--transcripts/--no-transcripts", default=False, help="Include the stored conversations.")
def feedback(db: Path, limit: int, since: str, transcripts: bool) -> None:
    """Feedback users left (check-in ratings and reports), newest first; one JSON object per line."""
    from .appdb import AppDB

    if not db.exists():
        raise click.ClickException(f"no app database at {db}")
    for f in AppDB(db).feedback(limit=limit, since=since):
        row = dataclasses.asdict(f)
        if not transcripts:
            row["transcript"] = len(row["transcript"] or [])  # just how long the conversation was
        _emit(row)


@main.command()
@click.option("--db", type=click.Path(path_type=Path), default=APP_DB, show_default=True)
@click.option("--days", type=int, default=30, show_default=True)
def usage(db: Path, days: int) -> None:
    """LLM usage per UTC day and model (tokens, replies, cost), newest first; one JSON object per line."""
    from .appdb import AppDB

    if not db.exists():
        raise click.ClickException(f"no app database at {db}")
    for row in AppDB(db).usage(days=days):
        _emit({**dataclasses.asdict(row), "tokens": row.tokens})


@main.command()
@click.option("--port", type=int, default=8399, show_default=True)
@click.option("--tokens", type=int, default=200, show_default=True, help="Tokens per reply.")
@click.option("--tps", type=float, default=60, show_default=True, help="Tokens per second per reply.")
def fakellm(port: int, tokens: int, tps: float) -> None:
    """A free, local OpenAI-compatible LLM for load-testing chat.

    Run the server with LLM_BASE_URL=http://127.0.0.1:8399/v1 LLM_MODEL=fake LLM_API_KEY=fake.
    """
    import uvicorn

    from .fakellm import create_app

    uvicorn.run(create_app(tokens, tps), host="127.0.0.1", port=port, log_level="warning")


@main.command()
@click.option("--url", default=f"http://127.0.0.1:{os.environ.get('PORT', '{{cookiecutter.default_port}}')}",
              show_default=True)  # fmt: skip
@click.option("--levels", default="5,10,100,1000", show_default=True,
              help="Comma-separated client counts, ramped cumulatively.")  # fmt: skip
@click.option("--hold", type=float, default=15, show_default=True, help="Seconds measured at each level.")
@click.option("--settle", type=float, default=3, show_default=True, help="Seconds to wait after ramping.")
@click.option("--churn", type=float, default=0, show_default=True,
              help="Mean seconds between filter changes per client; 0 = read-only clients.")  # fmt: skip
@click.option("--ramp", type=float, default=200, show_default=True, help="New clients per second.")
@click.option("--chat", type=float, default=0, show_default=True,
              help="Mean seconds between chat questions per client; 0 = none. Use `fakellm`!")  # fmt: skip
def loadtest(url: str, levels: str, hold: float, settle: float, churn: float, ramp: float, chat: float) -> None:
    """Hold N clients against a running server; one JSON result per level.

    Watch /admin while it runs: the "cost by connected clients" table fills in.
    """
    from . import loadtest as lt
    from .metrics import raise_open_files_limit

    raise_open_files_limit()
    try:
        counts = sorted({int(x) for x in levels.split(",") if x.strip()})
    except ValueError as e:
        raise click.BadParameter(f"levels must be integers: {levels}") from e
    try:
        asyncio.run(lt.run(url.rstrip("/"), counts, hold, settle, churn, ramp, chat))
    except KeyboardInterrupt:
        sys.exit(130)


@main.command(name="eval")
@click.argument("only", nargs=-1)
@click.option("--cases", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=Path("evals/cases.toml"), show_default=True)  # fmt: skip
@click.option("--warehouse", type=click.Path(path_type=Path), default=DATA / "warehouse", show_default=True)
@click.option("--model", default="", help="Assistant model to evaluate (default: LLM_MODEL).")
@click.option("--reasoning", type=int, default=None,
              help="Assistant thinking budget in tokens (default: LLM_REASONING_TOKENS).")  # fmt: skip
@click.option("--judge", default="", help="Judge model (default: EVAL_JUDGE_MODEL).")
@click.option("--parallel", type=int, default=4, show_default=True, help="Cases run at once.")
@click.option("--repeat", type=int, default=1, show_default=True, help="Run each case N times (flakiness).")
def eval_(only: tuple[str, ...], cases: Path, warehouse: Path, model: str, reasoning: int | None, judge: str,
          parallel: int, repeat: int) -> None:  # fmt: skip
    """Run the assistant against evals/cases.toml with the real model; one JSON result per case.

    ONLY picks cases whose id contains any of the given substrings. Exits 1 if
    any case fails. Costs real money: the assistant plus a judge call or two
    per case.
    """
    from . import evals
    from .llm import LLMConfig

    llm = LLMConfig.from_env()
    if model:  # prompt caching (cache_control) is for anthropic models
        llm = dataclasses.replace(llm, model=model, prompt_cache=model.startswith("anthropic/"))
    if reasoning is not None:
        llm = dataclasses.replace(llm, reasoning_tokens=reasoning)
    if not llm.configured:
        raise click.ClickException("no LLM configured (LLM_API_KEY or OPENROUTER_API_KEY)")
    judge_model = judge or os.environ.get("EVAL_JUDGE_MODEL", evals.DEFAULT_JUDGE)
    judge_cfg = dataclasses.replace(llm, model=judge_model, max_tokens=8000, reasoning_tokens=0,
                                    prompt_cache=judge_model.startswith("anthropic/"))  # fmt: skip
    try:
        battery = evals.load_cases(cases, only) * repeat
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if not battery:
        raise click.ClickException(f"no cases match {' '.join(only)!r}")
    thinking = f" (reasoning {llm.reasoning_tokens})" if llm.reasoning_tokens else ""
    click.echo(f"eval: {len(battery)} cases · assistant {llm.model}{thinking} · judge {judge_cfg.model}", err=True)

    def report(r: evals.Result) -> None:
        click.echo(evals.to_json(r))
        click.echo(f"  {'pass' if r.ok else 'FAIL'} {r.id} ({r.seconds:.0f}s)", err=True)

    results = evals.Evaluator(warehouse, llm, judge_cfg).run(battery, parallel=parallel, on_result=report)
    click.echo(evals.summarize(results), err=True)
    sys.exit(0 if all(r.ok for r in results) else 1)
