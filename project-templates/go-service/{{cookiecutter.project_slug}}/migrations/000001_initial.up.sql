CREATE TABLE IF NOT EXISTS examples (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    value TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_examples_created_at ON examples(created_at DESC);
