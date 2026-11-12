-- Applied at startup by sqlx::migrate!(), which embeds this directory in the
-- binary. Add 0002_*.sql next to it; never edit a migration that has shipped.
CREATE TABLE messages (
    id         INTEGER PRIMARY KEY,
    body       TEXT    NOT NULL CHECK (length(body) BETWEEN 1 AND 500),
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
