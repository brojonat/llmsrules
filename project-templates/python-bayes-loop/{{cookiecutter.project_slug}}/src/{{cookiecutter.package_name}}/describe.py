"""A plain-English description of a model, written by an LLM from its diagram.

The web server calls this once per model (the sampler stores the model's
DOT, PyMC spec and domain context in `models`), streams the text into the
page as it arrives, and keeps the result in `model_notes` so reloads and
other browsers don't pay for it again. The LLM is whatever llm.LLMConfig
points at (OpenRouter + Claude Haiku 4.5 by default).
"""

import logging
from collections.abc import AsyncIterator

import httpx

from {{cookiecutter.package_name}}.llm import Delta, LLMConfig, Usage, stream_chat

log = logging.getLogger(__name__)

SYSTEM = """\
You explain Bayesian models to engineers who know some statistics but not \
this model. You are given a PyMC model's specification, its graph, the labels \
along each dimension, and a note from the model's author about the data.

Write two short paragraphs of plain text, at most 150 words in all:
1. What the data is and what question the model answers about it.
2. How the parts fit together, naming each variable exactly as it appears in \
the graph (mu, sigma, z, ...) so the reader can find it in the diagram, and \
what sharing information across the groups buys.

No Markdown, headings, lists or equations. Use the real labels (a city name, \
a feature name) when an example helps."""


class NoCredentials(Exception):
    """No LLM API key configured: nothing to describe with."""


def prompt(model: dict) -> str:
    """The user turn: everything the sampler recorded about the model."""
    return (
        f"Author's note about the data:\n{model['context']}\n\n"
        f"PyMC specification (model.str_repr()):\n{model['spec']}\n\n"
        f"Dimensions and their labels (JSON):\n{model['coords']}\n\n"
        f"Observations per fit: {model['n']}\n\n"
        f"Graph (pm.model_to_graphviz, DOT):\n{model['dot']}"
    )


async def describe(http: httpx.AsyncClient, cfg: LLMConfig, model: dict) -> AsyncIterator[str]:
    """Yield the description's text as it streams in. Raises llm.LLMError on provider errors."""
    if not cfg.configured:
        raise NoCredentials("no LLM_API_KEY or OPENROUTER_API_KEY")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(model)}]
    async for event in stream_chat(http, cfg, messages):
        if isinstance(event, Delta):
            yield event.text
        elif isinstance(event, Usage):
            log.info("described the model: %d+%d tokens, $%s", event.prompt_tokens, event.completion_tokens, event.cost)
