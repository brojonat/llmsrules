"""Fully-jitted samplers: warmup + sampling + constraining in one XLA program.

Each `make_*` returns `run(key, data) -> Fit`. Everything that changes the
shape of the program (chain count, warmup/draw lengths) is fixed at build
time; everything else (data values, PRNG key) is a traced argument. Calling
`run` again with same-shaped data reuses the compiled executable.
"""

from collections.abc import Callable
from typing import NamedTuple

import blackjax
import jax
import jax.numpy as jnp
import optax
from blackjax.adaptation.base import get_filter_adapt_info_fn
from jax.flatten_util import ravel_pytree

from {{cookiecutter.package_name}}.compile import Data, JaxModel


class Fit(NamedTuple):
    draws: dict[str, jax.Array]  # each leaf: (chains, draws, *shape)
    divergences: jax.Array  # (chains, draws) bool
    grad_evals: jax.Array  # total leapfrog steps across all chains, warmup excluded


type Run = Callable[[jax.Array, Data], Fit]


def _flat(jm: JaxModel):
    """Samplers see one flat vector per chain (ChEES requires it; NUTS doesn't care)."""
    x0, unravel = ravel_pytree(jm.initial_position)
    return x0, lambda x, data: jm.logdensity(unravel(x), data), lambda x, data: jm.constrain(unravel(x), data)


def _dispersed_init(key: jax.Array, x0: jax.Array, num_chains: int) -> jax.Array:
    """PyMC-style jitter: initial point + U(-1, 1) per chain, on the unconstrained space."""
    return x0 + jax.random.uniform(key, (num_chains, x0.size), minval=-1.0, maxval=1.0, dtype=x0.dtype)


def make_nuts(
    jm: JaxModel,
    *,
    num_chains: int,
    num_warmup: int,
    num_draws: int,
    target_accept: float = 0.8,
    vectorized: bool = True,
) -> Run:
    """Stan-style window adaptation + NUTS with independent chains.

    vectorized=True vmaps chains into lockstep: right for GPU, where every lane
    waits for the deepest tree but the batched logp is nearly free. On CPU that
    lockstep is ruinous (XLA runs the batched while-loop on one thread), so
    vectorized=False runs chains back to back with lax.map instead.
    """

    x0, logdensity_fn, constrain = _flat(jm)

    def one_chain(logdensity, key, position):
        k_warm, k_draw = jax.random.split(key)
        warmup = blackjax.window_adaptation(
            blackjax.nuts,
            logdensity,
            target_acceptance_rate=target_accept,
            adaptation_info_fn=get_filter_adapt_info_fn(),
        )
        (state, params), _ = warmup.run(k_warm, position, num_warmup)
        step = blackjax.nuts(logdensity, **params).step

        def body(state, k):
            state, info = step(k, state)
            return state, (state.position, info.is_divergent, info.num_integration_steps)

        _, out = jax.lax.scan(body, state, jax.random.split(k_draw, num_draws))
        return out

    def run(key: jax.Array, data: Data) -> Fit:
        def logdensity(x):
            return logdensity_fn(x, data)

        k_init, k_chains = jax.random.split(key)
        init = _dispersed_init(k_init, x0, num_chains)
        keys = jax.random.split(k_chains, num_chains)
        if vectorized:
            positions, divergent, n_steps = jax.vmap(one_chain, in_axes=(None, 0, 0))(logdensity, keys, init)
        else:
            positions, divergent, n_steps = jax.lax.map(lambda a: one_chain(logdensity, *a), (keys, init))
        constrained = jax.vmap(jax.vmap(lambda x: constrain(x, data)))(positions)
        return Fit(constrained, divergent, n_steps.sum())

    return jax.jit(run)


def make_chees(
    jm: JaxModel,
    *,
    num_chains: int,
    num_warmup: int,
    num_draws: int,
    learning_rate: float = 0.025,
    vectorized: bool = True,  # accepted for a uniform signature; ChEES is always vectorized
) -> Run:
    """ChEES-tuned jittered HMC (Hoffman, Radul & Sountsov 2021).

    Every chain takes the same number of leapfrog steps per iteration, so there
    is no divergent control flow across vmap lanes. Built for many chains
    (64-1024+) and few draws per chain - the GPU-native way to run HMC.
    """
    x0, logdensity_fn, constrain = _flat(jm)

    def run(key: jax.Array, data: Data) -> Fit:
        def logdensity(x):
            return logdensity_fn(x, data)

        k_init, k_warm, k_draw = jax.random.split(key, 3)
        init = _dispersed_init(k_init, x0, num_chains)
        warmup = blackjax.chees_adaptation(
            logdensity,
            num_chains,
            mass_matrix_estimation="diagonal",
            adaptation_info_fn=get_filter_adapt_info_fn(),
        )
        (states, params), _ = warmup.run(
            k_warm, init, step_size=0.1, optim=optax.adam(learning_rate),
            num_steps=num_warmup, max_sampling_steps=num_draws,
        )  # fmt: skip
        step = jax.vmap(blackjax.dhmc(logdensity, **params).step)

        def body(states, k):
            states, info = step(jax.random.split(k, num_chains), states)
            return states, (states.position, info.is_divergent, info.num_integration_steps)

        _, (positions, divergent, n_steps) = jax.lax.scan(body, states, jax.random.split(k_draw, num_draws))
        positions = jnp.swapaxes(positions, 0, 1)  # scan stacks draws first; match NUTS
        constrained = jax.vmap(jax.vmap(lambda x: constrain(x, data)))(positions)
        return Fit(constrained, divergent.T, n_steps.sum())

    return jax.jit(run)


SAMPLERS = {"nuts": make_nuts, "chees": make_chees}
