import asyncio

import pytest

from {{cookiecutter.package_name}}.describe import NoCredentials, describe
from {{cookiecutter.package_name}}.llm import LLMConfig, LLMError

from tests.fakes import fake_llm

MODEL = {
    "context": "Each row is one customer in one city.",
    "spec": "mu ~ Normal(0, 1)",
    "coords": '{"group": ["Austin", "Boston"], "feature": ["age"]}',
    "n": 2000,
    "dot": "digraph { mu -> beta }",
}


def collect(http, cfg) -> str:
    async def go():
        return "".join([t async for t in describe(http, cfg, MODEL)])

    return asyncio.run(go())


def test_streams_text_and_sends_everything_the_sampler_recorded():
    http, cfg, seen = fake_llm(["Customers ", "in cities."])
    assert collect(http, cfg) == "Customers in cities."
    payload = seen[0]
    assert payload["model"] == "fake/model" and payload["stream"] is True
    system, user = payload["messages"]
    assert system["role"] == "system" and "plain text" in system["content"]
    for part in ("one customer in one city", "mu ~ Normal(0, 1)", "Austin", "2000", "mu -> beta"):
        assert part in user["content"]


def test_provider_errors_carry_the_providers_message():
    http, cfg, _ = fake_llm([], status=401)
    with pytest.raises(LLMError, match="401: No auth credentials found"):
        collect(http, cfg)


def test_no_key_never_calls_out():
    http, _, seen = fake_llm(["unused"])
    with pytest.raises(NoCredentials):
        collect(http, LLMConfig(api_key=""))
    assert seen == []


def test_config_reads_nhtsa_env_names(monkeypatch):
    for var in ("LLM_API_KEY", "OPENAI_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    cfg = LLMConfig.from_env()
    assert cfg.api_key == "or-key" and cfg.model == "anthropic/claude-haiku-4.5"
    assert cfg.base_url == "https://openrouter.ai/api/v1"
