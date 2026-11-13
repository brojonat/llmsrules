-- Applied at startup by sqlx::migrate!(), which embeds this directory in the
-- binary. Add 0002_*.sql next to it; never edit a migration that has shipped.
CREATE TABLE todos (
    id      INTEGER PRIMARY KEY,
    session TEXT    NOT NULL,
    text    TEXT    NOT NULL CHECK (length(text) BETWEEN 1 AND 200),
    done    BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX todos_session ON todos (session, id);
