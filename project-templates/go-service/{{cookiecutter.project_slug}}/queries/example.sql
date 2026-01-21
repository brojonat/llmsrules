-- Example sqlc queries
-- Modify this file and run `make sqlc` to generate Go code

-- name: GetExample :one
SELECT * FROM examples
WHERE id = $1 LIMIT 1;

-- name: ListExamples :many
SELECT * FROM examples
ORDER BY created_at DESC
LIMIT $1 OFFSET $2;

-- name: CreateExample :one
INSERT INTO examples (name, value)
VALUES ($1, $2)
RETURNING *;

-- name: DeleteExample :exec
DELETE FROM examples
WHERE id = $1;
