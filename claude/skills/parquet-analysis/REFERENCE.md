# Ibis API Reference for Parquet Analysis

This reference covers the most commonly used Ibis APIs for parquet file analysis. For complete documentation, visit [ibis-project.org](https://ibis-project.org).

## Connection and Data Loading

### Connect to DuckDB

```python
import ibis

# Connect (default in-memory)
con = ibis.duckdb.connect()

# Connect with persistent database
con = ibis.duckdb.connect("my_database.ddb")
```

### Read Parquet Files

```python
# Single file
table = con.read_parquet("data.parquet")

# Multiple files (glob pattern)
table = con.read_parquet("data/*.parquet")

# Specific columns only
table = con.read_parquet("data.parquet", columns=["id", "amount", "date"])
```

## Table Expressions API

[Full documentation](https://ibis-project.org/reference/expression-tables)

### Selection Operations

```python
# Select columns
table.select("col1", "col2", "col3")
table.select(["col1", "col2"])

# Select with rename
table.select(new_name=table.old_name)

# Drop columns
table.drop("col1", "col2")

# Select all except
table.select(~s.matches(".*_temp"))  # Exclude temp columns
```

### Filtering

```python
# Filter rows
table.filter(table.amount > 100)
table.filter((table.a > 100) & (table.b < 50))

# Filter with contains
table.filter(table.name.contains("test"))

# Filter null/not null
table.filter(table.column.notnull())
table.filter(table.column.isnull())
```

### Sorting

```python
# Order by ascending
table.order_by("amount")
table.order_by(table.amount)

# Order by descending
table.order_by(ibis.desc("amount"))
table.order_by(table.amount.desc())

# Multiple columns
table.order_by(["date", ibis.desc("amount")])
```

### Limiting

```python
# First N rows
table.head(10)
table.limit(10)

# Last N rows
table.tail(10)
```

### Grouping and Aggregation

```python
# Group by single column
table.group_by("category").aggregate(total=table.amount.sum())

# Group by multiple columns
table.group_by(["year", "month"]).aggregate(...)

# Multiple aggregations
table.group_by("category").aggregate(
    total=table.amount.sum(),
    avg=table.amount.mean(),
    count=table.count(),
    min_val=table.amount.min(),
    max_val=table.amount.max()
)
```

### Joins

```python
# Inner join
left.join(right, left.id == right.id)
left.join(right, left.id == right.id, how="inner")

# Left join
left.join(right, left.id == right.id, how="left")

# Other join types: "right", "outer", "semi", "anti"
```

### Mutation (Add/Modify Columns)

```python
# Add new columns
table.mutate(
    new_col=table.col1 + table.col2,
    another=table.col3 * 2
)

# Replace existing columns
table.mutate(amount=table.amount * 1.1)
```

### Deduplication

```python
# Drop duplicate rows
table.distinct()

# Keep first occurrence per group
table.group_by("customer_id").order_by(table.date.desc()).head(1)
```

### Schema Operations

```python
# Get schema
table.schema()

# Get column names
table.columns

# Cast column types
table.mutate(id=table.id.cast("int64"))
```

## Generic Expressions API

[Full documentation](https://ibis-project.org/reference/expression-generic)

### Type Casting

```python
# Cast to different types
column.cast("int64")
column.cast("float64")
column.cast("string")
column.cast("date")
column.cast("timestamp")
```

### Null Handling

```python
# Check for nulls
column.isnull()
column.notnull()

# Fill nulls
column.fillna(0)
column.fillna("unknown")

# Coalesce (first non-null)
column.coalesce(other_column, 0)
```

### Conditional Logic

```python
# Simple case
ibis.case()
    .when(condition1, value1)
    .when(condition2, value2)
    .else_(default_value)
    .end()

# If-else shorthand
column.ifelse(condition, true_value, false_value)
```

## Numeric Expressions API

[Full documentation](https://ibis-project.org/reference/expression-numeric)

### Basic Math

```python
# Arithmetic
column + 10
column - 5
column * 2
column / 3
column // 2  # Integer division
column % 3   # Modulo

# Power
column ** 2
column.pow(2)
```

### Rounding

```python
column.round()      # Round to nearest integer
column.round(2)     # Round to 2 decimal places
column.ceil()       # Round up
column.floor()      # Round down
column.truncate()   # Truncate decimals
```

### Math Functions

```python
column.abs()        # Absolute value
column.sqrt()       # Square root
column.exp()        # e^x
column.log()        # Natural log
column.log10()      # Log base 10
column.log2()       # Log base 2
```

### Aggregation Functions

```python
column.sum()        # Sum
column.mean()       # Average
column.min()        # Minimum
column.max()        # Maximum
column.std()        # Standard deviation
column.var()        # Variance
column.median()     # Median
column.quantile(0.95)  # 95th percentile
```

### Comparison

```python
column > 100
column >= 100
column < 100
column <= 100
column == 100
column != 100
column.between(10, 100)  # 10 <= column <= 100
```

## String Expressions API

[Full documentation](https://ibis-project.org/reference/expression-string)

### Case Conversion

```python
column.lower()      # Lowercase
column.upper()      # Uppercase
column.capitalize() # Capitalize first letter
```

### Trimming

```python
column.strip()      # Strip whitespace from both ends
column.lstrip()     # Strip from left
column.rstrip()     # Strip from right
```

### Substring and Slicing

```python
column[0:5]         # First 5 characters
column.substr(0, 5) # Same as above
column.left(5)      # First 5 characters
column.right(5)     # Last 5 characters
```

### Search and Replace

```python
column.contains("text")         # Check if contains
column.startswith("prefix")     # Starts with
column.endswith("suffix")       # Ends with
column.like("%pattern%")        # SQL LIKE pattern
column.replace("old", "new")    # Replace substring
```

### Splitting and Joining

```python
column.split(",")               # Split by delimiter
column.split(",")[0]            # Get first element
```

### Length

```python
column.length()     # String length
```

### Regular Expressions

```python
column.re_search("pattern")     # Search for pattern
column.re_extract("(\\d+)", 0)  # Extract first match
column.re_replace("pattern", "replacement")
```

## Temporal Expressions API

[Full documentation](https://ibis-project.org/reference/expression-temporal)

### Date/Time Extraction

```python
# Extract components
date_column.year()
date_column.month()
date_column.day()
date_column.quarter()
date_column.day_of_week.index()  # 0=Monday
date_column.day_of_year()

# Time components
timestamp_column.hour()
timestamp_column.minute()
timestamp_column.second()
```

### Date Truncation

```python
date_column.truncate("Y")   # Year
date_column.truncate("M")   # Month
date_column.truncate("D")   # Day
date_column.truncate("W")   # Week
timestamp_column.truncate("h")  # Hour
```

### Date Arithmetic

```python
# Add/subtract intervals
date_column + ibis.interval(days=7)
date_column - ibis.interval(months=1)
date_column + ibis.interval(years=1)

# Available units: years, months, weeks, days, hours, minutes, seconds
```

### Date Construction

```python
ibis.date("2024-01-01")
ibis.timestamp("2024-01-01 12:00:00")
```

### Date Formatting

```python
# Format as string
date_column.strftime("%Y-%m-%d")
timestamp_column.strftime("%Y-%m-%d %H:%M:%S")
```

## Selectors API

[Full documentation](https://ibis-project.org/reference/selectors)

### Select by Type

```python
import ibis.selectors as s

# Numeric columns
table.select(s.numeric())

# String columns
table.select(s.string())

# Temporal columns
table.select(s.temporal())

# Boolean columns
table.select(s.boolean())
```

### Select by Pattern

```python
# Columns matching pattern
table.select(s.matches(".*_id"))
table.select(s.matches("amount.*"))

# Columns starting with
table.select(s.startswith("temp_"))

# Columns ending with
table.select(s.endswith("_date"))
```

### Selector Combinations

```python
# AND
table.select(s.numeric() & s.matches(".*_amount"))

# OR
table.select(s.numeric() | s.temporal())

# NOT
table.select(~s.matches(".*_temp"))
```

### Select All Except

```python
# All columns except specific ones
table.select(~s.matches("temp_.*"))

# All except by type
table.select(~s.numeric())
```

## Window Functions

[Full documentation](https://ibis-project.org/reference/expression-window)

### Basic Windows

```python
# Rank
column.rank().over(ibis.window(order_by="amount"))

# Dense rank (no gaps)
column.dense_rank().over(ibis.window(order_by="amount"))

# Row number
column.row_number().over(ibis.window(order_by="date"))
```

### Partitioned Windows

```python
# Rank within groups
column.rank().over(
    ibis.window(
        group_by="category",
        order_by=table.amount.desc()
    )
)
```

### Aggregate Windows

```python
# Running total
column.sum().over(
    ibis.window(order_by="date", rows=(None, 0))
)

# Moving average (last 7 rows)
column.mean().over(
    ibis.window(order_by="date", rows=(-6, 0))
)

# Cumulative max
column.max().over(
    ibis.window(order_by="date", rows=(None, 0))
)
```

### Lead and Lag

```python
# Next value
column.lead(1).over(ibis.window(order_by="date"))

# Previous value
column.lag(1).over(ibis.window(order_by="date"))

# With default for NULL
column.lag(1, default=0).over(ibis.window(order_by="date"))
```

## Execution and Output

### Execute Queries

```python
# Execute and return pandas DataFrame
df = table.execute()

# Execute count
count = table.count().execute()

# Execute aggregate
result = table.aggregate(total=table.amount.sum()).execute()
```

### Export Data

```python
# To parquet
con.to_parquet(table, "output.parquet")

# To CSV (via pandas)
df = table.execute()
df.to_csv("output.csv", index=False)
```

### Show SQL

```python
# See generated SQL
print(ibis.to_sql(table))
```

## Common Patterns

### Deduplication

```python
# Keep most recent per group
table.group_by("customer_id").order_by(table.date.desc()).head(1)

# Keep first occurrence
table.distinct()
```

### Pivoting (Manual)

```python
# Create columns for each category value
table.group_by("date").aggregate([
    table.amount.sum().filter(table.category == "A").name("category_a"),
    table.amount.sum().filter(table.category == "B").name("category_b")
])
```

### Binning

```python
# Age groups
table.mutate(
    age_group=ibis.case()
        .when(table.age < 18, "0-17")
        .when(table.age < 35, "18-34")
        .when(table.age < 50, "35-49")
        .else_("50+")
        .end()
)
```

### Percentiles

```python
# 95th percentile by group
table.group_by("category").aggregate(
    p95=table.amount.quantile(0.95)
)
```

For additional context on using Ibis, see [../../ibis.md](../../ibis.md).
