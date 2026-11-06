"""JSON API routes for events and entities."""

import asyncio
import json
from datetime import datetime
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server.deps import LakeDep, SessionDep

api_router = APIRouter(prefix="/api", tags=["api"])

# Chunk size for streaming
STREAM_CHUNK_SIZE = 500


# --- Schemas ---


class EventCreate(BaseModel):
    timestamp: datetime
    entity_id: str
    event_type: str
    value: float | None = None
    value_string: str | None = None
    metadata: dict | None = None
    date: str | None = None


class EventItem(BaseModel):
    timestamp: datetime
    entity_id: str
    event_type: str
    value: float | None = None
    value_string: str | None = None
    metadata: dict | None = None


class EntityListItem(BaseModel):
    entity_id: str


class QueryRequest(BaseModel):
    """Raw query request."""

    sql: str


# --- Routes ---


EVENT_COLUMNS = "timestamp, entity_id, event_type, value, value_string, metadata"


def event_filters(
    entity_id: str | None,
    event_type: str | None,
    start: datetime | None,
    end: datetime | None,
) -> tuple[str, list]:
    """A WHERE clause with `?` placeholders, and its parameters."""
    conditions, params = [], []
    for clause, value in (
        ("entity_id = ?", entity_id),
        ("event_type = ?", event_type),
        ("timestamp >= ?", start),
        ("timestamp <= ?", end),
    ):
        if value is not None:
            conditions.append(clause)
            params.append(value)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


def event_item(row: tuple) -> EventItem:
    metadata = json.loads(row[5]) if isinstance(row[5], str) else row[5]
    return EventItem(
        timestamp=row[0],
        entity_id=row[1],
        event_type=row[2],
        value=row[3],
        value_string=row[4],
        metadata=metadata,
    )


@api_router.post("/events", status_code=status.HTTP_201_CREATED)
async def create_events(
    events: list[EventCreate],
    lake: LakeDep,
    session: SessionDep,
) -> dict[str, int]:
    """Append events to the lake in one snapshot. Live views pick the change up."""
    if not events:
        return {"inserted": 0}
    rows = [
        [
            e.timestamp,
            e.entity_id,
            e.event_type,
            e.value,
            e.value_string,
            json.dumps(e.metadata) if e.metadata is not None else None,
            e.date or e.timestamp.date().isoformat(),
        ]
        for e in events
    ]
    await asyncio.to_thread(
        lake.execute_many,
        f"INSERT INTO lake.events ({EVENT_COLUMNS}, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return {"inserted": len(rows)}


@api_router.get("/events")
async def list_events(
    lake: LakeDep,
    session: SessionDep,
    entity_id: str | None = Query(None),
    event_type: str | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=10000),
    offset: int = Query(0, ge=0),
) -> list[EventItem]:
    """List events with optional filters."""
    where, params = event_filters(entity_id, event_type, start, end)
    rows = lake.query(
        f"SELECT {EVENT_COLUMNS} FROM lake.events {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return [event_item(row) for row in rows]


@api_router.get("/entities")
async def list_entities(
    lake: LakeDep,
    session: SessionDep,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: str = Query(""),
) -> list[EntityListItem]:
    """List distinct entities."""
    rows = lake.query(
        "SELECT DISTINCT entity_id FROM lake.events "
        "WHERE entity_id ILIKE '%' || ? || '%' ORDER BY entity_id LIMIT ? OFFSET ?",
        [search, limit, offset],
    )
    return [EntityListItem(entity_id=row[0]) for row in rows]


@api_router.get("/events/stream", response_model=None)
async def stream_events(
    lake: LakeDep,
    session: SessionDep,
    entity_id: str = Query(...),
    event_type: str | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
) -> StreamingResponse:
    """Stream events as NDJSON.

    First line is metadata: {"_metadata": {"total": N, "entity_id": "..."}}
    Subsequent lines are event objects.
    """
    where, params = event_filters(entity_id, event_type, start, end)

    async def generate() -> AsyncGenerator[str, None]:
        count = lake.query(f"SELECT COUNT(*) FROM lake.events {where}", params)[0][0]

        meta = {"_metadata": {"total": count, "entity_id": entity_id}}
        yield json.dumps(meta) + "\n"

        offset = 0
        while offset < count:
            rows = lake.query(
                f"SELECT {EVENT_COLUMNS} FROM lake.events {where} "
                f"ORDER BY timestamp LIMIT ? OFFSET ?",
                [*params, STREAM_CHUNK_SIZE, offset],
            )
            for row in rows:
                yield event_item(row).model_dump_json() + "\n"
            offset += STREAM_CHUNK_SIZE

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@api_router.post("/query")
async def execute_query(
    request: QueryRequest,
    lake: LakeDep,
    session: SessionDep,
) -> list[dict[str, Any]]:
    """Execute a raw DuckDB/Ibis query.

    Note: This endpoint should be restricted in production.
    """
    result = lake.con.sql(request.sql).to_pyarrow()
    return result.to_pylist()
