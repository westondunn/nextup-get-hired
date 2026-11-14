"""Helpers for tests that inspect the application's routes."""


def api_routes(application):
    """Every route of the application, including those of included routers."""
    found = []
    for route in application.routes:
        inner = getattr(route, "original_router", None)
        found.extend(api_routes(inner) if inner is not None else [route])
    return found
