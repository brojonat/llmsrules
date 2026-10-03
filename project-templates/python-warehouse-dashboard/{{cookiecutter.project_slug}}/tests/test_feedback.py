import json

from click.testing import CliRunner

from {{cookiecutter.package_name}}.appdb import AppDB
from {{cookiecutter.package_name}}.cli import main

from .test_chat import FakeLLM, J, ToolLLM, drive, wait_for


def test_migrations_run_once(tmp_path):
    db = AppDB(tmp_path / "a.sqlite")
    assert db.version == 2
    db.add_feedback(kind="rating", session="s", rating=2)
    db.close()
    again = AppDB(tmp_path / "a.sqlite")
    assert again.version == 2 and len(again.feedback()) == 1


def test_checkin_rates_then_takes_an_optional_note(warehouse, tmp_path):
    path = tmp_path / "app.sqlite"
    with drive(warehouse, FakeLLM(), app_db=path) as c:
        c.get("/")
        c.post("/filter/toggle", json={"dim": "products", "value": "Ledger"}, headers=J)
        c.post("/chat/send", json={"message": "hi"}, headers=J)
        wait_for(c, "<strong>mean</strong>")
        assert "How is the assistant doing?" not in c.get("/").text  # not after one answer
        assert c.post("/chat/feedback", json={"action": "open"}, headers=J).status_code == 204  # the button
        assert "How is the assistant doing?" in c.get("/").text
        assert c.post("/chat/feedback", json={"action": "rate", "rating": 9}, headers=J).status_code == 400
        c.post("/chat/feedback", json={"action": "rate", "rating": 3}, headers=J)
        assert "Anything to add?" in c.get("/").text
        c.post("/chat/feedback", json={"action": "comment", "text": "clear answer"}, headers=J)
        assert "Thanks for the feedback." in c.get("/").text
    [f] = AppDB(path).feedback()
    assert (f.kind, f.rating, f.comment) == ("rating", 3, "clear answer")
    assert f.dataset["products"] == ["Ledger"] and f.transcript[0] == {"role": "user", "content": "hi"}
    assert len(f.session) == 16  # a hash, not the cookie


def test_checkin_appears_after_three_answers_once(warehouse, tmp_path):
    with drive(warehouse, FakeLLM(), app_db=tmp_path / "app.sqlite") as c:
        c.get("/")
        for i in range(3):
            c.post("/chat/send", json={"message": f"q{i}"}, headers=J)
            wait_for(c, f"q{i}")
        page = wait_for(c, "How is the assistant doing?")
        assert "<kbd>1</kbd> Bad" in page
        c.post("/chat/feedback", json={"action": "dismiss"}, headers=J)
        c.post("/chat/send", json={"message": "q3"}, headers=J)
        assert "How is the assistant doing?" not in wait_for(c, "q3")


def test_assistant_drafts_and_only_the_user_sends(warehouse, tmp_path):
    path = tmp_path / "app.sqlite"
    args = json.dumps({"category": "data_quality", "summary": "Texas escalations look high",
                       "details": "I expected fewer."})  # fmt: skip
    fake = ToolLLM(args, tool="submit_feedback")
    with drive(warehouse, fake, app_db=path) as c:
        c.get("/")
        c.post("/chat/send", json={"message": "that number is wrong, tell them"}, headers=J)
        page = wait_for(c, "Done:")
        assert "Texas escalations look high" in page and ">Send</button>" in page
        assert AppDB(path).feedback() == []  # a draft is not a submission
        assert "NOT been sent" in json.loads(fake.requests[1]["messages"][-1]["content"])["status"]
        assert c.post("/chat/feedback/draft", json={"call_id": "nope", "action": "send"}).status_code == 404
        c.post("/chat/feedback/draft", json={"call_id": "call_1", "action": "send"}, headers=J)
        c.post("/chat/feedback/draft", json={"call_id": "call_1", "action": "send"}, headers=J)  # double click
        assert "✓ Sent. Thank you." in c.get("/").text
    [f] = AppDB(path).feedback()
    assert (f.kind, f.category, f.summary, f.comment) == ("report", "data_quality", "Texas escalations look high",
                                                          "I expected fewer.")  # fmt: skip


def test_discarded_drafts_store_nothing(warehouse, tmp_path):
    path = tmp_path / "app.sqlite"
    fake = ToolLLM(json.dumps({"category": "praise", "summary": "nice", "details": "nice"}), tool="submit_feedback")
    with drive(warehouse, fake, app_db=path) as c:
        c.get("/")
        c.post("/chat/send", json={"message": "tell them it's nice"}, headers=J)
        wait_for(c, "Done:")
        c.post("/chat/feedback/draft", json={"call_id": "call_1", "action": "discard"}, headers=J)
        assert "Discarded." in c.get("/").text
    assert AppDB(path).feedback() == []


def test_cli_lists_feedback_and_usage(tmp_path):
    db = AppDB(tmp_path / "app.sqlite")
    db.add_feedback(kind="rating", session="s", rating=1, transcript=[{"role": "user", "content": "x"}])
    db.add_usage("m", 100, 20, 50, 0.01)
    out = CliRunner().invoke(main, ["feedback", "--db", str(tmp_path / "app.sqlite")])
    row = json.loads(out.output)
    assert out.exit_code == 0 and row["rating"] == 1 and row["transcript"] == 1
    out = CliRunner().invoke(main, ["usage", "--db", str(tmp_path / "app.sqlite")])
    assert json.loads(out.output)["tokens"] == 120
