---
name: marimo-notebook
description: Author marimo notebooks with conventions for interactive scatter exploration. Use when creating a new marimo notebook, choosing how to run marimo locally, or wiring up jscatter scatter plots with lasso selection feeding a table below the plot.
---

# marimo Notebook

[marimo](https://marimo.io) is a reactive Python notebook — cells form a
dataflow graph, and changing one cell automatically re-runs its dependents.
This skill encodes conventions for how to **run marimo** and how to build a
canonical **scatter-plot-with-selected-rows-table** exploration UI.

## Running marimo

Run marimo listening on all interfaces, with no token, in sandbox mode:

```bash
marimo edit --host 0.0.0.0 --no-token --sandbox notebook.py
# view-only (app mode):
marimo run  --host 0.0.0.0 --no-token --sandbox notebook.py
```

Why each flag:

| Flag | Purpose |
| --- | --- |
| `--host 0.0.0.0` | Bind to every interface so a phone, tablet, or another laptop on the LAN can hit `http://<host-ip>:<port>`. `127.0.0.1` (the default) only reaches localhost. |
| `--no-token` | Skip the URL token, so the link is paste-able. Also: servers started with `--no-token` register in marimo's local server registry, which is what tooling like `marimo-pair` relies on to auto-discover sessions. |
| `--sandbox` | Run the notebook in an isolated uv-managed venv driven by inline `# /// script` dependency metadata at the top of the `.py` file. Keeps per-notebook deps out of the system/project env. |

Use `--no-token` only on trusted networks (home LAN, local dev). On anything
shared, leave the token on and use `MARIMO_TOKEN` to pass it to tooling.

### Inline dependencies for sandbox mode

With `--sandbox`, put PEP 723 script metadata at the top of the notebook so
uv knows what to install:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "polars",
#     "jupyter-scatter",
#     "pandas",
# ]
# ///

import marimo
app = marimo.App()
```

Edit this block when you add imports — sandbox mode will refuse to import
anything that isn't declared here.

## Scatter plots: always use jscatter

Default to [jupyter-scatter](https://jupyter-scatter.dev) (`import jscatter`)
for scatter plots. It's GPU-accelerated, handles millions of points, has a
built-in lasso selection tool, and bridges cleanly into marimo's reactive
graph through traitlets. Reach for matplotlib / plotly / altair only for
small, non-interactive cases.

### Long-press activates the lasso

Explicitly enable long-press as the lasso initiator:

```python
scatter.lasso(on_long_press=True)
```

`on_long_press=True` is actually jupyter-scatter's default, but **set it
explicitly** — the keyboard-modifier initiator (shift+drag) is unreliable on
some machines/keyboards/OSes, so readers of the notebook should be able to
see at a glance that long-press is the supported gesture and not have to
guess at a keyboard shortcut.

### Always show a table of the selected rows below the plot

Bridge the jscatter widget's `selection` trait into marimo's reactive graph
with `mo.state` + `.observe(...)`, then render a `mo.ui.table` in the next
cell that filters the dataframe by the current selection. The table updates
live as the user lassos.

```python
@app.cell
def _(df, mo):
    import jscatter

    # jupyter-scatter wants pandas
    pdf = df.to_pandas() if hasattr(df, "to_pandas") else df

    scatter = (
        jscatter.Scatter(x="x", y="y", data=pdf)
        .height(500)
        .color(by="category")
        .legend(True)
        .tooltip(True)
    )
    scatter.lasso(on_long_press=True)

    # bridge jscatter's `selection` traitlet into marimo's reactive graph
    get_selection, set_selection = mo.state(scatter.widget.selection)
    scatter.widget.observe(
        lambda _: set_selection(scatter.widget.selection),
        names=["selection"],
    )
    scatter.widget
    return get_selection, pdf
```

```python
@app.cell
def _(get_selection, mo, pdf):
    sel = get_selection()
    mo.ui.table(
        pdf.iloc[sel] if len(sel) else pdf.head(0),
        page_size=25,
    )
    return
```

Notes:

- **Use `scatter.widget`, not `scatter`, for the observe/display.** `Scatter`
  is a configuration object; `scatter.widget` is the anywidget instance that
  owns the `selection` traitlet.
- **Return `get_selection` (the getter), not the state value.** Returning
  the scalar freezes the downstream cell at construction time; returning
  the getter lets the downstream cell re-read on every reactive tick.
- **Empty-selection handling:** show `pdf.head(0)` (empty frame with
  headers) rather than the full table when nothing is selected — the point
  of the table is to reflect the lasso, not to be a second data browser.
- **`mo.ui.table` vs `quak.Widget`:** `mo.ui.table` is the default. Reach
  for `mo.ui.anywidget(quak.Widget(df))` when you want SQL-style filtering,
  faceting, and column stats inside the table itself.

## Notebook skeleton

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo", "polars", "jupyter-scatter", "pandas"]
# ///

import marimo
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import polars as pl
    return mo, pl


@app.cell
def _(pl):
    df = pl.read_parquet("data.parquet")
    return (df,)


# ... scatter cell + selected-rows table cell from above ...


if __name__ == "__main__":
    app.run()
```

## Gotchas

- **Don't edit the `.py` file while `marimo edit` is running on it.** The
  kernel owns the file; writes from the outside will be clobbered or ignored.
  Use the marimo UI, or stop the server first.
- **Sandbox mode is per-notebook.** Each `--sandbox` invocation resolves its
  own venv from the inline script metadata. Don't try to share a venv across
  notebooks via `--sandbox`; just run them with the project's regular env.
- **`--no-token` leaks your notebook to the LAN.** On coffee-shop wifi or a
  shared office network, either drop `--host 0.0.0.0` or keep the token.
- **Widget traitlets live outside the reactive graph.** Setting
  `scatter.widget.selection = [...]` directly from Python works, but won't
  flow into marimo state unless you've wired an `.observe(...)` bridge like
  the one above.
