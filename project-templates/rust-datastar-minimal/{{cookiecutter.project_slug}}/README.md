# {{cookiecutter.project_name}}

{{cookiecutter.description}}

A real-time, multiplayer web app in one Rust file, with its state in SQLite.

```bash
mise run dev     # or: cargo run
```

Open <http://localhost:8080> in two tabs and type in one of them. The first
build compiles tokio, axum and sqlx (a minute or so); after that an edit
rebuilds and restarts in a few seconds.

## What it is

| File | Job |
| --- | --- |
| `src/main.rs` | The whole program: SQL, state, templates, handlers, compression |
| `migrations/*.sql` | The schema, embedded in the binary and applied at startup |
| `build.rs` | Rebuilds when a migration changes (see Gotchas) |
| `mise.toml` | `dev` (watchexec, tees `logs/serve.log`), `test`, `lint`, `fmt`, `build` |

The browser gets `datastar.js` from a CDN in one script tag. There is no
frontend build step and no `node_modules`.

| Route | Method | Job |
| --- | --- | --- |
| `/` | GET | First paint, and opens the stream |
| `/updates` | GET | The long-lived read. Pushes HTML on every change |
| `/add` | POST | A command. Inserts a row and returns `204` |
| `/clear` | POST | A command. Deletes every row and returns `204` |

Configuration is three environment variables (`.env` is loaded by mise; see
`.env.example`): `PORT` (8080), `DATABASE_URL` (`sqlite://app.db`, created if
missing) and `LOG_LEVEL` (`info`, or any `tracing` filter).

## The shape it is showing off

This follows [the Tao of Datastar][tao], the same as `go-datastar-minimal`.

**The backend is the source of truth.** All state is in SQLite. The browser
holds one signal, `message`, bound to the text input.

**CQRS: one long-lived read, many short-lived writes.** `GET /updates` renders
the board, waits for a change, renders again, forever. `POST /add` writes a
row, bumps a version counter and answers `204`: it never renders. Every open
stream wakes on the bump, so the app is multiplayer without any extra code.

**Patch elements, and trust morph.** Each change re-renders all of
`<main id="board">` and Datastar morphs it in, touching only what differs.

**Backend templating.** [maud] renders the first page and every fragment from
the same `board` function. It checks the markup at compile time and escapes
every `(expr)`, so a message containing `<script>` arrives as text.

[tao]: https://data-star.dev/guide/the_tao_of_datastar
[maud]: https://maud.lambda.xyz/

## Writing SQL

[sqlx] is not an ORM. You write SQL strings, bind parameters with `?`, and map
rows onto structs. Everything lives in the "Database" section of `main.rs`.

**The schema is a migration.** `migrations/0001_messages.sql` is plain DDL.
`sqlx::migrate!()` embeds the directory in the binary and applies whatever
hasn't run yet at startup, recording it in a `_sqlx_migrations` table. To
change the schema, add `0002_<what>.sql`; never edit one that has shipped.
Constraints belong there too: the `CHECK` on `body` length holds even if a
handler forgets to validate.

**Four calls cover almost everything:**

```rust
// Rows onto a struct: #[derive(FromRow)] matches columns by name.
let messages: Vec<Message> =
    sqlx::query_as("SELECT id, body, created_at FROM messages ORDER BY id DESC LIMIT ?")
        .bind(KEEP)
        .fetch_all(&db)          // or fetch_one, fetch_optional
        .await?;

// One value.
let id: i64 = sqlx::query_scalar("INSERT INTO messages (body) VALUES (?) RETURNING id")
    .bind(body)
    .fetch_one(&db)
    .await?;

// No rows back.
let deleted = sqlx::query("DELETE FROM messages").execute(&db).await?.rows_affected();

// Aggregates name their columns with AS; a nullable column is an Option.
#[derive(FromRow)]
struct Stats { total: i64, last_at: Option<String> }
let stats: Stats =
    sqlx::query_as("SELECT count(*) AS total, max(created_at) AS last_at FROM messages")
        .fetch_one(&db)
        .await?;
```

**Transactions** are a value. `insert_message` inserts and trims the table to
the newest 50 rows atomically:

```rust
let mut tx = db.begin().await?;
sqlx::query("...").execute(&mut *tx).await?;   // &mut *tx where you'd pass &db
sqlx::query("...").execute(&mut *tx).await?;
tx.commit().await?;                            // dropped without commit = rollback
```

That rollback-on-drop also makes a transaction cancel safe: if the future is
dropped halfway, nothing is half-written.

**Two queries at once** need no spawning: `render_board` runs both with
`tokio::try_join!`, borrowing the pool.

**Checked at runtime, by choice.** These queries are strings, so a typo in a
column name is an error when the query runs; the tests run every query. sqlx can
also check SQL at compile time with the `query!` / `query_as!` macros, which
read the schema from a live database. That needs `DATABASE_URL` set during
`cargo build`, or `cargo sqlx prepare` (from `sqlx-cli`) to cache the query
metadata in a committed `.sqlx/` directory. Worth switching once the schema
settles; it is left out here so `cargo run` is the whole setup.

**SQLite settings** are in `connect`: WAL mode, so the streams' reads don't
block a write, and a 5 second busy timeout, so a write waits for another
write instead of failing with "database is locked".

**Postgres** is a feature flag and a URL away: enable `postgres` in sqlx's
features, use `PgPool`, and write `$1, $2` instead of `?`.

[sqlx]: https://github.com/launchbadge/sqlx

## Compression

Fat-morph HTML compresses around 200:1 because each stream keeps one Brotli
context, so every frame is compressed against the ones before it. The
`datastar` crate doesn't compress, and tower-http's `CompressionLayer` skips
`text/event-stream` and can't set the window, so `updates` compresses itself:
about 40 lines at the bottom of `main.rs`.

Each open stream holds that context, and quality sets its size more than
the window does. Measured with 16 KB frames: quality 1 at lgwin 17 (a
128 KiB window) holds about 170 KiB per stream and sends 1.7 KB per frame;
quality 5 holds about 1.6 MiB and sends 1.2 KB; the usual default window
(lgwin 22) holds about 9 MiB. Open streams are what a crowd multiplies, so
this uses quality 1. Keep 2^lgwin at least twice the size of your largest
frame. `curl` sends no `Accept-Encoding` by default, so the stream
stays readable by hand; `curl --compressed` shows the browser's view.

## Async notes

- **No `Arc` in sight.** `AppState` holds a pool, a `watch::Sender` and a
  `CancellationToken`, all cheap-to-clone handles, so axum clones the state
  for each request.
- **The stream cleans up after itself.** `/updates` returns a body built from
  a `Stream`. When the client goes away axum drops it, which cancels the loop
  at its next `.await` and drops the subscription. There is no goroutine to
  leak and no unsubscribe to forget.
- **Writes are spawned.** A handler's future is dropped if the client
  disconnects. `add` and `clear` run the write and the notify in
  `tokio::spawn`, so a disconnect can't land between the commit and the
  notify and leave other tabs stale.
- **Graceful shutdown ends the streams.** axum's graceful shutdown waits for
  open requests, and an SSE stream never finishes on its own, so SIGTERM
  cancels a token that every stream selects on.

## Gotchas

- **`openWhenHidden: true` on the stream.** Without it Datastar closes GET
  streams when the tab is hidden, and the tab goes stale.
- **Never wait for `networkidle`** in Playwright: the stream never completes.
  Wait for an element or `domcontentloaded`.
- **No idle or read timeouts** on anything between browser and server, or
  they will cut the stream.
- **`sqlite::memory:` is one database per connection.** A pool of several
  in-memory connections runs migrations on one and queries an empty other
  ("no such table"). The tests use `max_connections(1)`.
- **New migrations need a rebuild.** `migrate!()` reads the directory at
  compile time; `build.rs` tells cargo to rebuild when it changes. Without it
  a new `.sql` file is silently missing from the binary.
- **`PreEscaped` turns escaping off.** It is only used for the constant CSS.

## Making it yours

Replace the `messages` table and the `board` function with what your app is
about, and keep the shape: writes change the database and notify, the stream
re-renders, and state stays on the server.

Left out, in rough order of when you will want them: `/healthz` and
`/metrics`, per-session views instead of one shared board, rendering on a
tick instead of once per stream per change (see the datastar skill's
"Immediate-mode rendering"), compile-time checked queries, and a Dockerfile.
The `rust-service` template has the health, metrics and CLI pieces.

## Notes for agents

- `mise run dev` is the dev loop; its output is in `logs/serve.log`.
  `mise run test` and `mise run lint` must pass before you're done.
- Keep `main.rs` one file. If it needs splitting, the app has outgrown this
  template.
- Mutation handlers must not render. If you are writing HTML in a `POST`
  handler, you have left the pattern.
- Schema changes are new files in `migrations/`, never edits to old ones.
- The datastar.js URL is pinned to a release tag; bump it deliberately, in
  step with the `datastar` crate.
