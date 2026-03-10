"""HTML page routes (HTMX)."""

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

pages_router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


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
    """Dashboard page - overview of entities and events."""
    # Get entity count
    try:
        entity_count = lake.con.raw_sql(
            "SELECT COUNT(DISTINCT entity_id) FROM lake.events"
        ).fetchone()[0]
    except Exception:
        entity_count = 0

    # Get event count
    try:
        event_count = lake.con.raw_sql("SELECT COUNT(*) FROM lake.events").fetchone()[0]
    except Exception:
        event_count = 0

    # Get recent event types
    try:
        event_types = lake.con.raw_sql(
            "SELECT DISTINCT event_type FROM lake.events ORDER BY event_type LIMIT 20"
        ).fetchall()
        event_types = [row[0] for row in event_types]
    except Exception:
        event_types = []

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "session": session,
            "entity_count": entity_count,
            "event_count": event_count,
            "event_types": event_types,
        },
    )


@pages_router.get("/entities", response_class=HTMLResponse)
async def entities_list(
    request: Request,
    lake: LakeDep,
    session: SessionDep,
    search: str | None = Query(None),
):
    """Entity list page."""
    where = ""
    if search:
        where = f"WHERE entity_id ILIKE '%{search}%'"

    try:
        result = lake.con.raw_sql(
            f"SELECT DISTINCT entity_id FROM lake.events {where} ORDER BY entity_id LIMIT 100"
        ).fetchall()
        entities = [row[0] for row in result]
    except Exception:
        entities = []

    is_htmx = request.headers.get("HX-Request") == "true"

    if is_htmx:
        # Return just the list fragment
        items_html = ""
        for entity in entities:
            items_html += f'<tr><td><a href="/entities/{entity}">{entity}</a></td></tr>'
        if not entities:
            items_html = '<tr><td class="empty-state">No entities found.</td></tr>'
        return HTMLResponse(items_html)

    return templates.TemplateResponse(
        request=request,
        name="entities.html",
        context={
            "entities": entities,
            "search": search,
            "session": session,
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

    import uuid

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
