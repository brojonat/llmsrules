"""Tag CRUD and entity tagging API routes."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from server.deps import AppDbDep, SessionDep

tags_router = APIRouter(prefix="/api", tags=["tags"])


# --- Schemas ---


class TagCreate(BaseModel):
    tag_type: str
    key: str
    value: str
    description: str | None = None


class TagEntityRequest(BaseModel):
    tag_id: str


# --- Tag CRUD ---


@tags_router.post("/tags", status_code=status.HTTP_201_CREATED)
def create_tag(body: TagCreate, db: AppDbDep, session: SessionDep):
    """Create a tag (or return existing if already exists)."""
    result = db.raw_sql(
        f"INSERT INTO tags (tag_type, key, value, description, created_by) "
        f"VALUES ('{body.tag_type}', '{body.key}', '{body.value}', "
        f"'{body.description or ''}', '{session.user_id}') "
        f"ON CONFLICT (tag_type, key, value) DO UPDATE SET tag_type = tags.tag_type "
        f"RETURNING id, tag_type, key, value, description"
    ).fetchone()
    return {
        "id": str(result[0]),
        "tag_type": result[1],
        "key": result[2],
        "value": result[3],
        "description": result[4],
    }


@tags_router.get("/tags")
def list_tags(
    db: AppDbDep,
    session: SessionDep,
    tag_type: str | None = None,
    key: str | None = None,
):
    """List tags, optionally filtered by type and/or key."""
    conditions = []
    if tag_type:
        conditions.append(f"tag_type = '{tag_type}'")
    if key:
        conditions.append(f"key = '{key}'")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = db.raw_sql(
        f"SELECT id, tag_type, key, value, description FROM tags {where} ORDER BY tag_type, key"
    ).fetchall()

    return [
        {"id": str(r[0]), "tag_type": r[1], "key": r[2], "value": r[3], "description": r[4]}
        for r in rows
    ]


@tags_router.delete("/tags/{tag_id}")
def delete_tag(tag_id: str, db: AppDbDep, session: SessionDep):
    """Delete a tag and all its entity associations."""
    result = db.raw_sql(f"DELETE FROM tags WHERE id = '{tag_id}' RETURNING id").fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"deleted": True}


# --- Entity tagging ---


@tags_router.post(
    "/entities/{entity_type}/{entity_id}/tags",
    status_code=status.HTTP_201_CREATED,
)
def tag_entity(
    entity_type: str,
    entity_id: str,
    body: TagEntityRequest,
    db: AppDbDep,
    session: SessionDep,
):
    """Apply a tag to an entity."""
    # Verify tag exists
    tag = db.raw_sql(f"SELECT id FROM tags WHERE id = '{body.tag_id}'").fetchone()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    result = db.raw_sql(
        f"INSERT INTO entity_tags (tag_id, entity_type, entity_id, created_by) "
        f"VALUES ('{body.tag_id}', '{entity_type}', '{entity_id}', '{session.user_id}') "
        f"ON CONFLICT (tag_id, entity_type, entity_id) DO NOTHING "
        f"RETURNING id"
    ).fetchone()

    return {"id": str(result[0]) if result else None, "applied": True}


@tags_router.delete("/entities/{entity_type}/{entity_id}/tags/{tag_id}")
def untag_entity(
    entity_type: str,
    entity_id: str,
    tag_id: str,
    db: AppDbDep,
    session: SessionDep,
):
    """Remove a tag from an entity."""
    result = db.raw_sql(
        f"DELETE FROM entity_tags "
        f"WHERE tag_id = '{tag_id}' AND entity_type = '{entity_type}' "
        f"AND entity_id = '{entity_id}' RETURNING id"
    ).fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="Tag not applied to this entity")
    return {"removed": True}


@tags_router.get("/entities/{entity_type}/{entity_id}/tags")
def get_entity_tags(
    entity_type: str,
    entity_id: str,
    db: AppDbDep,
    session: SessionDep,
):
    """Get all tags for an entity."""
    rows = db.raw_sql(
        f"SELECT t.id, t.tag_type, t.key, t.value, t.description "
        f"FROM tags t JOIN entity_tags et ON t.id = et.tag_id "
        f"WHERE et.entity_type = '{entity_type}' AND et.entity_id = '{entity_id}' "
        f"ORDER BY t.tag_type, t.key"
    ).fetchall()

    return [
        {"id": str(r[0]), "tag_type": r[1], "key": r[2], "value": r[3], "description": r[4]}
        for r in rows
    ]
