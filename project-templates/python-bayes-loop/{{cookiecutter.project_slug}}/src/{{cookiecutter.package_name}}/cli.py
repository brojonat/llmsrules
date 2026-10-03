"""{{cookiecutter.project_slug}}: compile-once GPU inference for a PyMC model, on a DuckDB belt.

  bench   refit fresh same-shape data (simulated, or a file's chunks); one JSON line per fit
  db      own data/belt.duckdb and serve it over Quack
  feed    insert batches: simulated from a drifting truth, or replayed from a file
  sample  fit each new batch on the GPU, write summaries
  serve   the dashboard
  note    post to the dashboard's agent thread: what changed and why, results, a report
  inbox   the dashboard user's unread messages (JSON per line); --wait blocks for one
  source  the model.py a model version was compiled from
  describe  the dashboard's plain-English description of the current model version
  plots   render the dashboard's figures (ArviZ) for each model version's latest fit
  figure  add a PNG of your own to the dashboard's figures
  figures the figures on the dashboard (JSON per line); --save DIR writes the PNGs to look at

JSON on stdout, progress on stderr. Quack settings come from QUACK_URL and
QUACK_TOKEN (see mise.toml).
"""

import argparse
import contextlib
import json
import logging
import os
import signal
import sys
import threading
import time
import warnings
from pathlib import Path

# The RTX 20xx/30xx/40xx consumer cards run float64 at 1/32-1/64 of float32
# throughput. Default to float32 unless the caller set PYTENSOR_FLAGS.
os.environ.setdefault("PYTENSOR_FLAGS", "floatX=float32")
# PyTensor emits int64 shape casts; with x64 off JAX truncates them to int32. Harmless.
warnings.filterwarnings("ignore", message="Explicitly requested dtype .* is not available")

log = logging.getLogger("{{cookiecutter.package_name}}")

# Only `bench` and `sample` import JAX: importing it initializes CUDA, and the
# db, feeder and web server have no business holding a GPU context.
SAMPLER_NAMES = ["nuts", "chees"]  # == samplers.SAMPLERS keys (tests check)
BASELINE_NAMES = ["pymc", "pymc-numpyro", "pymc-blackjax"]


def _require_jax_device() -> None:
    """Fail with a readable message when JAX can't initialize its backend.

    With jax[cuda13] installed, a broken driver makes the *first* jnp call
    raise, which for us is deep inside `import blackjax`.
    """
    import jax

    try:
        jax.devices()
    except RuntimeError as e:
        sys.exit(
            f"JAX could not initialize a device: {e}\n"
            "If `nvidia-smi` says 'Driver/library version mismatch', the NVIDIA kernel module is older "
            "than the userspace driver: reboot. To run on CPU instead: `mise run up:cpu` (or set JAX_PLATFORMS=cpu)."
        )


def _sizes(args) -> dict[str, int]:
    """The simulator's dim sizes: model.SIM_DIMS, then BELT_DIMS, then --dim flags."""
    from {{cookiecutter.package_name}}.model import SIM_DIMS

    sizes = dict(SIM_DIMS)
    env = [(item, "BELT_DIMS (mise.cpu.toml or .env)") for item in os.environ.get("BELT_DIMS", "").split()]
    for item, origin in [*env, *((item, "--dim") for item in args.dim or [])]:
        name, _, size = item.partition("=")
        if name not in SIM_DIMS or not size.isdigit():
            sys.exit(f"bad dim size {item!r} from {origin}: want NAME=SIZE with NAME one of {', '.join(SIM_DIMS)}")
        sizes[name] = int(size)
    return sizes


def cmd_bench(args) -> None:
    _require_jax_device()
    from {{cookiecutter.package_name}} import bench

    bench.run(args, _sizes(args))


def _quack() -> tuple[str, str]:
    url, token = os.environ.get("QUACK_URL", "quack:localhost"), os.environ.get("QUACK_TOKEN", "")
    if len(token) < 4:
        sys.exit("QUACK_TOKEN must be set (4+ characters); mise.toml sets a dev default")
    return url, token


def _run_until_signal(target, *args, **kwargs) -> None:
    """Run target(*args, stop, **kwargs) in a thread; the main thread handles signals.

    A Python signal handler only runs when the main thread is executing Python,
    which it isn't during a multi-second XLA call. So the work runs in a thread
    and the main thread waits: first Ctrl-C/SIGTERM sets `stop` (finish the
    current fit), a second exits immediately.
    """
    stop = threading.Event()
    failed: list[Exception] = []

    def handle(signum, frame):
        if stop.is_set():
            os._exit(128 + signum)
        log.info("stopping after the current fit; signal again to abort")
        stop.set()

    def work():
        try:
            target(*args, stop, **kwargs)
        except Exception as e:  # noqa: BLE001 - not swallowed: re-raised on the main thread below
            failed.append(e)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle)
    t = threading.Thread(target=work, name=target.__name__)
    t.start()
    while t.is_alive():
        t.join(0.2)
    if failed:
        raise failed[0]


def cmd_db(args) -> None:
    from {{cookiecutter.package_name}} import belt
    from {{cookiecutter.package_name}}.model import OBS_DDL  # model imports pymc lazily: no PyTensor in the db process

    os.makedirs(os.path.dirname(args.path) or ".", exist_ok=True)
    belt.serve(args.path, *_quack(), ddl=OBS_DDL, housekeep_s=_env("BELT_HOUSEKEEP_S", 60.0))


def cmd_feed(args) -> None:
    import numpy as np

    from {{cookiecutter.package_name}} import belt, feed

    sizes = None if args.source else _sizes(args)  # bad sizes fail before waiting on the db
    con = belt.connect(*_quack())
    try:
        if args.source:
            feed.replay(con, args.source, n=args.n, order_by=args.order_by, every=args.every, count=args.count)
        else:
            feed.simulate(
                con, np.random.default_rng(args.seed), n=args.n, sizes=sizes,
                every=args.every, drift=args.drift, count=args.count,
            )  # fmt: skip
    except KeyboardInterrupt:
        pass


def cmd_sample(args) -> None:
    _require_jax_device()
    from {{cookiecutter.package_name}} import belt, worker

    con = belt.connect(*_quack())
    _run_until_signal(
        worker.run, con, sampler=args.sampler, chains=args.chains, warmup=args.warmup,
        draws=args.draws, latest=args.latest, poll=args.poll, seed=args.seed, refit=args.refit,
    )  # fmt: skip


def _listeners(port: int) -> list[int]:
    """PIDs listening on a TCP port (via `ss`; a uvicorn reloader and its child share one socket)."""
    import re
    import subprocess

    out = subprocess.run(["ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True, check=True).stdout
    return sorted({int(p) for p in re.findall(r"pid=(\d+)", out)})


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode().strip()
    except OSError:
        return ""


def _free_port(port: int, replace: bool) -> None:
    """Fail clearly if the port is taken; with replace, stop an old dashboard holding it.

    A dev server whose terminal went away can outlive `mise run up` and keep
    the port, so the next `dev` dies with "Address already in use" while the
    browser keeps talking to stale code.
    """
    pids = _listeners(port)
    if not pids:
        return
    held = {pid: _cmdline(pid) for pid in pids}
    ours = any("{{cookiecutter.project_slug}} serve" in cmd for cmd in held.values())
    if not (replace and ours):
        who = "; ".join(f"pid {pid}: {cmd[:80]}" for pid, cmd in held.items())
        hint = "an old dashboard; `mise run stop`, then retry" if ours else "not {{cookiecutter.project_slug}}; pick another PORT"
        sys.exit(f"port {port} is in use ({who}) - {hint}")
    for pid in pids:  # the reloader and its worker child share the socket
        log.info("stopping old dashboard on :%d (pid %d)", port, pid)
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while _listeners(port) and time.monotonic() < deadline:
        time.sleep(0.1)
    for pid in _listeners(port):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def cmd_plots(args) -> None:
    from {{cookiecutter.package_name}} import belt, plots

    con = belt.connect(*_quack())
    _run_until_signal(plots.run, con, every=args.every, poll=args.poll)


def cmd_figure(args) -> None:
    from {{cookiecutter.package_name}} import belt, plots

    con = belt.connect(*_quack(), wait_s=5)
    print(json.dumps(plots.post_file(con, Path(args.path), args.title)))


def cmd_figures(args) -> None:
    from {{cookiecutter.package_name}} import belt, journal, plots

    con = belt.connect(*_quack(), wait_s=5)
    figs = plots.carousel(con, journal.versions(con))
    if args.save:
        Path(args.save).mkdir(parents=True, exist_ok=True)
    for f in figs:
        row = {k: f[k] for k in ("id", "version", "kind", "title", "author")}
        if args.save:
            png = belt.read(con, f"select png from figures where id = {f['id']}")["png"][0].as_py()
            row["path"] = str(Path(args.save) / f"{f['key']}.png")
            Path(row["path"]).write_bytes(png)
        print(json.dumps(row))


def cmd_note(args) -> None:
    from {{cookiecutter.package_name}} import belt, journal

    text = (sys.stdin.read() if args.text == ["-"] else " ".join(args.text)).strip()
    if not text:
        sys.exit("nothing to post: give the text as arguments, or - to read it from stdin")
    con = belt.connect(*_quack(), wait_s=5)
    model_id = journal.latest_model(con) if args.model is None else args.model
    message_id = journal.post(con, "agent", args.kind, text, model_id)
    print(json.dumps({"id": message_id, "kind": args.kind, "model_id": model_id}))


def cmd_describe(args) -> None:
    from {{cookiecutter.package_name}} import belt, journal

    text = (sys.stdin.read() if args.text == ["-"] else " ".join(args.text)).strip()
    if not text:
        sys.exit("nothing to post: give the text as arguments, or - to read it from stdin")
    con = belt.connect(*_quack(), wait_s=5)
    model_id = journal.latest_model(con) if args.model is None else args.model
    if model_id is None:
        sys.exit("no fitted model yet: describe it once the sampler has fit a batch")
    journal.describe(con, model_id, text)
    print(json.dumps({"model_id": model_id, "version": journal.versions(con).get(model_id)}))


def cmd_inbox(args) -> None:
    from {{cookiecutter.package_name}} import belt, journal

    con = belt.connect(*_quack(), wait_s=5)
    messages = journal.unread(con)
    if not messages and args.wait:
        journal.post(con, "agent", "status", "waiting for feedback")
        deadline = time.monotonic() + args.wait
        while not messages and time.monotonic() < deadline:
            time.sleep(1.0)
            messages = journal.unread(con)
    if not messages:
        return
    journal.mark_read(con, [m["id"] for m in messages])
    journal.post(con, "agent", "status", "working on your feedback")
    versions = journal.versions(con)
    for m in messages:
        print(json.dumps({**m, "version": versions.get(m["model_id"])}, default=str))


def cmd_source(args) -> None:
    from {{cookiecutter.package_name}} import belt, journal

    con = belt.connect(*_quack(), wait_s=5)
    model_id = args.model
    if model_id.startswith("v"):  # a version: its newest compile
        ids = [i for i, v in journal.versions(con).items() if f"v{v}" == model_id]
        model_id = str(max(ids)) if ids else ""
    rows = belt.read(con, f"select source from models where id = {int(model_id)}") if model_id.isdigit() else None
    if rows is None or not rows.num_rows or rows["source"][0].as_py() is None:
        sys.exit(f"no model.py recorded for {args.model}")
    sys.stdout.write(rows["source"][0].as_py())


def cmd_serve(args) -> None:
    import uvicorn

    _free_port(args.port, args.replace)
    # uvicorn runs at WARNING; say where the dashboard is, so logs/serve.log shows it started.
    log.info(
        "dashboard on http://%s:%d", "localhost" if args.host in ("0.0.0.0", "127.0.0.1") else args.host, args.port
    )
    uvicorn.run(
        "{{cookiecutter.package_name}}.web:create_app", factory=True, host=args.host, port=args.port,
        reload=args.reload, reload_dirs=["src"] if args.reload else None, log_level="warning",
        # The dashboard never imports model.py, so a model edit shouldn't restart it. And a reload
        # must not wait on open SSE streams (a watching browser holds one forever): give them 1 s.
        reload_excludes=["model.py"] if args.reload else None, timeout_graceful_shutdown=1,
    )  # fmt: skip


def _env[T: (int, float)](name: str, default: T) -> T:
    """A flag default from the environment, parsed as the default's type."""
    raw = os.environ.get(name)
    return default if raw is None else type(default)(raw)


def parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="{{cookiecutter.project_slug}}", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def problem(sp, n=100_000):
        sp.add_argument("--n", type=int, default=n, help="observations per batch")
        sp.add_argument(
            "--dim", action="append", metavar="NAME=SIZE",
            help="simulated dim size, repeatable (default: model.SIM_DIMS, then BELT_DIMS)",
        )  # fmt: skip

    def sampling(sp, choices, chains=256, warmup=300, draws=50, sampler="chees"):
        sp.add_argument("--sampler", choices=choices, default=sampler)
        sp.add_argument("--chains", type=int, default=chains)
        sp.add_argument("--warmup", type=int, default=warmup)
        sp.add_argument("--draws", type=int, default=draws)
        sp.add_argument("--seed", type=int, default=0)

    def source(sp, env: bool):
        """--from/--order-by; with env, defaulted from FEED_FROM/FEED_ORDER_BY (feed only: bench stays simulated)."""
        sp.add_argument(
            "--from", dest="source", metavar="PATH", default=(os.environ.get("FEED_FROM") or None) if env else None,
            help="a file of obs rows (parquet/csv/json, columns as model.OBS_DDL), in chunks of --n rows"
            + (" (env FEED_FROM)" if env else ""),
        )  # fmt: skip
        sp.add_argument(
            "--order-by", metavar="COLUMN", default=(os.environ.get("FEED_ORDER_BY") or None) if env else None,
            help="with --from: chunk in this column's order, e.g. a timestamp" + (" (env FEED_ORDER_BY)" if env else ""),
        )  # fmt: skip

    sp = sub.add_parser("bench", help="refit fresh same-shape data (simulated, or --from a file); JSON per fit")
    problem(sp)
    source(sp, env=False)
    sampling(sp, [*SAMPLER_NAMES, *BASELINE_NAMES], chains=8, warmup=500, draws=500, sampler="nuts")
    sp.add_argument(
        "--reps", type=int, default=3,
        help="refits: fresh simulated data, or the file's first full chunks (a short tail is skipped)",
    )  # fmt: skip
    sp.add_argument("--skip", type=int, default=0, metavar="K", help="with --from: skip the file's first K chunks")
    sp.add_argument(
        "--params", action="store_true", help="also print each rep's posterior summary, one line per scalar"
    )
    sp.set_defaults(fn=cmd_bench)

    sp = sub.add_parser("db", help="own the database file and serve it over Quack")
    sp.add_argument("--path", default=os.environ.get("BELT_DB", "data/belt.duckdb"))
    sp.set_defaults(fn=cmd_db)

    # feed and sample take their defaults from the environment so a mise profile
    # (mise.cpu.toml) can resize the whole belt; flags still win.
    sp = sub.add_parser("feed", help="insert batches: simulated, or replayed from a file")
    problem(sp, n=_env("BELT_N", 100_000))
    source(sp, env=True)
    sp.add_argument("--every", type=float, default=_env("FEED_EVERY", 1.0), help="seconds between batches")
    sp.add_argument("--drift", type=float, default=0.02, help="simulator: random-walk scale of the truth")
    sp.add_argument("--count", type=int, default=0, help="stop after this many (0 = forever, or the whole file)")
    sp.add_argument("--seed", type=int, default=0)
    sp.set_defaults(fn=cmd_feed)

    sp = sub.add_parser("sample", help="fit each new batch, write summaries")
    sampling(
        sp, SAMPLER_NAMES, chains=_env("SAMPLE_CHAINS", 256), warmup=_env("SAMPLE_WARMUP", 300),
        draws=_env("SAMPLE_DRAWS", 50),
    )  # fmt: skip
    sp.add_argument(
        "--latest", action="store_true", default=bool(_env("SAMPLE_LATEST", 0)),
        help="skip a backlog: always fit the newest batch",
    )  # fmt: skip
    sp.add_argument(
        "--refit", type=int, default=_env("SAMPLE_REFIT", 0), metavar="N",
        help="on start, re-fit the newest N batches with the current model (after a model edit)",
    )  # fmt: skip
    sp.add_argument("--poll", type=float, default=0.05, help="seconds between checks when idle")
    sp.set_defaults(fn=cmd_sample)

    sp = sub.add_parser("note", help="post to the dashboard's agent thread")
    sp.add_argument("text", nargs="+", help="the message; - reads it from stdin")
    sp.add_argument("--kind", choices=["note", "report", "commit"], default="note")
    sp.add_argument("--model", type=int, default=None, help="model id it's about (default: the one on the dashboard)")
    sp.set_defaults(fn=cmd_note)

    sp = sub.add_parser("inbox", help="print (and mark read) the dashboard user's unread messages, JSON per line")
    sp.add_argument(
        "--wait", type=float, default=0, metavar="SECONDS",
        help="block up to this long for a message; the dashboard shows the agent as waiting",
    )  # fmt: skip
    sp.set_defaults(fn=cmd_inbox)

    sp = sub.add_parser("describe", help="set the dashboard's plain-English description of the current model")
    sp.add_argument("text", nargs="+", help="two short paragraphs; - reads them from stdin")
    sp.add_argument("--model", type=int, default=None, help="model id (default: the one on the dashboard)")
    sp.set_defaults(fn=cmd_describe)

    sp = sub.add_parser("source", help="print the model.py a model version was compiled from")
    sp.add_argument("model", help="a model id, or a version like v3")
    sp.set_defaults(fn=cmd_source)

    sp = sub.add_parser("plots", help="render the dashboard's figures for each model version's latest fit")
    sp.add_argument(
        "--every", type=float, default=_env("PLOTS_EVERY", 60.0),
        help="seconds between renders of the same version (a new version renders at once)",
    )  # fmt: skip
    sp.add_argument("--poll", type=float, default=1.0, help="seconds between checks for new fits")
    sp.set_defaults(fn=cmd_plots)

    sp = sub.add_parser("figure", help="add a PNG of your own to the dashboard's figures")
    sp.add_argument("path", help="a PNG file")
    sp.add_argument("--title", required=True, help="the caption, e.g. 'Observed vs expected churners by tenure'")
    sp.set_defaults(fn=cmd_figure)

    sp = sub.add_parser("figures", help="list the dashboard's figures; --save DIR writes the PNGs")
    sp.add_argument("--save", metavar="DIR", help="write each figure as DIR/<key>.png")
    sp.set_defaults(fn=cmd_figures)

    sp = sub.add_parser("serve", help="the dashboard")
    sp.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    sp.add_argument("--port", type=int, default=int(os.environ.get("PORT", "{{cookiecutter.default_port}}")))
    sp.add_argument("--reload", action="store_true")
    sp.add_argument("--replace", action="store_true", help="stop an old {{cookiecutter.project_slug}} dashboard holding the port")
    sp.set_defaults(fn=cmd_serve)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    # Third-party loggers stay at WARNING (PyTensor is chatty at INFO); ours follow LOG_LEVEL.
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(asctime)s %(name)s %(message)s")
    log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    args = parse(argv)
    args.fn(args)
