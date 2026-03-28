---
name: ibis-data
description: Use Ibis for database-agnostic data access in Python. Use when writing data queries, connecting to databases (DuckDB, PostgreSQL, SQLite), or building portable data pipelines that should work across backends.
---

# Ibis Data Interface

[Ibis](https://ibis-project.org) provides a database-agnostic Python DataFrame API. Write queries once in Python; Ibis translates them to optimized SQL for the connected backend (DuckDB, PostgreSQL, SQLite, etc.).

## Why Ibis

- **Portability**: Develop with DuckDB, deploy against PostgreSQL -- change only the connection
- **Lazy evaluation**: Operations build an expression tree; nothing executes until `.execute()`
- **Full SQL power**: Window functions, CTEs, joins, aggregations -- all through Python
- **No ORM**: You get SQL performance without SQL strings

## Connecting

```python
import ibis

# DuckDB (default for local/parquet work)
con = ibis.duckdb.connect()
con = ibis.duckdb.connect("my.duckdb")

# PostgreSQL
con = ibis.postgres.connect(host="localhost", database="mydb", user="user", password="pass")

# SQLite
con = ibis.sqlite.connect("my.sqlite")

# Read files directly
table = con.read_parquet("data.parquet")
table = con.read_csv("data.csv")
```

## Core Operations

```python
# Explore
table.schema()          # column names and types
table.head(10)          # preview rows
table.describe()        # summary statistics
table.count().execute() # row count

# Select and filter
selected = table.select("id", "amount", "date")
filtered = table.filter((table.amount > 100) & (table.date >= "2024-01-01"))
sorted_data = table.order_by(table.amount.desc())

# Transform
enriched = table.mutate(
    revenue=table.quantity * table.unit_price,
    year=table.date.year(),
    size=ibis.case()
        .when(table.amount < 100, "small")
        .when(table.amount < 1000, "medium")
        .else_("large")
        .end()
)

# Aggregate
summary = (
    table.group_by("category")
    .aggregate(
        total=table.amount.sum(),
        avg=table.amount.mean(),
        count=table.count()
    )
)

# Join
joined = (
    orders
    .join(customers, orders.customer_id == customers.id, how="left")
    .select(orders.order_id, orders.amount, customers.name)
)

# Window functions
ranked = table.mutate(
    rank=table.amount.rank().over(
        ibis.window(group_by="category", order_by=table.amount.desc())
    )
)

# Execute and export
df = summary.execute()              # -> pandas DataFrame
con.to_parquet(summary, "out.parquet")
df.to_csv("out.csv", index=False)
```

## API Reference

| API | What it covers |
| --- | --- |
| [Table expressions](https://ibis-project.org/reference/expression-tables) | `select`, `filter`, `mutate`, `group_by`, `agg`, `join`, `order_by` |
| [Selectors](https://ibis-project.org/reference/selectors) | Choose columns by name, type, or regex |
| [Generic expressions](https://ibis-project.org/reference/expression-generic) | `.cast()`, `.isnull()`, `.fillna()`, `case()`, `.ifelse()` |
| [Numeric expressions](https://ibis-project.org/reference/expression-numeric) | `sum()`, `mean()`, `std()`, rounding, logarithms |
| [String expressions](https://ibis-project.org/reference/expression-string) | Slicing, regex, case conversion, stripping |
| [Temporal expressions](https://ibis-project.org/reference/expression-temporal) | `.year()`, `.month()`, interval arithmetic, formatting |
| [Collection expressions](https://ibis-project.org/reference/expression-collection) | Array/map operations, unnesting |
| [JSON expressions](https://ibis-project.org/reference/expression-json) | Path-based extraction from JSON columns |

## Best Practices

- **Filter early**: Reduce data volume before aggregations
- **Stay lazy**: Chain operations before calling `.execute()`
- **Use selectors**: Apply operations to multiple columns programmatically
- **Handle nulls**: Check with `.isnull()` and handle with `.fillna()` explicitly
- **Check SQL**: Use `ibis.to_sql(expr)` to inspect generated queries

## Installation

```bash
uv add "ibis-framework[duckdb]"        # DuckDB backend
uv add "ibis-framework[postgres]"      # PostgreSQL backend
```
