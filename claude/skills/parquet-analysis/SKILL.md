---
name: parquet-analysis
description: Analyze parquet files using Python and Ibis. Use when the user wants to explore, transform, or analyze parquet data files, perform aggregations, joins, or export results. Works with local parquet files and provides database-agnostic data operations.
---

# Parquet Analysis with Python and Ibis

This skill helps you analyze parquet files using [Ibis](https://ibis-project.org), a database-agnostic Python DataFrame API. Ibis translates Python operations into optimized queries for the underlying backend (DuckDB by default for parquet files).

## Quick Start

### Read and explore a parquet file

```python
import ibis

# Connect to DuckDB backend (best for parquet files)
con = ibis.duckdb.connect()

# Read parquet file
table = con.read_parquet("data.parquet")

# View schema
print(table.schema())

# Preview first rows
print(table.head(10))

# Get summary statistics
print(table.describe())
```

### Basic operations

```python
# Filter rows
filtered = table.filter(table.amount > 1000)

# Select columns
selected = table.select("customer_id", "amount", "date")

# Sort
sorted_data = table.order_by(table.amount.desc())

# Aggregate
summary = table.group_by("category").aggregate(
    total_amount=table.amount.sum(),
    avg_amount=table.amount.mean(),
    count=table.count()
)

# Display results
print(summary.execute())
```

## Common Analysis Patterns

### Data exploration

```python
# Get row count
row_count = table.count().execute()

# Check for nulls
null_counts = table.select([
    col.isnull().sum().name(f"{col}_nulls")
    for col in table.columns
])
print(null_counts.execute())

# Unique values in a column
unique_categories = table.category.nunique().execute()

# Value counts
value_counts = (
    table.group_by("category")
    .aggregate(count=table.count())
    .order_by(ibis.desc("count"))
)
print(value_counts.execute())
```

### Filtering and transformation

```python
# Multiple conditions
filtered = table.filter(
    (table.amount > 100) &
    (table.date >= "2024-01-01") &
    (table.status == "completed")
)

# Add computed columns
enriched = table.mutate(
    amount_usd=table.amount * table.exchange_rate,
    year=table.date.year(),
    month=table.date.month()
)

# Conditional logic
categorized = table.mutate(
    size_category=ibis.case()
        .when(table.amount < 100, "small")
        .when(table.amount < 1000, "medium")
        .else_("large")
        .end()
)
```

### Aggregations

```python
# Group by single column
by_category = (
    table.group_by("category")
    .aggregate(
        total=table.amount.sum(),
        avg=table.amount.mean(),
        min=table.amount.min(),
        max=table.amount.max(),
        count=table.count()
    )
)

# Group by multiple columns
by_date_category = (
    table.group_by(["date", "category"])
    .aggregate(
        total_sales=table.amount.sum(),
        num_transactions=table.count()
    )
)

# Window functions
ranked = table.mutate(
    rank=table.amount.rank().over(
        ibis.window(group_by="category", order_by=table.amount.desc())
    )
)
```

### Joins

```python
# Read multiple parquet files
customers = con.read_parquet("customers.parquet")
orders = con.read_parquet("orders.parquet")

# Inner join
joined = orders.join(
    customers,
    orders.customer_id == customers.id,
    how="inner"
)

# Left join with column selection
result = (
    orders
    .join(customers, orders.customer_id == customers.id, how="left")
    .select(
        orders.order_id,
        orders.amount,
        customers.name,
        customers.email
    )
)
```

### Time series operations

```python
# Date filtering
recent = table.filter(
    table.date >= ibis.date("2024-01-01")
)

# Extract date components
dated = table.mutate(
    year=table.date.year(),
    month=table.date.month(),
    day=table.date.day(),
    day_of_week=table.date.day_of_week.index()
)

# Time-based aggregation
monthly = (
    table.mutate(month=table.date.truncate("M"))
    .group_by("month")
    .aggregate(
        total=table.amount.sum(),
        count=table.count()
    )
    .order_by("month")
)
```

## Writing Results

### To parquet

```python
# Write filtered/transformed data to new parquet file
result = table.filter(table.amount > 1000)
con.to_parquet(result, "output.parquet")
```

### To pandas (for visualization or further processing)

```python
# Convert to pandas DataFrame
df = table.execute()

# Now you can use matplotlib, seaborn, etc.
import matplotlib.pyplot as plt
df.plot(x="date", y="amount", kind="line")
plt.savefig("trend.png")
```

### To CSV

```python
# Via pandas
df = table.execute()
df.to_csv("output.csv", index=False)
```

## Best Practices

1. **Use lazy evaluation**: Ibis operations are lazy - they don't execute until you call `.execute()` or convert to pandas. Chain operations before executing.

2. **Filter early**: Apply filters as early as possible to reduce data volume:
   ```python
   # Good
   result = table.filter(table.date > "2024-01-01").group_by("category").aggregate(total=table.amount.sum())

   # Less efficient
   result = table.group_by("category").aggregate(total=table.amount.sum()).filter(...)
   ```

3. **Use appropriate backends**: DuckDB is excellent for local parquet files and provides fast analytical queries.

4. **Handle nulls explicitly**: Check for and handle null values:
   ```python
   cleaned = table.filter(table.important_column.notnull())
   # or
   filled = table.mutate(important_column=table.important_column.fillna(0))
   ```

5. **Leverage Ibis selectors** for column operations:
   ```python
   import ibis.selectors as s

   # Select all numeric columns
   numeric_cols = table.select(s.numeric())

   # Select columns matching pattern
   amount_cols = table.select(s.matches(".*_amount"))
   ```

## Complete Example Workflow

See [examples/sample-analysis.py](examples/sample-analysis.py) for a complete working example that:
- Reads a parquet file
- Performs data exploration
- Applies filters and transformations
- Creates aggregations
- Joins multiple datasets
- Exports results

## Reference

For detailed API documentation, see:
- [Ibis Table Expressions API](https://ibis-project.org/reference/expression-tables)
- [Ibis Selectors API](https://ibis-project.org/reference/selectors)
- [Ibis Numeric Expressions](https://ibis-project.org/reference/expression-numeric)
- [Ibis String Expressions](https://ibis-project.org/reference/expression-string)
- [Ibis Temporal Expressions](https://ibis-project.org/reference/expression-temporal)

Also see [../../ibis.md](../../ibis.md) for additional context on using Ibis.

## Troubleshooting

**Import error**: Ensure ibis is installed: `uv add "ibis-framework[duckdb]"`

**Large files**: DuckDB handles large parquet files efficiently. If you run into memory issues, process in chunks or use more selective queries.

**Schema mismatches**: When joining, ensure column types match. Use `.cast()` to convert types:
```python
table = table.mutate(id=table.id.cast("int64"))
```

**Performance**: For very large datasets, consider:
- Filtering early and aggressively
- Using DuckDB's native SQL for complex queries: `con.sql("SELECT ... FROM table")`
- Partitioning output parquet files by key columns
