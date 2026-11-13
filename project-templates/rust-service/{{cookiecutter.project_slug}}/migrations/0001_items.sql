-- Applied at startup by sqlx::migrate!(), which embeds this directory in the
-- binary. Add 0002_*.sql next to it; never edit a migration that has shipped.
CREATE TABLE items (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    created_by TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
