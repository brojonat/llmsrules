# Parquet Analysis Skill

This skill enables Claude to analyze parquet files using Python and Ibis.

## Contents

- **SKILL.md** - Main instructions and patterns for parquet analysis
- **examples/sample-analysis.py** - Complete working example with all common patterns
- **templates/analysis-template.py** - Quick-start template for new analyses

## Installation

This skill requires the following Python packages:

```bash
uv add "ibis-framework[duckdb]"

# Optional for visualization
uv add matplotlib
```

## Usage

### With Claude Code

1. Place this skill in `~/.claude/skills/parquet-analysis/`
2. Claude will automatically discover and use it when you ask about parquet files

Example prompts:
- "Analyze this sales.parquet file and show me summary statistics"
- "Read transactions.parquet and calculate total revenue by category"
- "Join customers.parquet and orders.parquet on customer_id"

### Standalone

Run the example script:

```bash
python examples/sample-analysis.py
```

Or use the template for a quick start:

```bash
cp templates/analysis-template.py my-analysis.py
# Edit my-analysis.py with your file paths and logic
python my-analysis.py
```

## Key Capabilities

- Read and explore parquet files
- Data quality checks (nulls, value counts)
- Filtering and transformation
- Aggregations and grouping
- Joins across multiple parquet files
- Time series operations
- Export to parquet, CSV, or pandas DataFrames
- Visualization with matplotlib

## Reference

See [SKILL.md](SKILL.md) for detailed documentation and patterns.

Also see [../../ibis.md](../../ibis.md) for general Ibis usage patterns.
