import json
import time

import duckdb
import httpx
import pytest
from starlette.testclient import TestClient

from {{cookiecutter.package_name}} import llm
from {{cookiecutter.package_name}}.chat import Message
from {{cookiecutter.package_name}}.llm import Delta, LLMConfig, LLMError, Usage
from {{cookiecutter.package_name}}.search import TextIndex
from {{cookiecutter.package_name}}.sql import SqlSandbox
from {{cookiecutter.package_name}}.tools import ViewTools, _chart_panels, _chart_series, _chart_table, _legend
from {{cookiecutter.package_name}}.warehouse import Filter, Warehouse
from {{cookiecutter.package_name}}.web import Config, create_app

J = {"Datastar-Request": "true"}


def sse(*chunks: dict | str) -> bytes:
    """An OpenAI-style stream, with an OpenRouter keep-alive comment first."""
    lines = [": OPENROUTER PROCESSING", ""]
    for c in chunks:
        lines += [f"data: {c if isinstance(c, str) else json.dumps(c)}", ""]
    return "\n".join(lines).encode()


def delta(text: str) -> dict:
    return {"choices": [{"index": 0, "delta": {"role": "assistant", "content": text}}]}


USAGE = {"choices": [], "usage": {"prompt_tokens": 900, "completion_tokens": 12, "cost": 0.0009}}
CFG = LLMConfig(base_url="https://llm.test/v1", api_key="k", model="m", max_tokens=100)


class FakeLLM:
    """Records requests; replies with `reply` streamed in two chunks."""

    def __init__(self, reply: str = "Resolution time is a **mean** over resolved tickets.", status: int = 200) -> None:
        self.requests: list[dict] = []
        self.reply, self.status = reply, status

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "m", "context_length": 200_000}]})
        self.requests.append(json.loads(request.content))
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "no credits"}})
        half = len(self.reply) // 2
        body = sse(delta(self.reply[:half]), delta(self.reply[half:]), USAGE, "[DONE]")
        return httpx.Response(200, stream=httpx.ByteStream(body), headers={"content-type": "text/event-stream"})


class ToolLLM:
    """Turn 1: call set_view with `args` (streamed in fragments). Turn 2: answer in text."""

    def __init__(self, args: str = '{"products": ["ledger"], "states": ["Texas"]}', tool: str = "set_view") -> None:
        self.requests: list[dict] = []
        self.args, self.tool = args, tool

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        body = json.loads(request.content)
        self.requests.append(body)
        if body["messages"][-1]["role"] == "user":
            call = {"index": 0, "id": "call_1", "type": "function", "function": {"name": self.tool, "arguments": ""}}
            first = {"choices": [{"index": 0, "delta": {"content": "Working. ", "tool_calls": [call]}}]}
            rest = [{"choices": [{"index": 0, "delta": {"tool_calls": [
                        {"index": 0, "function": {"arguments": self.args[i : i + 7]}}]}}]}
                    for i in range(0, len(self.args), 7)]  # fmt: skip
            chunks = [first, *rest, {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}, USAGE]
        else:
            chunks = [delta("Done: here it is."), USAGE]
        return httpx.Response(200, stream=httpx.ByteStream(sse(*chunks, "[DONE]")))


async def collect(fake, messages=None, cfg=CFG, tools=None) -> list:
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as http:
        return [e async for e in llm.stream_chat(http, cfg, messages or [{"role": "user", "content": "hi"}], tools)]


def drive(warehouse, fake, cfg=CFG, **config) -> TestClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return TestClient(create_app(Config(warehouse=warehouse, sample_interval=0.05, llm=cfg, **config), llm_http=http))


def wait_for(c: TestClient, text: str, timeout: float = 5) -> str:
    """Poll until `text` is in a finished reply, then return a fresh page.
    The first paint renders its regions one after another, awaiting queries
    in between, so the page that first shows the reply can hold a builder
    rendered just before the reply's tool call landed. (In a browser the
    stream repaints both; here we fetch again.)"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        page = c.get("/").text
        if text in page and "msg assistant typing" not in page:
            return c.get("/").text
        time.sleep(0.02)
    raise AssertionError(f"{text!r} never appeared")


@pytest.fixture
def tools(warehouse):
    wh = Warehouse(warehouse)
    wh.reload_if_changed()
    return ViewTools(wh, {}, lambda sid: None, SqlSandbox(warehouse), TextIndex(warehouse))


# --- the client --------------------------------------------------------------------------


async def test_stream_parses_deltas_usage_and_skips_comments():
    events = await collect(FakeLLM("hello world"))
    assert "".join(e.text for e in events if isinstance(e, Delta)) == "hello world"
    assert events[-1] == Usage(900, 12, 0.0009)


async def test_request_is_openai_compatible():
    fake = FakeLLM()
    await collect(fake)
    body = fake.requests[0]
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True} and body["model"] == "m"


async def test_errors_before_and_during_the_stream():
    with pytest.raises(LLMError, match="402: no credits"):
        await collect(FakeLLM(status=402))

    class MidStream:
        def handler(self, request):
            return httpx.Response(200, stream=httpx.ByteStream(sse(delta("par"), {"error": {"message": "overloaded"}})))

    with pytest.raises(LLMError, match="overloaded"):
        await collect(MidStream())


async def test_stream_reassembles_tool_call_fragments():
    fake = ToolLLM()
    events = await collect(fake, tools=[{}])
    [calls] = [e for e in events if isinstance(e, llm.ToolCalls)]
    assert [(c.id, c.name, json.loads(c.arguments)) for c in calls.calls] == [
        ("call_1", "set_view", {"products": ["ledger"], "states": ["Texas"]})
    ]
    assert fake.requests[0]["tools"] == [{}]


async def test_reasoning_fragments_merge_and_budget_adds_to_max_tokens():
    thinking = [
        {"choices": [{"index": 0, "delta": {"reasoning_details": [
            {"type": "reasoning.text", "text": "Let me ", "index": 0, "format": "anthropic-claude-v1"}]}}]},
        {"choices": [{"index": 0, "delta": {"reasoning_details": [
            {"type": "reasoning.text", "text": "think.", "index": 0, "signature": "sig"}]}}]},
    ]  # fmt: skip
    seen = []

    class Thinker:
        def handler(self, request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, stream=httpx.ByteStream(sse(*thinking, delta("Done."), USAGE, "[DONE]")))

    cfg = LLMConfig(base_url="https://llm.test/v1", api_key="k", model="m", max_tokens=100, reasoning_tokens=2000)
    events = await collect(Thinker(), cfg=cfg)
    assert seen[0]["reasoning"] == {"max_tokens": 2000} and seen[0]["max_tokens"] == 2100
    [r] = [e for e in events if isinstance(e, llm.Reasoning)]
    assert r.details == [{"type": "reasoning.text", "text": "Let me think.", "index": 0,
                          "format": "anthropic-claude-v1", "signature": "sig"}]  # fmt: skip
    assert Message("assistant", "Done.", reasoning=r.details).to_api()["reasoning_details"] == r.details


# --- the chat panel ----------------------------------------------------------------------


def test_send_is_a_command_and_the_reply_lands_in_the_page(warehouse):
    fake = FakeLLM()
    with drive(warehouse, fake) as c:
        assert "Context ≈" in c.get("/").text  # an estimate before the first reply
        r = c.post("/chat/send", json={"message": "How is resolution time computed?"}, headers=J)
        assert r.status_code == 204 and r.text == ""
        page = wait_for(c, "<strong>mean</strong>")
        assert "How is resolution time computed?" in page
        assert "Context 912 / 200,000 tokens" in page  # exact: provider prompt + completion
        system = fake.requests[0]["messages"][0]
        assert system["role"] == "system" and "# Methodology" in system["content"]
        assert "## tickets_state_year (" in system["content"]  # the live schema
        assert "Values of `product`" in system["content"] and "Data runs from" in system["content"]


def test_follow_ups_carry_history_and_clear_starts_over(warehouse):
    fake = FakeLLM()
    with drive(warehouse, fake) as c:
        c.get("/")
        c.post("/chat/send", json={"message": "first"}, headers=J)
        wait_for(c, "<strong>mean</strong>")
        c.post("/chat/send", json={"message": "second"}, headers=J)
        wait_for(c, "second")
        time.sleep(0.2)
        assert [m["role"] for m in fake.requests[-1]["messages"]] == ["system", "user", "assistant", "user"]
        assert c.post("/chat/clear", headers=J).status_code == 204
        page = c.get("/").text
        assert "first" not in page and "Context ≈" in page
        with TestClient(c.app) as other:  # conversations are per session
            assert "second" not in other.get("/").text


def test_model_output_cannot_inject_html(warehouse):
    with drive(warehouse, FakeLLM("<script>alert(1)</script> and <b>bold</b>")) as c:
        c.get("/")
        c.post("/chat/send", json={"message": "hi"}, headers=J)
        page = wait_for(c, "alert(1)")
        assert "<script>alert(1)" not in page and "&lt;script&gt;" in page


def test_out_of_context_and_empty_messages_are_refused(warehouse):
    tiny = LLMConfig(base_url="https://llm.test/v1", api_key="k", model="m", context_window=50, max_tokens=10)
    with drive(warehouse, FakeLLM(), cfg=tiny) as c:
        c.get("/")
        assert c.post("/chat/send", json={"message": "  "}).status_code == 400
        r = c.post("/chat/send", json={"message": "anything"})
        assert r.status_code == 400 and "out of context" in r.text
        assert "out of context" in c.get("/").text  # shown in the panel too


def test_unconfigured_chat_says_so(client):
    assert "Chat isn't configured" in client.get("/").text
    assert client.post("/chat/send", json={"message": "hi"}).status_code == 400


def test_usage_is_recorded_per_day_and_the_budget_stops_chat(warehouse, tmp_path):
    cfg = LLMConfig(base_url="https://llm.test/v1", api_key="k", model="m", max_tokens=100, daily_tokens=500)
    with drive(warehouse, FakeLLM(), cfg=cfg, app_db=tmp_path / "app.sqlite") as c:
        c.get("/")
        assert c.post("/chat/send", json={"message": "hi"}).status_code == 204  # 0 of 500 used
        wait_for(c, "<strong>mean</strong>")
        [row] = c.app.state.s.appdb.usage()
        assert (row.model, row.replies, row.tokens, row.cost) == ("m", 1, 912, 0.0009)
        r = c.post("/chat/send", json={"message": "again"})  # 912 ≥ 500
        assert r.status_code == 400 and "budget" in r.text
        assert "_chat_tokens_today 912" in c.get("/metrics").text


# --- the assistant driving the dashboard -------------------------------------------------


def test_assistant_changes_the_view_through_the_same_command_path(warehouse, db):
    fake = ToolLLM()
    with drive(warehouse, fake) as c:
        c.get("/")
        c.post("/chat/send", json={"message": "show ledger in texas"}, headers=J)
        page = wait_for(c, "Done: here it is.")
        assert 'selected="TX"' in page and 'aria-label="Remove Ledger"' in page  # the dashboard moved
        assert "↳ dataset: Ledger · TX" in page  # and the chat says so
        msgs = fake.requests[1]["messages"]  # the call and its result went back to the model
        assert msgs[-2]["tool_calls"][0]["function"]["name"] == "set_view"
        result = json.loads(msgs[-1]["content"])
        [(n,)] = db("SELECT count(*) FROM tickets WHERE product = 'Ledger' AND state = 'TX'")
        assert result["view"]["products"] == ["Ledger"] and result["totals"]["tickets"] == n


def test_bad_tool_arguments_come_back_as_errors_not_view_changes(warehouse):
    fake = ToolLLM('{"states": ["Atlantis"]}')
    with drive(warehouse, fake) as c:
        c.get("/")
        c.post("/chat/send", json={"message": "show atlantis"}, headers=J)
        page = wait_for(c, "Done:")
        assert "set_view failed: unknown state" in page and 'selected=""' in page
        assert "unknown state" in json.loads(fake.requests[1]["messages"][-1]["content"])["error"]


def test_loose_names_resolve_to_values_in_the_data(tools):
    assert tools.resolve("plans", "enterprise") == ("Enterprise", None)
    assert tools.resolve("categories", "how to") == ("How-to", None)
    assert tools.resolve("categories", "data-loss") == ("Data loss", None)
    assert tools.resolve("products", "harb") == ("Harbor", None)
    value, err = tools.resolve("products", "zzz")
    assert value == "" and "no product matches" in err["error"] and "Ledger" in err["values"]


async def test_query_and_search_tools(tools, db):
    r = await tools.call("s", "query_data", {"sql": "SELECT count(*) AS n FROM tickets", "purpose": "count"})
    assert r["rows"] == [list(db("SELECT count(*) FROM tickets")[0])]
    assert "only SELECT" in (await tools.call("s", "query_data", {"sql": "DROP VIEW tickets"}))["error"]
    s = await tools.call("s", "search_text", {"query": "invoice", "purpose": "x"})
    assert s["matching_tickets"] > 0 and s["recent_excerpts"]
    narrowed = await tools.call("s", "search_text", {"query": "invoice", "purpose": "x", "product": "Relay"})
    assert narrowed["matching_tickets"] < s["matching_tickets"] == narrowed["matches_before_filters"]


async def test_sql_filter_reproduces_the_dashboard_exactly(tools, warehouse):
    tools.filters["s"] = Filter(products=("Ledger", "Relay"), plans=("Pro",), years=(2023,))
    view = await tools.call("s", "get_view", {})
    flt = view["sql_filter"]
    rollup = duckdb.sql(f"SELECT sum(tickets) FROM '{warehouse}/tickets_state_year.parquet' WHERE {flt}")
    detail = duckdb.sql(f"SELECT count(*) FROM '{warehouse}/tickets.parquet' WHERE {flt}")
    assert rollup.fetchone()[0] == detail.fetchone()[0] == view["totals"]["tickets"] > 0


def test_sql_tool_calls_show_as_expandable_chips(warehouse):
    fake = ToolLLM('{"sql": "SELECT count(*) AS n FROM tickets", "purpose": "all tickets"}', tool="query_data")
    with drive(warehouse, fake) as c:
        c.get("/")
        c.post("/chat/send", json={"message": "how many tickets?"}, headers=J)
        page = wait_for(c, "Done:")
        assert "↳ queried: all tickets · 1 row" in page
        assert "<pre>SELECT count(*) AS n FROM tickets</pre>" in page


# --- charts in the chat ------------------------------------------------------------------


def test_chart_renders_in_the_chat_from_sql_not_model_numbers(warehouse, db):
    sql = "SELECT year, count(*) AS n FROM tickets GROUP BY 1 ORDER BY 1"
    fake = ToolLLM(json.dumps({"kind": "bar", "title": "Tickets per year", "unit": "tickets", "sql": sql}),
                   tool="show_chart")  # fmt: skip
    with drive(warehouse, fake) as c:
        c.get("/")
        c.post("/chat/send", json={"message": "chart tickets per year"}, headers=J)
        page = wait_for(c, "Done:")
        expected = [list(r) for r in db(sql)]
        assert f"<chart-bars id=\"chart-call_1-1\" series='{json.dumps(expected)}'" in page
        assert "↳ charted: Tickets per year · 2 points" in page
        sent = json.loads(fake.requests[1]["messages"][-1]["content"])  # a summary, not a render spec
        assert sent["points"] == 2 and "chart" not in sent and "__attachment__" not in sent


def test_chart_series_shapes():
    one = _chart_series(["year", "n"], [[2020, 5], [2021, 7]], "bar")
    assert one == [{"name": "", "points": [[2020, 5], [2021, 7]]}]
    many = _chart_series(["year", "plan", "n"], [[2020, "A", 1], [2020, "B", 2], [2021, "A", 3]], "line")
    assert [s["name"] for s in many] == ["A", "B"]
    assert _chart_table(["year", "plan", "n"], [{"name": "", "series": many}]) == {
        "header": ["year", "A", "B"],
        "rows": [[2020, 1, 2], [2021, 3, None]],
    }
    [s] = _chart_series(["year", "n"], [[2005, 1], [2008, 4]], "bar")  # gaps are "no data", not zero
    assert s["points"] == [[2005, 1], [2006, None], [2007, None], [2008, 4]]
    with pytest.raises(ValueError, match="at most 4"):
        _chart_series(["x", "s", "y"], [[1, str(i), 1] for i in range(5)], "line")
    with pytest.raises(ValueError, match="numeric"):
        _chart_series(["x", "y"], [[1, "oops"]], "bar")


def test_facets_split_align_and_keep_colors():
    panels = _chart_panels(["state", "year", "n"], [["CA", 2020, 5], ["CA", 2022, 7], ["TX", 2021, 3]], "bar", True)
    assert [p["name"] for p in panels] == ["CA", "TX"]
    assert [pt[0] for pt in panels[1]["series"][0]["points"]] == [2020, 2021, 2022]  # bars line up
    rows = [["CA", 2020, "Pro", 1], ["CA", 2020, "Team", 2], ["TX", 2020, "Team", 3]]
    panels = _chart_panels(["state", "year", "plan", "n"], rows, "line", facet=True)
    assert _legend(panels) == [("Pro", 0), ("Team", 1)]
    assert panels[1]["series"][0]["c"] == 1  # Team keeps its color in every facet
    with pytest.raises(ValueError, match="facets"):
        _chart_panels(["s", "x", "y"], [[str(i), 1, 1] for i in range(17)], "bar", facet=True)
