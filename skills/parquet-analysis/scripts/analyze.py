#!/usr/bin/env python3
"""
Sample parquet analysis workflow using Ibis

This example demonstrates a complete data analysis workflow:
1. Read parquet files
2. Explore data structure and quality
3. Transform and enrich data
4. Aggregate and summarize
5. Join multiple datasets
6. Export results
"""

import ibis
from pathlib import Path

# Connect to DuckDB (optimized for parquet)
con = ibis.duckdb.connect()

# ============================================================================
# Step 1: Read and explore data
# ============================================================================

print("=" * 80)
print("STEP 1: Load and explore data")
print("=" * 80)

# Read parquet file (replace with your actual file)
sales = con.read_parquet("sales.parquet")

# View schema
print("\nSchema:")
print(sales.schema())

# Preview data
print("\nFirst 10 rows:")
print(sales.head(10).execute())

# Basic statistics
print("\nSummary statistics:")
print(sales.describe().execute())

# ============================================================================
# Step 2: Data quality checks
# ============================================================================

print("\n" + "=" * 80)
print("STEP 2: Data quality checks")
print("=" * 80)

# Count rows
row_count = sales.count().execute()
print(f"\nTotal rows: {row_count}")

# Check for nulls
print("\nNull counts by column:")
null_counts = sales.select([
    col.isnull().sum().name(f"{col}_nulls")
    for col in sales.columns
])
print(null_counts.execute())

# Value counts for categorical column
print("\nProduct category distribution:")
category_counts = (
    sales.group_by("category")
    .aggregate(count=sales.count())
    .order_by(ibis.desc("count"))
)
print(category_counts.execute())

# ============================================================================
# Step 3: Transform and enrich
# ============================================================================

print("\n" + "=" * 80)
print("STEP 3: Transform and enrich data")
print("=" * 80)

# Add computed columns
enriched = sales.mutate(
    # Extract date components
    year=sales.sale_date.year(),
    month=sales.sale_date.month(),
    quarter=sales.sale_date.quarter(),

    # Calculate revenue
    revenue=sales.quantity * sales.unit_price,

    # Categorize by size
    order_size=ibis.case()
        .when(sales.quantity < 10, "small")
        .when(sales.quantity < 100, "medium")
        .else_("large")
        .end()
)

print("\nEnriched data sample:")
print(enriched.head(5).execute())

# ============================================================================
# Step 4: Aggregate and summarize
# ============================================================================

print("\n" + "=" * 80)
print("STEP 4: Aggregations")
print("=" * 80)

# Monthly sales summary
monthly_sales = (
    enriched
    .group_by(["year", "month"])
    .aggregate(
        total_revenue=enriched.revenue.sum(),
        total_quantity=enriched.quantity.sum(),
        num_orders=enriched.count(),
        avg_order_value=enriched.revenue.mean()
    )
    .order_by(["year", "month"])
)

print("\nMonthly sales:")
print(monthly_sales.execute())

# Category performance
category_performance = (
    enriched
    .group_by("category")
    .aggregate(
        total_revenue=enriched.revenue.sum(),
        avg_quantity=enriched.quantity.mean(),
        num_orders=enriched.count()
    )
    .order_by(ibis.desc("total_revenue"))
)

print("\nCategory performance:")
print(category_performance.execute())

# ============================================================================
# Step 5: Filtering
# ============================================================================

print("\n" + "=" * 80)
print("STEP 5: Filtered analysis")
print("=" * 80)

# High value orders (revenue > $1000)
high_value = enriched.filter(enriched.revenue > 1000)

print(f"\nHigh value orders: {high_value.count().execute()}")
print("\nTop 5 high value orders:")
print(
    high_value
    .order_by(ibis.desc("revenue"))
    .head(5)
    .execute()
)

# Recent sales (last 90 days from max date)
max_date = sales.sale_date.max().execute()
recent_cutoff = max_date - ibis.interval(days=90)
recent_sales = sales.filter(sales.sale_date >= recent_cutoff)

print(f"\nRecent sales (last 90 days): {recent_sales.count().execute()}")

# ============================================================================
# Step 6: Joins (if you have multiple parquet files)
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: Joins (example)")
print("=" * 80)

# Example: Join sales with customer data
# customers = con.read_parquet("customers.parquet")
#
# joined = (
#     sales
#     .join(customers, sales.customer_id == customers.id, how="left")
#     .select(
#         sales.order_id,
#         sales.sale_date,
#         sales.revenue,
#         customers.name.name("customer_name"),
#         customers.segment
#     )
# )
#
# print("\nJoined data sample:")
# print(joined.head(5).execute())

print("\n(Skipping join example - would need customers.parquet)")

# ============================================================================
# Step 7: Export results
# ============================================================================

print("\n" + "=" * 80)
print("STEP 7: Export results")
print("=" * 80)

# Create output directory
output_dir = Path("outputs")
output_dir.mkdir(exist_ok=True)

# Export enriched data to parquet
enriched_path = output_dir / "enriched_sales.parquet"
con.to_parquet(enriched, str(enriched_path))
print(f"\nEnriched data saved to: {enriched_path}")

# Export monthly summary to parquet
monthly_path = output_dir / "monthly_summary.parquet"
con.to_parquet(monthly_sales, str(monthly_path))
print(f"Monthly summary saved to: {monthly_path}")

# Export category performance to CSV (via pandas)
category_df = category_performance.execute()
csv_path = output_dir / "category_performance.csv"
category_df.to_csv(csv_path, index=False)
print(f"Category performance saved to: {csv_path}")

# ============================================================================
# Step 8: Visualization (optional)
# ============================================================================

print("\n" + "=" * 80)
print("STEP 8: Visualization (optional)")
print("=" * 80)

try:
    import matplotlib.pyplot as plt

    # Monthly revenue trend
    monthly_df = monthly_sales.execute()
    monthly_df["month_label"] = monthly_df["year"].astype(str) + "-" + monthly_df["month"].astype(str).str.zfill(2)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Revenue trend
    ax1.plot(monthly_df["month_label"], monthly_df["total_revenue"], marker="o")
    ax1.set_xlabel("Month")
    ax1.set_ylabel("Revenue")
    ax1.set_title("Monthly Revenue Trend")
    ax1.tick_params(axis='x', rotation=45)

    # Category performance
    category_df = category_performance.execute()
    ax2.barh(category_df["category"], category_df["total_revenue"])
    ax2.set_xlabel("Total Revenue")
    ax2.set_ylabel("Category")
    ax2.set_title("Revenue by Category")

    plt.tight_layout()
    plot_path = output_dir / "analysis_charts.png"
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    print(f"\nCharts saved to: {plot_path}")

except ImportError:
    print("\nMatplotlib not available - skipping visualization")
    print("Install with: uv add matplotlib")

print("\n" + "=" * 80)
print("Analysis complete!")
print("=" * 80)
