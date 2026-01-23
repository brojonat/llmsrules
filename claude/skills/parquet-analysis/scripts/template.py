#!/usr/bin/env python3
"""
Quick-start template for parquet analysis with Ibis

Replace the placeholders with your actual:
- File paths
- Column names
- Business logic

Usage:
    python analysis-template.py
"""

import ibis
from pathlib import Path

# ============================================================================
# Configuration
# ============================================================================

INPUT_FILE = "YOUR_FILE.parquet"  # Replace with your parquet file
OUTPUT_DIR = Path("outputs")

# ============================================================================
# Setup
# ============================================================================

con = ibis.duckdb.connect()
OUTPUT_DIR.mkdir(exist_ok=True)

# ============================================================================
# Load data
# ============================================================================

table = con.read_parquet(INPUT_FILE)

print("Schema:")
print(table.schema())

print("\nFirst 10 rows:")
print(table.head(10).execute())

# ============================================================================
# Data exploration
# ============================================================================

# Row count
print(f"\nTotal rows: {table.count().execute()}")

# Summary statistics
print("\nSummary statistics:")
print(table.describe().execute())

# Check for nulls
# null_counts = table.select([
#     col.isnull().sum().name(f"{col}_nulls")
#     for col in table.columns
# ])
# print("\nNull counts:")
# print(null_counts.execute())

# ============================================================================
# Transform and filter (customize this section)
# ============================================================================

# Example: Add computed columns
# transformed = table.mutate(
#     new_column=table.existing_column * 2,
#     category=ibis.case()
#         .when(table.value < 100, "low")
#         .when(table.value < 1000, "medium")
#         .else_("high")
#         .end()
# )

# Example: Filter data
# filtered = table.filter(
#     (table.date >= "2024-01-01") &
#     (table.status == "completed")
# )

# ============================================================================
# Aggregate (customize this section)
# ============================================================================

# Example: Group by and aggregate
# summary = (
#     table
#     .group_by("category")
#     .aggregate(
#         total=table.amount.sum(),
#         avg=table.amount.mean(),
#         count=table.count()
#     )
#     .order_by(ibis.desc("total"))
# )
#
# print("\nSummary:")
# print(summary.execute())

# ============================================================================
# Export results (customize this section)
# ============================================================================

# Example: Write to parquet
# output_path = OUTPUT_DIR / "result.parquet"
# con.to_parquet(summary, str(output_path))
# print(f"\nResults saved to: {output_path}")

# Example: Write to CSV
# df = summary.execute()
# csv_path = OUTPUT_DIR / "result.csv"
# df.to_csv(csv_path, index=False)
# print(f"CSV saved to: {csv_path}")

print("\nDone!")
