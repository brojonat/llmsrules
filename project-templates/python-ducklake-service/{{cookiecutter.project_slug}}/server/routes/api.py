"""JSON API routes for events and entities."""

import json
from datetime import datetime
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Query
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
    conditions = []
    if entity_id:
        conditions.append(f"entity_id = '{entity_id}'")
    if event_type:
        conditions.append(f"event_type = '{event_type}'")
    if start:
        conditions.append(f"timestamp >= '{start.isoformat()}'")
    if end:
        conditions.append(f"timestamp <= '{end.isoformat()}'")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (
        f"SELECT timestamp, entity_id, event_type, value, value_string, metadata "
        f"FROM lake.events {where} "
        f"ORDER BY timestamp DESC LIMIT {limit} OFFSET {offset}"
    )

    result = lake.con.raw_sql(sql).fetchall()
    return [
        EventItem(
            timestamp=row[0],
            entity_id=row[1],
            event_type=row[2],
            value=row[3],
            value_string=row[4],
            metadata=row[5],
        )
        for row in result
    ]


@api_router.get("/entities")
async def list_entities(
    lake: LakeDep,
    session: SessionDep,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
) -> list[EntityListItem]:
    """List distinct entities."""
    where = ""
    if search:
        where = f"WHERE entity_id ILIKE '%{search}%'"

    sql = (
        f"SELECT DISTINCT entity_id FROM lake.events {where} "
        f"ORDER BY entity_id LIMIT {limit} OFFSET {offset}"
    )

    result = lake.con.raw_sql(sql).fetchall()
    return [EntityListItem(entity_id=row[0]) for row in result]


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
    conditions = [f"entity_id = '{entity_id}'"]
    if event_type:
        conditions.append(f"event_type = '{event_type}'")
    if start:
        conditions.append(f"timestamp >= '{start.isoformat()}'")
    if end:
        conditions.append(f"timestamp <= '{end.isoformat()}'")

    where = " AND ".join(conditions)

    async def generate() -> AsyncGenerator[str, None]:
        count_sql = f"SELECT COUNT(*) FROM lake.events WHERE {where}"
        count = lake.con.raw_sql(count_sql).fetchone()[0]

        meta = {"_metadata": {"total": count, "entity_id": entity_id}}
        yield json.dumps(meta) + "\n"

        offset = 0
        while offset < count:
            sql = (
                f"SELECT timestamp, entity_id, event_type, value, value_string, metadata "
                f"FROM lake.events WHERE {where} "
                f"ORDER BY timestamp LIMIT {STREAM_CHUNK_SIZE} OFFSET {offset}"
            )
            rows = lake.con.raw_sql(sql).fetchall()
            for row in rows:
                yield (
                    json.dumps(
                        {
                            "timestamp": row[0].isoformat() if row[0] else None,
                            "entity_id": row[1],
                            "event_type": row[2],
                            "value": row[3],
                            "value_string": row[4],
                            "metadata": row[5],
                        }
                    )
                    + "\n"
                )
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
