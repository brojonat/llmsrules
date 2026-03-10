"""API routes and page handlers."""

from server.routes.api import api_router
from server.routes.pages import pages_router
from server.routes.tags import tags_router

__all__ = ["api_router", "pages_router", "tags_router"]
