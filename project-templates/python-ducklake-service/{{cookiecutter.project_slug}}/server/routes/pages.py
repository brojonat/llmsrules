"""HTML page routes (Datastar).

Pages render whole documents. A live page (the dashboard) also opens one
long-lived SSE stream that receives every later render of its region; see
server/live.py. Writes never render: they go to /api and the next frame shows
the result.
"""

import uuid

from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.fastapi import DatastarResponse, ReadSignals
from fastapi import APIRouter, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from server.auth import create_session, invalidate_session, verify_magic_link
from server.auth.jwt import TokenError
from server.auth.magic_link import create_magic_link
from server.deps import (
    BaseUrlDep,
    LakeDep,
    OptionalSessionDep,
    SessionDep,
    SettingsDep,
)
from server.email import send_magic_link_email
from server.live import Frames, render_dashboard

pages_router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")

ENTITY_LIMIT = 100


@pages_router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    session: OptionalSessionDep,
):
    """Landing page."""
    if session:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
    )


@pages_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    lake: LakeDep,
    session: SessionDep,
):
    """Dashboard page: overview of entities and events, live."""
    frames: Frames = request.app.state.frames
    _, html, _ = frames.current("dashboard")
    if html is None:  # the renderer has not published yet
        html = render_dashboard(templates, lake)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"session": session, "dashboard": html, "stream_url": "/dashboard/stream"},
    )


@pages_router.get("/dashboard/stream")
async def dashboard_stream(request: Request, session: SessionDep):
    """The dashboard's long-lived read: the newest frame, every time it changes.

    It never renders; the renderer in server/live.py does that once per change
    for every viewer, and this only copies bytes.
    """
    frames: Frames = request.app.state.frames

    async def stream():
        sent = 0
        while True:
            version, html, next_frame = frames.current("dashboard")
            if html is not None and version != sent:
                yield SSE.patch_elements(html)
                sent = version
            await next_frame.wait()

    return DatastarResponse(stream())


def find_entities(lake, search: str) -> list[str]:
    try:
        rows = lake.query(
            "SELECT DISTINCT entity_id FROM lake.events "
            "WHERE entity_id ILIKE '%' || ? || '%' ORDER BY entity_id LIMIT ?",
            [search, ENTITY_LIMIT],
        )
    except Exception:  # no events table yet
        return []
    return [row[0] for row in rows]


@pages_router.get("/entities", response_class=HTMLResponse)
async def entities_list(
    request: Request,
    lake: LakeDep,
    session: SessionDep,
    search: str = Query(""),
):
    """Entity list page."""
    return templates.TemplateResponse(
        request=request,
        name="entities.html",
        context={
            "entities": find_entities(lake, search),
            "search": search,
            "session": session,
        },
    )


@pages_router.get("/entities/rows")
async def entity_rows(lake: LakeDep, session: SessionDep, signals: ReadSignals):
    """Patch the entity table for the current search signal.

    A one-shot read rather than a stream: the result depends only on the
    query, so there is nothing to push later.
    """
    search = str((signals or {}).get("search", ""))
    html = templates.get_template("_entity_rows.html").render(entities=find_entities(lake, search))
    return DatastarResponse(SSE.patch_elements(html))


@pages_router.get("/entities/{entity_id:path}", response_class=HTMLResponse)
async def entity_detail(
    request: Request,
    entity_id: str,
    lake: LakeDep,
    session: SessionDep,
):
    """One entity: events per day and its most recent events."""
    try:
        per_day = lake.query(
            "SELECT strftime(date_trunc('day', timestamp), '%Y-%m-%d') AS day, COUNT(*) "
            "FROM lake.events WHERE entity_id = ? GROUP BY day ORDER BY day",
            [entity_id],
        )
        events = lake.query(
            "SELECT timestamp, event_type, value, value_string FROM lake.events "
            "WHERE entity_id = ? ORDER BY timestamp DESC LIMIT 100",
            [entity_id],
        )
    except Exception:
        per_day, events = [], []

    return templates.TemplateResponse(
        request=request,
        name="entity.html",
        context={
            "session": session,
            "entity_id": entity_id,
            "per_day": [list(row) for row in per_day],
            "events": events,
        },
    )


@pages_router.get("/auth/magic-link", response_class=HTMLResponse)
async def magic_link_form(request: Request):
    """Show magic link request form."""
    return templates.TemplateResponse(
        request=request,
        name="auth/magic_link.html",
    )


@pages_router.post("/auth/magic-link", response_class=HTMLResponse)
async def request_magic_link(
    request: Request,
    settings: SettingsDep,
    base_url: BaseUrlDep,
    email: str = Form(...),
):
    """Send magic link email."""
    link = create_magic_link(email, settings, base_url)

    sent = await send_magic_link_email(email, link, settings)

    if not sent:
        return templates.TemplateResponse(
            request=request,
            name="auth/magic_link.html",
            context={"error": "Failed to send email. Please try again."},
        )

    return templates.TemplateResponse(
        request=request,
        name="auth/magic_link.html",
        context={"success": True, "email": email},
    )


@pages_router.get("/auth/verify")
async def verify_token(
    settings: SettingsDep,
    token: str = Query(...),
):
    """Verify magic link token and create session."""
    try:
        email = verify_magic_link(token, settings)
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, email))
    session = await create_session(
        user_id=user_id,
        email=email,
        expires_in=settings.session_expiry,
    )

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="session",
        value=session.session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.session_expiry,
    )
    return response


@pages_router.post("/auth/logout")
async def logout(
    session: SessionDep,
):
    """Log out and clear session."""
    await invalidate_session(session.session_id)

    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session")
    return response
