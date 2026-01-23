# Parquet Analysis Examples

This file contains detailed examples for common parquet analysis tasks.

## Complete Analysis Workflow

See [scripts/analyze.py](scripts/analyze.py) for a complete working example that demonstrates:
1. Loading and exploring parquet files
2. Data quality checks (nulls, value counts)
3. Transformations and enrichment
4. Aggregations (monthly sales, category performance)
5. Filtering strategies
6. Join patterns
7. Multiple export formats (parquet, CSV)
8. Optional visualization with matplotlib

To run the complete example:

```bash
python scripts/analyze.py
```

## Data Exploration Examples

### Basic exploration

```python
import ibis

con = ibis.duckdb.connect()
table = con.read_parquet("data.parquet")

# View schema
print(table.schema())

# Preview data
print(table.head(10).execute())

# Summary statistics
print(table.describe().execute())

# Count rows
row_count = table.count().execute()
print(f"Total rows: {row_count}")
```

### Check data quality

```python
# Check for nulls
null_counts = table.select([
    col.isnull().sum().name(f"{col}_nulls")
    for col in table.columns
])
print(null_counts.execute())

# Value counts for categorical
category_counts = (
    table.group_by("category")
    .aggregate(count=table.count())
    .order_by(ibis.desc("count"))
)
print(category_counts.execute())

# Find unique values
unique_categories = table.category.nunique().execute()
print(f"Unique categories: {unique_categories}")
```

## Filtering Examples

### Simple filters

```python
# Single condition
high_value = table.filter(table.amount > 1000)

# Multiple conditions with AND
filtered = table.filter(
    (table.amount > 100) &
    (table.date >= "2024-01-01") &
    (table.status == "completed")
)

# Multiple conditions with OR
recent_or_large = table.filter(
    (table.date >= "2024-01-01") |
    (table.amount > 5000)
)

# String matching
tech_products = table.filter(table.category.like("%tech%"))

# NULL checks
valid_records = table.filter(table.email.notnull())
```

### Date-based filtering

```python
# Recent data (last 90 days)
max_date = table.date.max().execute()
recent_cutoff = max_date - ibis.interval(days=90)
recent = table.filter(table.date >= recent_cutoff)

# Specific date range
q1_2024 = table.filter(
    (table.date >= "2024-01-01") &
    (table.date < "2024-04-01")
)

# By year
year_2024 = table.filter(table.date.year() == 2024)
```

## Transformation Examples

### Add computed columns

```python
# Simple calculations
enriched = table.mutate(
    revenue=table.quantity * table.unit_price,
    profit=table.revenue - table.cost
)

# Extract date components
dated = table.mutate(
    year=table.date.year(),
    month=table.date.month(),
    quarter=table.date.quarter(),
    day_of_week=table.date.day_of_week.index()
)

# String operations
cleaned = table.mutate(
    email_lower=table.email.lower(),
    domain=table.email.split("@")[1]
)
```

### Conditional logic

```python
# Simple if/else
categorized = table.mutate(
    size=ibis.case()
        .when(table.amount < 100, "small")
        .when(table.amount < 1000, "medium")
        .else_("large")
        .end()
)

# Multiple conditions
classified = table.mutate(
    segment=ibis.case()
        .when(
            (table.revenue > 10000) & (table.frequency > 10),
            "vip"
        )
        .when(
            (table.revenue > 5000) & (table.frequency > 5),
            "premium"
        )
        .when(table.revenue > 1000, "regular")
        .else_("basic")
        .end()
)
```

## Aggregation Examples

### Basic aggregations

```python
# Overall statistics
summary = table.aggregate(
    total_revenue=table.amount.sum(),
    avg_amount=table.amount.mean(),
    min_amount=table.amount.min(),
    max_amount=table.amount.max(),
    count=table.count()
)
print(summary.execute())
```

### Group by single column

```python
by_category = (
    table.group_by("category")
    .aggregate(
        total=table.amount.sum(),
        avg=table.amount.mean(),
        count=table.count()
    )
    .order_by(ibis.desc("total"))
)
print(by_category.execute())
```

### Group by multiple columns

```python
# By date and category
daily_category = (
    table.group_by(["date", "category"])
    .aggregate(
        total_sales=table.amount.sum(),
        num_orders=table.count()
    )
    .order_by(["date", "category"])
)
print(daily_category.execute())
```

### Time-based aggregations

```python
# Monthly aggregation
monthly = (
    table.mutate(month=table.date.truncate("M"))
    .group_by("month")
    .aggregate(
        total=table.amount.sum(),
        count=table.count()
    )
    .order_by("month")
)
print(monthly.execute())

# Quarterly aggregation
quarterly = (
    table.mutate(
        year=table.date.year(),
        quarter=table.date.quarter()
    )
    .group_by(["year", "quarter"])
    .aggregate(total=table.amount.sum())
    .order_by(["year", "quarter"])
)
print(quarterly.execute())
```

### Window functions

```python
# Rank within groups
ranked = table.mutate(
    rank=table.amount.rank().over(
        ibis.window(
            group_by="category",
            order_by=table.amount.desc()
        )
    )
)

# Running totals
with_running_total = table.mutate(
    cumulative=table.amount.sum().over(
        ibis.window(
            order_by="date",
            rows=(None, 0)  # All preceding rows to current
        )
    )
)

# Moving average
with_ma = table.mutate(
    ma_7day=table.amount.mean().over(
        ibis.window(
            order_by="date",
            rows=(-6, 0)  # Last 7 days including current
        )
    )
)
```

## Join Examples

### Basic joins

```python
# Read multiple files
customers = con.read_parquet("customers.parquet")
orders = con.read_parquet("orders.parquet")

# Inner join
joined = orders.join(
    customers,
    orders.customer_id == customers.id,
    how="inner"
)

# Left join
all_orders = orders.join(
    customers,
    orders.customer_id == customers.id,
    how="left"
)

# Select specific columns after join
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

### Multiple joins

```python
# Chain multiple joins
products = con.read_parquet("products.parquet")

full_data = (
    orders
    .join(customers, orders.customer_id == customers.id)
    .join(products, orders.product_id == products.id)
    .select(
        orders.order_id,
        orders.date,
        customers.name.name("customer_name"),
        products.name.name("product_name"),
        orders.quantity,
        orders.amount
    )
)
```

## Export Examples

### Export to parquet

```python
# Write filtered/transformed data
result = table.filter(table.amount > 1000)
con.to_parquet(result, "output.parquet")

# Write with compression
con.to_parquet(
    result,
    "output.parquet",
    compression="snappy"  # or "gzip", "zstd"
)
```

### Export to CSV

```python
# Via pandas
df = table.execute()
df.to_csv("output.csv", index=False)

# With specific options
df.to_csv(
    "output.csv",
    index=False,
    sep="|",
    quoting=1  # QUOTE_ALL
)
```

### Export multiple results

```python
from pathlib import Path

output_dir = Path("outputs")
output_dir.mkdir(exist_ok=True)

# Summary by category
by_category = table.group_by("category").aggregate(
    total=table.amount.sum()
)
con.to_parquet(by_category, str(output_dir / "by_category.parquet"))

# Monthly trends
monthly = table.mutate(month=table.date.truncate("M")).group_by("month").aggregate(
    total=table.amount.sum()
)
con.to_parquet(monthly, str(output_dir / "monthly.parquet"))

# Top customers
top_customers = (
    table.group_by("customer_id")
    .aggregate(total=table.amount.sum())
    .order_by(ibis.desc("total"))
    .head(100)
)
con.to_parquet(top_customers, str(output_dir / "top_customers.parquet"))
```

## Visualization Examples

```python
import matplotlib.pyplot as plt

# Monthly trend line chart
monthly_df = monthly.execute()
plt.figure(figsize=(12, 6))
plt.plot(monthly_df["month"], monthly_df["total"], marker="o")
plt.xlabel("Month")
plt.ylabel("Total Revenue")
plt.title("Monthly Revenue Trend")
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig("monthly_trend.png")

# Category bar chart
category_df = by_category.execute()
plt.figure(figsize=(10, 6))
plt.barh(category_df["category"], category_df["total"])
plt.xlabel("Total Revenue")
plt.ylabel("Category")
plt.title("Revenue by Category")
plt.tight_layout()
plt.savefig("category_performance.png")
```

## Quick-Start Template

For a customizable template, see [scripts/template.py](scripts/template.py). Copy and modify it for your specific use case:

```bash
cp scripts/template.py my_analysis.py
# Edit my_analysis.py with your file paths and logic
python my_analysis.py
```
